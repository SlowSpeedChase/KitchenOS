import XCTest
@testable import KitchenOSKit

final class AddRequestParserTests: XCTestCase {
    func testParsesRecipeDayMeal() {
        let p = AddRequestParser.parse("add butter chicken to thursday dinner")
        XCTAssertEqual(p, PendingMealAddition(recipe: "Butter Chicken", day: "Thursday", meal: "dinner"))
    }

    func testDefaultsToDinnerWhenMealOmitted() {
        let p = AddRequestParser.parse("Add Beef Stew to Monday")
        XCTAssertEqual(p, PendingMealAddition(recipe: "Beef Stew", day: "Monday", meal: "dinner"))
    }

    func testHandlesForMeal() {
        let p = AddRequestParser.parse("please add pancakes to sunday for breakfast")
        XCTAssertEqual(p, PendingMealAddition(recipe: "Pancakes", day: "Sunday", meal: "breakfast"))
    }

    func testNilForNonAddRequests() {
        XCTAssertNil(AddRequestParser.parse("what's on my plan thursday"))
        XCTAssertNil(AddRequestParser.parse("find chicken recipes"))
    }
}
