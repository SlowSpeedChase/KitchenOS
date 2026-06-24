import Foundation
import FoundationModels

/// Structured recipe-search filters the on-device model extracts from free text.
/// Reused by `SmartFindRecipesIntent`, `KitchenOSClient.recipes(matching:)`, and `SmartSearchView`.
@Generable(description: "Structured recipe search filters extracted from a request.")
public struct RecipeQuery: Sendable, Equatable {
    @Guide(description: "A single key ingredient to search for, lowercase, or nil if none implied.")
    public var ingredient: String?

    @Guide(description: "Protein such as chicken, beef, pork, tofu, or nil if none implied.")
    public var protein: String?

    @Guide(description: "Cuisine such as Italian, Indian, Mexican, or nil if none implied.")
    public var cuisine: String?

    public var isEmpty: Bool { ingredient == nil && protein == nil && cuisine == nil }

    /// Pure predicate: does a recipe summary satisfy this query?
    /// Protein/cuisine are filtered strictly; the ingredient is only re-checked when the
    /// summary carries `ingredientItems` (the server already filtered by ingredient).
    public func matches(_ s: RecipeSummary) -> Bool {
        if let p = protein, s.protein?.localizedCaseInsensitiveContains(p) != true { return false }
        if let c = cuisine, s.cuisine?.localizedCaseInsensitiveContains(c) != true { return false }
        if let ing = ingredient, let items = s.ingredientItems {
            if !items.contains(where: { $0.localizedCaseInsensitiveContains(ing) }) { return false }
        }
        return true
    }
}
