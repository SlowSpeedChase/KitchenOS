import SwiftUI
import KitchenOSKit

/// Mapping between a `MealSlot` and the matching property on `MealPlanDay`.
extension MealSlot {
    var keyPath: WritableKeyPath<MealPlanDay, MealSlotValue?> {
        switch self {
        case .breakfast: \.breakfast
        case .lunch: \.lunch
        case .snack: \.snack
        case .dinner: \.dinner
        }
    }
    var label: String { rawValue.capitalized }
}

/// Weekly meal plan: navigate weeks, fill/clear slots, ask for suggestions.
struct MealPlanView: View {
    @State private var weekAnchor = Date()
    @State private var plan: MealPlan?
    @State private var status = ""
    @State private var isLoading = false
    @State private var editing: SlotRef?

    private var client: KitchenOSClient { KitchenOSClient(config: .resolved()) }
    private var weekID: String { WeekDate.weekID(for: weekAnchor) }

    /// Identifies one slot (day index + meal) for editing.
    struct SlotRef: Identifiable {
        let dayIndex: Int
        let meal: MealSlot
        var id: String { "\(dayIndex)-\(meal.rawValue)" }
    }

    var body: some View {
        List {
            if let plan {
                ForEach(Array(plan.days.enumerated()), id: \.offset) { dayIndex, day in
                    Section("\(day.day) · \(day.date)") {
                        ForEach(MealSlot.allCases, id: \.self) { meal in
                            slotRow(dayIndex: dayIndex, day: day, meal: meal)
                        }
                    }
                }
            } else if !isLoading {
                Text(status.isEmpty ? "No plan." : status).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Meal Plan")
        .overlay { if isLoading { ProgressView() } }
        .toolbar {
            ToolbarItemGroup {
                Button { shiftWeek(-1) } label: { Image(systemName: "chevron.left") }
                Text(weekID).font(.callout.monospaced())
                Button { shiftWeek(1) } label: { Image(systemName: "chevron.right") }
            }
        }
        .task(id: weekID) { await load() }
        .sheet(item: $editing) { ref in
            RecipePickerSheet { picked in
                setSlot(dayIndex: ref.dayIndex, meal: ref.meal,
                        value: picked.map { MealSlotValue(name: $0) })
            }
        }
    }

    @ViewBuilder
    private func slotRow(dayIndex: Int, day: MealPlanDay, meal: MealSlot) -> some View {
        let value = day[keyPath: meal.keyPath]
        HStack {
            Text(meal.label).frame(width: 80, alignment: .leading).foregroundStyle(.secondary)
            if let value {
                Text(value.name)
                Spacer()
                Stepper("×\(value.servings)", value: Binding(
                    get: { value.servings },
                    set: { setServings(dayIndex: dayIndex, meal: meal, servings: max(1, $0)) }
                ), in: 1...12)
                .labelsHidden()
                Text("×\(value.servings)").font(.caption).foregroundStyle(.secondary)
                Button(role: .destructive) {
                    setSlot(dayIndex: dayIndex, meal: meal, value: nil)
                } label: { Image(systemName: "xmark.circle") }
                .buttonStyle(.borderless)
            } else {
                Button("Add") { editing = SlotRef(dayIndex: dayIndex, meal: meal) }
                    .buttonStyle(.borderless)
                Spacer()
                Button("Suggest") { suggest(dayIndex: dayIndex, day: day, meal: meal) }
                    .buttonStyle(.borderless).font(.caption)
            }
        }
    }

    // MARK: - Mutation

    private func setSlot(dayIndex: Int, meal: MealSlot, value: MealSlotValue?) {
        guard var p = plan else { return }
        p.days[dayIndex][keyPath: meal.keyPath] = value
        plan = p
        Task { await save(p) }
    }

    private func setServings(dayIndex: Int, meal: MealSlot, servings: Int) {
        guard var p = plan, var slot = p.days[dayIndex][keyPath: meal.keyPath] else { return }
        slot.servings = servings
        p.days[dayIndex][keyPath: meal.keyPath] = slot
        plan = p
        Task { await save(p) }
    }

    private func suggest(dayIndex: Int, day: MealPlanDay, meal: MealSlot) {
        Task {
            do {
                let resp = try await client.suggestMeal(week: weekID, day: day.day, meal: meal.rawValue)
                if let name = resp.suggestion?.name {
                    setSlot(dayIndex: dayIndex, meal: meal, value: MealSlotValue(name: name))
                } else {
                    status = resp.message ?? "No suggestion."
                }
            } catch { status = "Error: \(error)" }
        }
    }

    // MARK: - Network

    private func shiftWeek(_ delta: Int) {
        weekAnchor = Calendar.current.date(byAdding: .day, value: delta * 7, to: weekAnchor) ?? weekAnchor
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do { plan = try await client.mealPlan(week: weekID) }
        catch { plan = nil; status = "Error: \(error)" }
    }

    private func save(_ p: MealPlan) async {
        do { try await client.putMealPlan(p) }
        catch { status = "Save failed: \(error)" }
    }
}
