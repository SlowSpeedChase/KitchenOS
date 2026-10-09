import AppIntents
import Foundation

/// Current ledger state, fetched again before every scheduling mutation.
public struct PlannedCook: Decodable, Sendable, Equatable {
    public let id: Int
    public let recipe: String
    public let week: String
    public let date: String?
    public let meal: String?
    public let cookedAt: String?
    public let bundleID: String?
    public let unassigned: Double

    enum CodingKeys: String, CodingKey {
        case id, recipe, week, date, meal, unassigned
        case cookedAt = "cooked_at", bundleID = "bundle_id"
    }
    public init(id: Int, recipe: String, week: String, date: String?, meal: String?, cookedAt: String?, bundleID: String?, unassigned: Double) {
        self.id = id; self.recipe = recipe; self.week = week; self.date = date; self.meal = meal
        self.cookedAt = cookedAt; self.bundleID = bundleID; self.unassigned = unassigned
    }
    public var isEligible: Bool { id > 0 && cookedAt == nil && bundleID == nil }
    public var needsFirstPlacement: Bool { date == nil || meal == nil }
}

public struct PlannedCookEntity: AppEntity, Identifiable {
    public let id: Int
    public let recipe: String
    public let week: String
    public let date: String?
    public let meal: String?
    public init(_ cook: PlannedCook) {
        id = cook.id; recipe = cook.recipe; week = cook.week; date = cook.date; meal = cook.meal
    }
    public static var typeDisplayRepresentation: TypeDisplayRepresentation { "Planned cook" }
    public static var defaultQuery = PlannedCookEntityQuery()
    /// The exact ledger number disambiguates even two unplaced copies of a recipe.
    public var selectionLabel: String {
        let weekLabel = WeekDate.date(forWeekID: week).map { WeekDate.weekRangeLabel(for: $0) } ?? "Unknown week"
        return "\(weekLabel) · \(date ?? "Unplaced")\(meal.map { " · " + $0 } ?? "") · Cook \(id)"
    }
    public var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(recipe)", subtitle: "\(selectionLabel)")
    }
}

public struct PlannedCookEntityQuery: EntityStringQuery {
    private let injectedClient: KitchenOSClient?
    public init() { injectedClient = nil }
    public init(client: KitchenOSClient) { injectedClient = client }
    private var client: KitchenOSClient { injectedClient ?? KitchenOSClient(config: .resolved()) }
    public func entities(for identifiers: [Int]) async throws -> [PlannedCookEntity] {
        var entities: [PlannedCookEntity] = []
        for id in identifiers where id > 0 {
            do {
                let cook = try await client.plannedCook(id: id)
                if cook.isEligible { entities.append(PlannedCookEntity(cook)) }
            } catch KitchenOSError.http(404) { continue }
        }
        return entities
    }
    public func suggestedEntities() async throws -> [PlannedCookEntity] {
        try await client.plannedCooks(week: WeekDate.currentWeekID()).map(PlannedCookEntity.init)
    }
    public func entities(matching string: String) async throws -> [PlannedCookEntity] {
        try await suggestedEntities().filter { $0.recipe.localizedCaseInsensitiveContains(string) }
    }
}

public enum CookingIntentParameterError: LocalizedError {
    case ineligible, wrongWeek, duration, time, servings, firstPlacement
    public var errorDescription: String? {
        switch self {
        case .ineligible: return "Choose an existing uncooked single-recipe cook."
        case .wrongWeek: return "Choose a cook and start time in the selected week."
        case .duration: return "Choose 15 to 360 minutes in 15-minute steps."
        case .time: return "Choose a start in 15-minute steps that finishes by midnight."
        case .servings: return "Enter a positive serving count within the cook’s available servings."
        case .firstPlacement: return "Enter servings to eat when placing this cook for the first time."
        }
    }
}

public struct CookingIntentParameters: Encodable, Sendable {
    public let date: String
    public let meal: String
    public let start: String
    public let timezone: String
    public let durationMinutes: Int
    public let servingsToEat: Double?
    public let expectedUnplaced: Bool
    enum CodingKeys: String, CodingKey {
        case date, meal, start, timezone
        case durationMinutes = "duration_minutes", servingsToEat = "servings_to_eat"
        case expectedUnplaced = "expected_unplaced"
    }
    public static func weekID(for date: Date, timeZone: TimeZone = .current) -> String {
        var calendar = Calendar(identifier: .iso8601); calendar.timeZone = timeZone
        return WeekDate.weekID(for: date, calendar: calendar)
    }
    public init(cook: PlannedCook, start: Date, timeZone: TimeZone = .current, durationMinutes: Int, meal: MealSlot, servingsToEat: Double?) throws {
        guard cook.isEligible else { throw CookingIntentParameterError.ineligible }
        guard Self.weekID(for: start, timeZone: timeZone) == cook.week else { throw CookingIntentParameterError.wrongWeek }
        guard (15...360).contains(durationMinutes), durationMinutes % 15 == 0 else { throw CookingIntentParameterError.duration }
        var calendar = Calendar(identifier: .iso8601); calendar.timeZone = timeZone
        let parts = calendar.dateComponents([.hour, .minute, .second, .nanosecond], from: start)
        guard let hour = parts.hour, let minute = parts.minute, minute % 15 == 0,
              parts.second == 0, parts.nanosecond == 0,
              hour * 60 + minute + durationMinutes <= 24 * 60 else { throw CookingIntentParameterError.time }
        if cook.needsFirstPlacement, servingsToEat == nil { throw CookingIntentParameterError.firstPlacement }
        if let servings = servingsToEat {
            guard servings.isFinite, servings > 0,
                  !cook.needsFirstPlacement || (cook.unassigned.isFinite && servings <= cook.unassigned) else { throw CookingIntentParameterError.servings }
        }
        let formatter = ISO8601DateFormatter(); formatter.timeZone = timeZone
        self.start = formatter.string(from: start)
        self.date = String(self.start.prefix(10))
        self.timezone = timeZone.identifier; self.durationMinutes = durationMinutes
        self.meal = meal.rawValue; self.servingsToEat = servingsToEat
        self.expectedUnplaced = cook.needsFirstPlacement
    }
    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(date, forKey: .date)
        try values.encode(meal, forKey: .meal)
        try values.encode(start, forKey: .start)
        try values.encode(timezone, forKey: .timezone)
        try values.encode(durationMinutes, forKey: .durationMinutes)
        // Explicit null preserves omission through the required wire key.
        try values.encode(servingsToEat, forKey: .servingsToEat)
        try values.encode(expectedUnplaced, forKey: .expectedUnplaced)
    }
}

