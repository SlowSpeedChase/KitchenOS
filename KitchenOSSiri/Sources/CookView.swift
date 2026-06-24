import SwiftUI
import KitchenOSKit

struct CookView: View {
    @State private var input = ""
    @State private var matches: [Suggestion] = []
    @State private var status = ""
    @State private var isWorking = false
    @State private var openRecipe: RecipeRef?

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        NavigationStack {
            List {
                Section("Ingredients you have") {
                    TextField("e.g. chicken, rice, broccoli", text: $input)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .onSubmit { cook(useInventory: false) }
                    Button("Find recipes") { cook(useInventory: false) }
                        .disabled(isWorking || input.isEmpty)
                    Button("Use my kitchen inventory") { cook(useInventory: true) }
                        .disabled(isWorking)
                    if !status.isEmpty {
                        Text(status).font(.caption).foregroundStyle(.secondary)
                    }
                }

                if !matches.isEmpty {
                    Section("Best matches (most ingredients in common)") {
                        ForEach(matches, id: \.name) { m in
                            Button { openRecipe = RecipeRef(id: m.name) } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(m.name)
                                    if let shared = m.sharedIngredients, !shared.isEmpty {
                                        Text("uses: \(shared.joined(separator: ", "))")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Cook")
            .sheet(item: $openRecipe) { ref in RecipeDetailView(name: ref.id) }
        }
    }

    private func cook(useInventory: Bool) {
        isWorking = true
        status = "Finding recipes…"
        matches = []
        Task {
            do {
                let ingredients: [String]
                if useInventory {
                    ingredients = try await client.inventoryItems()
                    if ingredients.isEmpty {
                        status = "Your inventory is empty or not documented yet."
                        isWorking = false
                        return
                    }
                } else {
                    ingredients = input
                        .split(separator: ",")
                        .map { $0.trimmingCharacters(in: .whitespaces) }
                        .filter { !$0.isEmpty }
                    if ingredients.isEmpty {
                        status = "Enter some ingredients, separated by commas."
                        isWorking = false
                        return
                    }
                }
                let result = try await client.recipesByIngredients(ingredients)
                matches = result
                status = result.isEmpty ? "No recipes share those ingredients." : "\(result.count) matches."
            } catch {
                status = "Error: \(error.localizedDescription)"
            }
            isWorking = false
        }
    }
}
