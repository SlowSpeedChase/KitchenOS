import Foundation
import CryptoKit

public enum AppleDomain: String, Codable, Sendable, CaseIterable { case shopping, prep, cooking }
public enum AppleAuthorization: String, Codable, Sendable {
    case unknown, notDetermined = "not_determined", denied, restricted, authorized, writeOnly = "write_only", unavailable
}
public enum AppleItemState: String, Codable, Sendable { case active, retired, history, conflict, suppressed }
public enum AppleScopeState: String, Codable, Sendable { case active, paused, archived }
public enum AppleAvailability: String, Codable, Sendable { case present, missing, unavailable }
public enum AppleObservationIssue: String, Codable, Sendable {
    case unsupportedAllDay = "unsupported_all_day", unsupportedRecurrence = "unsupported_recurrence", identityAmbiguous = "identity_ambiguous"
}
public enum AppleAction: String, Codable, Sendable { case upsert, delete }
public enum AppleAckOutcome: String, Codable, Sendable { case saved, deleted, changed, failed }
public enum AppleConflictChoice: String, Codable, Sendable {
    case keepKitchenOS = "keep_kitchenos", keepApple = "keep_apple", keepManual = "keep_manual", restore
}
public enum AppleIntegrationError: Error { case invalidDate, invalidFields, unsupportedVersion, unavailable, identityAmbiguous, batchTooLarge }

