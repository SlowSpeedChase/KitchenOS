import XCTest
@testable import KitchenOSKit

final class ModelsTests: XCTestCase {
    func testDecodeRecipeSummary() throws {
        let json = """
        [{"name":"Butter Chicken","cuisine":"Indian","protein":"chicken",
          "image":"Butter Chicken.jpg","ingredient_items":["chicken thighs","cream"]}]
        """.data(using: .utf8)!
        let recipes = try JSONDecoder().decode([RecipeSummary].self, from: json)
        XCTAssertEqual(recipes.first?.name, "Butter Chicken")
        XCTAssertEqual(recipes.first?.ingredientItems, ["chicken thighs", "cream"])
    }

    func testDecodeMealPlanWithNullSlots() throws {
        let json = """
        {"week":"2026-W26","days":[
          {"day":"Monday","date":"2026-06-22","breakfast":{"name":"Pancakes","servings":1,"kind":"recipe"},
           "lunch":null,"snack":null,"dinner":null}]}
        """.data(using: .utf8)!
        let plan = try JSONDecoder().decode(MealPlan.self, from: json)
        XCTAssertEqual(plan.days.first?.breakfast?.name, "Pancakes")
        XCTAssertNil(plan.days.first?.dinner)
    }

    func testDecodeSuggestResponseNull() throws {
        let json = #"{"suggestion":null,"message":"No suggestions available"}"#.data(using: .utf8)!
        let resp = try JSONDecoder().decode(SuggestResponse.self, from: json)
        XCTAssertNil(resp.suggestion)
    }
}
