import Foundation

public enum WeekDate {
    /// ISO-8601 week identifier like "2026-W26".
    public static func weekID(for date: Date, calendar: Calendar = isoCalendar()) -> String {
        let comps = calendar.dateComponents([.weekOfYear, .yearForWeekOfYear], from: date)
        let year = comps.yearForWeekOfYear ?? 0
        let week = comps.weekOfYear ?? 0
        return String(format: "%04d-W%02d", year, week)
    }

    public static func currentWeekID(now: Date = Date(), calendar: Calendar = isoCalendar()) -> String {
        weekID(for: now, calendar: calendar)
    }

    public static func isoCalendar() -> Calendar {
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = .current
        return cal
    }
}
