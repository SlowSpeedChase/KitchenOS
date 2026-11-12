import Foundation

public enum WebDayReference: Equatable, Sendable {
    case today
    case tomorrow
    case weekday(DayOfWeek, weekOffset: Int)
    case exact(String)
}

public enum WebDayResolutionError: Error, Equatable, Sendable {
    case invalidDate(String)
    case unsupportedWeekOffset(Int)
}

public enum WebDayResolver {
    /// Resolve civil dates in the device's time zone, using Gregorian dates and ISO weeks.
    /// Ambiguous natural-language phrases must be clarified before constructing a reference.
    public static func resolve(_ reference: WebDayReference, now: Date = Date(),
                               calendar: Calendar = WeekDate.isoCalendar()) throws -> String {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = calendar.timeZone
        local.firstWeekday = 2
        local.minimumDaysInFirstWeek = 4
        let day: Date
        switch reference {
        case .today:
            day = now
        case .tomorrow:
            guard let tomorrow = local.date(byAdding: .day, value: 1, to: now) else {
                throw WebDayResolutionError.invalidDate("tomorrow")
            }
            day = tomorrow
        case .weekday(let weekday, let weekOffset):
            guard weekOffset == 0 || weekOffset == 1 else {
                throw WebDayResolutionError.unsupportedWeekOffset(weekOffset)
            }
            let weekdays: [DayOfWeek] = [.monday, .tuesday, .wednesday, .thursday, .friday, .saturday, .sunday]
            let offset = weekdays.firstIndex(of: weekday)! + weekOffset * 7
            let start = WeekDate.weekRange(for: now, calendar: local).start
            guard let target = local.date(byAdding: .day, value: offset, to: start) else {
                throw WebDayResolutionError.invalidDate(weekday.rawValue)
            }
            day = target
        case .exact(let value):
            let bytes = Array(value.utf8)
            guard bytes.count == 10, bytes[4] == 45, bytes[7] == 45,
                  bytes.enumerated().allSatisfy({ index, byte in
                      index == 4 || index == 7 || (48...57).contains(byte)
                  }),
                  let year = Int(value.prefix(4)), year > 0,
                  let month = Int(value.dropFirst(5).prefix(2)),
                  let date = Int(value.suffix(2)),
                  let candidate = local.date(from: DateComponents(year: year, month: month, day: date, hour: 12)) else {
                throw WebDayResolutionError.invalidDate(value)
            }
            let components = local.dateComponents([.era, .year, .month, .day], from: candidate)
            guard components.era == 1, components.year == year, components.month == month, components.day == date else {
                throw WebDayResolutionError.invalidDate(value)
            }
            return value
        }
        let components = local.dateComponents([.year, .month, .day], from: day)
        guard let year = components.year, (1...9999).contains(year),
              let month = components.month, let date = components.day else {
            throw WebDayResolutionError.invalidDate("out of range")
        }
        return String(format: "%04d-%02d-%02d", year, month, date)
    }
}
