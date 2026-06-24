import XCTest
@testable import KitchenOSKit

final class RecipeLinkTests: XCTestCase {
    func testObsidianURL() throws {
        let url = try XCTUnwrap(RecipeLink.obsidianURL(recipe: "Butter Chicken", vault: "KitchenOS"))
        XCTAssertEqual(url.scheme, "obsidian")
        XCTAssertEqual(url.host, "open")
        let s = url.absoluteString
        XCTAssertTrue(s.contains("vault=KitchenOS"), s)
        XCTAssertTrue(s.contains("file=Recipes/Butter%20Chicken.md"), s)
    }

    func testNilForEmptyInputs() {
        XCTAssertNil(RecipeLink.obsidianURL(recipe: "", vault: "KitchenOS"))
        XCTAssertNil(RecipeLink.obsidianURL(recipe: "X", vault: "  "))
    }
}
