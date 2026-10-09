import XCTest
@testable import KitchenOSKit

private let owner = UUID(uuidString: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")!
private let token = UUID(uuidString: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")!
private let bridge = BridgeContext(ownerID: owner, ownerGeneration: 1)
private let fields = AppleFields(completed: false, due: nil)
private func report(_ queued: Int = 0, created: Int = 0) -> SyncReport {
    SyncReport(created: created, updated: 0, deleted: 0, queued: queued, conflicts: 0, unavailable: 0, lastSuccess: nil)
}
private func item(_ id: UUID = token, domain: AppleDomain = .shopping, linked: Bool = false, revision: Int = 1) -> SyncItem {
    SyncItem(logicalID: id.uuidString, domain: domain, week: "2026-W41", title: "Buy beans", fields: fields,
        sourceRevision: String(repeating: "a", count: 64), state: .active, revision: revision, generation: 1,
        token: id, destinationID: "list", locator: linked ? Locator(calendarID: "list", itemID: "saved", externalID: nil) : nil,
        commonFields: linked ? fields : nil)
}
private func operation(_ id: UUID = token, revision: Int = 1) -> AppleOperation {
    AppleOperation(operationID: UUID(), token: id, generation: 1, revision: revision, action: .upsert,
        destinationID: "list", locator: nil, title: "Buy beans", fields: fields, expectedAppleHash: nil)
}
private func observation(_ item: SyncItem, present: Bool) -> Observation {
    Observation(token: item.token, generation: item.generation, revision: item.revision,
        availability: present ? .present : .missing,
        locator: present ? Locator(calendarID: "list", itemID: "saved", externalID: nil) : nil,
        title: present ? item.title : nil, fields: present ? item.fields : AppleFields(), absenceConfirmed: false, issue: nil)
}

private actor Gate {
    var open = false
    var entered = false
    var waiters: [CheckedContinuation<Void, Never>] = []
    func wait() async { entered = true; if !open { await withCheckedContinuation { waiters.append($0) } } }
    func release() { open = true; for waiter in waiters { waiter.resume() }; waiters = [] }
}

private actor ServiceAPI: AppleIntegrationAPI {
    var items: [SyncItem] = [item()]
    var operations: [AppleOperation] = [operation()]
    var retries: [ObservationRetry] = []
    var retained: [SyncItem] = []
    var paused = false
    var connected = true
    var offline = false
    var loseAck = false
    var calls: [String] = []
    var observed: [[Observation]] = []
    var replayID: UUID?
    var gate: Gate?
    var removed: [OwnedRemovalItem] = []
    var changeRevisionAfterObservation = false
    var unavailableObservationToken: UUID?
    func configure(items: [SyncItem]? = nil, operations: [AppleOperation]? = nil, retries: [ObservationRetry]? = nil,
                   retained: [SyncItem]? = nil, paused: Bool = false, connected: Bool = true, offline: Bool = false,
                   loseAck: Bool = false, gate: Gate? = nil, unavailableObservationToken: UUID? = nil, changeRevisionAfterObservation: Bool = false) {
        if let items { self.items = items }; if let operations { self.operations = operations }
        if let retries { self.retries = retries }; if let retained { self.retained = retained }
        self.paused = paused; self.connected = connected; self.offline = offline; self.loseAck = loseAck; self.gate = gate; self.unavailableObservationToken = unavailableObservationToken; self.changeRevisionAfterObservation = changeRevisionAfterObservation
    }
    func registerOwner(_ id: UUID, permissions: [String: AppleAuthorization]?, destinations: [String: [AppleDestination]]?) async throws -> BridgeContext {
        calls.append("owner"); return bridge
    }
    func status() async throws -> IntegrationStatus {
        calls.append("status")
        if offline { throw KitchenOSError.unreachable }
        return IntegrationStatus(modelVersion: 1, configured: true, connected: connected, paused: paused,
            settingsRevision: 1, report: report(operations.count), permissions: [:], destinations: [:], scopes: [], conflicts: [])
    }
    func work(context: BridgeContext) async throws -> WorkBatch {
        calls.append("work"); if offline { throw KitchenOSError.unreachable }
        if let gate { self.gate = nil; await gate.wait() }
        return WorkBatch(modelVersion: 1, context: bridge, items: items, operations: operations, scopes: [],
            report: report(operations.count), paused: paused, retryRequests: retries, retainedItems: retained)
    }
    func observe(_ values: [Observation], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation] {
        calls.append("observe"); observed.append(values)
        if let retry = retries.first {
            guard retry.requestID == requestID, retry.observations == values else { throw KitchenOSError.http(409) }
            replayID = requestID; retries = []; return operations
        }
        if let token = unavailableObservationToken, values.contains(where: { $0.token == token }) { throw KitchenOSError.http(503) }
        // Model the bridge's exact lost-first-save acknowledgement repair.
        let found = Set(values.filter { $0.availability == .present }.map(\.token))
        operations.removeAll { found.contains($0.token) }
        if changeRevisionAfterObservation {
            changeRevisionAfterObservation = false
            items = [item(revision: 2)]; operations = [operation(revision: 2)]
        }
        return operations
    }
    func acknowledge(_ ack: OperationAck, context: BridgeContext) async throws -> SyncReport {
        calls.append("ack")
        if loseAck { loseAck = false; throw KitchenOSError.unreachable }
        operations.removeAll { $0.operationID == ack.operationID }
        return report(operations.count, created: ack.outcome == .saved ? 1 : 0)
    }
    func setScope(_ request: ScopeRequest) async throws -> SyncReport { calls.append("scope:\(request.domain.rawValue)"); return report() }
    func setPaused(_ value: Bool, expectedRevision: Int) async throws -> SyncReport {
        calls.append("pause:\(value)"); paused = value; return report(value ? 7 : 3)
    }
    func resolve(_ resolution: ConflictResolution) async throws -> SyncReport { report() }
    func disconnect(context: BridgeContext) async throws -> SyncReport { calls.append("disconnect"); connected = false; return report() }
    func restore(token: UUID, expectedRevision: Int) async throws -> SyncReport { report() }
    func removeOwned(_ items: [OwnedRemovalItem], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation] {
        removed = items; return []
    }
}

@MainActor private final class ServiceStore: AppleItemStore {
    var objects: Set<UUID> = []
    var writes: [UUID] = []
    var active = 0
    var maximumConcurrentWrites = 0
    var failingDomains: Set<AppleDomain> = []
    var requestCount = 0
    var applyGate: Gate?
    var observed: [[UUID]] = []
    var observedRevisions: [Int] = []
    func authorization(for domain: AppleDomain) -> AppleAuthorization { .authorized }
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization { requestCount += 1; return .authorized }
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination] { [AppleDestination(id: "list", title: "List")] }
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination { AppleDestination(id: "list", title: name) }
    func observe(_ items: [SyncItem]) async throws -> [Observation] {
        observed.append(items.map(\.token)); observedRevisions += items.map(\.revision)
        if items.contains(where: { failingDomains.contains($0.domain) }) { throw AppleIntegrationError.unavailable }
        return items.map { observation($0, present: objects.contains($0.token)) }
    }
    func apply(_ op: AppleOperation) async throws -> OperationAck {
        active += 1; maximumConcurrentWrites = max(maximumConcurrentWrites, active)
        defer { active -= 1 }
        if let applyGate { self.applyGate = nil; await applyGate.wait() }
        writes.append(op.token); objects.insert(op.token)
        return OperationAck(operationID: op.operationID, outcome: .saved,
            locator: Locator(calendarID: "list", itemID: "saved", externalID: nil), observedFields: op.fields,
            observedHash: try op.fields.canonicalHash(title: op.title))
    }
    func availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) async throws -> PlanningCalendarSnapshot { throw AppleIntegrationError.unavailable }
}

