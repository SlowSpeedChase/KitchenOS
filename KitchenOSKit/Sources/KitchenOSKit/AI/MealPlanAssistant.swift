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
    private let navigation = PendingWebDestinationStore()
    private let surface: AssistantSurface

    public init(client: KitchenOSClient = KitchenOSClient(config: .resolved()),
                surface: AssistantSurface = .chat) {
        self.client = client
        self.surface = surface
        session = LanguageModelSession(
            tools: Self.tools(client: client, surface: surface, proposals: proposals, navigation: navigation),
            instructions: Self.instructions(for: surface))
    }

    static func tools(client: KitchenOSClient, surface: AssistantSurface,
                      proposals: ProposalStore, navigation: PendingWebDestinationStore) -> [any Tool] {
        var tools: [any Tool] = [
            FindRecipesTool(client: client),
            MealPlanTool(client: client),
            SuggestMealTool(client: client),
            CookWithIngredientsTool(client: client),
            AddToMealPlanTool(onPropose: { proposals.set($0) }),
        ]
        if case .voice = surface {
            tools.append(OpenWebDestinationTool(client: client, store: navigation))
        }
        return tools
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
                changed the plan yourself. Only when the user explicitly says open or show, \
                call openWebDestination with one real saved recipe or meal-plan day. Ordinary \
                questions receive spoken answers without navigation. For find-and-show, use \
                the recipe lookup first, then its exact returned name. Never invent URLs. \
                A bare weekday means this ISO week; explicit next week means the next ISO week. \
                Ask for clarification for ambiguous next Friday or open that without a target \
                in this invocation. Never claim a page has opened; the foreground continuation \
                will report browser dispatch. Today is \((try? WebDayResolver.resolve(.today)) ?? "unavailable"); \
                the current ISO week is \(WeekDate.currentWeekID()).
                """
        }
    }

    /// Whether the on-device model is usable right now.
    public static var isAvailable: Bool { RecipeAI.isReady }

    public func reply(to message: String) async throws -> String {
        navigation.begin(request: message)
        if case .voice = surface { proposals.set(nil) }
        do {
            try Task.checkCancellation()
            let content = try await session.respond(to: message).content
            try Task.checkCancellation()
            return content
        } catch { navigation.clear(); proposals.set(nil); throw error }
    }

    /// A pending proposal produced during the last reply, if any.
    public func pendingProposal() -> PendingMealAddition? { proposals.take() }
    public func clearProposal() { proposals.set(nil) }
    public func takeNavigation() -> PendingWebNavigation { navigation.take() }

    /// Apply a confirmed proposal (the only write path). Returns a user-facing message.
    public func confirm(_ p: PendingMealAddition) async throws -> String {
        guard let slot = MealSlot(rawValue: p.meal.lowercased()) else {
            return "I didn't recognize the meal \"\(p.meal)\"."
        }
        try Task.checkCancellation()
        try await client.addRecipe(p.recipe, day: p.day, meal: slot, week: WeekDate.currentWeekID())
        clearProposal()
        return "Added \(p.recipe) to \(p.day) \(slot.title)."
    }
}
