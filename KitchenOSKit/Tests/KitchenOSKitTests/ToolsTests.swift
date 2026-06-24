import XCTest
@testable import KitchenOSKit

final class ToolsTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testFindRecipesToolFormatsResults() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/recipes")
            let body = #"[{"name":"Butter Chicken","cuisine":"Indian","protein":"chicken","ingredient_items":["chicken thighs"]}]"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let tool = FindRecipesTool(client: .mock())
        let out = try await tool.call(arguments: RecipeQuery(ingredient: "chicken", protein: nil, cuisine: nil))
        XCTAssertTrue(out.contains("Butter Chicken"))
        XCTAssertTrue(out.contains("Indian"))
    }

    func testMealPlanToolSummarizesWeek() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertTrue(req.url?.path.hasPrefix("/api/meal-plan/") ?? false)
            let body = #"{"week":"2026-W26","days":[{"day":"Monday","date":"2026-06-22","breakfast":{"name":"Pancakes","servings":1,"kind":"recipe"},"lunch":null,"snack":null,"dinner":null}]}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let tool = MealPlanTool(client: .mock())
        let out = try await tool.call(arguments: MealPlanToolArguments(day: nil))
        XCTAssertTrue(out.contains("Monday"))
        XCTAssertTrue(out.contains("Pancakes"))
    }

    func testSuggestMealToolReturnsSuggestion() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/suggest-meal")
            let body = #"{"suggestion":{"name":"Chili","score":0.8,"shared_ingredients":["beans"]},"message":null}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let tool = SuggestMealTool(client: .mock())
        let out = try await tool.call(arguments: SuggestMealToolArguments(day: "Friday", meal: "dinner"))
        XCTAssertTrue(out.contains("Chili"))
        XCTAssertTrue(out.contains("Friday"))
    }

    func testToolArgumentsRoundTrip() throws {
        let a = MealPlanToolArguments(day: "Monday")
        XCTAssertEqual(try MealPlanToolArguments(a.generatedContent).day, "Monday")
        let b = SuggestMealToolArguments(day: "Friday", meal: "dinner")
        let back = try SuggestMealToolArguments(b.generatedContent)
        XCTAssertEqual(back.day, "Friday")
        XCTAssertEqual(back.meal, "dinner")
    }
}
