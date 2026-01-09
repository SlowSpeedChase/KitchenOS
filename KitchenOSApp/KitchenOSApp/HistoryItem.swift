import Foundation
import AppKit

/// Model for a single recipe extraction history entry
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

    /// Open the recipe file in Obsidian
    func openInObsidian() {
        // Use obsidian:// URL scheme
        let obsidianVaultPath = "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"

        if filePath.hasPrefix(obsidianVaultPath) {
            let relativePath = String(filePath.dropFirst(obsidianVaultPath.count + 1))
            let encoded = relativePath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? relativePath
            let urlString = "obsidian://open?vault=KitchenOS&file=\(encoded)"

            if let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
            }
        } else {
            // Fallback: open file directly
            NSWorkspace.shared.open(URL(fileURLWithPath: filePath))
        }
    }
}
