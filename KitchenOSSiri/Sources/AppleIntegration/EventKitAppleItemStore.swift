#if os(macOS)
import Foundation
import EventKit
import KitchenOSKit

/// DTO-only main actor facade. Task 7 owns its lifetime and the refresh loop.
@MainActor final class EventKitAppleItemStore: AppleItemStore {
    private let worker = EventKitWorker()
    func authorization(for domain: AppleDomain) -> AppleAuthorization { EventKitWorker.authorization(domain) }
    func requestAccess(for domain: AppleDomain) async throws -> AppleAuthorization {
        try await worker.perform { worker, finish in worker.requestAccess(domain, finish: finish) }
    }
    func destinations(for domain: AppleDomain) async throws -> [AppleDestination] {
        try await worker.perform { worker, finish in
            finish(Result { try worker.requireAccess(domain); return worker.store.calendars(for: EventKitWorker.entity(domain)).filter(\.allowsContentModifications).map { AppleDestination(id: $0.calendarIdentifier, title: $0.title) } })
        }
    }
    func availabilityCalendars() async throws -> [AppleDestination] {
        try await worker.perform { worker, finish in
            finish(Result {
                try worker.requireAccess(.cooking)
                return worker.store.calendars(for: .event).map {
                    AppleDestination(id: $0.calendarIdentifier, title: "\($0.title) — \($0.source.title)")
                }
            })
        }
    }
    func createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination {
        try await worker.perform { worker, finish in finish(Result { try worker.createDestination(name: name, domain: domain) }) }
    }
    func observe(_ items: [SyncItem]) async throws -> [Observation] {
        try await worker.perform { worker, finish in worker.observe(items, finish: finish) }
    }
    func apply(_ operation: AppleOperation) async throws -> OperationAck {
        try await worker.perform { worker, finish in worker.apply(operation, finish: finish) }
    }
    func availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) async throws -> PlanningCalendarSnapshot {
        try await worker.perform { worker, finish in finish(Result { try worker.availabilitySnapshot(firmID: firmID, flexibleID: flexibleID, excludingOwnedTokens: excludingOwnedTokens) }) }
    }
}

