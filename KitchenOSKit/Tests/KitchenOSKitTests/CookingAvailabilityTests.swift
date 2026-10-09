import XCTest
@testable import KitchenOSKit

final class CookingAvailabilityTests: XCTestCase {
    var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "America/Chicago")!
        return c
    }
    func date(_ hour: Int, _ minute: Int = 0, day: Int = 4, month: Int = 9) -> Date {
        calendar.date(from: DateComponents(year: 2026, month: month, day: day, hour: hour, minute: minute))!
    }
    func testMorningAndNoonBoundary() {
        let morning = CookingCalendarEvent(start: date(9), end: date(12), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [morning], calendar: calendar), .good)
        let overlap = CookingCalendarEvent(start: date(11), end: date(12, 1), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [overlap], calendar: calendar), .busy)
    }
    func testFlexibleAndFirmPrecedence() {
        let block = CookingCalendarEvent(start: date(14), end: date(17), flexible: true)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [block], calendar: calendar), .possible)
        let firm = CookingCalendarEvent(start: date(20), end: date(21), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [block, firm], calendar: calendar), .busy)
    }
    func testAllDayAndFollowingDay() {
        let allDay = CookingCalendarEvent(start: date(0), end: date(0, day: 5), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [allDay], calendar: calendar), .busy)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0, day: 5), events: [allDay], calendar: calendar), .good)
    }
    func testDSTUsesLocalDayBoundary() {
        let nextDay = CookingCalendarEvent(start: date(0, day: 2, month: 11), end: date(1, day: 2, month: 11), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0, day: 1, month: 11), events: [nextDay], calendar: calendar), .good)
    }
}
