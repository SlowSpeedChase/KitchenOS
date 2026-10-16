import Foundation

public enum RecipeNavigationError: Error, Equatable, Sendable {
    case invalidName
    case missing(String)
    case ambiguous([String])
}

public enum RecipeNavigationResolver {
    /// Display names help lookup, but the returned target is always a saved canonical name.
    public static func resolve(name: String, recipes: [RecipeSummary]) throws -> String {
        guard isSafeName(name) else { throw RecipeNavigationError.invalidName }
        let safeRecipes = recipes.filter { isSafeName($0.name) }
        if safeRecipes.contains(where: { $0.name == name }) { return name }
        let matches = Set(safeRecipes.filter { recipe in
            recipe.name.compare(name, options: .caseInsensitive) == .orderedSame ||
                recipe.displayName?.compare(name, options: .caseInsensitive) == .orderedSame
        }.map(\.name)).sorted()
        guard !matches.isEmpty else { throw RecipeNavigationError.missing(name) }
        guard matches.count == 1 else { throw RecipeNavigationError.ambiguous(matches) }
        return matches[0]
    }

    private static func isSafeName(_ name: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != "." && trimmed != ".." &&
            !name.contains("/") && !name.contains("\\") &&
            name.rangeOfCharacter(from: .controlCharacters) == nil
    }
}
