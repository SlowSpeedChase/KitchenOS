import AppIntents

public struct SmartFindRecipesIntent: AppIntent {
    public static var title: LocalizedStringResource = "Find a Recipe (Smart)"
    public static var description = IntentDescription("Describe what you want and KitchenOS finds matching recipes.")

    @Parameter(title: "Request", requestValueDialog: "What are you in the mood for?")
    public var query: String

    public init() {}
    public init(query: String) { self.query = query }

    public func perform() async throws -> some IntentResult & ReturnsValue<[RecipeEntity]> & ProvidesDialog {
        let client = KitchenOSClient(config: .resolved())
        let recipes: [RecipeSummary]
        do {
            if RecipeAI.isReady {
                let parsed = try await RecipeAI.parseQuery(query)
                recipes = try await client.recipes(matching: parsed)
            } else {
                // Graceful fallback: treat the whole request as an ingredient term.
                recipes = try await client.findRecipes(ingredient: query)
            }
        } catch KitchenOSError.unreachable {
            return .result(value: [], dialog: "I can't reach KitchenOS right now.")
        }

        let entities = recipes.map(RecipeEntity.init)
        if entities.isEmpty {
            return .result(value: [], dialog: "I didn't find any recipes for that.")
        }
        let names = entities.prefix(5).map(\.id).joined(separator: ", ")
        let dialog: IntentDialog = entities.count == 1
            ? "I found \(names)."
            : "I found \(entities.count) recipes: \(names)."
        return .result(value: entities, dialog: dialog)
    }
}