/// A civil due value, never a UTC-midnight surrogate. Repeated DST hours remain
/// civil values; this wire contract cannot distinguish their two instants.
public struct DueValue: Codable, Sendable, Equatable {
    public let date: String
    public let time: String?
    public let timezone: String?
    enum CodingKeys: String, CodingKey { case date, time, timezone }
    public init(date: String, time: String? = nil, timezone: String? = nil) throws {
        self.date = date; self.time = time; self.timezone = timezone
        _ = try dateComponents()
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(date: c.decode(String.self, forKey: .date), time: c.decode(Optional<String>.self, forKey: .time), timezone: c.decode(Optional<String>.self, forKey: .timezone))
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(date, forKey: .date); try c.encode(time, forKey: .time); try c.encode(timezone, forKey: .timezone)
    }
    public func dateComponents() throws -> DateComponents {
        guard date.range(of: #"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"#, options: .regularExpression) != nil else { throw AppleIntegrationError.invalidDate }
        let parts = date.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, parts[0] > 0, (time == nil) == (timezone == nil) else { throw AppleIntegrationError.invalidDate }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var components = DateComponents(year: parts[0], month: parts[1], day: parts[2])
        components.calendar = calendar
        if let time, let timezone {
            guard time.range(of: #"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"#, options: .regularExpression) != nil,
                  let zone = TimeZone(identifier: timezone) else { throw AppleIntegrationError.invalidDate }
            calendar.timeZone = zone; components.calendar = calendar; components.timeZone = zone
            let clock = time.split(separator: ":").compactMap { Int($0) }
            components.hour = clock[0]; components.minute = clock[1]; components.second = 0
        }
        guard let instant = calendar.date(from: components) else { throw AppleIntegrationError.invalidDate }
        let check = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: instant)
        guard check.year == components.year, check.month == components.month, check.day == components.day,
              components.hour == nil || (check.hour == components.hour && check.minute == components.minute) else { throw AppleIntegrationError.invalidDate }
        return components
    }
    public init(components: DateComponents) throws {
        guard let y = components.year, let m = components.month, let d = components.day,
              components.calendar == nil || components.calendar?.identifier == .gregorian else { throw AppleIntegrationError.invalidDate }
        let date = String(format: "%04d-%02d-%02d", y, m, d)
        if let hour = components.hour {
            guard let minute = components.minute, let zone = components.timeZone, (components.second ?? 0) == 0 else { throw AppleIntegrationError.invalidDate }
            try self.init(date: date, time: String(format: "%02d:%02d", hour, minute), timezone: zone.identifier)
        } else {
            guard components.minute == nil else { throw AppleIntegrationError.invalidDate }
            try self.init(date: date)
        }
    }
}

/// Partial fields preserve absent versus explicit-null due, needed for clearing.
public struct AppleFields: Codable, Sendable, Equatable {
    public var completed: Bool?
    public var due: DueValue?
    public var hasDue: Bool
    public var start: String?
    public var timezone: String?
    public var durationMinutes: Int?
    enum CodingKeys: String, CodingKey { case completed, due, start, timezone; case durationMinutes = "duration_minutes" }
    public init() { hasDue = false }
    public init(completed: Bool, due: DueValue?) { self.completed = completed; self.due = due; hasDue = true }
    public init(start: String, timezone: String, durationMinutes: Int) throws {
        self.start = start; self.timezone = timezone; self.durationMinutes = durationMinutes; hasDue = false
        try validate()
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        completed = try c.decodeIfPresent(Bool.self, forKey: .completed)
        hasDue = c.contains(.due); due = try c.decodeIfPresent(DueValue.self, forKey: .due)
        start = try c.decodeIfPresent(String.self, forKey: .start)
        timezone = try c.decodeIfPresent(String.self, forKey: .timezone)
        durationMinutes = try c.decodeIfPresent(Int.self, forKey: .durationMinutes)
        try validate()
    }
    public func encode(to encoder: Encoder) throws {
        try validate()
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(completed, forKey: .completed)
        if hasDue { try c.encode(due, forKey: .due) }
        try c.encodeIfPresent(start, forKey: .start); try c.encodeIfPresent(timezone, forKey: .timezone)
        try c.encodeIfPresent(durationMinutes, forKey: .durationMinutes)
    }
    public func validate() throws {
        if let start { _ = try Self.instant(start) }
        if let timezone, TimeZone(identifier: timezone) == nil { throw AppleIntegrationError.invalidDate }
        if let durationMinutes, !(15...360).contains(durationMinutes) || durationMinutes % 15 != 0 { throw AppleIntegrationError.invalidFields }
    }
    public static func instant(_ value: String) throws -> Date {
        guard value.range(of: #"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"#, options: .regularExpression) != nil else { throw AppleIntegrationError.invalidDate }
        // Foundation's ISO parser normalizes February 30 into March. Validate the
        // literal civil date before asking it to resolve the offset-bearing instant.
        _ = try DueValue(date: String(value.prefix(10)))
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        guard let date = formatter.date(from: value) else { throw AppleIntegrationError.invalidDate }
        return date
    }
    public func canonicalHash(title: String) throws -> String {
        struct Value: Encodable { let title: String; let fields: AppleFields }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return SHA256.hash(data: try encoder.encode(Value(title: title, fields: self))).map { String(format: "%02x", $0) }.joined()
    }
}

/// Pure boundary mapping shared by the EventKit worker and store-free tests.
/// The reference carries wire spelling; the snapshot supplies every actual value.
public enum AppleFieldMapping {
    public static func reminder(completed: Bool, dueComponents: DateComponents?, reference: AppleFields? = nil) throws -> AppleFields {
        let due = try dueComponents.map { components in
            let actual = try DueValue(components: components)
            guard let zone = components.timeZone, actual.time != nil else { return actual }
            return try DueValue(date: actual.date, time: actual.time,
                timezone: wireTimezone(zone, reference: reference?.due?.timezone))
        }
        return AppleFields(completed: completed, due: due)
    }
    public static func cooking(start: Date, end: Date, timezone: TimeZone, reference: AppleFields? = nil) throws -> AppleFields {
        let minutes = end.timeIntervalSince(start) / 60
        guard minutes.rounded() == minutes else { throw AppleIntegrationError.invalidFields }
        let formatter = ISO8601DateFormatter(); formatter.timeZone = timezone
        let formatted = formatter.string(from: start)
        // Python datetime.isoformat() uses an explicit zero offset, including London
        // in winter. Hashes and first-save recovery compare the exact wire spelling.
        let timestamp = formatted.hasSuffix("Z") ? String(formatted.dropLast()) + "+00:00" : formatted
        return try AppleFields(start: timestamp, timezone: wireTimezone(timezone, reference: reference?.timezone), durationMinutes: Int(minutes))
    }
    private static func wireTimezone(_ actual: TimeZone, reference: String?) -> String {
        // Foundation turns UTC into GMT. Retain the original wire alias only when
        // Foundation resolves it to this exact zone; matching today's offset would
        // incorrectly conceal a real change such as Europe/London -> GMT in winter.
        if let reference, TimeZone(identifier: reference)?.identifier == actual.identifier { return reference }
        return actual.identifier
    }
}

public struct SourceItem: Codable, Sendable, Equatable {
    public let logicalID: String
    public let domain: AppleDomain
    public let week: String
    public let title: String
    public let fields: AppleFields
    public let sourceRevision: String
    public let state: AppleItemState
    enum CodingKeys: String, CodingKey {
        case logicalID = "logical_id"
        case domain
        case week
        case title
        case fields
        case sourceRevision = "source_revision"
        case state
    }
    public init(logicalID: String, domain: AppleDomain, week: String, title: String, fields: AppleFields, sourceRevision: String, state: AppleItemState) {
        self.logicalID = logicalID
        self.domain = domain
        self.week = week
        self.title = title
        self.fields = fields
        self.sourceRevision = sourceRevision
        self.state = state
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        logicalID = try c.decode(String.self, forKey: .logicalID)
        domain = try c.decode(AppleDomain.self, forKey: .domain)
        week = try c.decode(String.self, forKey: .week)
        title = try c.decode(String.self, forKey: .title)
        fields = try c.decode(AppleFields.self, forKey: .fields)
        sourceRevision = try c.decode(String.self, forKey: .sourceRevision)
        state = try c.decode(AppleItemState.self, forKey: .state)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(logicalID, forKey: .logicalID)
        try c.encode(domain, forKey: .domain)
        try c.encode(week, forKey: .week)
        try c.encode(title, forKey: .title)
        try c.encode(fields, forKey: .fields)
        try c.encode(sourceRevision, forKey: .sourceRevision)
        try c.encode(state, forKey: .state)
    }
}

public struct Locator: Codable, Sendable, Equatable {
    public let calendarID: String
    public let itemID: String
    public let externalID: String?
    enum CodingKeys: String, CodingKey {
        case calendarID = "calendar_id"
        case itemID = "item_id"
        case externalID = "external_id"
    }
    public init(calendarID: String, itemID: String, externalID: String?) {
        self.calendarID = calendarID
        self.itemID = itemID
        self.externalID = externalID
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        calendarID = try c.decode(String.self, forKey: .calendarID)
        itemID = try c.decode(String.self, forKey: .itemID)
        externalID = try c.decode(Optional<String>.self, forKey: .externalID)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(calendarID, forKey: .calendarID)
        try c.encode(itemID, forKey: .itemID)
        try c.encode(externalID, forKey: .externalID)
    }
}

public struct BridgeContext: Codable, Sendable, Equatable {
    public let ownerID: UUID
    public let ownerGeneration: Int
    enum CodingKeys: String, CodingKey {
        case ownerID = "owner_id"
        case ownerGeneration = "owner_generation"
    }
    public init(ownerID: UUID, ownerGeneration: Int) {
        self.ownerID = ownerID
        self.ownerGeneration = ownerGeneration
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ownerID = try c.decode(UUID.self, forKey: .ownerID)
        ownerGeneration = try c.decode(Int.self, forKey: .ownerGeneration)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(ownerID.uuidString.lowercased(), forKey: .ownerID)
        try c.encode(ownerGeneration, forKey: .ownerGeneration)
    }
}

public struct SyncItem: Codable, Sendable, Equatable {
    public let logicalID: String
    public let domain: AppleDomain
    public let week: String
    public let title: String
    public let fields: AppleFields
    public let sourceRevision: String
    public let state: AppleItemState
    public let revision: Int
    public let generation: Int
    public let token: UUID
    public let destinationID: String
    public let locator: Locator?
    public let commonFields: AppleFields?
    enum CodingKeys: String, CodingKey {
        case logicalID = "logical_id"
        case domain
        case week
        case title
        case fields
        case sourceRevision = "source_revision"
        case state
        case revision
        case generation
        case token
        case destinationID = "destination_id"
        case locator
        case commonFields = "common_fields"
    }
    public init(logicalID: String, domain: AppleDomain, week: String, title: String, fields: AppleFields, sourceRevision: String, state: AppleItemState, revision: Int, generation: Int, token: UUID, destinationID: String, locator: Locator?, commonFields: AppleFields?) {
        self.logicalID = logicalID
        self.domain = domain
        self.week = week
        self.title = title
        self.fields = fields
        self.sourceRevision = sourceRevision
        self.state = state
        self.revision = revision
        self.generation = generation
        self.token = token
        self.destinationID = destinationID
        self.locator = locator
        self.commonFields = commonFields
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        logicalID = try c.decode(String.self, forKey: .logicalID)
        domain = try c.decode(AppleDomain.self, forKey: .domain)
        week = try c.decode(String.self, forKey: .week)
        title = try c.decode(String.self, forKey: .title)
        fields = try c.decode(AppleFields.self, forKey: .fields)
        sourceRevision = try c.decode(String.self, forKey: .sourceRevision)
        state = try c.decode(AppleItemState.self, forKey: .state)
        revision = try c.decode(Int.self, forKey: .revision)
        generation = try c.decode(Int.self, forKey: .generation)
        token = try c.decode(UUID.self, forKey: .token)
        destinationID = try c.decode(String.self, forKey: .destinationID)
        locator = try c.decode(Optional<Locator>.self, forKey: .locator)
        commonFields = try c.decode(Optional<AppleFields>.self, forKey: .commonFields)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(logicalID, forKey: .logicalID)
        try c.encode(domain, forKey: .domain)
        try c.encode(week, forKey: .week)
        try c.encode(title, forKey: .title)
        try c.encode(fields, forKey: .fields)
        try c.encode(sourceRevision, forKey: .sourceRevision)
        try c.encode(state, forKey: .state)
        try c.encode(revision, forKey: .revision)
        try c.encode(generation, forKey: .generation)
        try c.encode(token.uuidString.lowercased(), forKey: .token)
        try c.encode(destinationID, forKey: .destinationID)
        try c.encode(locator, forKey: .locator)
        try c.encode(commonFields, forKey: .commonFields)
    }
}

public struct Observation: Codable, Sendable, Equatable {
    public let token: UUID
    public let generation: Int
    public let revision: Int
    public let availability: AppleAvailability
    public let locator: Locator?
    public let title: String?
    public let fields: AppleFields
    public let absenceConfirmed: Bool
    public let issue: AppleObservationIssue?
    /// Nil preserves the exact shape of older unfinished observation requests.
    public let hasUserNotes: Bool?
    enum CodingKeys: String, CodingKey {
        case token
        case generation
        case revision
        case availability
        case locator
        case title
        case fields
        case absenceConfirmed = "absence_confirmed"
        case issue
        case hasUserNotes = "has_user_notes"
    }
    public init(token: UUID, generation: Int, revision: Int, availability: AppleAvailability, locator: Locator?, title: String?, fields: AppleFields, absenceConfirmed: Bool, issue: AppleObservationIssue?, hasUserNotes: Bool? = nil) {
        self.token = token
        self.generation = generation
        self.revision = revision
        self.availability = availability
        self.locator = locator
        self.title = title
        self.fields = fields
        self.absenceConfirmed = absenceConfirmed
        self.issue = issue
        self.hasUserNotes = hasUserNotes
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(UUID.self, forKey: .token)
        generation = try c.decode(Int.self, forKey: .generation)
        revision = try c.decode(Int.self, forKey: .revision)
        availability = try c.decode(AppleAvailability.self, forKey: .availability)
        locator = try c.decode(Optional<Locator>.self, forKey: .locator)
        title = try c.decode(Optional<String>.self, forKey: .title)
        fields = try c.decode(AppleFields.self, forKey: .fields)
        absenceConfirmed = try c.decode(Bool.self, forKey: .absenceConfirmed)
        issue = try c.decode(Optional<AppleObservationIssue>.self, forKey: .issue)
        hasUserNotes = try c.decodeIfPresent(Bool.self, forKey: .hasUserNotes)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(token.uuidString.lowercased(), forKey: .token)
        try c.encode(generation, forKey: .generation)
        try c.encode(revision, forKey: .revision)
        try c.encode(availability, forKey: .availability)
        try c.encode(locator, forKey: .locator)
        try c.encode(title, forKey: .title)
        try c.encode(fields, forKey: .fields)
        try c.encode(absenceConfirmed, forKey: .absenceConfirmed)
        try c.encode(issue, forKey: .issue)
        try c.encodeIfPresent(hasUserNotes, forKey: .hasUserNotes)
    }
}

public struct AppleOperation: Codable, Sendable, Equatable {
    public let operationID: UUID
    public let token: UUID
    public let generation: Int
    public let revision: Int
    public let action: AppleAction
    public let destinationID: String
    public let locator: Locator?
    public let title: String
    public let fields: AppleFields
    public let expectedAppleHash: String?
    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id"
        case token
        case generation
        case revision
        case action
        case destinationID = "destination_id"
        case locator
        case title
        case fields
        case expectedAppleHash = "expected_apple_hash"
    }
    public init(operationID: UUID, token: UUID, generation: Int, revision: Int, action: AppleAction, destinationID: String, locator: Locator?, title: String, fields: AppleFields, expectedAppleHash: String?) {
        self.operationID = operationID
        self.token = token
        self.generation = generation
        self.revision = revision
        self.action = action
        self.destinationID = destinationID
        self.locator = locator
        self.title = title
        self.fields = fields
        self.expectedAppleHash = expectedAppleHash
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        operationID = try c.decode(UUID.self, forKey: .operationID)
        token = try c.decode(UUID.self, forKey: .token)
        generation = try c.decode(Int.self, forKey: .generation)
        revision = try c.decode(Int.self, forKey: .revision)
        action = try c.decode(AppleAction.self, forKey: .action)
        destinationID = try c.decode(String.self, forKey: .destinationID)
        locator = try c.decode(Optional<Locator>.self, forKey: .locator)
        title = try c.decode(String.self, forKey: .title)
        fields = try c.decode(AppleFields.self, forKey: .fields)
        expectedAppleHash = try c.decode(Optional<String>.self, forKey: .expectedAppleHash)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(operationID.uuidString.lowercased(), forKey: .operationID)
        try c.encode(token.uuidString.lowercased(), forKey: .token)
        try c.encode(generation, forKey: .generation)
        try c.encode(revision, forKey: .revision)
        try c.encode(action, forKey: .action)
        try c.encode(destinationID, forKey: .destinationID)
        try c.encode(locator, forKey: .locator)
        try c.encode(title, forKey: .title)
        try c.encode(fields, forKey: .fields)
        try c.encode(expectedAppleHash, forKey: .expectedAppleHash)
    }
}

public struct OperationAck: Codable, Sendable, Equatable {
    public let operationID: UUID
    public let outcome: AppleAckOutcome
    public let locator: Locator?
    public let observedFields: AppleFields
    public let observedHash: String?
    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id"
        case outcome
        case locator
        case observedFields = "observed_fields"
        case observedHash = "observed_hash"
    }
    public init(operationID: UUID, outcome: AppleAckOutcome, locator: Locator?, observedFields: AppleFields, observedHash: String?) {
        self.operationID = operationID
        self.outcome = outcome
        self.locator = locator
        self.observedFields = observedFields
        self.observedHash = observedHash
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        operationID = try c.decode(UUID.self, forKey: .operationID)
        outcome = try c.decode(AppleAckOutcome.self, forKey: .outcome)
        locator = try c.decode(Optional<Locator>.self, forKey: .locator)
        observedFields = try c.decode(AppleFields.self, forKey: .observedFields)
        observedHash = try c.decode(Optional<String>.self, forKey: .observedHash)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(operationID.uuidString.lowercased(), forKey: .operationID)
        try c.encode(outcome, forKey: .outcome)
        try c.encode(locator, forKey: .locator)
        try c.encode(observedFields, forKey: .observedFields)
        try c.encode(observedHash, forKey: .observedHash)
    }
}

