import SwiftUI
import KitchenOSKit

/// Drag-and-drop weekly planner: drag a recipe from the palette onto a day/slot.
/// Native replacement for the web `meal_planner.html` board.
struct PlannerBoardView: View {
    @State private var weekAnchor = Date()
    @State private var plan: MealPlan?
    @State private var recipes: [RecipeSummary] = []
    @State private var paletteSearch = ""
    @State private var status = ""
    @State private var isLoading = false

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }

    private var palette: [RecipeSummary] {
        paletteSearch.isEmpty ? recipes
            : recipes.filter { $0.name.localizedCaseInsensitiveContains(paletteSearch) }
    }

    var body: some View {
        HStack(spacing: 0) {
            paletteColumn
                .frame(width: 220)
            Divider()
            boardColumn
        }
        .navigationTitle("Planner Board")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItemGroup {
                Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }
                Text(weekID).font(.callout.monospaced())
                Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }
            }
        }
        .task(id: weekID) { await load() }
        .task { await loadRecipes() }
    }

    private var paletteColumn: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("Search recipes", text: $paletteSearch)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal, 8).padding(.top, 8)
            List(palette, id: \.name) { r in
                Text(r.name)
                    .lineLimit(1)
                    .draggable(r.name)
            }
        }
    }

    private var boardColumn: some View {
        ScrollView {
            if let plan {
                VStack(spacing: 8) {
                    ForEach(Array(plan.days.enumerated()), id: \.offset) { dayIndex, day in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(day.day) · \(day.date)").font(.headline)
                            HStack(spacing: 8) {
                                ForEach(MealSlot.allCases, id: \.self) { meal in
                                    slotTile(dayIndex: dayIndex, day: day, meal: meal)
                                }
                            }
                        }
                        Divider()
                    }
                }
                .padding()
            } else if !status.isEmpty {
                Text(status).foregroundStyle(.secondary).padding()
            }
        }
    }

    private func slotTile(dayIndex: Int, day: MealPlanDay, meal: MealSlot) -> some View {
        let value = day[keyPath: meal.keyPath]
        return VStack(alignment: .leading, spacing: 2) {
            Text(meal.label).font(.caption2).foregroundStyle(.secondary)
            if let value {
                if value.kind == "recipe" {
                    NavigationLink {
                        RecipeDetailView(name: value.name)
                    } label: {
                        Text(value.name).font(.caption).lineLimit(2)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(value.name).font(.caption).lineLimit(2)
                }
                Spacer(minLength: 0)
                Button(role: .destructive) {
                    setSlot(dayIndex: dayIndex, meal: meal, value: nil)
                } label: { Image(systemName: "xmark.circle").font(.caption2) }
                .buttonStyle(.borderless)
            } else {
                Text("Drop here").font(.caption2).foregroundStyle(.tertiary)
                Spacer(minLength: 0)
            }
        }
        .padding(6)
        .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 6).fill(.quaternary.opacity(0.4)))
        .dropDestination(for: String.self) { items, _ in
            guard let name = items.first else { return false }
            setSlot(dayIndex: dayIndex, meal: meal, value: MealSlotValue(name: name))
            return true
        }
    }

    // MARK: - Mutation / network

    private func setSlot(dayIndex: Int, meal: MealSlot, value: MealSlotValue?) {
        guard var p = plan else { return }
        p.days[dayIndex][keyPath: meal.keyPath] = value
        plan = p
        Task {
            do { try await client.putMealPlan(p) }
            catch { status = "Save failed: \(error)" }
        }
    }

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { plan = try await client.mealPlan(week: weekID) }
        catch { plan = nil; status = "Error: \(error)" }
    }

    private func loadRecipes() async {
        recipes = (try? await client.allRecipes()) ?? []
    }
}
