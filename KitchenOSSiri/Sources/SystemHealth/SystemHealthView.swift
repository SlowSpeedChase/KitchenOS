import SwiftUI
import KitchenOSKit

/// At-a-glance system health: Ollama, vault, recent recipes, batch run logs.
struct SystemHealthView: View {
    @State private var health: SystemHealth?
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        List {
            if let h = health {
                if let ollama = h.ollama {
                    Section("Ollama") {
                        Label(ollama.alive ? "Running" : "Down",
                              systemImage: ollama.alive ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundStyle(ollama.alive ? .green : .red)
                        if let models = ollama.models, !models.isEmpty {
                            Text(models.joined(separator: ", "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let err = ollama.error { Text(err).font(.caption).foregroundStyle(.red) }
                    }
                }
                if let vault = h.vault {
                    Section("Vault") {
                        Label(vault.writable ? "Writable" : (vault.exists ? "Read-only" : "Missing"),
                              systemImage: vault.writable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(vault.writable ? .green : .orange)
                        if let p = vault.path {
                            Text(p).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }
                if let recipes = h.recentRecipes, !recipes.isEmpty {
                    Section("Recent recipes") {
                        ForEach(recipes, id: \.name) { r in
                            HStack {
                                Text(r.name).lineLimit(1)
                                Spacer()
                                if let m = r.modifiedISO {
                                    Text(m.prefix(16).replacingOccurrences(of: "T", with: " "))
                                        .font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                if let logs = h.runLogs, !logs.isEmpty {
                    Section("Batch runs") {
                        ForEach(Array(logs.enumerated()), id: \.offset) { _, log in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(log.timestamp?.replacingOccurrences(of: "T", with: " ") ?? "—")
                                    .font(.caption)
                                Text("\(log.succeeded ?? 0) ok · \(log.failed ?? 0) failed · \(log.invalid ?? 0) invalid · \(log.total ?? 0) total")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            } else if !isLoading {
                Text(status.isEmpty ? "No data." : status).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("System Health")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItem { Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") } }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { health = try await client.systemHealth() }
        catch { status = "Error: \(error)" }
    }
}
