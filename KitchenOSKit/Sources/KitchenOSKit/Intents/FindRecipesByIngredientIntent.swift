import AppIntents

public struct FindRecipesByIngredientIntent: AppIntent {
    public static var title: LocalizedStringResource = "Find Recipes by Ingredient"
    public static var description = IntentDescription("Find KitchenOS recipes that contain an ingredient.")

    @Parameter(title: "Ingredient")
    public var ingredient: String

    public init() {}
    public init(ingredient: String) { self.ingredient = ingredient }

    public func perform() async throws -> some IntentResult & ReturnsValue<[RecipeEntity]> & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let recipes: [RecipeSummary]
        do { recipes = try await client.findRecipes(ingredient: ingredient) }
        catch KitchenOSError.unreachable { return .result(value: [], dialog: "I can't reach KitchenOS right now.") }

        let entities = recipes.map(RecipeEntity.init)
        if entities.isEmpty {
            return .result(value: [], dialog: "I didn't find any recipes with \(ingredient).")
        }
        let names = entities.prefix(5).map(\.id).joined(separator: ", ")
        let dialog: IntentDialog = entities.count == 1
            ? "I found \(names)."
            : "I found \(entities.count) recipes: \(names)."
        return .result(value: entities, dialog: dialog)
    }
}
