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

    /// The Monday…Sunday dates of the ISO week containing `date`.
    public static func weekRange(for date: Date,
                                 calendar: Calendar = isoCalendar()) -> (start: Date, end: Date) {
        let start = calendar.dateInterval(of: .weekOfYear, for: date)?.start ?? date
        let end = calendar.date(byAdding: .day, value: 6, to: start) ?? start
        return (start, end)
    }

    /// A human label for the ISO week's date span, e.g. "Jun 22–28" or
    /// "Jun 29 – Jul 5" when it crosses a month boundary.
    public static func weekRangeLabel(for date: Date,
                                      calendar: Calendar = isoCalendar()) -> String {
        let (start, end) = weekRange(for: date, calendar: calendar)
        let df = DateFormatter()
        df.calendar = calendar
        df.locale = .current
        df.dateFormat = "MMM d"
        let startStr = df.string(from: start)
        let sameMonth = calendar.component(.month, from: start)
            == calendar.component(.month, from: end)
        df.dateFormat = sameMonth ? "d" : "MMM d"
        let endStr = df.string(from: end)
        return sameMonth ? "\(startStr)–\(endStr)" : "\(startStr) – \(endStr)"
    }
}
