import XCTest
import CoreSpotlight
@testable import KitchenOSKit

final class RecipeEntityIndexTests: XCTestCase {
    func testAttributeSetIncludesNameAndFacets() {
        let e = RecipeEntity(id: "Butter Chicken", cuisine: "Indian", proteinName: "chicken")
        let set = e.attributeSet
        XCTAssertEqual(set.title, "Butter Chicken")
        XCTAssertEqual(set.displayName, "Butter Chicken")
        XCTAssertEqual(set.keywords, ["Indian", "chicken"])
        XCTAssertEqual(set.contentDescription, "Indian · chicken")
    }

    func testAttributeSetWithNoFacets() {
        let e = RecipeEntity(id: "Plain Toast")
        XCTAssertEqual(e.attributeSet.title, "Plain Toast")
        XCTAssertNil(e.attributeSet.keywords)
    }
}