public struct ScopeRequest: Codable, Sendable, Equatable {
    public let domain: AppleDomain
    public let week: String
    public let destinationID: String
    public let state: AppleScopeState
    public let expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case domain
        case week
        case destinationID = "destination_id"
        case state
        case expectedRevision = "expected_revision"
    }
    public init(domain: AppleDomain, week: String, destinationID: String, state: AppleScopeState, expectedRevision: Int) {
        self.domain = domain
        self.week = week
        self.destinationID = destinationID
        self.state = state
        self.expectedRevision = expectedRevision
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        domain = try c.decode(AppleDomain.self, forKey: .domain)
        week = try c.decode(String.self, forKey: .week)
        destinationID = try c.decode(String.self, forKey: .destinationID)
        state = try c.decode(AppleScopeState.self, forKey: .state)
        expectedRevision = try c.decode(Int.self, forKey: .expectedRevision)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(domain, forKey: .domain)
        try c.encode(week, forKey: .week)
        try c.encode(destinationID, forKey: .destinationID)
        try c.encode(state, forKey: .state)
        try c.encode(expectedRevision, forKey: .expectedRevision)
    }
}

public struct AppleScope: Codable, Sendable, Equatable {
    public let domain: AppleDomain
    public let week: String
    public let destinationID: String
    public let status: AppleScopeState
    public let revision: Int
    enum CodingKeys: String, CodingKey {
        case domain
        case week
        case destinationID = "destination_id"
        case status
        case revision
    }
    public init(domain: AppleDomain, week: String, destinationID: String, status: AppleScopeState, revision: Int) {
        self.domain = domain
        self.week = week
        self.destinationID = destinationID
        self.status = status
        self.revision = revision
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        domain = try c.decode(AppleDomain.self, forKey: .domain)
        week = try c.decode(String.self, forKey: .week)
        destinationID = try c.decode(String.self, forKey: .destinationID)
        status = try c.decode(AppleScopeState.self, forKey: .status)
        revision = try c.decode(Int.self, forKey: .revision)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(domain, forKey: .domain)
        try c.encode(week, forKey: .week)
        try c.encode(destinationID, forKey: .destinationID)
        try c.encode(status, forKey: .status)
        try c.encode(revision, forKey: .revision)
    }
}

