import Foundation

public struct CookingCalendarEvent {
    public let start: Date
    public let end: Date
    public let flexible: Bool

    public init(start: Date, end: Date, flexible: Bool) {
        self.start = start
        self.end = end
        self.flexible = flexible
    }
}

public enum CookingOpportunity: String, Codable {
    case good, possible, busy, unknown

    /// Cooking needs one unbroken window this long.
    public static let cookMinutes = 90
    /// The window searched for cooking time: noon to 9:30 pm local.
    static let windowStart = (hour: 12, minute: 0)
    static let windowEnd = (hour: 21, minute: 30)

    /// good: a 90-minute window clear of every event.
    /// possible: a 90-minute window clear of commitments, but overlapping Time Blocking.
    /// busy: commitments leave no 90-minute window.
    public static func classify(day: Date, events: [CookingCalendarEvent], calendar: Calendar) -> Self {
        let start = calendar.startOfDay(for: day)
        guard let from = calendar.date(bySettingHour: windowStart.hour, minute: windowStart.minute, second: 0, of: start),
              let to = calendar.date(bySettingHour: windowEnd.hour, minute: windowEnd.minute, second: 0, of: start),
              to > from else { return .unknown }
        let valid = events.filter { $0.end > $0.start }
        if hasGap(from: from, to: to, blocking: valid) { return .good }
        if hasGap(from: from, to: to, blocking: valid.filter { !$0.flexible }) { return .possible }
        return .busy
    }

    static func hasGap(from: Date, to: Date, blocking: [CookingCalendarEvent]) -> Bool {
        let need = TimeInterval(cookMinutes * 60)
        var cursor = from
        for event in blocking.filter({ $0.start < to && $0.end > from }).sorted(by: { $0.start < $1.start }) {
            if event.start.timeIntervalSince(cursor) >= need { return true }
            cursor = max(cursor, event.end)
            if cursor >= to { return false }
        }
        return to.timeIntervalSince(cursor) >= need
    }
}

public extension KitchenOSClient {
    func syncCookingAvailability(days: [String: CookingOpportunity]) async throws {
        struct Snapshot: Encodable { let days: [String: CookingOpportunity] }
        try await postJSON(path: "/api/cooking-availability", body: Snapshot(days: days))
    }
}

public struct CookingAvailabilitySnapshot: Decodable {
    public let days: [String: CookingOpportunity]
}

public extension KitchenOSClient {
    func cookingAvailability(week: String) async throws -> CookingAvailabilitySnapshot {
        try await getJSON(baseURL.appendingPathComponent("/api/cooking-availability/\(week)"))
    }
}

public extension CookingOpportunity {
    var label: String {
        switch self {
        case .good: "Good cooking day"
        case .possible: "Possible · flexible blocks"
        case .busy: "Busy · keep food easy"
        case .unknown: "Availability unknown"
        }
    }
}
