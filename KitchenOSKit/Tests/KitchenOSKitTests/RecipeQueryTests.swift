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
}
