import XCTest
@testable import KitchenOSKit

final class WeekDateTests: XCTestCase {
    func testWeekIDFormat() {
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = TimeZone(identifier: "America/Chicago")!
        // 2026-06-22 is a Monday in ISO week 26.
        let comps = DateComponents(year: 2026, month: 6, day: 22)
        let date = cal.date(from: comps)!
        XCTAssertEqual(WeekDate.weekID(for: date, calendar: cal), "2026-W26")
    }
}
