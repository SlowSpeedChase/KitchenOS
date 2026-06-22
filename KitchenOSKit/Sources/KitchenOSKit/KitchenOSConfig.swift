import Foundation

public struct KitchenOSConfig {
    public var baseURL: URL
    public var credentials: CredentialStore

    public init(baseURL: URL, credentials: CredentialStore) {
        self.baseURL = baseURL
        self.credentials = credentials
    }

    /// Default base URL when none is stored. iOS talks to the Mac mini over
    /// Tailscale (IP avoids any MagicDNS dependency); macOS uses localhost.
    public static var defaultBaseURLString: String {
        #if os(iOS)
        "http://100.111.6.10:5001"
        #else
        "http://localhost:5001"
        #endif
    }

    /// Resolve from UserDefaults (base URL) + Keychain (token).
    /// IMPORTANT: @AppStorage does not persist its UI default, so a fresh install
    /// has no stored value — fall back to the platform default, never localhost on iOS.
    public static func resolved(defaults: UserDefaults = .standard,
                                credentials: CredentialStore = KeychainCredentialStore()) -> KitchenOSConfig {
        let raw = defaults.string(forKey: "kitchenos.baseURL") ?? defaultBaseURLString
        let url = URL(string: raw) ?? URL(string: defaultBaseURLString)!
        return KitchenOSConfig(baseURL: url, credentials: credentials)
    }
}
