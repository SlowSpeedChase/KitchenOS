import AppIntents

public struct SuggestForMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Suggest a Meal to Add"
    public static var description = IntentDescription("Suggest a recipe for the next empty slot on the meal plan.")

    @Parameter(title: "Day")
    public var day: DayOfWeek?

    @Parameter(title: "Meal")
    public var meal: MealSlot?

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        let plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        guard let (dayName, mealName) = Self.targetSlot(plan: plan, day: day, meal: meal) else {
            return .result(dialog: "The plan looks full — nothing to suggest.")
        }
        let resp = try await client.suggestMeal(week: week, day: dayName, meal: mealName, skipIndex: 0)
        guard let s = resp.suggestion else {
            return .result(dialog: IntentDialog(stringLiteral: resp.message ?? "No suggestions available."))
        }
        return .result(dialog: "For \(mealName) on \(dayName), try \(s.name).")
    }

    /// Pick the requested slot, or the first empty slot in week order.
    static func targetSlot(plan: MealPlan, day: DayOfWeek?, meal: MealSlot?) -> (String, String)? {
        func value(_ d: MealPlanDay, _ m: MealSlot) -> MealSlotValue? {
            switch m { case .breakfast: return d.breakfast; case .lunch: return d.lunch
                       case .snack: return d.snack; case .dinner: return d.dinner }
        }
        let days = day == nil ? plan.days
                              : plan.days.filter { $0.day.lowercased() == day!.title.lowercased() }
        let meals: [MealSlot] = meal.map { [$0] } ?? [.breakfast, .lunch, .snack, .dinner]
        for d in days { for m in meals where value(d, m) == nil { return (d.day, m.rawValue) } }
        return nil
    }
}
