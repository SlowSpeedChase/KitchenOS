#if os(macOS)
import Foundation
import AppKit

/// Model for a single recipe extraction history entry.
struct HistoryItem: Identifiable {
    let id = UUID()
    let recipeName: String
    let filePath: String
    let extractedAt: Date

    var timeAgo: String {
        let interval = Date().timeIntervalSince(extractedAt)
        let minutes = Int(interval / 60)

        if minutes < 1 {
            return "just now"
        } else if minutes < 60 {
            return "\(minutes)m"
        } else {
            let hours = minutes / 60
            return "\(hours)h"
        }
    }

    /// Open the recipe file in Obsidian via the `obsidian://` URL scheme,
    /// falling back to opening the file directly.
    func openInObsidian() {
        if let vaultName = filePath.kitchenOSVaultName,
           let range = filePath.range(of: "/\(vaultName)/") {
            let relativePath = String(filePath[range.upperBound...])
            let encoded = relativePath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? relativePath
            let urlString = "obsidian://open?vault=\(vaultName)&file=\(encoded)"
            if let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
                return
            }
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: filePath))
    }
}

private extension String {
    /// Best-effort Obsidian vault name: the directory component immediately
    /// above a `Recipes/` segment (matches the KitchenOS vault layout).
    var kitchenOSVaultName: String? {
        let parts = components(separatedBy: "/")
        guard let recipesIdx = parts.firstIndex(of: "Recipes"), recipesIdx > 0 else { return nil }
        return parts[recipesIdx - 1]
    }
}
#endif
