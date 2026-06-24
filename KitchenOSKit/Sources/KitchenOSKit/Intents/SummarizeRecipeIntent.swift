import AppIntents

public struct SummarizeRecipeIntent: AppIntent {
    public static var title: LocalizedStringResource = "Summarize Recipe"
    public static var description = IntentDescription("Get a short on-device summary of a recipe.")

    @Parameter(title: "Recipe")
    public var recipe: RecipeEntity

    public init() {}

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        guard RecipeAI.isReady else {
            return .result(dialog: "Recipe summaries need Apple Intelligence enabled.")
        }
        let client = KitchenOSClient(config: .resolved())
        let detail: RecipeDetail
        do { detail = try await client.recipeDetail(name: recipe.id) }
        catch KitchenOSError.unreachable { return .result(dialog: "I can't reach KitchenOS right now.") }
        catch KitchenOSError.http(404) { return .result(dialog: "I couldn't find \(recipe.id).") }

        let summary = try await RecipeAI.summarize(detail)
        return .result(dialog: IntentDialog(stringLiteral: summary))
    }
}
