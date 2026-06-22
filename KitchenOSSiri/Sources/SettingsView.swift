import SwiftUI
import KitchenOSKit

struct SettingsView: View {
    @AppStorage("kitchenos.baseURL") private var baseURL = KitchenOSConfig.defaultBaseURLString
    @State private var token = ""
    @State private var savedNote = ""
    private let creds = KeychainCredentialStore()

    var body: some View {
        Form {
            Section("Connection") {
                TextField("Base URL", text: $baseURL)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                SecureField("API token (optional)", text: $token)
                Button("Save token") {
                    creds.setToken(token.isEmpty ? nil : token)
                    savedNote = token.isEmpty ? "Token cleared." : "Token saved to Keychain."
                }
                if !savedNote.isEmpty {
                    Text(savedNote).font(.caption).foregroundStyle(.secondary)
                }
            }
            Section {
                Text("Mac uses localhost; iPad uses the Tailscale host. The token is only required for remote (non-localhost) calls.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(minWidth: 360, minHeight: 220)
        .onAppear { token = creds.token() ?? "" }
    }
}

#Preview {
    SettingsView()
}
