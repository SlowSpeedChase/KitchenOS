import SwiftUI
import KitchenOSKit

/// Modal recipe picker. Calls `onPick(name)` with the chosen recipe, or
/// `onPick(nil)` if the user cancels.
struct RecipePickerSheet: View {
    let onPick: (String?) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var all: [RecipeSummary] = []
    @State private var searchText = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    private var filtered: [RecipeSummary] {
        searchText.isEmpty ? all
            : all.filter { $0.name.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        NavigationStack {
            List(filtered, id: \.name) { r in
                Button {
                    onPick(r.name); dismiss()
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.name).foregroundStyle(.primary)
                        let sub = [r.cuisine, r.protein].compactMap { $0 }.joined(separator: " · ")
                        if !sub.isEmpty {
                            Text(sub).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Pick a Recipe")
            .searchable(text: $searchText, prompt: "Search recipes")
            .overlay { if isLoading { ProgressView() } }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { onPick(nil); dismiss() }
                }
            }
            .task { await load() }
        }
        .frame(minWidth: 360, minHeight: 420)
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        all = (try? await client.allRecipes()) ?? []
    }
}
