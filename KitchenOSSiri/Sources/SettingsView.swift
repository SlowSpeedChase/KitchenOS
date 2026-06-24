import SwiftUI
import KitchenOSKit

struct SettingsView: View {
    @AppStorage("kitchenos.baseURL") private var baseURL = KitchenOSConfig.defaultBaseURLString
    @AppStorage("kitchenos.obsidianVault") private var obsidianVault = "KitchenOS"
    @State private var token = ""
    @State private var savedNote = ""
    @State private var testResult = ""
    @State private var indexNote = ""
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

            Section("Obsidian") {
                TextField("Vault name", text: $obsidianVault)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Text("Used for \"Open in Obsidian\" links. Must match your vault's name on this device.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("Spotlight / Siri search") {
                Button("Reindex recipes") { reindex() }
                if !indexNote.isEmpty {
                    Text(indexNote).font(.caption).foregroundStyle(.secondary)
                }
                Text("Indexes your recipes so Siri and Spotlight can find them by meaning. Runs automatically on launch.")
                    .font(.caption).foregroundStyle(.secondary)
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
            // Raw probe so we surface the true NSError instead of a generic "unreachable".
            let url = KitchenOSConfig.resolved().baseURL.appendingPathComponent("/health")
            do {
                let (_, resp) = try await URLSession.shared.data(from: url)
                let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
                testResult = "✅ Reached \(url.absoluteString) (HTTP \(code))"
            } catch {
                let ns = error as NSError
                testResult = "❌ \(url.absoluteString)\n\(ns.domain) \(ns.code): \(ns.localizedDescription)"
            }
        }
    }

    private func reindex() {
        indexNote = "Indexing…"
        Task {
            do {
                let count = try await RecipeIndexer.reindexAll()
                indexNote = "Indexed \(count) recipes."
            } catch {
                indexNote = "Couldn't index: \(error.localizedDescription)"
            }
        }
    }
}

#Preview {
    SettingsView()
}
