import SwiftUI
import KitchenOSKit

/// Pantry view of current stock (derived from inventory, summed across locations).
/// Read-only — edits happen on the Inventory screen.
struct PantryView: View {
    @State private var items: [PantryItem] = []
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        List {
            if items.isEmpty, !isLoading {
                Text(status.isEmpty ? "Pantry is empty." : status).foregroundStyle(.secondary)
            }
            ForEach(items.sorted { $0.item < $1.item }, id: \.item) { p in
                HStack {
                    Text(p.item)
                    Spacer()
                    Text([p.amount, p.unit].compactMap { $0 }.joined(separator: " "))
                        .foregroundStyle(.secondary).monospacedDigit()
                }
            }
        }
        .navigationTitle("Pantry")
        .overlay { if isLoading { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { items = try await client.pantry() }
        catch { status = "Error: \(error)" }
    }
}
