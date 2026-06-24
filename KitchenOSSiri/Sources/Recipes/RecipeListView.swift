import SwiftUI
import KitchenOSKit

/// Browse the full recipe library with text search + cuisine/protein filters.
struct RecipeListView: View {
    @State private var all: [RecipeSummary] = []
    @State private var searchText = ""
    @State private var cuisineFilter: String?
    @State private var proteinFilter: String?
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    private var cuisines: [String] {
        Set(all.compactMap { $0.cuisine }).sorted()
    }
    private var proteins: [String] {
        Set(all.compactMap { $0.protein }).sorted()
    }

    private var filtered: [RecipeSummary] {
        all.filter { r in
            (cuisineFilter == nil || r.cuisine == cuisineFilter) &&
            (proteinFilter == nil || r.protein == proteinFilter) &&
            (searchText.isEmpty || r.name.localizedCaseInsensitiveContains(searchText))
        }
    }

    var body: some View {
        List {
            if !cuisines.isEmpty || !proteins.isEmpty {
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            FilterMenu(title: "Cuisine", options: cuisines, selection: $cuisineFilter)
                            FilterMenu(title: "Protein", options: proteins, selection: $proteinFilter)
                        }
                    }
                }
            }

            Section(filtered.isEmpty ? status : "\(filtered.count) recipes") {
                ForEach(filtered, id: \.name) { r in
                    NavigationLink(value: r.name) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.name)
                            let sub = [r.cuisine, r.protein].compactMap { $0 }.joined(separator: " · ")
                            if !sub.isEmpty {
                                Text(sub).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("Recipes")
        .navigationDestination(for: String.self) { name in
            RecipeDetailView(name: name)
        }
        .searchable(text: $searchText, prompt: "Search recipes")
        .overlay { if isLoading { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            all = try await client.allRecipes()
            status = all.isEmpty ? "No recipes." : ""
        } catch {
            status = "Error: \(error)"
        }
    }
}

private struct FilterMenu: View {
    let title: String
    let options: [String]
    @Binding var selection: String?

    var body: some View {
        Menu {
            Button("All \(title)") { selection = nil }
            Divider()
            ForEach(options, id: \.self) { opt in
                Button {
                    selection = (selection == opt) ? nil : opt
                } label: {
                    if selection == opt { Label(opt, systemImage: "checkmark") } else { Text(opt) }
                }
            }
        } label: {
            Label(selection ?? title, systemImage: "line.3.horizontal.decrease.circle")
                .font(.caption)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
    }
}
