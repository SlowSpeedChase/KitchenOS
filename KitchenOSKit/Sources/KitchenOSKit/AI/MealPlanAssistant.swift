import Foundation
import FoundationModels

/// On-device conversational assistant that plans over real KitchenOS data via tools.
/// Reuses the C1 `RecipeAI` availability gating; read + suggest only (writes go through
/// the confirm-gated AddRecipeToMealPlanIntent).
@MainActor
public final class MealPlanAssistant {
    private let session: LanguageModelSession

    public init(client: KitchenOSClient = KitchenOSClient(config: .resolved())) {
        let tools: [any Tool] = [
            FindRecipesTool(client: client),
            MealPlanTool(client: client),
            SuggestMealTool(client: client),
        ]
        session = LanguageModelSession(tools: tools, instructions: """
            You are KitchenOS's meal-planning assistant. Help the user explore their recipe \
            library and weekly meal plan. Always use the provided tools to look up real data \
            before answering — never invent recipes or plan entries. Be concise and friendly. \
            You can read recipes, read the meal plan, and suggest meals, but you cannot modify \
            the plan: if the user asks to add or change something, tell them to confirm it via \
            Siri ("Add a recipe to my KitchenOS meal plan") or in the app.
            """)
    }

    /// Whether the on-device model is usable right now.
    public static var isAvailable: Bool { RecipeAI.isReady }

    public func reply(to message: String) async throws -> String {
        try await session.respond(to: message).content
    }
}