@MainActor final class AppleIntegrationServiceTests: XCTestCase {
    private func service(_ api: ServiceAPI, _ store: ServiceStore, sleep: @escaping @Sendable (TimeInterval) async throws -> Void = { _ in }) -> AppleIntegrationService {
        AppleIntegrationService(api: api, store: store, ownerID: owner, sleep: sleep)
    }
    private func entered(_ gate: Gate) async {
        for _ in 0..<10000 { if await gate.entered { return }; await Task.yield() }
        XCTFail("Expected suspended operation")
    }
    func testSaveBeforeAckIsRecoveredOnce() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); await api.configure(loseAck: true)
        let service = service(api, store)
        _ = try await service.perform(.sync)
        _ = try await service.reconcile(trigger: .launch)
        XCTAssertEqual(store.writes, [token])
        XCTAssertEqual(store.requestCount, 0)
        let observed = await api.observed
        XCTAssertTrue(observed.contains { $0.contains { $0.token == token && $0.availability == .present } })
    }
    func testOverlappingCommandsStaySerialAndReturnTheirOwnOutcomes() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); let gate = Gate(); store.applyGate = gate
        let service = service(api, store)
        let first = Task { try await service.perform(.sync) }
        await entered(gate)
        let second = Task { try await service.perform(.setPaused(true, revision: 1)) }
        for _ in 0..<100 { await Task.yield() }
        let before = await api.calls
        XCTAssertFalse(before.contains("pause:true"))
        await gate.release()
        let firstReport = try await first.value; let secondReport = try await second.value
        XCTAssertEqual(firstReport.created, 1)
        XCTAssertEqual(secondReport.queued, 7)
        XCTAssertEqual(store.maximumConcurrentWrites, 1)
    }
    func testReplayRequiresExactPayloadThenFreshWorkAndObservation() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); store.objects.insert(token)
        let replay = ObservationRetry(requestID: UUID(), observations: [observation(item(), present: false)])
        await api.configure(retries: [replay])
        _ = try await service(api, store).perform(.sync)
        let calls = await api.calls; let values = await api.observed; let replayID = await api.replayID
        XCTAssertEqual(replayID, replay.requestID)
        XCTAssertEqual(values.first, replay.observations)
        XCTAssertEqual(values.last?.first?.availability, .present)
        let firstObserve = try XCTUnwrap(calls.firstIndex(of: "observe"))
        XCTAssertEqual(Array(calls[(firstObserve + 1)...].prefix(2)), ["work", "observe"])
        XCTAssertTrue(store.writes.isEmpty)
    }
    func testDomainObservationFailureDoesNotBlockOtherDomainOrCreateFromUnknownAbsence() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); store.failingDomains = [.shopping]
        let prep = UUID(); await api.configure(items: [item(), item(prep, domain: .prep)], operations: [operation(), operation(prep)])
        let result = try await service(api, store).perform(.sync)
        XCTAssertEqual(store.writes, [prep])
        XCTAssertEqual(result.created, 1)
        XCTAssertGreaterThan(result.unavailable, 0)
        let observed = await api.observed
        XCTAssertEqual(observed.first?.first?.availability, .unavailable)
        XCTAssertEqual(observed.first?.first?.absenceConfirmed, false)
    }

    func testUnavailableServerSourceDoesNotBlockHealthyDomain() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); let prep = UUID()
        store.objects.insert(token)
        await api.configure(items: [item(linked: true), item(prep, domain: .prep)],
            operations: [operation(), operation(prep)], unavailableObservationToken: token)
        let result = try await service(api, store).perform(.sync)
        XCTAssertEqual(store.writes, [prep])
        XCTAssertEqual(result.created, 1)
        XCTAssertGreaterThan(result.unavailable, 0)
    }
    func testPausedAndDisconnectedDoNotRegisterOrWrite() async throws {
        for paused in [true, false] {
            let api = ServiceAPI(); let store = ServiceStore(); await api.configure(paused: paused, connected: paused)
            let result = try await service(api, store).perform(.sync)
            XCTAssertEqual(result.created, 0); XCTAssertGreaterThan(result.queued, 0)
            XCTAssertTrue(store.writes.isEmpty)
            let calls = await api.calls; XCTAssertFalse(calls.contains("owner"))
        }
    }
    func testOfflineBackoffIsBoundedAndNeverUsesCachedWork() async throws {
        actor Delays { var values: [Double] = []; func add(_ delay: Double) { values.append(delay) } }
        let delays = Delays(); let api = ServiceAPI(); let store = ServiceStore(); await api.configure(offline: true)
        let result = try await service(api, store, sleep: { await delays.add($0) }).perform(.sync)
        let values = await delays.values
        XCTAssertEqual(values, [1, 2, 4, 8, 16, 30])
        XCTAssertGreaterThan(result.queued, 0); XCTAssertEqual(result.created, 0)
        XCTAssertTrue(store.writes.isEmpty)
    }
    func testRepeatedNotificationsCoalesceAndNeverDeliverPreviousCallCounts() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); let gate = Gate(); await api.configure(gate: gate)
        let service = service(api, store)
        let first = Task { try await service.reconcile(trigger: .launch) }
        await entered(gate)
        let tasks = (0..<20).map { _ in Task { try await service.reconcile(trigger: .eventStoreChanged) } }
        for _ in 0..<100 { await Task.yield() }
        await gate.release(); _ = try await first.value
        for task in tasks { let value = try await task.value; XCTAssertEqual(value.created, 0) }
        XCTAssertEqual(store.writes.count, 1)
        let values = await api.observed
        XCTAssertLessThanOrEqual(values.count, 3)
    }
    func testRemoveOwnedUsesFreshIndividualRevisionsAndIncludesRetainedOnlyExplicitly() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); let old = UUID()
        await api.configure(items: [item(token, linked: true, revision: 3)], operations: [], retained: [item(old, linked: true, revision: 8)])
        store.objects = [token, old]
        let service = service(api, store)
        _ = try await service.perform(.removeOwned([AppleOwnedSelection(token: token, revision: 3), AppleOwnedSelection(token: old, revision: 8)]))
        let removed = await api.removed
        XCTAssertEqual(removed.map(\.expectedRevision), [3, 8])
        XCTAssertTrue(removed.allSatisfy { $0.observation.availability == .present })
        XCTAssertEqual(removed.map(\.observation.revision), [3, 8])
    }

    func testChangingServerDuringFreshWorkPreventsAppleWrites() async throws {
        actor Permission { var allowed = true; func deny() { allowed = false } }
        let permission = Permission(); let api = ServiceAPI(); let store = ServiceStore(); let gate = Gate()
        await api.configure(gate: gate)
        let service = AppleIntegrationService(api: api, store: store, ownerID: owner, sleep: { _ in },
            isCurrentServer: { await permission.allowed })
        let pending = Task { try await service.perform(.sync) }
        await entered(gate); await permission.deny(); await gate.release()
        do { _ = try await pending.value; XCTFail("Changed server must stop the old writer") } catch {}
        XCTAssertTrue(store.writes.isEmpty)
    }

    func testSourceRevisionChangedAfterObservationRequiresAnotherAppleScan() async throws {
        let api = ServiceAPI(); let store = ServiceStore()
        await api.configure(changeRevisionAfterObservation: true)
        let result = try await service(api, store).perform(.sync)
        XCTAssertEqual(store.observedRevisions, [1, 2])
        XCTAssertEqual(store.writes, [token])
        XCTAssertEqual(result.created, 1)
    }
    func testNewOperationsCannotBypassFreshAppleObservation() async throws {
        let api = ServiceAPI(); let store = ServiceStore(); let unseen = UUID()
        await api.configure(items: [], operations: [operation(unseen)])
        let result = try await service(api, store).perform(.sync)
        XCTAssertTrue(store.writes.isEmpty)
        XCTAssertGreaterThan(result.queued, 0)
    }
    func testLinkedUncertainAbsenceIsSentAndNeverRecreated() async throws {
        let api = ServiceAPI(); let store = ServiceStore()
        await api.configure(items: [item(linked: true)], operations: [operation()])
        let result = try await service(api, store).perform(.sync)
        XCTAssertTrue(store.writes.isEmpty); XCTAssertGreaterThan(result.unavailable, 0)
        let values = await api.observed
        XCTAssertEqual(values.first?.first?.availability, .missing)
    }
}

