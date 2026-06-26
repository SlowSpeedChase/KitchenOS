import Foundation

/// Presentation helpers for inventory rows. Pure (no I/O) so they unit-test
/// cleanly; the SwiftUI view in KitchenOSSiri renders from these.
public extension InventoryItem {

    /// Emoji flag for the row: 🔴 expired, 🟡 soon, nil otherwise.
    var expiryBadge: String? {
        switch expiryStatus {
        case "expired": return "🔴"
        case "soon": return "🟡"
        default: return nil
        }
    }

    /// Sort key so the items worth tossing rise to the top of their group:
    /// 0 = expired, 1 = soon, 2 = everything else.
    var expiryRank: Int {
        switch expiryStatus {
        case "expired": return 0
        case "soon": return 1
        default: return 2
        }
    }

    /// "Added Jun 13 · Exp Jun 23 🔴" — segments omitted when their date is nil.
    var inventorySecondaryLine: String {
        var parts: [String] = []
        if let added = Self.shortDate(purchased) {
            parts.append("Added \(added)")
        }
        if let exp = Self.shortDate(expires) {
            var seg = "Exp \(exp)"
            if let badge = expiryBadge { seg += " \(badge)" }
            parts.append(seg)
        } else {
            parts.append("No expiry")
        }
        return parts.joined(separator: " · ")
    }

    /// ISO date string → "MMM d" (e.g. "Jun 13"), or nil if absent/unparseable.
    static func shortDate(_ iso: String?) -> String? {
        guard let iso, !iso.isEmpty else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: iso) else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US_POSIX")
        out.dateFormat = "MMM d"
        return out.string(from: date)
    }
}
