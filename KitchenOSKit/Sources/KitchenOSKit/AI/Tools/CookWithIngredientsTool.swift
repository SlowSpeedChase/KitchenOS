import Foundation
import FoundationModels

@Generable(description: "Arguments for finding recipes from ingredients on hand.")
public struct CookWithArguments: Sendable {
    @Guide(description: "Ingredients the user has or wants to use. Leave empty to use the kitchen inventory.")
    public var ingredients: [String]
}

/// Tool: rank recipes by overlap with the given ingredients (or the kitchen inventory when
/// none are given). Reuses `recipesByIngredients` + `inventoryItems`.
public struct CookWithIngredientsTool: Tool {
    public let name = "cookWithIngredients"
    public let description = "Find recipes that use the most of a list of ingredients the user has. If no ingredients are given, use the kitchen inventory."

    let client: KitchenOSClient
    public init(client: KitchenOSClient) { self.client = client }

    public func call(arguments: CookWithArguments) async throws -> String {
        var ingredients = arguments.ingredients.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        if ingredients.isEmpty {
            ingredients = try await client.inventoryItems()
            if ingredients.isEmpty {
                return "No ingredients were given and the kitchen inventory is empty or not documented yet."
            }
        }
        let matches = try await client.recipesByIngredients(ingredients)
        return Self.format(matches)
    }

    static func format(_ matches: [Suggestion]) -> String {
        if matches.isEmpty { return "No recipes share those ingredients." }
        return matches.prefix(8).map { s in
            let shared = (s.sharedIngredients ?? []).joined(separator: ", ")
            return shared.isEmpty ? "- \(s.name)" : "- \(s.name) (uses \(shared))"
        }.joined(separator: "\n")
    }
}
