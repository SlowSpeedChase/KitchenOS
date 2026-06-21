import Foundation
import Security

public protocol CredentialStore: AnyObject {
    func token() -> String?
    func setToken(_ token: String?)
}

public final class InMemoryCredentialStore: CredentialStore {
    private var value: String?
    public init(_ initial: String? = nil) { self.value = initial }
    public func token() -> String? { value }
    public func setToken(_ token: String?) { value = token }
}

public final class KeychainCredentialStore: CredentialStore {
    private let account = "kitchenos.api.token"
    private let service = "com.kitchenos.siri"
    public init() {}

    public func token() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let str = String(data: data, encoding: .utf8) else { return nil }
        return str
    }

    public func setToken(_ token: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        guard let token, let data = token.data(using: .utf8) else { return }
        var add = base
        add[kSecValueData as String] = data
        SecItemAdd(add as CFDictionary, nil)
    }
}
