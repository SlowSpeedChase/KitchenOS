import Foundation

/// Transport seam; all merge decisions and durable operation identity stay on the server.
public protocol AppleIntegrationAPI: Sendable {
    func registerOwner(_ id: UUID, permissions: [String: AppleAuthorization]?, destinations: [String: [AppleDestination]]?) async throws -> BridgeContext
    func status() async throws -> IntegrationStatus
    func work(context: BridgeContext) async throws -> WorkBatch
    func observe(_ observations: [Observation], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation]
    func acknowledge(_ ack: OperationAck, context: BridgeContext) async throws -> SyncReport
    func setScope(_ request: ScopeRequest) async throws -> SyncReport
    func setPaused(_ paused: Bool, expectedRevision: Int) async throws -> SyncReport
    func resolve(_ resolution: ConflictResolution) async throws -> SyncReport
    func disconnect(context: BridgeContext) async throws -> SyncReport
    func restore(token: UUID, expectedRevision: Int) async throws -> SyncReport
    func removeOwned(_ items: [OwnedRemovalItem], context: BridgeContext, requestID: UUID) async throws -> [AppleOperation]
}
extension AppleIntegrationClient: AppleIntegrationAPI {}

public struct AppleOwnedSelection: Sendable {
    public let token: UUID
    public let revision: Int
    public init(token: UUID, revision: Int) { self.token = token; self.revision = revision }
}
public enum AppleIntegrationCommand: Sendable {
    case activate(AppleDomain, week: String, destination: String)
    case sync
    case setPaused(Bool, revision: Int)
    case archive(AppleDomain, week: String)
    case resolve(UUID, choice: AppleConflictChoice, revision: Int)
    case disconnect
    case restore(UUID, revision: Int)
    case removeOwned([AppleOwnedSelection])
}
public enum AppleIntegrationTrigger: Sendable { case launch, wake, foreground, eventStoreChanged, periodic, domainChanged }

