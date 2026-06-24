import Foundation
import FoundationModels

/// Tool: find recipes in the user's library. Reuses `RecipeQuery` as its arguments and
/// `KitchenOSClient.recipes(matching:)` as its implementation.
public struct FindRecipesTool: Tool {
    public let name = "findRecipes"
    public let description = "Find recipes in the user's KitchenOS library by ingredient, protein, and/or cuisine."

    let client: KitchenOSClient
    public init(client: KitchenOSClient) { self.client = client }

    public func call(arguments: RecipeQuery) async throws -> String {
        let results = try await client.recipes(matching: arguments)
        if results.isEmpty { return "No matching recipes were found." }
        return results.prefix(10).map { r in
            let extra = [r.cuisine, r.protein].compactMap { $0 }.joined(separator: ", ")
            return extra.isEmpty ? "- \(r.name)" : "- \(r.name) (\(extra))"
        }.joined(separator: "\n")
    }
}
