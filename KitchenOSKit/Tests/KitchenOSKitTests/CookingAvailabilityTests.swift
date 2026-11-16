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
        // Running a minute past noon still leaves the afternoon and evening free.
        let overlap = CookingCalendarEvent(start: date(11), end: date(12, 1), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [overlap], calendar: calendar), .good)
    }
    func testFlexibleAndFirmPrecedence() {
        // Time Blocking across the whole cooking window: cooking may still fit.
        let block = CookingCalendarEvent(start: date(12), end: date(21, 30), flexible: true)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [block], calendar: calendar), .possible)
        // Commitments across the whole window leave no cooking time.
        let firm = CookingCalendarEvent(start: date(12), end: date(21), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [block, firm], calendar: calendar), .busy)
    }
    func testOneShortCommitmentDoesNotMakeTheDayBusy() {
        // A single evening appointment still leaves a free 90-minute window.
        let firm = CookingCalendarEvent(start: date(19), end: date(20, 30), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [firm], calendar: calendar), .good)
    }
    func testNeedsNinetyFreeMinutes() {
        // Commitments leave only 60-minute gaps (12-13, 15-16, 18-19, 21-21:30 is too short).
        let events = [
            CookingCalendarEvent(start: date(13), end: date(15), flexible: false),
            CookingCalendarEvent(start: date(16), end: date(18), flexible: false),
            CookingCalendarEvent(start: date(19), end: date(21), flexible: false),
        ]
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: events, calendar: calendar), .busy)
        // Widen one gap to exactly 90 minutes and the day can host a cook.
        let wider = [events[0], CookingCalendarEvent(start: date(16, 30), end: date(18), flexible: false), events[2]]
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: wider, calendar: calendar), .good)
    }
    func testFreeGapOnlyInsideTimeBlockingIsPossible() {
        let firm = CookingCalendarEvent(start: date(12), end: date(18), flexible: false)
        let block = CookingCalendarEvent(start: date(18), end: date(21, 30), flexible: true)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [firm, block], calendar: calendar), .possible)
    }
    func testLateNightFreedomDoesNotCount() {
        // Busy until 10pm: the free time after the cooking window is ignored.
        let firm = CookingCalendarEvent(start: date(12), end: date(22), flexible: false)
        XCTAssertEqual(CookingOpportunity.classify(day: date(0), events: [firm], calendar: calendar), .busy)
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