public extension KitchenOSClient {
    func plannedCook(id: Int) async throws -> PlannedCook {
        guard id > 0 else { throw CookingIntentParameterError.ineligible }
        let cook: PlannedCook = try await getJSON(baseURL.appendingPathComponent("/api/cooks/\(id)"))
        guard cook.id == id else { throw KitchenOSError.decoding }
        return cook
    }
    func plannedCooks(week: String) async throws -> [PlannedCook] {
        guard WeekDate.date(forWeekID: week) != nil else { throw CookingIntentParameterError.wrongWeek }
        struct Board: Decodable { let cooks: [PlannedCook] }
        let board: Board = try await getJSON(baseURL.appendingPathComponent("/api/week-board/\(week)"))
        return board.cooks.filter { $0.isEligible && $0.week == week }
    }
    /// Always fetch the current ledger row; a restored AppEntity is only an identity.
    func scheduleCooking(cookID: Int, week: String, start: Date, timeZone: TimeZone = .current, durationMinutes: Int, meal: MealSlot, servingsToEat: Double?) async throws {
        let cook = try await plannedCook(id: cookID)
        guard cook.week == week else { throw CookingIntentParameterError.wrongWeek }
        let parameters = try CookingIntentParameters(cook: cook, start: start, timeZone: timeZone,
            durationMinutes: durationMinutes, meal: meal, servingsToEat: servingsToEat)
        try await postJSON(path: "/api/cooks/\(cookID)/schedule", body: parameters)
    }
}

public struct AppleIntentResult: Sendable, Equatable {
    public enum Outcome: Sendable { case delivered, queued, partial, conflict, unavailable, setup }
    public let outcome: Outcome
    public let message: String
    private init(outcome: Outcome, message: String) { self.outcome = outcome; self.message = message }
    public static var setup: AppleIntentResult {
        AppleIntentResult(outcome: .setup, message: "Finish Apple integration setup in KitchenOS. Run the action again when setup is complete.")
    }
    /// Keep this operation's delivered counts while accounting for newer pending
    /// work and local EventKit availability in the subsequent status snapshot.
    public init(report: SyncReport, latest: IntegrationStatus, scopeActive: Bool = true) {
        let active = latest.scopes.filter { $0.status == .active }
        let available = active.allSatisfy { scope in
            latest.permissions[scope.domain.rawValue] == .authorized &&
                latest.destinations[scope.domain.rawValue]?.contains { $0.id == scope.destinationID } == true
        }
        let combined = SyncReport(created: report.created, updated: report.updated, deleted: report.deleted,
            queued: max(report.queued, latest.report.queued),
            conflicts: max(report.conflicts, latest.report.conflicts),
            unavailable: max(report.unavailable, latest.report.unavailable), lastSuccess: report.lastSuccess)
        self.init(report: combined, connected: latest.configured && latest.connected,
            scopeActive: scopeActive && !active.isEmpty, paused: latest.paused, availabilityConfirmed: available)
    }
    public init(report: SyncReport, connected: Bool = true, scopeActive: Bool = true, paused: Bool = false, availabilityConfirmed: Bool = true) {
        let changed = report.created + report.updated + report.deleted
        let unfinished = report.queued + report.conflicts + report.unavailable > 0 || paused || !connected || !scopeActive || !availabilityConfirmed
        if changed > 0 && unfinished { outcome = .partial }
        else if !connected || !scopeActive || !availabilityConfirmed { outcome = .unavailable }
        else if report.conflicts > 0 { outcome = .conflict }
        else if report.unavailable > 0 { outcome = .unavailable }
        else if report.queued > 0 || paused { outcome = .queued }
        else { outcome = .delivered }
        let heading: String
        switch outcome {
        case .delivered: heading = "Apple sync is up to date."
        case .queued: heading = paused ? "Apple sync is paused; delivery is pending." : "Apple changes are queued; delivery is pending."
        case .partial: heading = "Apple sync finished partly; some changes still need attention."
        case .conflict: heading = "Review conflicting changes in KitchenOS."
        case .unavailable: heading = "Some Apple items are unavailable; check integration status in KitchenOS."
        case .setup: heading = Self.setup.message
        }
        let currentState = !connected ? "Apple integration is disconnected; delivery is not confirmed. " :
            !scopeActive ? "The selected sync scope changed or is inactive; delivery is not confirmed. " :
            !availabilityConfirmed ? "Apple permissions or destinations are unavailable; delivery is not confirmed. " : ""
        message = "\(currentState)\(heading) \(report.created) created, \(report.updated) updated, \(report.deleted) removed, \(report.queued) queued, \(report.conflicts) conflicts, \(report.unavailable) unavailable."
    }
}
