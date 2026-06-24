import Foundation
import FoundationModels

/// Thread-safe holder for the latest proposed addition (the tool runs off the main actor).
final class ProposalStore: @unchecked Sendable {
    private let lock = NSLock()
    private var value: PendingMealAddition?
    func set(_ v: PendingMealAddition?) { lock.lock(); value = v; lock.unlock() }
    func take() -> PendingMealAddition? { lock.lock(); defer { lock.unlock() }; return value }
}

/// On-device conversational assistant that plans over real KitchenOS data via tools.
/// Reads/suggests freely; additions are *proposed* by the model and applied only after the
/// user taps Confirm (the app performs the write via `KitchenOSClient.addRecipe`).
@MainActor
public final class MealPlanAssistant {
    private let session: LanguageModelSession
    private let client: KitchenOSClient
    private let proposals = ProposalStore()

    public init(client: KitchenOSClient = KitchenOSClient(config: .resolved())) {
        self.client = client
        let store = proposals
        let tools: [any Tool] = [
            FindRecipesTool(client: client),
            MealPlanTool(client: client),
            SuggestMealTool(client: client),
            AddToMealPlanTool(onPropose: { store.set($0) }),
        ]
        session = LanguageModelSession(tools: tools, instructions: """
            You are KitchenOS's meal-planning assistant. Help the user explore their recipe \
            library and weekly meal plan. Always use the provided tools to look up real data \
            before answering — never invent recipes or plan entries. Be concise and friendly. \
            To add a recipe to the plan, call proposeAddToMealPlan and tell the user to tap \
            Confirm; never claim you have changed the plan yourself.
            """)
    }

    /// Whether the on-device model is usable right now.
    public static var isAvailable: Bool { RecipeAI.isReady }

    public func reply(to message: String) async throws -> String {
        try await session.respond(to: message).content
    }

    /// A pending proposal produced during the last reply, if any.
    public func pendingProposal() -> PendingMealAddition? { proposals.take() }
    public func clearProposal() { proposals.set(nil) }

    /// Apply a confirmed proposal (the only write path). Returns a user-facing message.
    public func confirm(_ p: PendingMealAddition) async throws -> String {
        guard let slot = MealSlot(rawValue: p.meal.lowercased()) else {
            return "I didn't recognize the meal \"\(p.meal)\"."
        }
        try await client.addRecipe(p.recipe, day: p.day, meal: slot, week: WeekDate.currentWeekID())
        clearProposal()
        return "Added \(p.recipe) to \(p.day) \(slot.title)."
    }
}
