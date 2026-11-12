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

    public static func classify(day: Date, events: [CookingCalendarEvent], calendar: Calendar) -> Self {
        let start = calendar.startOfDay(for: day)
        guard let noon = calendar.date(bySettingHour: 12, minute: 0, second: 0, of: start),
              let end = calendar.date(byAdding: .day, value: 1, to: start) else { return .unknown }
        let overlapping = events.filter { $0.start < end && $0.end > noon && $0.end > $0.start }
        if overlapping.contains(where: { !$0.flexible }) { return .busy }
        return overlapping.isEmpty ? .good : .possible
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
