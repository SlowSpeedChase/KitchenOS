import SwiftUI
import ServiceManagement

struct ContentView: View {
    @StateObject private var manager = ExtractionManager()
    @State private var urlInput: String = ""
    @AppStorage("launchAtLogin") private var launchAtLogin = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // URL Input
            HStack {
                TextField("YouTube URL", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        extract()
                    }
                    .disabled(manager.isExtracting)
            }

            // Extract Button
            Button(action: extract) {
                HStack {
                    if manager.isExtracting {
                        ProgressView()
                            .controlSize(.small)
                            .padding(.trailing, 4)
                    }
                    Text(manager.isExtracting ? "Extracting..." : "Extract Recipe")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(manager.isExtracting || urlInput.isEmpty)

            Divider()

            // Status
            HStack {
                Text("Status:")
                    .foregroundColor(.secondary)
                Text(manager.status)
                    .foregroundColor(manager.statusIsError ? .red : .primary)
                    .lineLimit(1)
            }
            .font(.caption)

            // History
            if !manager.history.isEmpty {
                Divider()

                Text("Recent:")
                    .font(.caption)
                    .foregroundColor(.secondary)

                ForEach(manager.history) { item in
                    Button(action: { item.openInObsidian() }) {
                        HStack {
                            Image(systemName: "doc.text")
                                .foregroundColor(.secondary)
                            Text(item.recipeName)
                                .lineLimit(1)
                            Spacer()
                            Text(item.timeAgo)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }

            Divider()

            // Settings
            HStack {
                Toggle("Launch at Login", isOn: $launchAtLogin)
                    .toggleStyle(.checkbox)
                    .font(.caption)
                    .onChange(of: launchAtLogin) { _, newValue in
                        updateLaunchAtLogin(enabled: newValue)
                    }

                Spacer()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
                .buttonStyle(.plain)
                .font(.caption)
                .foregroundColor(.secondary)
            }
        }
        .padding()
        .frame(width: 300)
    }

    private func extract() {
        guard !urlInput.isEmpty else { return }
        let url = urlInput
        urlInput = ""
        manager.extract(url: url)
    }

    private func updateLaunchAtLogin(enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            print("Failed to update launch at login: \(error)")
        }
    }
}

#Preview {
    ContentView()
}
