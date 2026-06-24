import CoreSpotlight
import Foundation

/// Pushes the recipe library into the system semantic index (CoreSpotlight) so Siri,
/// Spotlight, and Apple Intelligence can match recipes by meaning. Reuses `findRecipes`
/// and `RecipeEntity`.
public enum RecipeIndexer {
    /// Reindex every recipe. Returns the number indexed.
    @discardableResult
    public static func reindexAll(client: KitchenOSClient = KitchenOSClient(config: .resolved())) async throws -> Int {
        let recipes = try await client.findRecipes(ingredient: "")
        let entities = recipes.map(RecipeEntity.init)
        try await CSSearchableIndex.default().indexAppEntities(entities)
        return entities.count
    }
}
