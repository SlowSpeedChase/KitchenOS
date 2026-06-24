import Foundation
import FoundationModels

/// The single on-device LLM gateway for KitchenOS (Apple Foundation Models).
/// C1 uses it for recipe summaries and natural-language query parsing; C2 will add a
/// tools-enabled session, C3 reuses the availability gating. Requires iOS/macOS 26.
public enum RecipeAI {
    public enum AIAvailability: Sendable, Equatable {
        case available
        case unavailable(reason: String)
    }

    public static var availability: AIAvailability {
        switch SystemLanguageModel.default.availability {
        case .available:
            return .available
        case .unavailable(let reason):
            let message: String
            switch reason {
            case .deviceNotEligible:
                message = "This device doesn't support Apple Intelligence."
            case .appleIntelligenceNotEnabled:
                message = "Turn on Apple Intelligence in Settings to use this."
            case .modelNotReady:
                message = "The on-device model is still preparing. Try again shortly."
            @unknown default:
                message = "Apple Intelligence is unavailable right now."
            }
            return .unavailable(reason: message)
        }
    }

    public static var isReady: Bool {
        if case .available = availability { return true }
        return false
    }

    /// A short, appetizing on-device summary of a recipe (<= 2 sentences).
    public static func summarize(_ detail: RecipeDetail) async throws -> String {
        let session = LanguageModelSession(instructions: """
            You write concise, appetizing recipe summaries. Given recipe facts, reply with \
            at most two sentences and no preamble.
            """)
        let response = try await session.respond(to: "Summarize this recipe:\n\(facts(for: detail))")
        return response.content
    }

    /// Parse free text into structured search filters via guided generation.
    public static func parseQuery(_ text: String) async throws -> RecipeQuery {
        let session = LanguageModelSession(instructions: """
            Extract recipe search filters from the user's request. Only fill a field when it \
            is clearly implied; otherwise leave it nil. The ingredient is a single key \
            ingredient in lowercase.
            """)
        let response = try await session.respond(to: text, generating: RecipeQuery.self)
        return response.content
    }

    private static func facts(for d: RecipeDetail) -> String {
        var parts = ["Title: \(d.title)"]
        if let s = d.servings { parts.append("Servings: \(s)") }
        if let c = d.nutritionCalories { parts.append("Calories per serving: \(Int(c))") }
        if let p = d.nutritionProtein { parts.append("Protein per serving: \(Int(p))g") }
        return parts.joined(separator: "\n")
    }
}
