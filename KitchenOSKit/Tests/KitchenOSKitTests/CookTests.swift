import XCTest
@testable import KitchenOSKit

final class CookTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testRecipesByIngredientsParses() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/recipes/by-ingredients")
            XCTAssertEqual(req.httpMethod, "POST")
            let body = #"{"matches":[{"name":"Stir Fry","score":0.6,"shared_ingredients":["chicken","rice"]}]}"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let r = try await client.recipesByIngredients(["chicken", "rice"])
        XCTAssertEqual(r.first?.name, "Stir Fry")
        XCTAssertEqual(r.first?.sharedIngredients, ["chicken", "rice"])
    }

    func testCookToolFallsBackToInventoryWhenEmpty() async throws {
        MockURLProtocol.handler = { req in
            if req.url?.path == "/api/inventory" {
                return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                        #"[{"name":"eggs"},{"name":"spinach"}]"#.data(using: .utf8)!)
            }
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"matches":[{"name":"Omelette","score":0.5,"shared_ingredients":["eggs"]}]}"#.data(using: .utf8)!)
        }
        let tool = CookWithIngredientsTool(client: .mock())
        let out = try await tool.call(arguments: CookWithArguments(ingredients: []))
        XCTAssertTrue(out.contains("Omelette"), out)
    }

    func testFormatListsSharedIngredients() {
        let out = CookWithIngredientsTool.format([Suggestion(name: "A", score: 0.5, sharedIngredients: ["x", "y"])])
        XCTAssertTrue(out.contains("uses x, y"), out)
    }
}
