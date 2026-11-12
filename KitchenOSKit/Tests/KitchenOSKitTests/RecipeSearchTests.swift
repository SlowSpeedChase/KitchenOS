import XCTest
@testable import KitchenOSKit

final class RecipeSearchTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testRecipesMatchingSendsIngredientAndFiltersLocally() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/recipes")
            XCTAssertEqual(req.url?.query, "ingredient=chicken")
            let body = """
            [{"name":"Butter Chicken","cuisine":"Indian","protein":"chicken","ingredient_items":["chicken thighs"]},
             {"name":"Chicken Tacos","cuisine":"Mexican","protein":"chicken","ingredient_items":["chicken breast"]}]
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let q = RecipeQuery(ingredient: "chicken", protein: nil, cuisine: "Indian")
        let results = try await client.recipes(matching: q)
        XCTAssertEqual(results.map(\.name), ["Butter Chicken"])  // Mexican filtered out by cuisine
    }

    func testRecipesMatchingWithNoIngredientSendsEmptyAndFiltersByProtein() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.query, "ingredient=")
            let body = """
            [{"name":"Beef Stew","protein":"beef"},{"name":"Tofu Bowl","protein":"tofu"}]
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let q = RecipeQuery(ingredient: nil, protein: "tofu", cuisine: nil)
        let results = try await client.recipes(matching: q)
        XCTAssertEqual(results.map(\.name), ["Tofu Bowl"])
    }

    func testAllRecipesIncludeIngredientsSendsParamAndDecodes() async throws {
        MockURLProtocol.handler = { request in
            let comps = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!
            XCTAssertEqual(comps.path, "/api/recipes")
            XCTAssertTrue(comps.queryItems?.contains(URLQueryItem(name: "include_ingredients", value: "1")) ?? false)
            let body = #"[{"name": "Butter Chicken", "cuisine": "Indian", "protein": "chicken", "ingredient_items": ["chicken thighs", "garam masala"]}]"#
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    Data(body.utf8))
        }
        let recipes = try await KitchenOSClient.mock().allRecipes(includeIngredients: true)
        XCTAssertEqual(recipes.first?.ingredientItems, ["chicken thighs", "garam masala"])
    }
}
