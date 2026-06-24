import AppIntents

public struct AddRecipeToMealPlanIntent: AppIntent {
    public static var title: LocalizedStringResource = "Add Recipe to Meal Plan"
    public static var description = IntentDescription("Add a recipe to a day on the meal plan.")

    @Parameter(title: "Recipe")
    public var recipe: RecipeEntity

    @Parameter(title: "Day")
    public var day: DayOfWeek

    @Parameter(title: "Meal")
    public var meal: MealSlot

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        try await requestConfirmation(
            actionName: .add,
            dialog: "Add \(recipe.id) to \(day.title) \(meal.title)?"
        )

        let client = KitchenOSClient(config: .resolved())
        let week = WeekDate.currentWeekID()
        var plan: MealPlan
        do { plan = try await client.mealPlan(week: week) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }

        guard let idx = plan.days.firstIndex(where: { $0.day.lowercased() == day.title.lowercased() }) else {
            return .result(dialog: "I couldn't find \(day.title) on this week's plan.")
        }
        let slot = MealSlotValue(name: recipe.id)
        switch meal {
        case .breakfast: plan.days[idx].breakfast = slot
        case .lunch:     plan.days[idx].lunch = slot
        case .snack:     plan.days[idx].snack = slot
        case .dinner:    plan.days[idx].dinner = slot
        }
        do { try await client.putMealPlan(plan) }
        catch { return .result(dialog: "I couldn't update the meal plan.") }
        return .result(dialog: "Added \(recipe.id) to \(day.title) \(meal.title).")
    }
}
