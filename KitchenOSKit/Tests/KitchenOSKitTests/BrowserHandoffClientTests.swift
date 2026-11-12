import XCTest
@testable import KitchenOSKit

final class BrowserHandoffClientTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }
    func testPostsTypedDestinationWithHeaderOnlyBearerAndReturnsValidatedPath() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "POST")
            XCTAssertEqual(req.url?.absoluteString, "http://kitchen.example:5001/api/browser-handoffs")
            XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer private-key")
            XCTAssertEqual(req.value(forHTTPHeaderField: "Content-Type"), "application/json")
            let data: Data
            if let body = req.httpBody { data = body } else {
                let stream = req.httpBodyStream!; stream.open(); defer { stream.close() }
                var bytes = [UInt8](repeating: 0, count: 2048)
                let count = stream.read(&bytes, maxLength: bytes.count)
                data = Data(bytes.prefix(count))
            }
            XCTAssertEqual(try JSONSerialization.jsonObject(with: data) as? [String: String], ["kind": "recipe", "name": "Rice & Beans"])
            let body = #"{"handoff_path":"/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF","expires_at":1790000000}"#
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        let response = try await KitchenOSClient.mock(baseURL: "http://kitchen.example:5001", token: "private-key").createBrowserHandoff(destination: .recipe(name: "Rice & Beans"))
        XCTAssertEqual(response.handoffPath, "/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF")
        XCTAssertEqual(response.expiresAt, 1790000000)
    }
    func testRejectsPoisonedResponsePathAndCrossOriginResponse() async {
        for (path, origin) in [("https://evil.example/browser/open#code=x", "http://kitchen.example:5001"), ("/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF", "https://evil.example")] {
            MockURLProtocol.handler = { _ in
                let data = try JSONSerialization.data(withJSONObject: ["handoff_path": path, "expires_at": 1790000000])
                return (HTTPURLResponse(url: URL(string: origin)!, statusCode: 200, httpVersion: nil, headerFields: nil)!, data)
            }
            do {
                _ = try await KitchenOSClient.mock(baseURL: "http://kitchen.example:5001").createBrowserHandoff(destination: .mealPlan(date: "2026-10-16"))
                XCTFail("Untrusted handoff must fail")
            } catch { }
        }
    }
    func testInvalidTargetFailsBeforeNetwork() async {
        MockURLProtocol.handler = { _ in XCTFail("Invalid target should not make a request"); throw URLError(.badURL) }
        for target in [WebDestination.recipe(name: "../private"), .mealPlan(date: "2026-02-29")] {
            do { _ = try await KitchenOSClient.mock().createBrowserHandoff(destination: target); XCTFail("Expected validation") }
            catch { }
        }
    }
    func testHandoffCancellationRemainsCancellationRatherThanUnreachable() async {
        MockURLProtocol.handler = { _ in throw URLError(.cancelled) }
        do {
            _ = try await KitchenOSClient.mock().createBrowserHandoff(destination: .recipe(name: "Beans"))
            XCTFail("Cancelled handoff should throw")
        } catch {
            XCTAssertTrue(error is CancellationError, "Cancellation must not become a server-unreachable error: \(error)")
        }
    }
    func testRedirectDelegateRefusesEvenSameOriginRedirect() {
        let delegate = BrowserHandoffRedirectPolicy()
        let session = URLSession(configuration: .ephemeral)
        let task = session.dataTask(with: URL(string: "http://kitchen.example:5001/api/browser-handoffs")!)
        let target = URL(string: "http://kitchen.example:5001/other")!
        let response = HTTPURLResponse(url: target, statusCode: 307, httpVersion: nil, headerFields: nil)!
        var didDecide = false
        delegate.urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: URLRequest(url: target)) { request in
            didDecide = true
            XCTAssertNil(request)
        }
        XCTAssertTrue(didDecide)
        session.invalidateAndCancel()
    }
}