public struct SyncReport: Codable, Sendable, Equatable {
    public let created: Int
    public let updated: Int
    public let deleted: Int
    public let queued: Int
    public let conflicts: Int
    public let unavailable: Int
    public let lastSuccess: String?
    enum CodingKeys: String, CodingKey {
        case created
        case updated
        case deleted
        case queued
        case conflicts
        case unavailable
        case lastSuccess = "last_success"
    }
    public init(created: Int, updated: Int, deleted: Int, queued: Int, conflicts: Int, unavailable: Int, lastSuccess: String?) {
        self.created = created
        self.updated = updated
        self.deleted = deleted
        self.queued = queued
        self.conflicts = conflicts
        self.unavailable = unavailable
        self.lastSuccess = lastSuccess
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = try c.decode(Int.self, forKey: .created)
        updated = try c.decode(Int.self, forKey: .updated)
        deleted = try c.decode(Int.self, forKey: .deleted)
        queued = try c.decode(Int.self, forKey: .queued)
        conflicts = try c.decode(Int.self, forKey: .conflicts)
        unavailable = try c.decode(Int.self, forKey: .unavailable)
        lastSuccess = try c.decode(Optional<String>.self, forKey: .lastSuccess)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(created, forKey: .created)
        try c.encode(updated, forKey: .updated)
        try c.encode(deleted, forKey: .deleted)
        try c.encode(queued, forKey: .queued)
        try c.encode(conflicts, forKey: .conflicts)
        try c.encode(unavailable, forKey: .unavailable)
        try c.encode(lastSuccess, forKey: .lastSuccess)
    }
}

