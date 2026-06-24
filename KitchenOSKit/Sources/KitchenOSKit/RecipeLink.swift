import Foundation

/// Deep links into the user's Obsidian vault (synced on-device) so a recipe can be
/// opened and verified. Reused by Smart Search rows and the recipe summary.
public enum RecipeLink {
    /// `obsidian://open?vault=<vault>&file=Recipes/<name>.md`
    public static func obsidianURL(recipe name: String, vault: String) -> URL? {
        let vault = vault.trimmingCharacters(in: .whitespaces)
        guard !vault.isEmpty, !name.isEmpty else { return nil }
        var c = URLComponents()
        c.scheme = "obsidian"
        c.host = "open"
        c.queryItems = [
            URLQueryItem(name: "vault", value: vault),
            URLQueryItem(name: "file", value: "Recipes/\(name).md"),
        ]
        return c.url
    }
}
