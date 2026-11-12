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

public extension PlanningCalendarSnapshot {
    /// Compatibility and detailed views share one filtered EventKit read, including
    /// owned-token exclusion. Never republish a snapshot past the server's six-hour TTL.
    func cookingAvailability(now: Date = Date()) throws -> [String: CookingOpportunity] {
        let generatedFormatter = ISO8601DateFormatter()
        generatedFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let generated = generatedFormatter.date(from: generated_at), now.timeIntervalSince(generated) >= 0, now.timeIntervalSince(generated) < 6 * 3600,
              let zone = TimeZone(identifier: timezone) else { throw AppleIntegrationError.unavailable }
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
        let date = DateFormatter(); date.calendar = calendar; date.locale = Locale(identifier: "en_US_POSIX")
        date.timeZone = zone; date.dateFormat = "yyyy-MM-dd"
        guard let start = date.date(from: coverage_start), let end = date.date(from: coverage_end), end > start else { throw AppleIntegrationError.invalidDate }
        let instant = ISO8601DateFormatter()
        let values = try events.map { event -> CookingCalendarEvent in
            guard let start = instant.date(from: event.start), let end = instant.date(from: event.end) else { throw AppleIntegrationError.invalidDate }
            return CookingCalendarEvent(start: start, end: end, flexible: event.role == "flexible")
        }
        var days: [String: CookingOpportunity] = [:]; var day = start
        while day < end {
            guard days.count < 35, let next = calendar.date(byAdding: .day, value: 1, to: day) else { throw AppleIntegrationError.invalidDate }
            days[date.string(from: day)] = CookingOpportunity.classify(day: day, events: values, calendar: calendar)
            day = next
        }
        return days
    }
}
