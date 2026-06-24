import AppIntents
import KitchenOSKit

// AppShortcutsProvider MUST live in the app target — Apple's App Intents metadata
// processor only harvests App Shortcuts from the main app, not from linked packages.
// The intents themselves live in KitchenOSKit.
struct KitchenOSShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: FindRecipesByIngredientIntent(),
            phrases: [
                "Find \(.applicationName) recipes by ingredient",
                "Search \(.applicationName) recipes",
            ],
            shortTitle: "Find by Ingredient",
            systemImageName: "magnifyingglass"
        )
        AppShortcut(
            intent: GetMealPlanIntent(),
            phrases: ["What's on my \(.applicationName) meal plan"],
            shortTitle: "Meal Plan",
            systemImageName: "calendar"
        )
        AppShortcut(
            intent: SuggestForMealPlanIntent(),
            phrases: ["Suggest a \(.applicationName) meal to add"],
            shortTitle: "Suggest a Meal",
            systemImageName: "wand.and.stars"
        )
        AppShortcut(
            intent: AddRecipeToMealPlanIntent(),
            phrases: ["Add a recipe to my \(.applicationName) meal plan"],
            shortTitle: "Add to Plan",
            systemImageName: "plus.circle"
        )
        AppShortcut(
            intent: GetRecipeNutritionIntent(),
            phrases: ["How many calories in a \(.applicationName) recipe"],
            shortTitle: "Recipe Nutrition",
            systemImageName: "flame"
        )
        AppShortcut(
            intent: SmartFindRecipesIntent(),
            phrases: [
                "Find a \(.applicationName) recipe",
                "Find me something in \(.applicationName)",
            ],
            shortTitle: "Smart Find",
            systemImageName: "sparkles"
        )
        AppShortcut(
            intent: SummarizeRecipeIntent(),
            phrases: ["Summarize a \(.applicationName) recipe"],
            shortTitle: "Summarize",
            systemImageName: "text.quote"
        )
    }
}
