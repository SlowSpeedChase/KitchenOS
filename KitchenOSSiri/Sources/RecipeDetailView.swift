import SwiftUI
import KitchenOSKit

struct RecipeDetailView: View {
    let name: String
    @AppStorage("kitchenos.obsidianVault") private var vault = "KitchenOS"
    @State private var detail: RecipeDetail?
    @State private var summary = ""
    @State private var status = ""
    @Environment(\.dismiss) private var dismiss

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        NavigationStack {
            List {
                Section { Text(name).font(.headline) }

                if let d = detail {
                    Section("Nutrition (per serving)") {
                        if d.nutritionCalories == nil && d.nutritionProtein == nil {
                            Text("No nutrition data yet.").foregroundStyle(.secondary)
                        } else {
                            if let c = d.nutritionCalories { Text("\(Int(c)) cal") }
                            if let p = d.nutritionProtein { Text("\(Int(p)) g protein") }
                            if let cb = d.nutritionCarbs { Text("\(Int(cb)) g carbs") }
                            if let f = d.nutritionFat { Text("\(Int(f)) g fat") }
                        }
                    }
                }

                if RecipeAI.isReady {
                    Section("Summary") {
                        if summary.isEmpty {
                            Button("Summarize on device") { summarize() }
                        } else {
                            Text(summary).italic()
                        }
                    }
                }

                if let url = RecipeLink.obsidianURL(recipe: name, vault: vault) {
                    Section { Link("Open in Obsidian", destination: url) }
                }

                if !status.isEmpty {
                    Text(status).font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Recipe")
            .toolbar { Button("Done") { dismiss() } }
            .task { await load() }
        }
    }

    private func load() async {
        do { detail = try await client.recipeDetail(name: name) }
        catch { status = "Couldn't load recipe details." }
    }

    private func summarize() {
        Task {
            guard let d = detail else { return }
            do { summary = try await RecipeAI.summarize(d) }
            catch { summary = "Couldn't summarize." }
        }
    }
}