public struct ConflictSummary: Codable, Sendable, Equatable {
    public let conflictID: UUID
    public let token: UUID
    public let field: String
    public let revision: Int
    enum CodingKeys: String, CodingKey {
        case conflictID = "conflict_id"
        case token
        case field
        case revision
    }
    public init(conflictID: UUID, token: UUID, field: String, revision: Int) {
        self.conflictID = conflictID
        self.token = token
        self.field = field
        self.revision = revision
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conflictID = try c.decode(UUID.self, forKey: .conflictID)
        token = try c.decode(UUID.self, forKey: .token)
        field = try c.decode(String.self, forKey: .field)
        revision = try c.decode(Int.self, forKey: .revision)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(conflictID.uuidString.lowercased(), forKey: .conflictID)
        try c.encode(token.uuidString.lowercased(), forKey: .token)
        try c.encode(field, forKey: .field)
        try c.encode(revision, forKey: .revision)
    }
}

public struct ConflictResolution: Codable, Sendable, Equatable {
    public let conflictID: UUID
    public let choice: AppleConflictChoice
    public let expectedRevision: Int
    enum CodingKeys: String, CodingKey {
        case conflictID = "conflict_id"
        case choice
        case expectedRevision = "expected_revision"
    }
    public init(conflictID: UUID, choice: AppleConflictChoice, expectedRevision: Int) {
        self.conflictID = conflictID
        self.choice = choice
        self.expectedRevision = expectedRevision
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conflictID = try c.decode(UUID.self, forKey: .conflictID)
        choice = try c.decode(AppleConflictChoice.self, forKey: .choice)
        expectedRevision = try c.decode(Int.self, forKey: .expectedRevision)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(conflictID.uuidString.lowercased(), forKey: .conflictID)
        try c.encode(choice, forKey: .choice)
        try c.encode(expectedRevision, forKey: .expectedRevision)
    }
}

