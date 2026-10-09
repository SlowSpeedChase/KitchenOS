import Foundation
import CryptoKit

public struct PlanningCalendarEvent: Codable, Sendable {
    public let id: String
    public let title: String
    public let start: String
    public let end: String
    public let all_day: Bool
    public let role: String

    public static func identity(calendarID: String, eventID: String, occurrence: String) -> String {
        digest([calendarID, eventID, occurrence])
    }
    static func digest(_ values: [String]) -> String {
        let bytes = try! JSONEncoder().encode(values)
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
    public init(calendarID: String, eventID: String, title: String, start: Date, end: Date, allDay: Bool, flexible: Bool, timezone: TimeZone = .current) throws {
        guard !calendarID.isEmpty, !eventID.isEmpty, end > start else { throw KitchenOSError.decoding }
        let formatter = ISO8601DateFormatter()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timezone
        // EventKit marks the occurrence all-day, but imported calendars may
        // retain an inclusive end-of-day time. Cover those civil dates with an
        // exclusive midnight boundary; leave timed events untouched.
        let normalizedStart = allDay ? calendar.startOfDay(for: start) : start
        let endDay = calendar.startOfDay(for: end)
        let normalizedEnd = allDay && end != endDay ? calendar.date(byAdding: .day, value: 1, to: endDay)! : end
        self.start = formatter.string(from: normalizedStart)
        self.end = formatter.string(from: normalizedEnd)
        id = Self.identity(calendarID: calendarID, eventID: eventID, occurrence: self.start)
        // Match the server's Unicode scalar bound, without cutting a grapheme.
        var bounded = ""
        for character in title {
            guard bounded.unicodeScalars.count + character.unicodeScalars.count <= 300 else { break }
            bounded.append(character)
        }
        self.title = bounded
        all_day = allDay
        role = flexible ? "flexible" : "firm"
    }
}

public struct PlanningCalendarSnapshot: Encodable, Sendable {
    public let version = 1
    public let selection_id: String
    public let generated_at: String
    public let timezone: String
    public let coverage_start: String
    public let coverage_end: String
    public let events: [PlanningCalendarEvent]

    public init(firmID: String, flexibleID: String, generatedAt: Date, timezone: String, coverageStart: String, coverageEnd: String, events: [PlanningCalendarEvent]) throws {
        guard events.count <= 5000, Set(events.map(\.id)).count == events.count else { throw KitchenOSError.decoding }
        selection_id = PlanningCalendarEvent.digest([firmID, flexibleID])
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        generated_at = formatter.string(from: generatedAt)
        self.timezone = timezone
        coverage_start = coverageStart
        coverage_end = coverageEnd
        self.events = events
        guard try JSONEncoder().encode(self).count <= 2 * 1024 * 1024 else { throw KitchenOSError.decoding }
    }
}

public extension KitchenOSClient {
    func syncPlanningCalendar(_ snapshot: PlanningCalendarSnapshot) async throws {
        try await postJSON(path: "/api/planning-calendar/snapshot", body: snapshot)
    }
    func clearPlanningCalendar() async throws {
        struct Clear: Encodable { let version = 1; let clear = true }
        try await postJSON(path: "/api/planning-calendar/snapshot", body: Clear())
    }
}
