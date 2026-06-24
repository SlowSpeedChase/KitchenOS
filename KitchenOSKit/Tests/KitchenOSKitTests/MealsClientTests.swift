import XCTest
@testable import KitchenOSKit

final class MealsClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testMealsUnwrapsList() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/meals")
            let body = """
            {"meals":[{"name":"Salmon Dinner","description":"","tags":["dinner"],
              "sub_recipes":[{"recipe":"Baked Salmon","servings":2},{"recipe":"Rice","servings":1}]}]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let meals = try await client.meals()
        XCTAssertEqual(meals.first?.name, "Salmon Dinner")
        XCTAssertEqual(meals.first?.subRecipes.count, 2)
        XCTAssertEqual(meals.first?.subRecipes.first?.servings, 2)
    }

    func testCreateMealPostsSubRecipes() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/meals")
            XCTAssertEqual(req.httpMethod, "POST")
            let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
            XCTAssertEqual(json["name"] as? String, "Taco Night")
            let subs = json["sub_recipes"] as! [[String: Any]]
            XCTAssertEqual(subs.first?["recipe"] as? String, "Tacos")
            let echo = #"{"name":"Taco Night","description":"","tags":[],"sub_recipes":[{"recipe":"Tacos","servings":1}]}"#
            return (HTTPURLResponse(url: req.url!, statusCode: 201, httpVersion: nil, headerFields: nil)!,
                    echo.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        let created = try await client.createMeal(
            Meal(name: "Taco Night", subRecipes: [SubRecipe(recipe: "Tacos")]))
        XCTAssertEqual(created.name, "Taco Night")
    }

    func testDeleteMealUsesDELETE() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "DELETE")
            XCTAssertEqual(req.url?.path, "/api/meals/Taco Night")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"status":"deleted"}"#.data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock()
        try await client.deleteMeal(name: "Taco Night")
    }

    func testTasksDecodeAndMarkDone() async throws {
        MockURLProtocol.handler = { req in
            if req.httpMethod == "POST" {
                XCTAssertEqual(req.url?.path, "/api/tasks/2026-W26/abc123/done")
                let json = try! JSONSerialization.jsonObject(with: req.bodyData()) as! [String: Any]
                XCTAssertEqual(json["done"] as? Bool, true)
                return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                        #"{"success":true}"#.data(using: .utf8)!)
            }
            XCTAssertEqual(req.url?.path, "/api/tasks/2026-W26")
            let body = """
            {"week":"2026-W26","generated_at":"2026-06-23T00:00:00",
             "tasks":[{"id":"abc123","recipe":"Chili","day":"Monday","slot":"dinner",
                       "step":1,"text":"Soak beans","type":"prep","time_minutes":5,
                       "can_do_ahead":true,"depends_on":[],"done":false}]}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let payload = try await client.tasks(week: "2026-W26")
        XCTAssertEqual(payload.tasks.first?.id, "abc123")
        XCTAssertTrue(payload.tasks.first?.canDoAhead == true)
        try await client.markTask(week: "2026-W26", taskId: "abc123", done: true)
    }
}

private extension URLRequest {
    func bodyData() -> Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
        stream.open(); defer { stream.close() }
        var data = Data()
        let bufSize = 1024
        let buf = UnsafeMutablePointer<UInt8>.allocate(capacity: bufSize)
        defer { buf.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buf, maxLength: bufSize)
            if read <= 0 { break }
            data.append(buf, count: read)
        }
        return data
    }
}
