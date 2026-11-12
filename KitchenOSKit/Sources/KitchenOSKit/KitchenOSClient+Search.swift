import Foundation

public extension KitchenOSClient {
    /// The full recipe index. With `includeIngredients`, each summary carries its
    /// `ingredient_items` (feeds the Spotlight keyword donation).
    func allRecipes(includeIngredients: Bool = false) async throws -> [RecipeSummary] {
        guard includeIngredients else { return try await findRecipes(ingredient: "") }
        var comps = URLComponents(url: baseURL.appendingPathComponent("/api/recipes"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "include_ingredients", value: "1")]
        return try await getJSON(comps.url!)
    }

    /// Search recipes for a structured query, reusing the existing `/api/recipes?ingredient=`
    /// endpoint and filtering protein/cuisine locally from the returned summaries.
    /// An empty `ingredient` returns the full index (server behavior), which is then
    /// narrowed by protein/cuisine — so it works for queries that specify only those.
    func recipes(matching query: RecipeQuery) async throws -> [RecipeSummary] {
        let base = try await findRecipes(ingredient: query.ingredient ?? "")
        return query.ranked(base.filter(query.matches))
    }
}
