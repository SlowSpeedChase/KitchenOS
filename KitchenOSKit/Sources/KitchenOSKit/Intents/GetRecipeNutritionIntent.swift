import AppIntents

public struct GetRecipeNutritionIntent: AppIntent {
    public static var title: LocalizedStringResource = "Get Recipe Nutrition"
    public static var description = IntentDescription("Report a recipe's calories and macros.")

    @Parameter(title: "Recipe")
    public var recipe: RecipeEntity

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let detail: RecipeDetail
        do { detail = try await client.recipeDetail(name: recipe.id) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }
        catch KitchenOSError.http(404) { return .result(dialog: "I couldn't find \(recipe.id).") }

        guard let cals = detail.nutritionCalories else {
            return .result(dialog: "\(recipe.id) doesn't have nutrition data yet.")
        }
        var parts = ["\(Int(cals)) calories"]
        if let p = detail.nutritionProtein { parts.append("\(Int(p)) grams of protein") }
        return .result(dialog: IntentDialog(stringLiteral: "\(recipe.id) has " + parts.joined(separator: " and ") + " per serving."))
    }
}