public struct ObservationRetry: Codable, Sendable, Equatable {
    public let requestID: UUID
    public let observations: [Observation]
    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case observations
    }
    public init(requestID: UUID, observations: [Observation]) {
        self.requestID = requestID
        self.observations = observations
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requestID = try c.decode(UUID.self, forKey: .requestID)
        observations = try c.decode([Observation].self, forKey: .observations)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(requestID.uuidString.lowercased(), forKey: .requestID)
        try c.encode(observations, forKey: .observations)
    }
}

public struct OwnedRemovalItem: Codable, Sendable, Equatable {
    public let token: UUID
    public let expectedRevision: Int
    public let observation: Observation
    enum CodingKeys: String, CodingKey {
        case token
        case expectedRevision = "expected_revision"
        case observation
    }
    public init(token: UUID, expectedRevision: Int, observation: Observation) {
        self.token = token
        self.expectedRevision = expectedRevision
        self.observation = observation
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(UUID.self, forKey: .token)
        expectedRevision = try c.decode(Int.self, forKey: .expectedRevision)
        observation = try c.decode(Observation.self, forKey: .observation)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(token.uuidString.lowercased(), forKey: .token)
        try c.encode(expectedRevision, forKey: .expectedRevision)
        try c.encode(observation, forKey: .observation)
    }
}

