import Foundation

/// Deep links into the user's Obsidian vault (synced on-device) so notes can be opened
/// and verified. Reused by Search rows, the recipe detail, and the meal-plan view.
public enum RecipeLink {
    /// `obsidian://open?vault=<vault>&file=<vaultPath>`
    public static func obsidianURL(vaultPath: String, vault: String) -> URL? {
        let vault = vault.trimmingCharacters(in: .whitespaces)
        guard !vault.isEmpty, !vaultPath.isEmpty else { return nil }
        var c = URLComponents()
        c.scheme = "obsidian"
        c.host = "open"
        c.queryItems = [
            URLQueryItem(name: "vault", value: vault),
            URLQueryItem(name: "file", value: vaultPath),
        ]
        return c.url
    }

    public static func obsidianURL(recipe name: String, vault: String) -> URL? {
        name.isEmpty ? nil : obsidianURL(vaultPath: "Recipes/\(name).md", vault: vault)
    }

    public static func mealPlanURL(week: String, vault: String) -> URL? {
        week.isEmpty ? nil : obsidianURL(vaultPath: "Meal Plans/\(week).md", vault: vault)
    }
}
