import XCTest
@testable import KitchenOSKit

final class RecipeQueryTests: XCTestCase {
    private func summary(_ name: String, cuisine: String? = nil,
                         protein: String? = nil, items: [String]? = nil) -> RecipeSummary {
        RecipeSummary(name: name, cuisine: cuisine, protein: protein, image: nil, ingredientItems: items)
    }

    func testEmptyQueryMatchesEverything() {
        let q = RecipeQuery(ingredient: nil, protein: nil, cuisine: nil)
        XCTAssertTrue(q.isEmpty)
        XCTAssertTrue(q.matches(summary("X", cuisine: "Thai", protein: "beef")))
    }

    func testProteinFilterIsCaseInsensitive() {
        let q = RecipeQuery(ingredient: nil, protein: "Chicken", cuisine: nil)
        XCTAssertTrue(q.matches(summary("A", protein: "chicken")))
        XCTAssertFalse(q.matches(summary("B", protein: "beef")))
    }

    func testCuisineFilter() {
        let q = RecipeQuery(ingredient: nil, protein: nil, cuisine: "indian")
        XCTAssertTrue(q.matches(summary("A", cuisine: "Indian")))
        XCTAssertFalse(q.matches(summary("B", cuisine: "Italian")))
    }

    func testIngredientCheckedOnlyWhenItemsPresent() {
        let q = RecipeQuery(ingredient: "egg", protein: nil, cuisine: nil)
        XCTAssertTrue(q.matches(summary("A", items: ["eggplant", "oil"])))
        XCTAssertFalse(q.matches(summary("B", items: ["beef"])))
        // No items (server already filtered by ingredient) -> ingredient check skipped.
        XCTAssertTrue(q.matches(summary("C", items: nil)))
    }

    func testGeneratedContentRoundTrip() throws {
        let q = RecipeQuery(ingredient: "eggplant", protein: nil, cuisine: "Italian")
        let back = try RecipeQuery(q.generatedContent)
        XCTAssertEqual(back, q)
    }

    private func nutri(_ name: String, protein: Double?, fat: Double?, cal: Double?) -> RecipeSummary {
        RecipeSummary(name: name, nutritionCalories: cal, nutritionProtein: protein, nutritionFat: fat)
    }

    func testRankedHighProteinLowFatSortsAndCaps() {
        let q = RecipeQuery(highProtein: true, lowFat: true)
        let input = [
            nutri("LowP", protein: 10, fat: 2, cal: 300),
            nutri("HighP_HighFat", protein: 40, fat: 30, cal: 600),
            nutri("HighP_LowFat", protein: 40, fat: 5, cal: 500),
        ]
        let r = q.ranked(input)
        XCTAssertEqual(r.map(\.name), ["HighP_LowFat", "HighP_HighFat", "LowP"])
    }

    func testRankedNoPreferenceReturnsUnchanged() {
        let q = RecipeQuery(ingredient: "chicken")
        let input = [nutri("A", protein: 5, fat: 5, cal: 100), nutri("B", protein: 50, fat: 1, cal: 200)]
        XCTAssertEqual(q.ranked(input).map(\.name), ["A", "B"])
    }

    func testRankedGracefulWhenNoNutritionData() {
        let q = RecipeQuery(highProtein: true)
        let input = [summary("A"), summary("B")]   // no nutrition fields
        XCTAssertEqual(q.ranked(input).map(\.name), ["A", "B"])
    }
}
