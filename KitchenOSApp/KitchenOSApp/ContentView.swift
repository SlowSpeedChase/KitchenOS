import SwiftUI
import ServiceManagement
import UserNotifications

struct ContentView: View {
    @StateObject private var manager = ExtractionManager()
    @State private var urlInput = ""
    @AppStorage("launchAtLogin") private var launchAtLogin = true

    var body: some View {
        VStack(spacing: 12) {
            // URL Input
            HStack {
                TextField("YouTube URL", text: $urlInput)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(extract)
            }

            // Extract Button
            Button(action: extract) {
                HStack {
                    if case .extracting = manager.status {
                        ProgressView()
                            .scaleEffect(0.7)
                            .frame(width: 16, height: 16)
                    }
                    Text("Extract Recipe")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isExtracting)

            Divider()

            // Status
            HStack {
                Text("Status:")
                    .foregroundColor(.secondary)
                Spacer()
                statusText
            }
            .font(.caption)

            // History
            if !manager.history.isEmpty {
                Divider()

                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent:")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    ForEach(manager.history) { item in
                        Button(action: { manager.openInObsidian(item: item) }) {
                            HStack {
                                Text(item.recipeName)
                                    .lineLimit(1)
                                Spacer()
                                Text(item.timeAgo)
                                    .foregroundColor(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                        .font(.caption)
                    }
                }
            }

            Divider()

            // Settings
            Toggle("Launch at Login", isOn: $launchAtLogin)
                .font(.caption)
                .onChange(of: launchAtLogin) { newValue in
                    updateLoginItem(enabled: newValue)
                }
        }
        .padding()
        .frame(width: 280)
        .onAppear {
            requestNotificationPermission()
        }
    }

    private var isExtracting: Bool {
        if case .extracting = manager.status { return true }
        return false
    }

    @ViewBuilder
    private var statusText: some View {
        switch manager.status {
        case .idle:
            Text("Ready")
                .foregroundColor(.secondary)
        case .extracting:
            Text("Extracting...")
                .foregroundColor(.orange)
        case .success(let name):
            Text("Saved: \(name)")
                .foregroundColor(.green)
                .lineLimit(1)
        case .error(let message):
            Text(message)
                .foregroundColor(.red)
                .lineLimit(1)
                .onTapGesture {
                    manager.resetError()
                }
        }
    }

    private func extract() {
        manager.extract(url: urlInput)
        urlInput = ""
    }

    private func updateLoginItem(enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            print("Failed to update login item: \(error)")
        }
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }
}