public struct AppleDestination: Codable, Sendable, Equatable {
    public let id: String
    public let title: String
    enum CodingKeys: String, CodingKey {
        case id
        case title
    }
    public init(id: String, title: String) {
        self.id = id
        self.title = title
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(title, forKey: .title)
    }
}

public struct WorkBatch: Codable, Sendable, Equatable {
    public let modelVersion: Int
    public let context: BridgeContext
    public let items: [SyncItem]
    public let operations: [AppleOperation]
    public let scopes: [AppleScope]
    public let report: SyncReport
    public let paused: Bool
    public let retryRequests: [ObservationRetry]
    public let retainedItems: [SyncItem]
    enum CodingKeys: String, CodingKey {
        case modelVersion = "model_version"
        case context
        case items
        case operations
        case scopes
        case report
        case paused
        case retryRequests = "retry_requests"
        case retainedItems = "retained_items"
    }
    public init(modelVersion: Int, context: BridgeContext, items: [SyncItem], operations: [AppleOperation], scopes: [AppleScope], report: SyncReport, paused: Bool, retryRequests: [ObservationRetry], retainedItems: [SyncItem]) {
        self.modelVersion = modelVersion
        self.context = context
        self.items = items
        self.operations = operations
        self.scopes = scopes
        self.report = report
        self.paused = paused
        self.retryRequests = retryRequests
        self.retainedItems = retainedItems
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelVersion = try c.decode(Int.self, forKey: .modelVersion)
        context = try c.decode(BridgeContext.self, forKey: .context)
        items = try c.decode([SyncItem].self, forKey: .items)
        operations = try c.decode([AppleOperation].self, forKey: .operations)
        scopes = try c.decode([AppleScope].self, forKey: .scopes)
        report = try c.decode(SyncReport.self, forKey: .report)
        paused = try c.decode(Bool.self, forKey: .paused)
        retryRequests = try c.decode([ObservationRetry].self, forKey: .retryRequests)
        retainedItems = try c.decode([SyncItem].self, forKey: .retainedItems)
        guard modelVersion == 1 else { throw AppleIntegrationError.unsupportedVersion }
        guard retryRequests.count <= 1, items.count + retainedItems.count + operations.count + retryRequests.reduce(0, { $0 + $1.observations.count }) <= 5000 else { throw AppleIntegrationError.batchTooLarge }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(modelVersion, forKey: .modelVersion)
        try c.encode(context, forKey: .context)
        try c.encode(items, forKey: .items)
        try c.encode(operations, forKey: .operations)
        try c.encode(scopes, forKey: .scopes)
        try c.encode(report, forKey: .report)
        try c.encode(paused, forKey: .paused)
        try c.encode(retryRequests, forKey: .retryRequests)
        try c.encode(retainedItems, forKey: .retainedItems)
    }
}

