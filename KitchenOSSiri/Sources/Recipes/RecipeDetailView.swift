import SwiftUI
import KitchenOSKit

/// Full recipe: metadata, nutrition, ingredients, instructions, tips,
/// plus an on-device AI summary when Apple Intelligence is available.
struct RecipeDetailView: View {
    let recipeName: String

    @State private var detail: RecipeDetail?
    @State private var summary: String?
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }

    var body: some View {
        Group {
            if let d = detail {
                List {
                    metaSection(d)
                    if let s = summary {
                        Section("Summary") { Text(s).italic() }
                    } else if RecipeAI.isReady {
                        Section { Button("Summarize with AI") { summarize(d) } }
                    }
                    nutritionSection(d)
                    ingredientsSection(d)
                    instructionsSection(d)
                    tipsSection(d)
                }
            } else if isLoading {
                ProgressView()
            } else {
                ContentUnavailableView(status.isEmpty ? recipeName : status,
                                       systemImage: "book.closed")
            }
        }
        .navigationTitle(detail?.title ?? recipeName)
        .task { await load() }
    }

    @ViewBuilder
    private func metaSection(_ d: RecipeDetail) -> some View {
        let chips = [d.cuisine, d.protein, d.dishType, d.difficulty].compactMap { $0 }
        if !chips.isEmpty || d.totalTime != nil || d.servings != nil || d.description?.isEmpty == false {
            Section {
                if let desc = d.description, !desc.isEmpty {
                    Text(desc)
                }
                if !chips.isEmpty {
                    Text(chips.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                }
                let facts = [
                    d.servings.map { "\($0) servings" },
                    d.totalTime.map { "Total \($0)" },
                    d.prepTime.map { "Prep \($0)" },
                    d.cookTime.map { "Cook \($0)" },
                ].compactMap { $0 }
                if !facts.isEmpty {
                    Text(facts.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                }
                if d.needsReview == true {
                    Label("Needs review", systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
        }
    }

    @ViewBuilder
    private func nutritionSection(_ d: RecipeDetail) -> some View {
        let parts = [
            d.nutritionCalories.map { "\(Int($0)) cal" },
            d.nutritionProtein.map { "\(Int($0))g protein" },
            d.nutritionCarbs.map { "\(Int($0))g carbs" },
            d.nutritionFat.map { "\(Int($0))g fat" },
        ].compactMap { $0 }
        if !parts.isEmpty {
            Section("Nutrition (per serving)") {
                Text(parts.joined(separator: " · ")).font(.callout)
            }
        }
    }

    @ViewBuilder
    private func ingredientsSection(_ d: RecipeDetail) -> some View {
        if let ings = d.ingredients, !ings.isEmpty {
            Section("Ingredients") {
                ForEach(Array(ings.enumerated()), id: \.offset) { _, ing in
                    let qty = [ing.amount, ing.unit].compactMap { $0 }.joined(separator: " ")
                    HStack(alignment: .firstTextBaseline) {
                        if !qty.isEmpty {
                            Text(qty).foregroundStyle(.secondary).frame(width: 90, alignment: .leading)
                        }
                        Text(ing.item)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func instructionsSection(_ d: RecipeDetail) -> some View {
        if let steps = d.instructions, !steps.isEmpty {
            Section("Instructions") {
                ForEach(steps, id: \.step) { s in
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(s.step).").bold().foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.text)
                            if let t = s.time { Text(t).font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func tipsSection(_ d: RecipeDetail) -> some View {
        if let tips = d.videoTips, !tips.isEmpty {
            Section("Tips") {
                ForEach(Array(tips.enumerated()), id: \.offset) { _, tip in
                    Label(tip, systemImage: "lightbulb")
                }
            }
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            detail = try await client.recipeDetail(name: recipeName)
        } catch {
            status = "Error: \(error)"
        }
    }

    private func summarize(_ d: RecipeDetail) {
        Task {
            do { summary = try await RecipeAI.summarize(d) }
            catch { summary = "Couldn't summarize." }
        }
    }
}