private actor ManualIntegrationClock {
    private var waiters: [(Double, CheckedContinuation<Void, Never>)] = []
    func sleep(_ seconds: Double) async { await withCheckedContinuation { waiters.append((seconds, $0)) } }
    func count(_ seconds: Double) -> Int { waiters.filter { $0.0 == seconds }.count }
    func advance(_ seconds: Double) {
        let ready = waiters.filter { $0.0 == seconds }; waiters.removeAll { $0.0 == seconds }
        for (_, waiter) in ready { waiter.resume() }
    }
}

@MainActor final class AppleIntegrationLifecycleTests: XCTestCase {
    private func settled(_ condition: () async -> Bool) async {
        for _ in 0..<10000 { if await condition() { return }; await Task.yield() }
        XCTFail("Expected lifecycle transition")
    }
    func testOnePeriodicLoopSurvivesForegroundAndWakeUntilShutdown() async {
        let clock = ManualIntegrationClock(); var events: [AppleIntegrationTrigger] = []
        let lifecycle = AppleIntegrationLifecycle(sleep: { await clock.sleep($0) }, action: { events.append($0) })
        lifecycle.start(); lifecycle.start()
        await settled { await clock.count(300) == 1 }
        lifecycle.notify(.wake); lifecycle.notify(.foreground)
        await settled { events.count == 3 }
        XCTAssertEqual(events.filter { $0 == .launch }.count, 1)
        // Window disappearance has no lifecycle stop; only app termination calls it.
        await clock.advance(300)
        await settled { events.contains(.periodic) }
        await settled { await clock.count(300) == 1 }
        lifecycle.stop(); let count = events.count
        await clock.advance(300); lifecycle.notify(.wake)
        for _ in 0..<100 { await Task.yield() }
        XCTAssertEqual(events.count, count)
    }
    func testStoreNotificationsDebounceAndStoppedDebounceNeverFires() async {
        let clock = ManualIntegrationClock(); var events: [AppleIntegrationTrigger] = []
        let lifecycle = AppleIntegrationLifecycle(sleep: { await clock.sleep($0) }, action: { events.append($0) })
        lifecycle.start(); await settled { await clock.count(300) == 1 }
        for _ in 0..<20 { lifecycle.notify(.eventStoreChanged); await Task.yield() }
        await settled { await clock.count(0.25) > 0 }
        await clock.advance(0.25)
        await settled { events.filter { $0 == .eventStoreChanged }.count == 1 }
        lifecycle.notify(.eventStoreChanged)
        await settled { await clock.count(0.25) == 1 }
        lifecycle.stop(); await clock.advance(0.25); await clock.advance(300)
        for _ in 0..<100 { await Task.yield() }
        XCTAssertEqual(events.filter { $0 == .eventStoreChanged }.count, 1)
    }
}
