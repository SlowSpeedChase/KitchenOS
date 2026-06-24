import Foundation

public extension KitchenOSClient {
    /// The full recipe index. The server returns every recipe when the
    /// `ingredient` filter is empty.
    func allRecipes() async throws -> [RecipeSummary] {
        try await findRecipes(ingredient: "")
    }

    /// Search recipes for a structured query, reusing the existing `/api/recipes?ingredient=`
    /// endpoint and filtering protein/cuisine locally from the returned summaries.
    /// An empty `ingredient` returns the full index (server behavior), which is then
    /// narrowed by protein/cuisine — so it works for queries that specify only those.
    func recipes(matching query: RecipeQuery) async throws -> [RecipeSummary] {
        let base = try await findRecipes(ingredient: query.ingredient ?? "")
        return base.filter(query.matches)
    }
}
