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

extension PlanningCalendarTests {
    func testCompatibilityAvailabilityUsesTheSameFilteredDetailedSnapshotAndExpires() throws {
        let format = ISO8601DateFormatter(); let now = format.date(from: "2026-10-09T12:00:00Z")!
        let event = try PlanningCalendarEvent(calendarID: "firm", eventID: "meeting", title: "Meeting",
            start: format.date(from: "2026-10-09T18:00:00Z")!, end: format.date(from: "2026-10-09T19:00:00Z")!,
            allDay: false, flexible: false, timezone: TimeZone(identifier: "America/Chicago")!)
        let snapshot = try PlanningCalendarSnapshot(firmID: "firm", flexibleID: "flex", generatedAt: now,
            timezone: "America/Chicago", coverageStart: "2026-10-09", coverageEnd: "2026-10-11", events: [event])
        let days = try snapshot.cookingAvailability(now: now)
        XCTAssertEqual(days, ["2026-10-09": .busy, "2026-10-10": .good])
        XCTAssertThrowsError(try snapshot.cookingAvailability(now: now.addingTimeInterval(21601)))
        XCTAssertThrowsError(try snapshot.cookingAvailability(now: now.addingTimeInterval(21600)))
        XCTAssertThrowsError(try snapshot.cookingAvailability(now: now.addingTimeInterval(-1)))
    }
}

extension PlanningCalendarTests {
    func testOnlyCurrentlyLinkedOwnedTokensExcludeAvailability() {
        let owned = UUID(uuidString: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")!
        let detached = UUID(uuidString: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")!
        let marker = AppleOwnership.url(for: owned).absoluteString
        let detachedMarker = AppleOwnership.url(for: detached).absoluteString
        let excluded: Set<UUID> = [owned]
        XCTAssertTrue(AppleOwnership.excludesFromAvailability(url: URL(string: marker), notes: nil, excludingOwnedTokens: excluded))
        XCTAssertTrue(AppleOwnership.excludesFromAvailability(url: nil, notes: "My notes\n" + marker, excludingOwnedTokens: excluded))
        XCTAssertFalse(AppleOwnership.excludesFromAvailability(url: URL(string: detachedMarker), notes: nil, excludingOwnedTokens: excluded))
        XCTAssertFalse(AppleOwnership.excludesFromAvailability(url: URL(string: marker), notes: detachedMarker, excludingOwnedTokens: excluded))
        XCTAssertFalse(AppleOwnership.excludesFromAvailability(url: nil, notes: "Same cooking title", excludingOwnedTokens: excluded))
        XCTAssertFalse(AppleOwnership.excludesFromAvailability(url: nil, notes: "See " + marker, excludingOwnedTokens: excluded))
        XCTAssertFalse(AppleOwnership.excludesFromAvailability(url: URL(string: marker + "?foreign=1"), notes: nil, excludingOwnedTokens: excluded))
    }
    func testUnsettledOrUnknownSyncCountsMarkedEventsAsExternalBusy() {
        let token = UUID()
        let linked: Set<UUID> = [token]
        let settled = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0,
            conflicts: 0, unavailable: 0, lastSuccess: "2026-10-09T12:00:00+00:00")
        let status = IntegrationStatus(modelVersion: 1, configured: true, connected: true, paused: false,
            settingsRevision: 1, report: settled, permissions: [:], destinations: [:], scopes: [], conflicts: [])
        XCTAssertEqual(AppleOwnership.availabilityExclusions(linked, status: status, syncReport: settled), linked)
        XCTAssertTrue(AppleOwnership.availabilityExclusions(linked, status: nil, syncReport: settled).isEmpty)
        let unavailable = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0,
            conflicts: 0, unavailable: 1, lastSuccess: settled.lastSuccess)
        XCTAssertTrue(AppleOwnership.availabilityExclusions(linked, status: status, syncReport: unavailable).isEmpty)
        let pending = SyncReport(created: 0, updated: 0, deleted: 0, queued: 1,
            conflicts: 0, unavailable: 0, lastSuccess: settled.lastSuccess)
        XCTAssertTrue(AppleOwnership.availabilityExclusions(linked, status: status, syncReport: pending).isEmpty)
    }
}