/// The retained worker, rather than actor isolation alone, serializes whole commands
/// across network and EventKit awaits. Each command has its own continuation/result.
public actor AppleIntegrationService {
    private struct PendingAcknowledgement { let ack: OperationAck; let context: BridgeContext }
    private struct AcknowledgementDeferred: Error {}
    // Proof from this process's successful adapter mutation. Never reconstruct a
    // deleted acknowledgement from a later missing-object scan after restart.
    private var pendingAcknowledgement: PendingAcknowledgement?
    private struct ScanVersion: Equatable { let generation: Int; let revision: Int }
    private struct Waiter { let id: UUID; let continuation: CheckedContinuation<SyncReport, Error> }
    private struct Job { let command: AppleIntegrationCommand; let trigger: Bool; var waiters: [Waiter] }
    private let api: any AppleIntegrationAPI
    private let store: any AppleItemStore
    private let ownerID: UUID
    private let sleep: @Sendable (TimeInterval) async throws -> Void
    private let isCurrentServer: @Sendable () async -> Bool
    private var jobs: [Job] = []
    private var worker: Task<Void, Never>?
    private var activeIDs: Set<UUID> = []
    private var cancelledIDs: Set<UUID> = []
    private var stopped = false
    private var replaySerial = 0
    private var knownOwnedCookingTokens: Set<UUID> = []
    private var lastReport = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)

    public init(api: any AppleIntegrationAPI, store: any AppleItemStore, ownerID: UUID,
                sleep: @escaping @Sendable (TimeInterval) async throws -> Void = { try await Task.sleep(for: .seconds($0)) },
                isCurrentServer: @escaping @Sendable () async -> Bool = { true }) {
        self.api = api; self.store = store; self.ownerID = ownerID; self.sleep = sleep
        self.isCurrentServer = isCurrentServer
    }
    public func perform(_ command: AppleIntegrationCommand) async throws -> SyncReport { try await enqueue(command, trigger: false) }
    public func reconcile(trigger: AppleIntegrationTrigger) async throws -> SyncReport { try await enqueue(.sync, trigger: true) }
    /// Includes retained ownership generations; only the adapter verifies markers in snapshots.
    public func ownedCookingTokens() -> Set<UUID> { knownOwnedCookingTokens }
    public func shutdown() {
        stopped = true; worker?.cancel()
        for job in jobs { for waiter in job.waiters { waiter.continuation.resume(throwing: CancellationError()) } }
        jobs.removeAll()
    }
    private func enqueue(_ command: AppleIntegrationCommand, trigger: Bool) async throws -> SyncReport {
        try Task.checkCancellation()
        guard !stopped else { throw CancellationError() }
        let id = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                let waiter = Waiter(id: id, continuation: continuation)
                if trigger, let index = jobs.indices.last, jobs[index].trigger {
                    jobs[index].waiters.append(waiter)
                } else { jobs.append(Job(command: command, trigger: trigger, waiters: [waiter])) }
                if worker == nil { worker = Task { await self.drain() } }
            }
        } onCancel: { Task { await self.cancel(id) } }
    }
    private func cancel(_ id: UUID) {
        if activeIDs.contains(id) { cancelledIDs.insert(id); return }
        for index in jobs.indices {
            if let position = jobs[index].waiters.firstIndex(where: { $0.id == id }) {
                jobs[index].waiters.remove(at: position).continuation.resume(throwing: CancellationError())
                if jobs[index].waiters.isEmpty { jobs.remove(at: index) }; return
            }
        }
    }
    private func checkRunning() throws {
        try Task.checkCancellation()
        if stopped || (!activeIDs.isEmpty && activeIDs.isSubset(of: cancelledIDs)) { throw CancellationError() }
    }
    private func checkAuthority() async throws {
        try checkRunning()
        guard await isCurrentServer() else { throw AppleIntegrationError.unavailable }
        try checkRunning()
    }
    private func drain() async {
        while !jobs.isEmpty && !stopped {
            let job = jobs.removeFirst(); activeIDs = Set(job.waiters.map(\.id))
            let result: Result<SyncReport, Error>
            do { try checkRunning(); result = .success(try await execute(job.command)) }
            catch { result = .failure(error) }
            for waiter in job.waiters {
                if cancelledIDs.contains(waiter.id) { waiter.continuation.resume(throwing: CancellationError()) }
                else { waiter.continuation.resume(with: result) }
            }
            cancelledIDs.subtract(activeIDs); activeIDs.removeAll()
        }
        worker = nil
    }
    private func register() async throws -> BridgeContext {
        var permissions: [String: AppleAuthorization] = [:]
        var destinations: [String: [AppleDestination]] = [:]
        for domain in AppleDomain.allCases {
            permissions[domain.rawValue] = await store.authorization(for: domain)
            destinations[domain.rawValue] = (try? await store.destinations(for: domain)) ?? []
        }
        try await checkAuthority()
        return try await api.registerOwner(ownerID, permissions: permissions, destinations: destinations)
    }
    private func execute(_ command: AppleIntegrationCommand) async throws -> SyncReport {
        try await checkAuthority()
        var recovered = Totals()
        var command = command
        if pendingAcknowledgement != nil, case let .setPaused(value, revision) = command {
            // Settings controls may unblock a paused acknowledgement, but cannot
            // authorize another Apple observation or write ahead of that proof.
            let result = try await api.setPaused(value, expectedRevision: revision)
            if value { return recovered.report(result, pending: true) }
            command = .sync
        }
        do { try await flushAcknowledgement(totals: &recovered) }
        catch is AcknowledgementDeferred {
            recovered.unavailable = max(1, recovered.unavailable)
            if case .sync = command { return recovered.report(lastReport, pending: true) }
            // An unrelated command was never executed, so do not return success.
            throw AppleIntegrationError.unavailable
        }
        let result = try await executeCommand(command)
        recovered.add(result)
        return recovered.report(result)
    }
    private func executeCommand(_ command: AppleIntegrationCommand) async throws -> SyncReport {
        switch command {
        case .sync: return try await synchronize()
        case let .setPaused(value, revision):
            let report = try await api.setPaused(value, expectedRevision: revision)
            return value ? report : try await synchronize()
        case let .activate(domain, week, destination):
            // Explicit foreground/intent action alone may connect an unconfigured owner.
            _ = try await register()
            let status = try await api.status()
            let revision = status.scopes.first { $0.domain == domain && $0.week == week }?.revision ?? 0
            try await checkAuthority()
            _ = try await api.setScope(ScopeRequest(domain: domain, week: week, destinationID: destination, state: .active, expectedRevision: revision))
            return try await synchronize()
        case let .archive(domain, week):
            let status = try await api.status()
            guard let scope = status.scopes.first(where: { $0.domain == domain && $0.week == week }) else { throw KitchenOSError.http(409) }
            try await checkAuthority()
            return try await api.setScope(ScopeRequest(domain: domain, week: week, destinationID: scope.destinationID, state: .archived, expectedRevision: scope.revision))
        case let .resolve(conflict, choice, revision):
            _ = try await api.resolve(ConflictResolution(conflictID: conflict, choice: choice, expectedRevision: revision))
            return try await synchronize()
        case .disconnect:
            let status = try await api.status()
            guard status.connected else { return status.report }
            let context = try await register()
            try await checkAuthority()
            let result = try await api.disconnect(context: context)
            knownOwnedCookingTokens.removeAll()
            return result
        case let .restore(token, revision):
            _ = try await api.restore(token: token, expectedRevision: revision)
            return try await synchronize()
        case let .removeOwned(selections): return try await remove(selections)
        }
    }
    private struct Totals {
        var created = 0; var updated = 0; var deleted = 0; var unavailable = 0
        mutating func add(_ report: SyncReport) {
            created += report.created; updated += report.updated; deleted += report.deleted
            recordAvailability(report)
        }
        mutating func recordAvailability(_ report: SyncReport) { unavailable = max(unavailable, report.unavailable) }
        func report(_ latest: SyncReport, pending: Bool = false) -> SyncReport {
            SyncReport(created: created, updated: updated, deleted: deleted, queued: max(latest.queued, pending ? 1 : 0),
                conflicts: latest.conflicts, unavailable: max(latest.unavailable, unavailable), lastSuccess: latest.lastSuccess)
        }
    }
    private func transient(_ error: Error) -> Bool {
        if let error = error as? KitchenOSError {
            switch error { case .unreachable: return true; case .http(let code): return code == 429 || code >= 500; default: return false }
        }
        return error is URLError
    }
    private func flushAcknowledgement(totals: inout Totals) async throws {
        guard let pending = pendingAcknowledgement else { return }
        let delays: [TimeInterval] = [1, 2, 4, 8, 16, 30]
        for attempt in 0...delays.count {
            try await checkAuthority()
            do {
                let result = try await api.acknowledge(pending.ack, context: pending.context)
                pendingAcknowledgement = nil
                totals.add(result); lastReport = result
                return
            } catch {
                try checkRunning()
                guard transient(error) else { throw error }
                guard attempt < delays.count else { throw AcknowledgementDeferred() }
                try await sleep(delays[attempt])
            }
        }
    }
    private func synchronize() async throws -> SyncReport {
        var totals = Totals()
        let delays: [TimeInterval] = [1, 2, 4, 8, 16, 30]
        for attempt in 0...delays.count {
            do {
                try checkRunning()
                let status = try await api.status(); lastReport = status.report
                guard status.configured, status.connected, !status.paused else {
                    if !status.connected { knownOwnedCookingTokens.removeAll() }
                    return totals.report(lastReport)
                }
                let context = try await register()
                // Changed acknowledgements request another complete pass, never a blind retry.
                for pass in 0..<3 {
                    var batch = try await freshWork(context, totals: &totals)
                    lastReport = batch.report
                    guard !batch.paused else { return totals.report(lastReport) }
                    let observationSerial = replaySerial
                    var allowed: [UUID: ScanVersion] = [:]; var blocked: Set<UUID> = []
                    for domain in AppleDomain.allCases {
                        let items = batch.items.filter { $0.domain == domain }
                        guard !items.isEmpty else { continue }
                        let (values, unavailable) = try await observations(for: items)
                        blocked.formUnion(unavailable)
                        try await checkAuthority()
                        do {
                            _ = try await api.observe(values, context: context, requestID: UUID())
                            for item in items { allowed[item.token] = ScanVersion(generation: item.generation, revision: item.revision) }
                        } catch KitchenOSError.http(503) {
                            // Source recovery may fail before the server reserves its
                            // request journal. Fence through fresh work/replay before
                            // another domain submits a new request ID. An unfinished
                            // request that still cannot replay stops the pass safely.
                            blocked.formUnion(items.map(\.token))
                        }
                        batch = try await freshWork(context, totals: &totals)
                        lastReport = batch.report
                        guard !batch.paused else { return totals.report(lastReport) }
                    }
                    if observationSerial != replaySerial {
                        // A replay completed mid-pass. Discard every earlier Apple
                        // scan and restart, including healthy domains, before writes.
                        if pass == 2 { return totals.report(batch.report, pending: true) }
                        continue
                    }
                    totals.unavailable = max(totals.unavailable, blocked.count)
                    let operations = batch.operations
                    // Retained rows never enter ordinary observation envelopes. Pending
                    // explicit cleanup nevertheless needs a fresh owned-object scan.
                    let retained = batch.retainedItems.filter { item in operations.contains { $0.token == item.token && $0.action == .delete } }
                    for item in retained {
                        if let values = try? await store.observe([item]), values.count == 1, let value = values.first,
                           value.token == item.token, value.generation == item.generation, value.revision == item.revision,
                           value.availability == .present, value.issue == nil { allowed[item.token] = ScanVersion(generation: item.generation, revision: item.revision) }
                        else { totals.unavailable += 1 }
                    }
                    let changed = try await apply(operations, context: context, allowed: allowed, blocked: blocked, totals: &totals)
                    if !changed || pass == 2 {
                        lastReport = try await api.status().report
                        return totals.report(lastReport, pending: changed)
                    }
                }
            } catch is AcknowledgementDeferred {
                totals.unavailable = max(1, totals.unavailable)
                return totals.report(lastReport, pending: true)
            } catch {
                try checkRunning()
                guard transient(error) else { throw error }
                if attempt == delays.count {
                    totals.unavailable = max(1, totals.unavailable)
                    return totals.report(lastReport, pending: true)
                }
                try await sleep(delays[attempt])
            }
        }
        return totals.report(lastReport, pending: true)
    }
    private func freshWork(_ context: BridgeContext, totals: inout Totals) async throws -> WorkBatch {
        var batch = try await api.work(context: context)
        totals.recordAvailability(batch.report)
        guard batch.context == context else { throw KitchenOSError.http(409) }
        // One unfinished request is permitted by the bridge. A repeated unfinished
        // request after successful replay is surfaced for review, not looped forever.
        if !batch.retryRequests.isEmpty {
            for request in batch.retryRequests {
                try await checkAuthority()
                _ = try await api.observe(request.observations, context: context, requestID: request.requestID)
            }
            batch = try await api.work(context: context)
            totals.recordAvailability(batch.report)
            guard batch.context == context, batch.retryRequests.isEmpty else { throw KitchenOSError.http(409) }
            replaySerial += 1
        }
        knownOwnedCookingTokens = Set((batch.items + batch.retainedItems).filter { $0.domain == .cooking }.map(\.token))
        return batch
    }
    private func observations(for items: [SyncItem]) async throws -> ([Observation], Set<UUID>) {
        var values: [Observation] = []; var blocked: Set<UUID> = []
        for domain in AppleDomain.allCases {
            let group = items.filter { $0.domain == domain }
            guard !group.isEmpty else { continue }
            let fresh: [Observation]
            do {
                fresh = try await store.observe(group)
                guard fresh.count == group.count, Set(fresh.map(\.token)) == Set(group.map(\.token)) else { throw AppleIntegrationError.identityAmbiguous }
            } catch {
                try checkRunning()
                values += group.map { Observation(token: $0.token, generation: $0.generation, revision: $0.revision,
                    availability: .unavailable, locator: nil, title: nil, fields: AppleFields(), absenceConfirmed: false, issue: nil) }
                blocked.formUnion(group.map(\.token)); continue
            }
            for value in fresh {
                guard let item = group.first(where: { $0.token == value.token }), item.generation == value.generation, item.revision == value.revision else { throw AppleIntegrationError.identityAmbiguous }
                // A complete no-match scan of a never-linked item permits the adapter's
                // fresh first-create scan. Unavailable scans and issues never qualify.
                if item.locator == nil, item.commonFields == nil, value.availability == .missing,
                   !value.absenceConfirmed, value.issue == nil { continue }
                values.append(value)
                if value.availability != .present || value.issue != nil { blocked.insert(value.token) }
            }
        }
        return (values, blocked)
    }
    private func apply(_ operations: [AppleOperation], context: BridgeContext, allowed: [UUID: ScanVersion], blocked: Set<UUID>, totals: inout Totals) async throws -> Bool {
        var changed = false
        for operation in operations where !blocked.contains(operation.token) {
            guard allowed[operation.token] == ScanVersion(generation: operation.generation, revision: operation.revision) else { changed = true; continue }
            try await checkAuthority()
            // Source/owner/scope may have changed while earlier items were saving.
            // Never execute an operation merely because an older response carried it.
            let current = try await api.work(context: context)
            totals.recordAvailability(current.report)
            guard current.context == context, !current.paused, current.retryRequests.isEmpty else { return true }
            guard current.operations.contains(operation) else { changed = true; continue }
            try await checkAuthority()
            let ack: OperationAck
            do { ack = try await store.apply(operation) }
            catch {
                try checkRunning()
                ack = OperationAck(operationID: operation.operationID, outcome: .failed, locator: nil, observedFields: AppleFields(), observedHash: nil)
            }
            if ack.outcome == .saved || ack.outcome == .deleted {
                pendingAcknowledgement = PendingAcknowledgement(ack: ack, context: context)
                try await flushAcknowledgement(totals: &totals)
            } else {
                // Changed/failed is not successful mutation proof and must never
                // become an automatic retry of an explicitly selected deletion.
                let result = try await api.acknowledge(ack, context: context)
                totals.add(result); lastReport = result
            }
            if ack.outcome == .changed { changed = true }
            if ack.outcome == .failed { totals.unavailable += 1 }
        }
        return changed
    }
    private func remove(_ selections: [AppleOwnedSelection]) async throws -> SyncReport {
        var totals = Totals()
        guard !selections.isEmpty, selections.count <= 5000, Set(selections.map(\.token)).count == selections.count else { throw AppleIntegrationError.invalidFields }
        let status = try await api.status()
        guard status.connected, !status.paused else { throw AppleIntegrationError.unavailable }
        let context = try await register(); let batch = try await freshWork(context, totals: &totals)
        guard !batch.paused else { throw AppleIntegrationError.unavailable }
        let candidates = batch.items + batch.retainedItems
        var removals: [OwnedRemovalItem] = []
        for selected in selections {
            guard let item = candidates.first(where: { $0.token == selected.token }), item.revision == selected.revision else { throw KitchenOSError.http(409) }
            let values = try await store.observe([item])
            guard values.count == 1, let value = values.first, value.token == item.token,
                  value.generation == item.generation, value.revision == item.revision,
                  value.availability == .present, value.issue == nil else { throw AppleIntegrationError.identityAmbiguous }
            removals.append(OwnedRemovalItem(token: item.token, expectedRevision: item.revision, observation: value))
        }
        try await checkAuthority()
        let operations = try await api.removeOwned(removals, context: context, requestID: UUID())
        let allowed = Dictionary(uniqueKeysWithValues: removals.map {
            ($0.token, ScanVersion(generation: $0.observation.generation, revision: $0.observation.revision))
        })
        let changed: Bool
        do { changed = try await apply(operations, context: context, allowed: allowed, blocked: [], totals: &totals) }
        catch is AcknowledgementDeferred {
            totals.unavailable = max(1, totals.unavailable)
            return totals.report(lastReport, pending: true)
        }
        if changed { totals.unavailable += 1 }
        // A changed delete needs a fresh explicit selection, especially for retained
        // generations that cannot enter the ordinary observation endpoint.
        return totals.report(try await api.status().report, pending: changed)
    }
}

