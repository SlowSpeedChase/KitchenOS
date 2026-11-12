import XCTest
@testable import KitchenOSKit

@MainActor final class WebBrowserOpenerTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }
    func testForegroundHandoffOpensExactlyValidatedBootstrapAndReportsDispatch() async throws {
        MockURLProtocol.handler = { req in
            let body = #"{"handoff_path":"/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF","expires_at":1790000000}"#
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        var opened: [URL] = []
        let opener = WebBrowserOpener { url in opened.append(url); return true }
        let status = try await OpenKitchenOSWebIntent(destination: .mealPlan(date: "2026-10-16")).open(client: .mock(baseURL: "http://kitchen.example:5001"), opener: opener)
        XCTAssertEqual(opened.map(\.absoluteString), ["http://kitchen.example:5001/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF"])
        XCTAssertTrue(status.contains("2026-10-16"))
        XCTAssertTrue(status.contains("browser"))
    }
    func testBrowserRejectionIsFailure() async {
        MockURLProtocol.handler = { req in
            let body = #"{"handoff_path":"/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF","expires_at":1790000000}"#
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(body.utf8))
        }
        do {
            _ = try await OpenKitchenOSWebIntent(destination: .recipe(name: "Beans")).open(client: .mock(), opener: WebBrowserOpener { _ in false })
            XCTFail("Browser refusal must not claim opened")
        } catch {
            XCTAssertEqual(error as? BrowserOpenError, .declined)
        }
    }
    func testCancellationAfterMintNeverDispatchesBrowser() async {
        let task = Task { @MainActor in
            do {
                _ = try await OpenKitchenOSWebIntent(destination: .recipe(name: "Beans")).open(
                    baseURL: URL(string: "https://kitchen.example")!,
                    mint: { _ in
                        withUnsafeCurrentTask { $0?.cancel() }
                        return BrowserHandoffResponse(
                            handoffPath: "/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF",
                            expiresAt: 1790000000)
                    },
                    opener: WebBrowserOpener { _ in XCTFail("Cancellation after mint must prevent browser dispatch"); return true })
                XCTFail("Cancelled continuation should throw")
            } catch { XCTAssertTrue(error is CancellationError) }
        }
        await task.value
    }
    func testCancelledBrowserContinuationDoesNotMintOrDispatch() async {
        let task = Task { @MainActor in
            withUnsafeCurrentTask { $0?.cancel() }
            do {
                _ = try await OpenKitchenOSWebIntent(destination: .recipe(name: "Beans")).open(
                    baseURL: URL(string: "https://kitchen.example")!,
                    mint: { _ in
                        XCTFail("Cancelled continuation must not mint")
                        return BrowserHandoffResponse(
                            handoffPath: "/browser/open#code=abcdefghijklmnopqrstuvwxyz0123456789_ABCDEF",
                            expiresAt: 1790000000)
                    },
                    opener: WebBrowserOpener { _ in XCTFail("Cancelled continuation must not dispatch"); return true })
                XCTFail("Cancelled continuation should throw")
            } catch { XCTAssertTrue(error is CancellationError) }
        }
        await task.value
    }
    func testIntentRejectsMixedFieldsBeforeHandoff() async {
        let intent = OpenKitchenOSWebIntent(destination: .recipe(name: "Beans"))
        intent.date = "2026-10-16"
        do {
            _ = try await intent.open(client: .mock(), opener: WebBrowserOpener { _ in XCTFail("Invalid intent must not open"); return true })
            XCTFail("Mixed fields must be invalid")
        } catch { }
    }
}
