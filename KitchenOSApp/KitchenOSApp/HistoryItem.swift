import Foundation

struct HistoryItem: Identifiable {
    let id = UUID()
    let recipeName: String
    let filePath: String
    let extractedAt: Date

    var timeAgo: String {
        let interval = Date().timeIntervalSince(extractedAt)
        if interval < 60 {
            return "just now"
        } else if interval < 3600 {
            let minutes = Int(interval / 60)
            return "\(minutes)m"
        } else {
            let hours = Int(interval / 3600)
            return "\(hours)h"
        }
    }
}
