import Foundation
import XCTest
@testable import KitchenOSKit

final class WebDayResolverTests: XCTestCase {
    private func calendar(_ zone: String = "America/Chicago") -> Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = TimeZone(identifier: zone)!
        return result
    }

    private func instant(_ year: Int, _ month: Int, _ day: Int, hour: Int = 12, calendar: Calendar) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour))!
    }

    func testTomorrowAcrossSundayAndISOYearBoundaries() throws {
        let cal = calendar()
        let cases = [(2026, 12, 27, "2026-12-28", "2026-W53"), (2027, 1, 3, "2027-01-04", "2027-W01")]
        for (year, month, day, expectedDate, expectedWeek) in cases {
            let now = instant(year, month, day, calendar: cal)
            let resolved = try WebDayResolver.resolve(.tomorrow, now: now, calendar: cal)
            XCTAssertEqual(resolved, expectedDate)
            var iso = WeekDate.isoCalendar()
            iso.timeZone = cal.timeZone
            XCTAssertEqual(WeekDate.weekID(for: cal.date(byAdding: .day, value: 1, to: now)!, calendar: iso), expectedWeek)
        }
    }

    func testWeekdayUsesCurrentISOWeekEvenWithSundayFirstCalendar() throws {
        let cal = calendar()
        let now = instant(2026, 10, 15, calendar: cal)
        XCTAssertEqual(try WebDayResolver.resolve(.weekday(.friday, weekOffset: 0), now: now, calendar: cal), "2026-10-16")
        XCTAssertEqual(try WebDayResolver.resolve(.weekday(.monday, weekOffset: 0), now: now, calendar: cal), "2026-10-12")
        XCTAssertEqual(try WebDayResolver.resolve(.weekday(.sunday, weekOffset: 0), now: now, calendar: cal), "2026-10-18")
        XCTAssertEqual(try WebDayResolver.resolve(.weekday(.friday, weekOffset: 1), now: now, calendar: cal), "2026-10-23")
    }

    func testSundayBelongsToPreviousMondayWeek() throws {
        let cal = calendar()
        XCTAssertEqual(try WebDayResolver.resolve(.weekday(.monday, weekOffset: 0), now: instant(2027, 1, 3, calendar: cal), calendar: cal), "2026-12-28")
    }

    func testUTCPositiveFourteenKeepsLocalCivilDate() throws {
        let cal = calendar("Pacific/Kiritimati")
        let now = instant(2026, 10, 16, hour: 0, calendar: cal)
        XCTAssertEqual(try WebDayResolver.resolve(.today, now: now, calendar: cal), "2026-10-16")
        XCTAssertEqual(try WebDayResolver.resolve(.tomorrow, now: now, calendar: cal), "2026-10-17")
        XCTAssertEqual(try WebDayResolver.resolve(.exact("2026-10-16"), now: now, calendar: cal), "2026-10-16")
    }

    func testTomorrowAcrossDaylightSavingChanges() throws {
        let cal = calendar()
        for (month, day, expected) in [(3, 8, "2026-03-09"), (11, 1, "2026-11-02")] {
            XCTAssertEqual(try WebDayResolver.resolve(.tomorrow, now: instant(2026, month, day, hour: 0, calendar: cal), calendar: cal), expected)
        }
    }

    func testExactDatesValidateGregorianLeapDaysAndStrictFormat() throws {
        let cal = calendar()
        let now = instant(2026, 10, 15, calendar: cal)
        XCTAssertEqual(try WebDayResolver.resolve(.exact("2028-02-29"), now: now, calendar: cal), "2028-02-29")
        for invalid in ["2026-02-29", "2026-04-31", "2026-13-01", "2026-00-01", "2026-10-00", "0000-01-01", "2026-2-01", "2026-10-16T00:00:00Z", " 2026-10-16", "٢٠٢٦-10-16"] {
            XCTAssertThrowsError(try WebDayResolver.resolve(.exact(invalid), now: now, calendar: cal), invalid)
        }
    }

    func testRejectsUnsupportedWeekOffsets() {
        let cal = calendar()
        for offset in [-1, 2] {
            XCTAssertThrowsError(try WebDayResolver.resolve(.weekday(.friday, weekOffset: offset), now: instant(2026, 10, 15, calendar: cal), calendar: cal)) { error in
                XCTAssertEqual(error as? WebDayResolutionError, .unsupportedWeekOffset(offset))
            }
        }
    }
}
