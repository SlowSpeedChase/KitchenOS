import XCTest
@testable import KitchenOSKit

final class MealPlanEditTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testAddRecipeIssuesGetThenPut() async throws {
        var methods: [String] = []
        MockURLProtocol.handler = { req in
            methods.append(req.httpMethod ?? "")
            if req.httpMethod == "PUT" {
                return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                        #"{"status":"saved","week":"2026-W26"}"#.data(using: .utf8)!)
            }
            let body = #"{"week":"2026-W26","days":[{"day":"Thursday","date":"2026-06-25","breakfast":null,"lunch":null,"snack":null,"dinner":null}]}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        try await client.addRecipe("Chili", day: "Thursday", meal: .dinner, week: "2026-W26")
        XCTAssertEqual(methods, ["GET", "PUT"])
    }

    func testAddRecipeThrows404WhenDayMissing() async {
        MockURLProtocol.handler = { req in
            let body = #"{"week":"2026-W26","days":[{"day":"Monday","date":"2026-06-22","breakfast":null,"lunch":null,"snack":null,"dinner":null}]}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        do {
            try await client.addRecipe("Chili", day: "Friday", meal: .dinner, week: "2026-W26")
            XCTFail("expected 404")
        } catch let KitchenOSError.http(code) {
            XCTAssertEqual(code, 404)
        } catch {
            XCTFail("wrong error: \(error)")
        }
    }

    func testAddToMealPlanToolCapturesProposalAndDoesNotWrite() async throws {
        let store = ProposalStore()
        let tool = AddToMealPlanTool(onPropose: { store.set($0) })
        let out = try await tool.call(arguments: AddToMealPlanArguments(recipe: "Chili", day: "Thursday", meal: "dinner"))
        XCTAssertTrue(out.contains("Confirm"))
        XCTAssertEqual(store.take(), PendingMealAddition(recipe: "Chili", day: "Thursday", meal: "dinner"))
    }

    func testAddArgumentsRoundTrip() throws {
        let a = AddToMealPlanArguments(recipe: "Chili", day: "Thursday", meal: "dinner")
        let back = try AddToMealPlanArguments(a.generatedContent)
        XCTAssertEqual(back.recipe, "Chili")
        XCTAssertEqual(back.day, "Thursday")
        XCTAssertEqual(back.meal, "dinner")
    }
}
