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

    @Guide(description: "true if the user wants high-protein recipes.")
    public var highProtein: Bool?

    @Guide(description: "true if the user wants low-fat recipes.")
    public var lowFat: Bool?

    @Guide(description: "true if the user wants low-calorie recipes.")
    public var lowCalorie: Bool?

    public init(ingredient: String? = nil, protein: String? = nil, cuisine: String? = nil,
                highProtein: Bool? = nil, lowFat: Bool? = nil, lowCalorie: Bool? = nil) {
        self.ingredient = ingredient; self.protein = protein; self.cuisine = cuisine
        self.highProtein = highProtein; self.lowFat = lowFat; self.lowCalorie = lowCalorie
    }

    public var hasNutritionPreference: Bool {
        highProtein == true || lowFat == true || lowCalorie == true
    }

    public var isEmpty: Bool {
        ingredient == nil && protein == nil && cuisine == nil && !hasNutritionPreference
    }

    /// Pure predicate: does a recipe summary satisfy the categorical filters?
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

    /// Rank by nutrition when a high/low preference is set (protein desc, then fat asc,
    /// then calories asc). Returns the input unchanged when there's no preference, or when
    /// the server returned no nutrition data (graceful — nutrition fields are optional).
    /// Caps to the top 25.
    public func ranked(_ summaries: [RecipeSummary]) -> [RecipeSummary] {
        guard hasNutritionPreference else { return summaries }
        let withData = summaries.filter {
            $0.nutritionProtein != nil || $0.nutritionFat != nil || $0.nutritionCalories != nil
        }
        guard !withData.isEmpty else { return summaries }
        let sorted = withData.sorted { a, b in
            if highProtein == true {
                let pa = a.nutritionProtein ?? -1, pb = b.nutritionProtein ?? -1
                if pa != pb { return pa > pb }
            }
            if lowFat == true {
                let fa = a.nutritionFat ?? .greatestFiniteMagnitude, fb = b.nutritionFat ?? .greatestFiniteMagnitude
                if fa != fb { return fa < fb }
            }
            if lowCalorie == true {
                let ca = a.nutritionCalories ?? .greatestFiniteMagnitude, cb = b.nutritionCalories ?? .greatestFiniteMagnitude
                if ca != cb { return ca < cb }
            }
            return a.name < b.name
        }
        return Array(sorted.prefix(25))
    }
}
