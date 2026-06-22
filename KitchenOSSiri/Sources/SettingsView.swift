import SwiftUI
import KitchenOSKit

struct SettingsView: View {
    @AppStorage("kitchenos.baseURL") private var baseURL = KitchenOSConfig.defaultBaseURLString
    @State private var token = ""
    @State private var savedNote = ""
    @State private var testResult = ""
    private let creds = KeychainCredentialStore()

    var body: some View {
        Form {
            Section("Connection") {
                TextField("Base URL", text: $baseURL)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                SecureField("API token (optional)", text: $token)
                Button("Save token") {
                    creds.setToken(token.isEmpty ? nil : token)
                    savedNote = token.isEmpty ? "Token cleared." : "Token saved to Keychain."
                }
                if !savedNote.isEmpty {
                    Text(savedNote).font(.caption).foregroundStyle(.secondary)
                }
            }

            Section("Diagnostics") {
                Text("Resolved URL: \(KitchenOSConfig.resolved().baseURL.absoluteString)")
                    .font(.caption).foregroundStyle(.secondary)
                Button("Test connection") { runTest() }
                if !testResult.isEmpty {
                    Text(testResult).font(.caption)
                }
            }

            Section {
                Text("Mac uses localhost; iPad uses the Mac mini over Tailscale. The token is only required for remote (non-localhost) calls.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(minWidth: 360, minHeight: 300)
        .onAppear { token = creds.token() ?? "" }
    }

    private func runTest() {
        testResult = "Testing…"
        Task {
            let client = KitchenOSClient(config: .resolved())
            do {
                let url = try await client.health()
                testResult = "✅ Reached \(url)"
            } catch KitchenOSError.unreachable {
                testResult = "❌ Unreachable: \(KitchenOSConfig.resolved().baseURL.absoluteString)"
            } catch let KitchenOSError.http(code) {
                testResult = "❌ HTTP \(code) from \(KitchenOSConfig.resolved().baseURL.absoluteString)"
            } catch {
                testResult = "❌ \(error)"
            }
        }
    }
}

#Preview {
    SettingsView()
}
