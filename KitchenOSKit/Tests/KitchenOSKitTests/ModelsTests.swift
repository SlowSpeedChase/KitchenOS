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

    func testDecodeFullRecipeDetail() throws {
        // Mirrors the /api/recipes/<name> payload shape.
        let json = """
        {"title":"Butter Chicken","cuisine":"Indian","protein":"chicken",
         "dish_type":"main","difficulty":"medium","servings":4,
         "prep_time":"20 min","cook_time":"30 min","total_time":"50 min",
         "dietary":["gluten-free"],"equipment":["blender"],"meal_occasion":["weeknight-dinner"],
         "nutrition_calories":620.0,"nutrition_protein":35.0,"nutrition_carbs":18.0,"nutrition_fat":40.0,
         "seasonal_ingredients":[],"source_url":"https://x.example","needs_review":false,
         "description":"Creamy and rich.",
         "ingredients":[{"amount":"1 1/2","unit":"cups","item":"cream","inferred":false},
                        {"amount":2,"unit":null,"item":"onions"}],
         "instructions":[{"step":1,"text":"Blend.","time":null},
                         {"step":2,"text":"Simmer.","time":"15 min"}],
         "video_tips":["Toast the spices first."]}
        """.data(using: .utf8)!
        let d = try JSONDecoder().decode(RecipeDetail.self, from: json)
        XCTAssertEqual(d.title, "Butter Chicken")
        XCTAssertEqual(d.servings, 4)
        XCTAssertEqual(d.totalTime, "50 min")
        XCTAssertEqual(d.mealOccasion, ["weeknight-dinner"])
        XCTAssertEqual(d.ingredients?.count, 2)
        // amount decoded from a string and from a bare number:
        XCTAssertEqual(d.ingredients?[0].amount, "1 1/2")
        XCTAssertEqual(d.ingredients?[0].unit, "cups")
        XCTAssertEqual(d.ingredients?[1].amount, "2")
        XCTAssertNil(d.ingredients?[1].unit)
        XCTAssertEqual(d.instructions?[1].time, "15 min")
        XCTAssertEqual(d.videoTips?.first, "Toast the spices first.")
    }

    func testDecodeMinimalRecipeDetail() throws {
        // Only the required title present; everything else absent.
        let json = #"{"title":"Toast"}"#.data(using: .utf8)!
        let d = try JSONDecoder().decode(RecipeDetail.self, from: json)
        XCTAssertEqual(d.title, "Toast")
        XCTAssertNil(d.ingredients)
        XCTAssertNil(d.nutritionCalories)
    }

    func testDecodeInventoryItemWithExpiry() throws {
        let json = Data("""
        {"name":"old milk","quantity":1,"unit":"gal","category":"dairy",
         "location":"fridge","purchased":"2026-06-13","expires":"2026-06-23",
         "expiry_status":"expired","source":"receipt","notes":""}
        """.utf8)
        let item = try JSONDecoder().decode(InventoryItem.self, from: json)
        XCTAssertEqual(item.expires, "2026-06-23")
        XCTAssertEqual(item.expiryStatus, "expired")
        XCTAssertEqual(item.purchased, "2026-06-13")
    }

    func testDecodeInventoryItemWithoutExpiryFields() throws {
        // Back-compat: name-only payloads still decode; new fields are nil.
        let json = Data(#"{"name":"rice"}"#.utf8)
        let item = try JSONDecoder().decode(InventoryItem.self, from: json)
        XCTAssertNil(item.expires)
        XCTAssertNil(item.expiryStatus)
        XCTAssertEqual(item.name, "rice")
    }
}
