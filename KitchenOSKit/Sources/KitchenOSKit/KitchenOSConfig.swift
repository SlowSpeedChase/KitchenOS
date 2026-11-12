import Foundation

public struct KitchenOSConfig {
    public var baseURL: URL
    public var credentials: CredentialStore

    public init(baseURL: URL, credentials: CredentialStore) {
        self.baseURL = baseURL
        self.credentials = credentials
    }

    /// Default base URL when none is stored. iOS talks to the Mac mini over
    /// the shared HTTPS gateway; macOS uses localhost.
    public static var defaultBaseURLString: String {
        #if os(iOS)
        "https://chases-mac-mini.taila69703.ts.net"
        #else
        "http://localhost:5001"
        #endif
    }

    /// Resolve from UserDefaults (base URL) + Keychain (token).
    /// IMPORTANT: @AppStorage does not persist its UI default, so a fresh install
    /// has no stored value — fall back to the platform default, never localhost on iOS.
    public static func resolved(defaults: UserDefaults = .standard,
                                credentials: CredentialStore = KeychainCredentialStore()) -> KitchenOSConfig {
        let raw = migrateLegacyDefault(defaults: defaults) ?? defaultBaseURLString
        let url = URL(string: raw) ?? URL(string: defaultBaseURLString)!
        return KitchenOSConfig(baseURL: url, credentials: credentials)
    }

    /// Upgrade only defaults previously shipped by the iOS app. Custom endpoints
    /// (including near matches) remain the user's choice; Keychain is untouched.
    private static func migrateLegacyDefault(defaults: UserDefaults) -> String? {
        guard let stored = defaults.string(forKey: "kitchenos.baseURL") else { return nil }
        let legacyDefaults = [
            "http://100.111.6.10:5001",
            "http://chases-mac-mini.taila69703.ts.net:5001",
            "http://Chases-Mac-mini.local:5001",
        ]
        guard legacyDefaults.contains(stored) else { return stored }
        let canonical = "https://chases-mac-mini.taila69703.ts.net"
        defaults.set(canonical, forKey: "kitchenos.baseURL")
        return canonical
    }
}