public struct IntegrationStatus: Codable, Sendable, Equatable {
    public let modelVersion: Int
    public let configured: Bool
    public let connected: Bool
    public let paused: Bool
    public let settingsRevision: Int
    public let report: SyncReport
    public let permissions: [String: AppleAuthorization]
    public let destinations: [String: [AppleDestination]]
    public let scopes: [AppleScope]
    public let conflicts: [ConflictSummary]
    enum CodingKeys: String, CodingKey {
        case modelVersion = "model_version"
        case configured
        case connected
        case paused
        case settingsRevision = "settings_revision"
        case report
        case permissions
        case destinations
        case scopes
        case conflicts
    }
    public init(modelVersion: Int, configured: Bool, connected: Bool, paused: Bool, settingsRevision: Int, report: SyncReport, permissions: [String: AppleAuthorization], destinations: [String: [AppleDestination]], scopes: [AppleScope], conflicts: [ConflictSummary]) {
        self.modelVersion = modelVersion
        self.configured = configured
        self.connected = connected
        self.paused = paused
        self.settingsRevision = settingsRevision
        self.report = report
        self.permissions = permissions
        self.destinations = destinations
        self.scopes = scopes
        self.conflicts = conflicts
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelVersion = try c.decode(Int.self, forKey: .modelVersion)
        configured = try c.decode(Bool.self, forKey: .configured)
        connected = try c.decode(Bool.self, forKey: .connected)
        paused = try c.decode(Bool.self, forKey: .paused)
        settingsRevision = try c.decode(Int.self, forKey: .settingsRevision)
        report = try c.decode(SyncReport.self, forKey: .report)
        permissions = try c.decode([String: AppleAuthorization].self, forKey: .permissions)
        destinations = try c.decode([String: [AppleDestination]].self, forKey: .destinations)
        scopes = try c.decode([AppleScope].self, forKey: .scopes)
        conflicts = try c.decode([ConflictSummary].self, forKey: .conflicts)
        guard modelVersion == 1 else { throw AppleIntegrationError.unsupportedVersion }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(modelVersion, forKey: .modelVersion)
        try c.encode(configured, forKey: .configured)
        try c.encode(connected, forKey: .connected)
        try c.encode(paused, forKey: .paused)
        try c.encode(settingsRevision, forKey: .settingsRevision)
        try c.encode(report, forKey: .report)
        try c.encode(permissions, forKey: .permissions)
        try c.encode(destinations, forKey: .destinations)
        try c.encode(scopes, forKey: .scopes)
        try c.encode(conflicts, forKey: .conflicts)
    }
}