/// App lifetime scheduler. Window views never own this object or its periodic task.
@MainActor public final class AppleIntegrationLifecycle {
    private let sleep: @Sendable (TimeInterval) async throws -> Void
    private let action: @MainActor (AppleIntegrationTrigger) async -> Void
    private var periodic: Task<Void, Never>?
    private var debounce: Task<Void, Never>?
    private var immediate: [UUID: Task<Void, Never>] = [:]
    private var epoch = UUID()
    private var running = false
    public init(sleep: @escaping @Sendable (TimeInterval) async throws -> Void = { try await Task.sleep(for: .seconds($0)) },
                action: @escaping @MainActor (AppleIntegrationTrigger) async -> Void) {
        self.sleep = sleep; self.action = action
    }
    public func start() {
        guard !running else { return }
        running = true; epoch = UUID(); let current = epoch
        periodic = Task { [weak self] in
            guard let self else { return }
            await self.action(.launch)
            while self.running && self.epoch == current && !Task.isCancelled {
                do { try await self.sleep(300) } catch { return }
                guard self.running, self.epoch == current, !Task.isCancelled else { return }
                await self.action(.periodic)
            }
        }
    }
    public func notify(_ trigger: AppleIntegrationTrigger) {
        guard running else { return }
        let current = epoch
        if trigger == .eventStoreChanged {
            debounce?.cancel()
            debounce = Task { [weak self] in
                guard let self else { return }
                do { try await self.sleep(0.25) } catch { return }
                guard self.running, self.epoch == current, !Task.isCancelled else { return }
                await self.action(trigger)
            }
        } else {
            let id = UUID()
            immediate[id] = Task { [weak self] in
                guard let self else { return }
                defer { self.immediate.removeValue(forKey: id) }
                guard self.running, self.epoch == current, !Task.isCancelled else { return }
                await self.action(trigger)
            }
        }
    }
    public func stop() {
        running = false; epoch = UUID()
        periodic?.cancel(); periodic = nil; debounce?.cancel(); debounce = nil
        for task in immediate.values { task.cancel() }; immediate.removeAll()
    }
}
