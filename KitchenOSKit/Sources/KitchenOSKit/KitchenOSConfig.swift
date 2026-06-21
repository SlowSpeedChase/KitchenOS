import Foundation

public struct KitchenOSConfig {
    public var baseURL: URL
    public var credentials: CredentialStore

    public init(baseURL: URL, credentials: CredentialStore) {
        self.baseURL = baseURL
        self.credentials = credentials
    }

    /// Resolve from UserDefaults (base URL) + Keychain (token). Falls back to localhost.
    public static func resolved(defaults: UserDefaults = .standard,
                                credentials: CredentialStore = KeychainCredentialStore()) -> KitchenOSConfig {
        let raw = defaults.string(forKey: "kitchenos.baseURL") ?? "http://localhost:5001"
        let url = URL(string: raw) ?? URL(string: "http://localhost:5001")!
        return KitchenOSConfig(baseURL: url, credentials: credentials)
    }
}
