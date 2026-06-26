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
/// Where the assistant's replies are surfaced, which changes how it should phrase
/// confirmations and format answers.
public enum AssistantSurface: Sendable {
    /// In-app text chat (`AssistantView`): the user taps a Confirm button.
    case chat
    /// Siri / spoken: replies are read aloud and the system asks to confirm out loud.
    case voice
}

@MainActor
public final class MealPlanAssistant {
    private let session: LanguageModelSession
    private let client: KitchenOSClient
    private let proposals = ProposalStore()

    public init(client: KitchenOSClient = KitchenOSClient(config: .resolved()),
                surface: AssistantSurface = .chat) {
        self.client = client
        let store = proposals
        let tools: [any Tool] = [
            FindRecipesTool(client: client),
            MealPlanTool(client: client),
            SuggestMealTool(client: client),
            CookWithIngredientsTool(client: client),
            AddToMealPlanTool(onPropose: { store.set($0) }),
        ]
        session = LanguageModelSession(tools: tools, instructions: Self.instructions(for: surface))
    }

    /// Surface-specific system instructions. The shared core (use real data, never invent,
    /// propose-don't-write) is constant; only the confirmation phrasing and formatting differ.
    static func instructions(for surface: AssistantSurface) -> String {
        let core = """
            You are KitchenOS's meal-planning assistant. Help the user explore their recipe \
            library and weekly meal plan. Always use the provided tools to look up real data \
            before answering — never invent recipes or plan entries.
            """
        switch surface {
        case .chat:
            return core + " " + """
                Be concise and friendly. To add a recipe to the plan, call proposeAddToMealPlan \
                and tell the user to tap Confirm; never claim you have changed the plan yourself.
                """
        case .voice:
            return core + " " + """
                Your replies are read aloud by Siri, so keep them to one or two short sentences \
                in plain conversational language — no markdown, bullet lists, emoji, or links, \
                and don't recite long lists (offer two or three options at most). To add a \
                recipe to the plan, call proposeAddToMealPlan; the system asks the user to \
                confirm out loud, so never tell them to tap anything and never claim you have \
                changed the plan yourself.
                """
        }
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
