import AppIntents

/// Opens the app to a recipe. Used when a recipe is tapped in Spotlight (the indexed
/// entity) or elsewhere; routes the UI via `RecipeRouter`.
public struct OpenRecipeIntent: OpenIntent {
    public static var title: LocalizedStringResource = "Open Recipe"

    @Parameter(title: "Recipe")
    public var target: RecipeEntity

    public init() {}
    public init(target: RecipeEntity) { self.target = target }

    @MainActor
    public func perform() async throws -> some IntentResult {
        RecipeRouter.shared.open(target.id)
        return .result()
    }
}
