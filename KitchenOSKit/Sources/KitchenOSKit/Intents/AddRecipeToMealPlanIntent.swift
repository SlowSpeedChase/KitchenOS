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
        do {
            try await client.addRecipe(recipe.id, day: day.title, meal: meal, week: WeekDate.currentWeekID())
        } catch KitchenOSError.unreachable {
            return .result(dialog: "I can't reach KitchenOS right now.")
        } catch KitchenOSError.http(404) {
            return .result(dialog: "I couldn't find \(day.title) on this week's plan.")
        } catch {
            return .result(dialog: "I couldn't update the meal plan.")
        }
        return .result(dialog: "Added \(recipe.id) to \(day.title) \(meal.title).")
    }
}
