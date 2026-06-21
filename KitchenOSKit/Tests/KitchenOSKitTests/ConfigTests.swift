import XCTest
@testable import KitchenOSKit

final class ConfigTests: XCTestCase {
    func testInMemoryCredentialStoreRoundTrips() {
        let store = InMemoryCredentialStore()
        XCTAssertNil(store.token())
        store.setToken("secret")
        XCTAssertEqual(store.token(), "secret")
        store.setToken(nil)
        XCTAssertNil(store.token())
    }

    func testConfigHoldsBaseURL() {
        let store = InMemoryCredentialStore()
        let cfg = KitchenOSConfig(baseURL: URL(string: "http://localhost:5001")!, credentials: store)
        XCTAssertEqual(cfg.baseURL.absoluteString, "http://localhost:5001")
    }
}
