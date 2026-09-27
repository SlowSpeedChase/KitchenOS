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
    func testPlatformDefault() {
        #if os(iOS)
        XCTAssertEqual(KitchenOSConfig.defaultBaseURLString, "https://chases-mac-mini.taila69703.ts.net")
        #else
        XCTAssertEqual(KitchenOSConfig.defaultBaseURLString, "http://localhost:5001")
        #endif
    }

    func testFreshConfigurationUsesPlatformDefault() {
        let suite = UUID().uuidString
        let defaults = RecordingDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let config = KitchenOSConfig.resolved(defaults: defaults, credentials: InMemoryCredentialStore())
        XCTAssertEqual(config.baseURL.absoluteString, KitchenOSConfig.defaultBaseURLString)
        XCTAssertEqual(defaults.writes, 0)
    }

    func testExactLegacyDefaultsMigrateAndPersistOnce() {
        for old in ["http://100.111.6.10:5001", "http://chases-mac-mini.taila69703.ts.net:5001", "http://Chases-Mac-mini.local:5001"] {
            let suite = UUID().uuidString
            let defaults = RecordingDefaults(suiteName: suite)!
            defer { defaults.removePersistentDomain(forName: suite) }
            defaults.set(old, forKey: "kitchenos.baseURL")
            defaults.writes = 0
            let credentials = InMemoryCredentialStore()
            credentials.setToken("keep-token")
            let config = KitchenOSConfig.resolved(defaults: defaults, credentials: credentials)
            XCTAssertEqual(config.baseURL.absoluteString, "https://chases-mac-mini.taila69703.ts.net")
            XCTAssertEqual(defaults.string(forKey: "kitchenos.baseURL"), config.baseURL.absoluteString)
            XCTAssertEqual(config.credentials.token(), "keep-token")
            _ = KitchenOSConfig.resolved(defaults: defaults, credentials: credentials)
            XCTAssertEqual(defaults.writes, 1)
        }
    }

    func testCustomEndpointsArePreserved() {
        for custom in ["https://custom.example:8443/api", "http://100.111.6.10:5001/", "http://localhost:5001", "http://user:pass@custom.example:5001"] {
            let suite = UUID().uuidString
            let defaults = RecordingDefaults(suiteName: suite)!
            defer { defaults.removePersistentDomain(forName: suite) }
            defaults.set(custom, forKey: "kitchenos.baseURL")
            defaults.writes = 0
            let config = KitchenOSConfig.resolved(defaults: defaults, credentials: InMemoryCredentialStore())
            XCTAssertEqual(config.baseURL.absoluteString, custom)
            XCTAssertEqual(defaults.writes, 0)
        }
    }
}

private final class RecordingDefaults: UserDefaults {
    var writes = 0
    override func set(_ value: Any?, forKey defaultName: String) {
        writes += 1
        super.set(value, forKey: defaultName)
    }
}
