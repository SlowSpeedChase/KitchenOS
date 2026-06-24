import XCTest
@testable import KitchenOSKit

final class KitchenOSClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }

    func testFindRecipesParsesAndSendsIngredientQuery() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/recipes")
            XCTAssertEqual(req.url?.query, "ingredient=chicken")
            let body = #"[{"name":"Butter Chicken","ingredient_items":["chicken thighs"]}]"#.data(using: .utf8)!
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let client = KitchenOSClient.mock()
        let recipes = try await client.findRecipes(ingredient: "chicken")
        XCTAssertEqual(recipes.map(\.name), ["Butter Chicken"])
    }

    func testSendsBearerTokenWhenSet() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer secret")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    "[]".data(using: .utf8)!)
        }
        let client = KitchenOSClient.mock(token: "secret")
        _ = try await client.findRecipes(ingredient: "x")
    }

    func testHTTPErrorThrows() async {
        MockURLProtocol.handler = { req in
            (HTTPURLResponse(url: req.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!,
             Data())
        }
        let client = KitchenOSClient.mock(token: "bad")
        do { _ = try await client.findRecipes(ingredient: "x"); XCTFail("expected throw") }
        catch let KitchenOSError.http(code) { XCTAssertEqual(code, 401) }
        catch { XCTFail("wrong error: \(error)") }
    }
}
