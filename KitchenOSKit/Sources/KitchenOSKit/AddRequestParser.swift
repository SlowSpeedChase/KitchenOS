import Foundation

/// Deterministically recognizes "add <recipe> to <day> [<meal>]" so the assistant can
/// surface a Confirm card without relying on the on-device model's tool-calling.
public enum AddRequestParser {
    private static let pattern = #"\badd\s+(.+?)\s+to\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:for\s+)?(breakfast|lunch|snack|dinner))?\b"#

    public static func parse(_ text: String) -> PendingMealAddition? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let m = re.firstMatch(in: text, options: [], range: range) else { return nil }

        func group(_ i: Int) -> String? {
            let r = m.range(at: i)
            guard r.location != NSNotFound, let rr = Range(r, in: text) else { return nil }
            return String(text[rr]).trimmingCharacters(in: .whitespaces)
        }

        guard let recipeRaw = group(1), !recipeRaw.isEmpty, let day = group(2) else { return nil }
        let meal = (group(3) ?? "dinner").lowercased()
        return PendingMealAddition(recipe: titleCased(recipeRaw), day: day.capitalized, meal: meal)
    }

    private static func titleCased(_ s: String) -> String {
        s.split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}
