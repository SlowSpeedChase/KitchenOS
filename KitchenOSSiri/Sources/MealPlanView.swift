import SwiftUI
import KitchenOSKit

struct MealPlanView: View {
    @AppStorage("kitchenos.obsidianVault") private var vault = "KitchenOS"
    @State private var plan: MealPlan?
    @State private var status = "Loading…"
    @State private var openRecipe: RecipeRef?

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var week: String { WeekDate.currentWeekID() }

    var body: some View {
        NavigationStack {
            List {
                if let plan {
                    ForEach(plan.days, id: \.day) { day in
                        Section(day.day) {
                            mealRow("Breakfast", day.breakfast)
                            mealRow("Lunch", day.lunch)
                            mealRow("Snack", day.snack)
                            mealRow("Dinner", day.dinner)
                        }
                    }
                } else {
                    Text(status).foregroundStyle(.secondary)
                }

                if let url = RecipeLink.mealPlanURL(week: week, vault: vault) {
                    Section { Link("Open plan in Obsidian", destination: url) }
                }
            }
            .navigationTitle("Plan · \(week)")
            .toolbar { Button("Refresh") { Task { await load() } } }
            .task { await load() }
            .sheet(item: $openRecipe) { ref in RecipeDetailView(name: ref.id) }
        }
    }

    @ViewBuilder
    private func mealRow(_ label: String, _ slot: MealSlotValue?) -> some View {
        if let slot {
            Button { openRecipe = RecipeRef(id: slot.name) } label: {
                HStack {
                    Text(label).foregroundStyle(.secondary)
                    Spacer()
                    Text(slot.name)
                }
            }
        } else {
            HStack {
                Text(label).foregroundStyle(.secondary)
                Spacer()
                Text("—").foregroundStyle(.secondary)
            }
        }
    }

    private func load() async {
        do {
            plan = try await client.mealPlan(week: week)
            status = ""
        } catch {
            status = "Couldn't load the plan."
        }
    }
}

struct RecipeRef: Identifiable { let id: String }
