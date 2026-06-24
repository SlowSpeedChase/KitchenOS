import XCTest
@testable import KitchenOSKit

final class SystemHealthClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testSystemHealthDecodes() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/system-health")
            let body = """
            {"generated_at":"2026-06-23T23:33:17",
             "ollama":{"alive":true,"error":null,"models":["mistral:7b"]},
             "vault":{"exists":true,"path":"/x/vault","writable":true},
             "recent_recipes":[{"name":"Toast","modified_iso":"2026-06-23T10:00:00"}],
             "run_logs":[{"timestamp":"2026-06-23T23:10:06","total":3,"succeeded":0,
                          "failed":0,"invalid":3,"skipped_duplicate":0,"duration_seconds":0}],
             "failure_logs":[],"reminders_queue":null}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let h = try await client.systemHealth()
        XCTAssertEqual(h.ollama?.alive, true)
        XCTAssertEqual(h.vault?.writable, true)
        XCTAssertEqual(h.recentRecipes?.first?.name, "Toast")
        XCTAssertEqual(h.runLogs?.first?.invalid, 3)
    }

    func testNutritionDashboardDecodes() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/nutrition/2026-W27")
            let body = """
            {"week":"2026-W27","week_label":"Week 27 (Jun 29 - Jul 05)",
             "targets":{"calories":2000,"protein":150,"carbs":200,"fat":65},
             "days":[{"day":"Monday","date":"2026-06-29","has_meals":false,
                      "calories":null,"protein":null,"carbs":null,"fat":null},
                     {"day":"Tuesday","date":"2026-06-30","has_meals":true,
                      "calories":1800,"protein":120,"carbs":160,"fat":60}],
             "averages":{"calories":1800,"protein":120,"carbs":160,"fat":60},
             "warnings":["Recipe 'X' missing nutrition data"]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let d = try await client.nutrition(week: "2026-W27")
        XCTAssertEqual(d.weekLabel, "Week 27 (Jun 29 - Jul 05)")
        XCTAssertEqual(d.days.count, 2)
        XCTAssertFalse(d.days[0].hasMeals)
        XCTAssertNil(d.days[0].calories)
        XCTAssertEqual(d.days[1].protein, 120)
        XCTAssertEqual(d.averages?.calories, 1800)
        XCTAssertEqual(d.warnings?.count, 1)
    }

    func testExtractReturnsRecipeName() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/extract")
            XCTAssertEqual(req.httpMethod, "POST")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"success","recipe":"Butter Chicken"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        let name = try await client.extract(url: "https://youtu.be/x")
        XCTAssertEqual(name, "Butter Chicken")
    }
}
