import SwiftUI
import KitchenOSKit

struct SmartSearchView: View {
    @State private var queryText = ""
    @State private var results: [RecipeSummary] = []
    @State private var status = ""
    @State private var summaries: [String: String] = [:]   // recipe name -> on-device gist
    @State private var isSearching = false
    @AppStorage("kitchenos.obsidianVault") private var obsidianVault = "KitchenOS"

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        NavigationStack {
            List {
                if case let .unavailable(reason) = RecipeAI.availability {
                    Section {
                        Label(reason, systemImage: "exclamationmark.triangle")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                Section {
                    TextField("e.g. something with eggplant", text: $queryText)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .onSubmit(runSearch)
                    Button(isSearching ? "Searching…" : "Search", action: runSearch)
                        .disabled(isSearching || queryText.isEmpty)
                    if !status.isEmpty {
                        Text(status).font(.caption).foregroundStyle(.secondary)
                    }
                }

                if !results.isEmpty {
                    Section("Results") {
                        ForEach(results, id: \.name) { r in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(r.name)
                                if !subtitle(r).isEmpty {
                                    Text(subtitle(r)).font(.caption).foregroundStyle(.secondary)
                                }
                                if let gist = summaries[r.name] {
                                    Text(gist).font(.caption).italic()
                                } else if RecipeAI.isReady {
                                    Button("Summarize") { summarize(r) }.font(.caption)
                                }
                                if let url = RecipeLink.obsidianURL(recipe: r.name, vault: obsidianVault) {
                                    Link("Open in Obsidian", destination: url).font(.caption)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Smart Search")
        }
    }

    private func subtitle(_ r: RecipeSummary) -> String {
        [r.cuisine, r.protein].compactMap { $0 }.joined(separator: " · ")
    }

    private func runSearch() {
        isSearching = true; status = "Searching…"; summaries = [:]
        Task {
            do {
                let found: [RecipeSummary]
                if RecipeAI.isReady {
                    let q = try await RecipeAI.parseQuery(queryText)
                    found = try await client.recipes(matching: q)
                } else {
                    found = try await client.findRecipes(ingredient: queryText)
                }
                results = found
                status = found.isEmpty ? "No matches." : "\(found.count) result(s)."
            } catch {
                results = []
                status = "Error: \(error)"
            }
            isSearching = false
        }
    }

    private func summarize(_ r: RecipeSummary) {
        Task {
            do {
                let detail = try await client.recipeDetail(name: r.name)
                summaries[r.name] = try await RecipeAI.summarize(detail)
            } catch {
                summaries[r.name] = "Couldn't summarize."
            }
        }
    }
}
