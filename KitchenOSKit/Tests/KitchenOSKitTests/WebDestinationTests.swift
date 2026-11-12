import Foundation
import XCTest
@testable import KitchenOSKit

final class WebDestinationTests: XCTestCase {
    private let code = String(repeating: "a", count: 43)

    func testRecipeJSONContainsOnlyTypedCanonicalIdentity() throws {
        let destination = WebDestination.recipe(name: "Crème & Rice #50%")
        let data = try JSONEncoder().encode(destination)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])
        XCTAssertEqual(json, ["kind": "recipe", "name": "Crème & Rice #50%"])
        XCTAssertEqual(try JSONDecoder().decode(WebDestination.self, from: data), destination)
    }

    func testMealPlanJSONContainsOnlyCivilDate() throws {
        let destination = WebDestination.mealPlan(date: "2026-10-16")
        let data = try JSONEncoder().encode(destination)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])
        XCTAssertEqual(json, ["kind": "meal_plan", "date": "2026-10-16"])
        XCTAssertEqual(try JSONDecoder().decode(WebDestination.self, from: data), destination)
    }

    func testDecoderRejectsUnknownKindsAndMixedOrExtraFields() {
        for json in [
            #"{"kind":"url","url":"https://example.com"}"#,
            #"{"kind":"recipe","name":"Rice","date":"2026-10-16"}"#,
            #"{"kind":"meal_plan","date":"2026-10-16","url":"https://example.com"}"#,
            #"{"kind":"recipe","name":"Rice","token":"secret"}"#,
            #"{"kind":"meal_plan"}"#
        ] {
            XCTAssertThrowsError(try JSONDecoder().decode(WebDestination.self, from: Data(json.utf8)), json)
        }
    }

    func testHandoffUsesConfiguredSchemeHostAndPort() throws {
        for origin in ["http://kitchen.tailnet:8787", "https://kitchen.example:8443/"] {
            let url = try WebDestination.handoffURL(relativePath: "/browser/open#code=\(code)", baseURL: URL(string: origin)!)
            XCTAssertEqual(url.absoluteString, origin.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/browser/open#code=\(code)")
        }
    }

    func testHandoffRejectsUnsupportedBaseOrigins() {
        for origin in ["file:///tmp/", "https://user:pass@kitchen.example", "https://kitchen.example/proxy/", "https://kitchen.example?token=secret", "https://kitchen.example#fragment", "/relative"] {
            XCTAssertThrowsError(try WebDestination.handoffURL(relativePath: "/browser/open#code=\(code)", baseURL: URL(string: origin)!), origin)
        }
    }

    func testHandoffRejectsEveryOtherBootstrapShape() {
        for path in [
            "https://evil.example/browser/open#code=\(code)", "//evil.example/browser/open#code=\(code)",
            "browser/open#code=\(code)", "/recipe/Rice#code=\(code)",
            "/browser/open?code=\(code)", "/browser/open?x=1#code=\(code)",
            "/browser/open/#code=\(code)", "/browser/../browser/open#code=\(code)",
            "/browser/%6fpen#code=\(code)", "/browser/open#code=short",
            "/browser/open#code=\(code)&code=\(code)", "/browser/open#code=\(code)&x=1",
            "/browser/open#code=\(code)%26", "/browser/open#code=\(code)\n",
            "/browser/open#code=\(String(repeating: "+", count: 43))"
        ] {
            XCTAssertThrowsError(try WebDestination.handoffURL(relativePath: path, baseURL: URL(string: "http://kitchen:8787")!), path)
        }
    }
}