/// One serial queue owns the sole store and every EventKit instance. Jobs remain
/// serialized across asynchronous reminder/permission callbacks, unlike a reentrant
/// actor method. Only Sendable DTO results leave this worker.
private final class EventKitWorker: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.kitchenos.apple-items", qos: .utility)
    private var jobs: [() -> Void] = []
    private var busy = false
    fileprivate lazy var store = EKEventStore()
    private var visibleAtObservation: [UUID: Set<String>] = [:]
    private var visibleLocators: [UUID: Locator] = [:]
    // Representation hints only, never cached authorization to write. Expected-hash
    // verification always reads current EventKit values. Preserve the last observed
    // alias when the proposed operation changes its target timezone.
    private var wireReferences: [UUID: AppleFields] = [:]

    static func entity(_ domain: AppleDomain) -> EKEntityType { domain == .cooking ? .event : .reminder }
    static func authorization(_ domain: AppleDomain) -> AppleAuthorization {
        switch EKEventStore.authorizationStatus(for: entity(domain)) {
        case .notDetermined: return .notDetermined
        case .restricted: return .restricted
        case .denied: return .denied
        case .fullAccess: return .authorized
        case .writeOnly: return .writeOnly
        @unknown default: return .unavailable
        }
    }
    func perform<T: Sendable>(_ body: @escaping (EventKitWorker, @escaping (Result<T, Error>) -> Void) -> Void) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                self.jobs.append {
                    body(self) { result in
                        dispatchPrecondition(condition: .onQueue(self.queue))
                        continuation.resume(with: result)
                        self.busy = false; self.next()
                    }
                }
                self.next()
            }
        }
    }
    private func next() {
        guard !busy, !jobs.isEmpty else { return }
        busy = true; jobs.removeFirst()()
    }
    func requireAccess(_ domain: AppleDomain) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        guard Self.authorization(domain) == .authorized else { throw AppleIntegrationError.unavailable }
    }
    func requestAccess(_ domain: AppleDomain, finish: @escaping (Result<AppleAuthorization, Error>) -> Void) {
        let completion: @Sendable (Bool, Error?) -> Void = { _, error in
            self.queue.async {
                if let error { finish(.failure(error)); return }
                self.store.reset()
                self.visibleAtObservation.removeAll(); self.visibleLocators.removeAll(); self.wireReferences.removeAll()
                finish(.success(Self.authorization(domain)))
            }
        }
        if domain == .cooking { store.requestFullAccessToEvents(completion: completion) }
        else { store.requestFullAccessToReminders(completion: completion) }
    }
    func createDestination(name: String, domain: AppleDomain) throws -> AppleDestination {
        try requireAccess(domain)
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw AppleIntegrationError.invalidFields }
        let type = Self.entity(domain)
        // Use the user's default account, never silently select an arbitrary provider.
        let defaultCalendar = domain == .cooking ? store.defaultCalendarForNewEvents : store.defaultCalendarForNewReminders()
        guard let source = defaultCalendar?.source else { throw AppleIntegrationError.unavailable }
        let calendar = EKCalendar(for: type, eventStore: store)
        calendar.title = name; calendar.source = source
        try store.saveCalendar(calendar, commit: true)
        return AppleDestination(id: calendar.calendarIdentifier, title: calendar.title)
    }

    private struct Scan {
        let items: [EKCalendarItem]
        let calendars: Set<String>
        let complete: Bool
    }
    /// Includes completed/undated reminders in every currently visible destination.
    /// For events, query the calendar year before/after each known start and today.
    /// Deduplicate by year; each query spans three years, below EventKit’s four-year cap.
    /// These finite scans recover moved objects but cannot establish global absence.
    private func scan(domain: AppleDomain, dates: [String], finish: @escaping (Scan?) -> Void) {
        guard Self.authorization(domain) == .authorized else { finish(nil); return }
        let calendars = store.calendars(for: Self.entity(domain))
        let ids = Set(calendars.map(\.calendarIdentifier))
        guard !calendars.isEmpty else { finish(nil); return }
        if domain == .cooking {
            var gregorian = Calendar(identifier: .gregorian); gregorian.timeZone = TimeZone(secondsFromGMT: 0)!
            let centers = [Date()] + dates.compactMap { try? AppleFields.instant($0) }
            var items: [String: EKCalendarItem] = [:]
            let years = Set(centers.map { gregorian.component(.year, from: $0) })
            for year in years.sorted() {
                guard let start = gregorian.date(from: DateComponents(year: year - 1, month: 1, day: 1)),
                      let end = gregorian.date(from: DateComponents(year: year + 2, month: 1, day: 1)) else { finish(nil); return }
                let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
                for event in store.events(matching: predicate) { items[event.calendarItemIdentifier] = event }
            }
            finish(Scan(items: Array(items.values), calendars: ids, complete: Self.authorization(domain) == .authorized))
        } else {
            var finished = false
            let predicate = store.predicateForReminders(in: calendars)
            let request = store.fetchReminders(matching: predicate) { reminders in
                self.queue.async {
                    guard !finished else { return }; finished = true
                    guard let reminders, Self.authorization(domain) == .authorized,
                          ids == Set(self.store.calendars(for: .reminder).map(\.calendarIdentifier)) else { finish(nil); return }
                    finish(Scan(items: reminders, calendars: ids, complete: true))
                }
            }
            queue.asyncAfter(deadline: .now() + 30) {
                guard !finished else { return }; finished = true
                self.store.cancelFetchRequest(request)
                finish(nil)
            }
        }
    }
    private func ownership(_ object: EKCalendarItem) -> Set<UUID> { AppleOwnership.tokens(url: object.url, notes: object.notes) }
    private func locator(_ object: EKCalendarItem) -> Locator {
        Locator(calendarID: object.calendar.calendarIdentifier, itemID: object.calendarItemIdentifier, externalID: object.calendarItemExternalIdentifier)
    }
    private func matching(token: UUID, domain: AppleDomain, prior: Locator?, scan: Scan) -> (AppleLookupDecision, EKCalendarItem?) {
        var candidates: [String: EKCalendarItem] = [:]
        var identityLost = false
        func consider(_ object: EKCalendarItem, fromLocator: Bool) {
            let markers = ownership(object)
            let correctType = domain == .cooking ? object is EKEvent : object is EKReminder
            if markers.contains(token), markers.count == 1, correctType {
                candidates[object.calendarItemIdentifier] = object
            } else if markers.contains(token) || fromLocator { identityLost = true }
        }
        // Identifiers have no date bounds: recover an event even years outside its week.
        if let prior {
            if let object = store.calendarItem(withIdentifier: prior.itemID) { consider(object, fromLocator: true) }
            if let external = prior.externalID {
                for object in store.calendarItems(withExternalIdentifier: external) { consider(object, fromLocator: true) }
            }
        }
        for object in scan.items { consider(object, fromLocator: false) }
        if identityLost { return (.ambiguous, nil) }
        let visible = prior == nil || scan.calendars.contains(prior!.calendarID) || !candidates.isEmpty
        // Reminder deletion is only inferred within this process, following a verified
        // previous observation with unchanged visibility and the same locator. A cold
        // restart, erased marker, or lost source remains unavailable.
        let previousVisible = visibleAtObservation[token]
        let reminderComplete = prior == nil || (previousVisible == scan.calendars && visibleLocators[token] == prior)
        let decision = AppleLookupDecision.resolve(domain: domain, hadLocator: prior != nil, matches: candidates.count,
            readable: visible, complete: scan.complete && (domain == .cooking || reminderComplete))
        return (decision, candidates.values.first)
    }
    private func fields(_ object: EKCalendarItem, reference: AppleFields? = nil) throws -> AppleFields {
        if let reminder = object as? EKReminder {
            return try AppleFieldMapping.reminder(completed: reminder.isCompleted, dueComponents: reminder.dueDateComponents, reference: reference)
        }
        guard let event = object as? EKEvent, !event.isAllDay,
              let zone = event.timeZone, let start = event.startDate, let end = event.endDate else { throw AppleIntegrationError.invalidFields }
        return try AppleFieldMapping.cooking(start: start, end: end, timezone: zone, reference: reference)
    }
    private func issue(_ object: EKCalendarItem) -> AppleObservationIssue? {
        if object.hasRecurrenceRules { return .unsupportedRecurrence }
        if let event = object as? EKEvent, event.isAllDay { return .unsupportedAllDay }
        if (try? fields(object)) == nil { return .identityAmbiguous }
        return nil
    }
    func observe(_ items: [SyncItem], finish: @escaping (Result<[Observation], Error>) -> Void) {
        guard items.count <= 5000, Set(items.map(\.token)).count == items.count else { finish(.failure(AppleIntegrationError.batchTooLarge)); return }
        var observations: [UUID: Observation] = [:]
        let groups: [(AppleDomain, [SyncItem])] = [(.shopping, items.filter { $0.domain != .cooking }), (.cooking, items.filter { $0.domain == .cooking })]
        func process(_ index: Int) {
            guard index < groups.count else { finish(.success(items.compactMap { observations[$0.token] })); return }
            let (domain, group) = groups[index]
            guard !group.isEmpty else { process(index + 1); return }
            scan(domain: domain, dates: group.compactMap { $0.fields.start }) { scan in
                for item in group {
                    var availability: AppleAvailability = .unavailable
                    var objectLocator: Locator?; var title: String?; var observed = AppleFields()
                    var confirmed = false; var problem: AppleObservationIssue?
                    var hasUserNotes: Bool?
                    if let scan {
                        let (decision, object) = self.matching(token: item.token, domain: item.domain, prior: item.locator, scan: scan)
                        switch decision {
                        case .present:
                            if let object {
                                availability = .present; objectLocator = self.locator(object); title = object.title ?? ""
                                problem = self.issue(object)
                                hasUserNotes = AppleOwnership.hasUserNotes(object.notes) ? true : nil
                                // Common fields retain the previously observed wire spelling;
                                // a first-save recovery has only its original source fields.
                                observed = (try? self.fields(object, reference: item.commonFields ?? item.fields)) ?? AppleFields()
                                if problem == nil { self.wireReferences[item.token] = observed }
                                self.visibleAtObservation[item.token] = scan.calendars; self.visibleLocators[item.token] = objectLocator
                            }
                        case .missing: availability = .missing; confirmed = true
                        case .newItem: availability = .missing // Never assert an external deletion for a first export.
                        case .ambiguous: problem = .identityAmbiguous
                        case .unavailable: break
                        }
                    }
                    observations[item.token] = Observation(token: item.token, generation: item.generation, revision: item.revision,
                        availability: availability, locator: objectLocator, title: title, fields: observed,
                        absenceConfirmed: confirmed, issue: problem, hasUserNotes: hasUserNotes)
                }
                process(index + 1)
            }
        }
        process(0)
    }
    private func ack(_ operation: AppleOperation, outcome: AppleAckOutcome, object: EKCalendarItem? = nil) -> OperationAck {
        let reference = outcome == .saved ? operation.fields : (wireReferences[operation.token] ?? operation.fields)
        let values = object.flatMap { try? fields($0, reference: reference) } ?? AppleFields()
        return OperationAck(operationID: operation.operationID, outcome: outcome, locator: object.map(locator), observedFields: values,
            observedHash: object.flatMap { try? values.canonicalHash(title: $0.title ?? "") })
    }
    func apply(_ operation: AppleOperation, finish: @escaping (Result<OperationAck, Error>) -> Void) {
        let domain: AppleDomain = operation.fields.start != nil ? .cooking : .shopping
        scan(domain: domain, dates: [operation.fields.start].compactMap { $0 }) { scan in
            guard let scan else { finish(.success(self.ack(operation, outcome: .failed))); return }
            let (decision, found) = self.matching(token: operation.token, domain: domain, prior: operation.locator, scan: scan)
            do {
                try self.requireAccess(domain)
                let object: EKCalendarItem
                switch decision {
                case .present:
                    // Re-resolve immediately before any mutation; never save a cached
                    // event that another process deleted (EventKit can recreate it).
                    guard let found, let fresh = self.store.calendarItem(withIdentifier: found.calendarItemIdentifier),
                          fresh.refresh(), self.ownership(fresh) == [operation.token], self.issue(fresh) == nil else {
                        finish(.success(self.ack(operation, outcome: .changed))); return
                    }
                    guard let expected = operation.expectedAppleHash,
                          try self.fields(fresh, reference: self.wireReferences[operation.token] ?? operation.fields).canonicalHash(title: fresh.title ?? "") == expected else {
                        finish(.success(self.ack(operation, outcome: .changed, object: fresh))); return
                    }
                    object = fresh
                case .newItem:
                    // Controller-approved first-export policy: never-located token only,
                    // after all available finite recovery scans. No global Calendar proof
                    // exists; an interrupted first save moved beyond these windows remains
                    // a documented residual duplicate risk.
                    guard operation.action == .upsert, operation.locator == nil, operation.expectedAppleHash == nil,
                          let destination = self.store.calendar(withIdentifier: operation.destinationID),
                          destination.allowedEntityTypes.contains(domain == .cooking ? .event : .reminder), destination.allowsContentModifications else {
                        finish(.success(self.ack(operation, outcome: .failed))); return
                    }
                    object = domain == .cooking ? EKEvent(eventStore: self.store) : EKReminder(eventStore: self.store)
                    object.calendar = destination
                    object.url = AppleOwnership.url(for: operation.token)
                case .ambiguous, .missing, .unavailable:
                    finish(.success(self.ack(operation, outcome: .changed))); return
                }
                guard object.calendar.allowsContentModifications else { finish(.success(self.ack(operation, outcome: .failed))); return }
                if operation.action == .delete {
                    // Only the freshly resolved unique object above can reach removal.
                    guard !AppleOwnership.hasUserNotes(object.notes) else {
                        finish(.success(self.ack(operation, outcome: .changed, object: object))); return
                    }
                    if let reminder = object as? EKReminder { try self.store.remove(reminder, commit: true) }
                    else if let event = object as? EKEvent { try self.store.remove(event, span: .thisEvent, commit: true) }
                    self.visibleAtObservation.removeValue(forKey: operation.token); self.visibleLocators.removeValue(forKey: operation.token)
                    self.wireReferences.removeValue(forKey: operation.token)
                    finish(.success(self.ack(operation, outcome: .deleted))); return
                }
                try self.update(object, operation: operation)
                // Persisted fields, rather than the proposed DTO, determine the ack.
                guard let saved = self.store.calendarItem(withIdentifier: object.calendarItemIdentifier),
                      self.ownership(saved) == [operation.token], self.issue(saved) == nil else {
                    finish(.success(self.ack(operation, outcome: .failed))); return
                }
                self.visibleAtObservation[operation.token] = scan.calendars; self.visibleLocators[operation.token] = self.locator(saved)
                let persisted = try self.fields(saved, reference: operation.fields)
                let expected = try operation.fields.canonicalHash(title: operation.title)
                guard try persisted.canonicalHash(title: saved.title ?? "") == expected else {
                    finish(.success(self.ack(operation, outcome: .changed, object: saved))); return
                }
                self.wireReferences[operation.token] = persisted
                finish(.success(self.ack(operation, outcome: .saved, object: saved)))
            } catch { finish(.failure(error)) }
        }
    }
    private func update(_ object: EKCalendarItem, operation: AppleOperation) throws {
        // The server carries a user's title override in operation.title. Notes, URL,
        // alarms, start components and every unmanaged field stay on the same object.
        let value = operation.fields
        if let reminder = object as? EKReminder {
            guard let completed = value.completed, value.hasDue, value.start == nil else { throw AppleIntegrationError.invalidFields }
            let due = try value.due?.dateComponents()
            reminder.title = operation.title; reminder.isCompleted = completed; reminder.dueDateComponents = due
            try store.save(reminder, commit: true)
        } else if let event = object as? EKEvent {
            guard let start = value.start, let timezone = value.timezone, let duration = value.durationMinutes,
                  let zone = TimeZone(identifier: timezone), value.completed == nil, !value.hasDue else { throw AppleIntegrationError.invalidFields }
            try value.validate()
            let instant = try AppleFields.instant(start)
            event.title = operation.title; event.startDate = instant
            event.endDate = instant.addingTimeInterval(Double(duration) * 60); event.timeZone = zone; event.isAllDay = false
            try store.save(event, span: .thisEvent, commit: true)
        } else { throw AppleIntegrationError.invalidFields }
    }
    func availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) throws -> PlanningCalendarSnapshot {
        try requireAccess(.cooking)
        guard firmID != flexibleID, let firm = store.calendar(withIdentifier: firmID), let flexible = store.calendar(withIdentifier: flexibleID),
              firm.allowedEntityTypes.contains(.event), flexible.allowedEntityTypes.contains(.event) else { throw AppleIntegrationError.unavailable }
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = .current
        let generatedAt = Date(); let start = calendar.startOfDay(for: generatedAt)
        guard let end = calendar.date(byAdding: .day, value: 35, to: start) else { throw AppleIntegrationError.invalidDate }
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [firm, flexible])
        let events = try store.events(matching: predicate).filter {
            $0.status != .canceled && $0.availability != .free &&
            !AppleOwnership.excludesFromAvailability(url: $0.url, notes: $0.notes, excludingOwnedTokens: excludingOwnedTokens) &&
            !($0.attendees?.contains(where: { $0.isCurrentUser && $0.participantStatus == .declined }) ?? false)
        }.map {
            try PlanningCalendarEvent(calendarID: $0.calendar.calendarIdentifier,
                eventID: $0.calendarItemExternalIdentifier ?? $0.calendarItemIdentifier, title: $0.title ?? "Untitled event",
                start: $0.startDate, end: $0.endDate, allDay: $0.isAllDay, flexible: $0.calendar.calendarIdentifier == flexibleID, timezone: calendar.timeZone)
        }
        try requireAccess(.cooking)
        let formatter = DateFormatter(); formatter.calendar = calendar; formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone; formatter.dateFormat = "yyyy-MM-dd"
        return try PlanningCalendarSnapshot(firmID: firmID, flexibleID: flexibleID, generatedAt: generatedAt, timezone: calendar.timeZone.identifier,
            coverageStart: formatter.string(from: start), coverageEnd: formatter.string(from: end), events: events)
    }
}
#endif
