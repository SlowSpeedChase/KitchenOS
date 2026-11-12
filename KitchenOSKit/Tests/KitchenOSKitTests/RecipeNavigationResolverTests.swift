import XCTest
@testable import KitchenOSKit

final class RecipeNavigationResolverTests: XCTestCase {
    func testExactCanonicalIdentityWinsOverCollidingDisplayNames() throws {
        let recipes = [RecipeSummary(name: "Rice"), RecipeSummary(name: "Rice With Beans", displayName: "Rice")]
        XCTAssertEqual(try RecipeNavigationResolver.resolve(name: "Rice", recipes: recipes), "Rice")
    }

    func testUniqueCaseInsensitiveCanonicalAndDisplayMatchesReturnCanonicalIdentity() throws {
        let recipes = [RecipeSummary(name: "Butter Chicken"), RecipeSummary(name: "High Protein Bean Lentil Dip", displayName: "Bean Dip")]
        XCTAssertEqual(try RecipeNavigationResolver.resolve(name: "butter chicken", recipes: recipes), "Butter Chicken")
        XCTAssertEqual(try RecipeNavigationResolver.resolve(name: "bean dip", recipes: recipes), "High Protein Bean Lentil Dip")
    }

    func testCollidingDisplayNamesAreAmbiguous() {
        let recipes = [RecipeSummary(name: "Chicken Caldo A", displayName: "Caldo"), RecipeSummary(name: "Chicken Caldo B", displayName: "Caldo")]
        XCTAssertThrowsError(try RecipeNavigationResolver.resolve(name: "caldo", recipes: recipes)) { error in
            XCTAssertEqual(error as? RecipeNavigationError, .ambiguous(["Chicken Caldo A", "Chicken Caldo B"]))
        }
    }

    func testMissingAndPartialNamesDoNotGuess() {
        for name in ["Unknown", "Chicken"] {
            XCTAssertThrowsError(try RecipeNavigationResolver.resolve(name: name, recipes: [RecipeSummary(name: "Butter Chicken")])) { error in
                XCTAssertEqual(error as? RecipeNavigationError, .missing(name))
            }
        }
    }

    func testUnsafeNamesNeverProduceTargetsEvenWhenListed() {
        for name in ["", " ", ".", "..", "../Rice", "Rice/Beans", "Rice\\Beans", "Rice\nBeans", "Rice\u{0}Beans"] {
            XCTAssertThrowsError(try RecipeNavigationResolver.resolve(name: name, recipes: [RecipeSummary(name: name)]), name)
        }
        XCTAssertThrowsError(try RecipeNavigationResolver.resolve(name: "Rice", recipes: [RecipeSummary(name: "../Rice", displayName: "Rice")]))
    }

    func testCanonicalUnicodeAndURLPunctuationRemainUnencoded() throws {
        let name = "Crème & Rice #50%"
        XCTAssertEqual(try RecipeNavigationResolver.resolve(name: name, recipes: [RecipeSummary(name: name)]), name)
        let literalPercent = "Rice %2F Beans"
        XCTAssertEqual(try RecipeNavigationResolver.resolve(name: literalPercent, recipes: [RecipeSummary(name: literalPercent)]), literalPercent)
    }

    func testBothSummaryPayloadVersionsResolveCanonicalName() throws {
        for json in [#"{"name":"Butter Chicken"}"#, #"{"name":"Butter Chicken","display_name":"Chicken"}"#] {
            let recipe = try JSONDecoder().decode(RecipeSummary.self, from: Data(json.utf8))
            XCTAssertEqual(try RecipeNavigationResolver.resolve(name: recipe.displayName ?? recipe.name, recipes: [recipe]), "Butter Chicken")
        }
    }
}
