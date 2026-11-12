import XCTest
@testable import KitchenOSKit

final class AppleIntegrationIntentParametersTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }
    private func cook(_ id: Int = 41, cooked: String? = nil, bundle: String? = nil, date: String? = nil, meal: String? = nil) -> PlannedCook {
        PlannedCook(id: id, recipe: "Same recipe", week: "2026-W41", date: date, meal: meal,
                    cookedAt: cooked, bundleID: bundle, unassigned: 4)
    }
    private let start = ISO8601DateFormatter().date(from: "2026-10-09T18:00:00-05:00")!
    private let zone = TimeZone(identifier: "America/Chicago")!
    private func json(_ id: Int, cooked: String = "null", bundle: String = "null") -> String {
        #"{"id":\#(id),"recipe":"Same recipe","week":"2026-W41","date":null,"meal":null,"cooked_at":\#(cooked),"bundle_id":\#(bundle),"unassigned":4}"#
    }
    func testDuplicateDisplayNamesRemainDistinctTypedIDs() {
        let a = PlannedCookEntity(cook(41)), b = PlannedCookEntity(cook(42))
        XCTAssertEqual(a.id, 41); XCTAssertEqual(b.id, 42)
        XCTAssertNotEqual(a.id, b.id)
        XCTAssertNotEqual(a.selectionLabel, b.selectionLabel)
    }
    func testISOWeekUsesWeekYearAndExplicitLocalTimezone() {
        let date = ISO8601DateFormatter().date(from: "2021-01-04T01:00:00Z")!
        XCTAssertEqual(CookingIntentParameters.weekID(for: date, timeZone: zone), "2020-W53")
        XCTAssertEqual(CookingIntentParameters.weekID(for: date, timeZone: TimeZone(secondsFromGMT: 0)!), "2021-W01")
    }
    func testExactEntityResolutionSkipsMissingCookedBundleAndNeverMatchesTitles() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer secret")
            let id = Int(request.url!.lastPathComponent)!
            XCTAssertEqual(request.url!.path, "/api/cooks/\(id)")
            let code = id == 43 ? 404 : 200
            let body = id == 44 ? self.json(id, cooked: #""2026-10-09""#) : id == 45 ? self.json(id, bundle: #""plate""#) : self.json(id)
            return (HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        let query = PlannedCookEntityQuery(client: .mock(token: "secret"))
        let entities = try await query.entities(for: [41, 42, 43, 44, 45])
        XCTAssertEqual(entities.map(\.id), [41,42])
    }
    func testLookupFailureIsNotInventedEntityOrEmptySuccess() async {
        MockURLProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 503, httpVersion: nil, headerFields: nil)!, Data())
        }
        do { _ = try await PlannedCookEntityQuery(client: .mock()).entities(for: [41]); XCTFail("unavailable must throw") }
        catch { XCTAssertEqual(error as? KitchenOSError, .http(503)) }
    }
    func testWeekOptionsFilterIneligibleCooksAndKeepDuplicateNames() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/week-board/2026-W41")
            let body = "{\"cooks\":[\(self.json(41)),\(self.json(42)),\(self.json(43,cooked: #""done""#)),\(self.json(44,bundle: #""plate""#))]}"
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        let options = try await KitchenOSClient.mock().plannedCooks(week: "2026-W41")
        XCTAssertEqual(options.map(\.id), [41,42])
    }
    func testRejectsInvalidDurationAndIneligibleCook() {
        for duration in [0,14,16,361,375] {
            XCTAssertThrowsError(try CookingIntentParameters(cook: cook(), start: start, timeZone: zone, durationMinutes: duration, meal: .dinner, servingsToEat: 1))
        }
        for value in [cook(cooked: "done"), cook(bundle: "plate"), cook(0)] {
            XCTAssertThrowsError(try CookingIntentParameters(cook: value, start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: 1))
        }
    }
    func testRequiresPositiveFiniteFirstPlacementWithinCapacity() {
        for value: Double? in [nil,0,-1,.nan,.infinity,5] {
            XCTAssertThrowsError(try CookingIntentParameters(cook: cook(), start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: value))
        }
        XCTAssertNoThrow(try CookingIntentParameters(cook: cook(), start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: 1.5))
        XCTAssertNoThrow(try CookingIntentParameters(cook: cook(date: "2026-10-08", meal: "lunch"), start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: nil))
    }
    func testRejectsOtherWeekOffGridTimeAndMidnightOverrun() {
        for text in ["2026-10-12T18:00:00-05:00", "2026-10-09T18:01:00-05:00", "2026-10-09T18:00:00.5-05:00", "2026-10-09T23:30:00-05:00"] {
            let formatter = ISO8601DateFormatter()
            if text.contains(".5") { formatter.formatOptions.insert(.withFractionalSeconds) }
            XCTAssertThrowsError(try CookingIntentParameters(cook: cook(), start: formatter.date(from: text)!, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: 1))
        }
    }
    func testSchedulingRefetchesIDThenPostsOffsetAndFractionalServingsToLedgerOnly() async throws {
        var paths: [String] = []
        MockURLProtocol.handler = { request in
            paths.append(request.httpMethod! + " " + request.url!.path)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer secret")
            if request.httpMethod == "POST" {
                let stream = request.httpBodyStream!; stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                let count = stream.read(&buffer, maxLength: buffer.count)
                let body = try JSONSerialization.jsonObject(with: Data(buffer.prefix(count))) as! [String:Any]
                XCTAssertEqual(Set(body.keys), ["date","meal","start","timezone","duration_minutes","servings_to_eat","expected_unplaced"])
                XCTAssertEqual(body["date"] as? String, "2026-10-09")
                XCTAssertEqual(body["start"] as? String, "2026-10-09T18:00:00-05:00")
                XCTAssertEqual(body["timezone"] as? String, "America/Chicago")
                XCTAssertEqual(body["servings_to_eat"] as? Double, 1.5)
                XCTAssertEqual(body["expected_unplaced"] as? Bool, true)
            }
            let body = request.httpMethod == "GET" ? self.json(41) : "{}"
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        try await KitchenOSClient.mock(token: "secret").scheduleCooking(cookID: 41, week: "2026-W41", start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: 1.5)
        XCTAssertEqual(paths, ["GET /api/cooks/41", "POST /api/cooks/41/schedule"])
    }
    func testStaleEntityCannotScheduleAfterCookedOrWeekChanged() async {
        var writes = 0
        MockURLProtocol.handler = { request in
            if request.httpMethod != "GET" { writes += 1 }
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(self.json(41,cooked: #""done""#).utf8))
        }
        do { try await KitchenOSClient.mock().scheduleCooking(cookID: 41, week: "2026-W41", start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: 1); XCTFail("stale cook") } catch {}
        XCTAssertEqual(writes, 0)
    }
    func testDisconnectedOrArchivedAfterSyncNeverReportsDelivery() {
        let empty = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)
        XCTAssertEqual(AppleIntentResult(report: empty, connected: false).outcome, .unavailable)
        XCTAssertEqual(AppleIntentResult(report: empty, scopeActive: false).outcome, .unavailable)
        let changed = SyncReport(created: 1, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)
        XCTAssertEqual(AppleIntentResult(report: changed, connected: false).outcome, .partial)
        XCTAssertEqual(AppleIntentResult(report: changed, scopeActive: false).outcome, .partial)
    }
    func testReportsDistinguishDeliveredQueuedPartialConflictUnavailableAndSetup() {
        func report(_ created: Int = 0, queued: Int = 0, conflicts: Int = 0, unavailable: Int = 0) -> SyncReport {
            SyncReport(created: created, updated: 0, deleted: 0, queued: queued, conflicts: conflicts, unavailable: unavailable, lastSuccess: nil)
        }
        XCTAssertEqual(AppleIntentResult(report: report(2)).outcome, .delivered)
        XCTAssertEqual(AppleIntentResult(report: report(queued: 2)).outcome, .queued)
        XCTAssertEqual(AppleIntentResult(report: report(1, queued: 2)).outcome, .partial)
        XCTAssertEqual(AppleIntentResult(report: report(conflicts: 1)).outcome, .conflict)
        XCTAssertEqual(AppleIntentResult(report: report(unavailable: 1)).outcome, .unavailable)
        XCTAssertEqual(AppleIntentResult(report: report(), paused: true).outcome, .queued)
        XCTAssertEqual(AppleIntentResult.setup.outcome, .setup)
        XCTAssertTrue(AppleIntentResult(report: report(1, queued: 2, conflicts: 3, unavailable: 4)).message.contains("2 queued"))
        XCTAssertTrue(AppleIntentResult.setup.message.contains("Run the action again"))
    }
    func testOmittedAnchoredServingsRemainNullAndCarryPlacementPrecondition() async throws {
        MockURLProtocol.handler = { request in
            if request.httpMethod == "POST" {
                let stream = request.httpBodyStream!; stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                let count = stream.read(&buffer, maxLength: buffer.count)
                let body = try JSONSerialization.jsonObject(with: Data(buffer.prefix(count))) as! [String:Any]
                XCTAssertTrue(body["servings_to_eat"] is NSNull, "omission must never become an invented serving")
                XCTAssertEqual(body["expected_unplaced"] as? Bool, false)
            }
            let body = request.httpMethod == "GET" ? self.json(41).replacingOccurrences(of: #""date":null,"meal":null"#, with: #""date":"2026-10-08","meal":"lunch""#) : "{}"
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        try await KitchenOSClient.mock().scheduleCooking(cookID: 41, week: "2026-W41", start: start, timeZone: zone, durationMinutes: 60, meal: .dinner, servingsToEat: nil)
    }

    func testFreshStatusAvailabilityAndPendingWorkOverrideAnEarlierCleanReport() {
        let clean = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)
        let changed = SyncReport(created: 2, updated: 1, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)
        func status(permission: AppleAuthorization? = .authorized, destinations: [AppleDestination] = [AppleDestination(id: "calendar", title: "Cooking")], report: SyncReport? = nil) -> IntegrationStatus {
            IntegrationStatus(modelVersion: 1, configured: true, connected: true, paused: false, settingsRevision: 1,
                report: report ?? clean, permissions: permission.map { ["cooking":$0] } ?? [:], destinations: ["cooking":destinations],
                scopes: [AppleScope(domain: .cooking, week: "2026-W41", destinationID: "calendar", status: .active, revision: 1)], conflicts: [])
        }
        for permission: AppleAuthorization? in [.denied, .writeOnly, .unknown, nil] {
            XCTAssertEqual(AppleIntentResult(report: clean, latest: status(permission: permission)).outcome, .unavailable)
            XCTAssertEqual(AppleIntentResult(report: changed, latest: status(permission: permission)).outcome, .partial)
        }
        for destinations in [[], [AppleDestination(id: "different", title: "Cooking")]] {
            XCTAssertEqual(AppleIntentResult(report: clean, latest: status(destinations: destinations)).outcome, .unavailable)
        }
        for (report, outcome): (SyncReport, AppleIntentResult.Outcome) in [
            (SyncReport(created: 0, updated: 0, deleted: 0, queued: 3, conflicts: 0, unavailable: 0, lastSuccess: nil), .queued),
            (SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 2, unavailable: 0, lastSuccess: nil), .conflict),
            (SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 1, lastSuccess: nil), .unavailable)
        ] {
            XCTAssertEqual(AppleIntentResult(report: clean, latest: status(report: report)).outcome, outcome)
            XCTAssertEqual(AppleIntentResult(report: changed, latest: status(report: report)).outcome, .partial)
        }
        XCTAssertEqual(AppleIntentResult(report: clean, latest: status()).outcome, .delivered)
        let result = AppleIntentResult(report: changed, latest: status(report: SyncReport(created: 9, updated: 9, deleted: 9, queued: 3, conflicts: 0, unavailable: 0, lastSuccess: nil)))
        XCTAssertTrue(result.message.contains("2 created, 1 updated"), "keep operation successes, not status historical counts")
        XCTAssertTrue(result.message.contains("3 queued"))
    }

    func testFreshAvailabilityChecksAllActiveScopesButDoesNotRequireInactiveDomains() {
        let report = SyncReport(created: 0, updated: 0, deleted: 0, queued: 0, conflicts: 0, unavailable: 0, lastSuccess: nil)
        let cooking = AppleScope(domain: .cooking, week: "2026-W41", destinationID: "calendar", status: .active, revision: 1)
        func latest(_ prepState: AppleScopeState) -> IntegrationStatus {
            IntegrationStatus(modelVersion: 1, configured: true, connected: true, paused: false, settingsRevision: 1, report: report,
                permissions: ["cooking":.authorized,"prep":.denied], destinations: ["cooking":[AppleDestination(id: "calendar", title: "Cooking")]],
                scopes: [cooking, AppleScope(domain: .prep, week: "2026-W41", destinationID: "list", status: prepState, revision: 1)], conflicts: [])
        }
        XCTAssertEqual(AppleIntentResult(report: report, latest: latest(.active)).outcome, .unavailable)
        XCTAssertEqual(AppleIntentResult(report: report, latest: latest(.archived)).outcome, .delivered)
        XCTAssertEqual(AppleIntentResult(report: report, latest: latest(.archived), scopeActive: false).outcome, .unavailable)
    }

}
