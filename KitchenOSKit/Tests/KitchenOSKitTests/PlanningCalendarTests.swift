import XCTest
@testable import KitchenOSKit

final class PlanningCalendarTests: XCTestCase {
    func testIdentitySeparatesCalendarAndRecurrence() {
        let a = PlanningCalendarEvent.identity(calendarID: "firm", eventID: "series", occurrence: "2026-09-21T12:00:00Z")
        XCTAssertEqual(a.count, 64)
        XCTAssertNotEqual(a, PlanningCalendarEvent.identity(calendarID: "flex", eventID: "series", occurrence: "2026-09-21T12:00:00Z"))
        XCTAssertNotEqual(a, PlanningCalendarEvent.identity(calendarID: "firm", eventID: "series", occurrence: "2026-09-22T12:00:00Z"))
        XCTAssertNotEqual(PlanningCalendarEvent.identity(calendarID: "a|b", eventID: "c", occurrence: "d"), PlanningCalendarEvent.identity(calendarID: "a", eventID: "b|c", occurrence: "d"))
    }
    func testMinimalSnapshotEncodingAndUnicodeBound() throws {
        let start = ISO8601DateFormatter().date(from: "2026-11-01T05:00:00Z")!
        let end = ISO8601DateFormatter().date(from: "2026-11-02T06:00:00Z")!
        let event = try PlanningCalendarEvent(calendarID: "private", eventID: "private-event", title: String(repeating: "🍳", count: 301), start: start, end: end, allDay: true, flexible: false)
        let snapshot = try PlanningCalendarSnapshot(firmID: "private", flexibleID: "other", generatedAt: start, timezone: "America/Chicago", coverageStart: "2026-11-01", coverageEnd: "2026-12-06", events: [event])
        let data = try JSONEncoder().encode(snapshot)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["version"] as? Int, 1)
        XCTAssertEqual(json["timezone"] as? String, "America/Chicago")
        let row = try XCTUnwrap((json["events"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(row.keys), Set(["id","title","start","end","all_day","role"]))
        XCTAssertEqual((row["title"] as? String)?.unicodeScalars.count, 300)
        XCTAssertEqual(row["role"] as? String, "firm")
        XCTAssertEqual(row["end"] as? String, "2026-11-02T06:00:00Z")
        XCTAssertFalse(String(data: data, encoding: .utf8)!.contains("private"))
        XCTAssertThrowsError(try PlanningCalendarSnapshot(firmID: "a", flexibleID: "b", generatedAt: start, timezone: "America/Chicago", coverageStart: "2026-11-01", coverageEnd: "2026-12-06", events: Array(repeating: event, count: 5001)))
        XCTAssertThrowsError(try PlanningCalendarEvent(calendarID: "a", eventID: "", title: "x", start: start, end: end, allDay: false, flexible: true))
    }
}

extension PlanningCalendarTests {
    func testWebOriginAndURLPolicy() throws {
        let base = URL(string: "http://100.111.6.10:5001")!
        let url = try XCTUnwrap(PlanningWebPolicy.plannerURL(base: base, week: "2026-W39"))
        XCTAssertEqual(url.absoluteString, "http://100.111.6.10:5001/meal-planner?week=2026-W39&view=calendar")
        XCTAssertTrue(PlanningWebPolicy.sameOrigin(url, base))
        XCTAssertFalse(PlanningWebPolicy.sameOrigin(URL(string:"http://100.111.6.10:5002/api/x")!,base))
        XCTAssertFalse(PlanningWebPolicy.sameOrigin(URL(string:"https://100.111.6.10:5001/api/x")!,base))
        XCTAssertNil(PlanningWebPolicy.plannerURL(base: base,week:"2026-W39&token=oops"))
        XCTAssertNil(PlanningWebPolicy.plannerURL(base:URL(string:"file:///tmp/test")!,week:"2026-W39"))
    }
}

extension PlanningCalendarTests {
    func testAllDayNormalizesInclusiveEndToExclusiveLocalMidnight() throws {
        let formatter=ISO8601DateFormatter()
        let event=try PlanningCalendarEvent(calendarID:"a",eventID:"b",title:"All day",
            start:formatter.date(from:"2026-09-21T05:00:00Z")!,
            end:formatter.date(from:"2026-09-28T04:59:59Z")!,allDay:true,flexible:false,timezone:TimeZone(identifier:"America/Chicago")!)
        XCTAssertEqual(event.start,"2026-09-21T05:00:00Z")
        XCTAssertEqual(event.end,"2026-09-28T05:00:00Z")
    }
}
