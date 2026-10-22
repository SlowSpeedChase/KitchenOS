import AppIntents

/// Conversational entry point that hands an open-ended request to the on-device
/// meal-planning assistant (RecipeAI + tools) so new Siri can answer over real
/// KitchenOS data. Any plan change the model proposes is gated behind a native
/// Siri confirmation before KitchenOS writes it — the assistant never writes on its own.
public struct AskKitchenOSIntent: AppIntent {
    public static var title: LocalizedStringResource = "Ask KitchenOS"
    public static var description = IntentDescription(
        "Ask KitchenOS anything about your recipes and meal plan; it answers using your real data."
    )

    @Parameter(title: "Request", requestValueDialog: "What can I help you with?")
    public var request: String

    public init() {}
    public init(request: String) { self.request = request }

    public func perform() async throws -> some IntentResult & ProvidesDialog & OpensIntent {
        try Task.checkCancellation()
        guard RecipeAI.isReady else {
            return .result(dialog: "The KitchenOS assistant needs Apple Intelligence enabled.")
        }

        let assistant = await MealPlanAssistant(surface: .voice)
        let reply: String
        do {
            reply = Self.plainSpoken(try await assistant.reply(to: request))
        } catch is CancellationError {
            throw CancellationError()
        } catch KitchenOSError.unreachable {
            return .result(dialog: "I can't reach KitchenOS right now.")
        } catch {
            return .result(dialog: "Something went wrong reaching the assistant.")
        }

        let outcome = await Self.finish(
            reply: reply, proposal: assistant.pendingProposal(), navigation: assistant.takeNavigation(),
            confirm: { proposal in
                try await requestConfirmation(
                    actionName: .add,
                    dialog: "Add \(proposal.recipe) to \(proposal.day) \(proposal.meal)?")
            },
            add: { proposal in try await assistant.confirm(proposal) })
        if let destination = outcome.destination {
            try Task.checkCancellation()
            return .result(opensIntent: OpenKitchenOSWebIntent(destination: destination),
                           dialog: IntentDialog(stringLiteral: outcome.dialog))
        }
        return .result(dialog: IntentDialog(stringLiteral: outcome.dialog))
    }

    struct ReplyOutcome {
        let dialog: String
        let destination: WebDestination?
    }

    /// Both Siri and the tests use the same confirmation/write/navigation order.
    @MainActor static func finish(
        reply: String, proposal: PendingMealAddition?, navigation: PendingWebNavigation,
        confirm: (PendingMealAddition) async throws -> Void,
        add: (PendingMealAddition) async throws -> String
    ) async -> ReplyOutcome {
        do { try Task.checkCancellation() }
        catch { return ReplyOutcome(dialog: "Cancelled.", destination: nil) }
        var dialog = reply
        if let proposal {
            guard MealSlot(rawValue: proposal.meal.lowercased()) != nil else {
                return ReplyOutcome(dialog: "I didn't recognize that meal. Please say breakfast, lunch, snack, or dinner.", destination: nil)
            }
            do {
                try await confirm(proposal)
                try Task.checkCancellation()
            } catch { return ReplyOutcome(dialog: "Okay, I didn't change the meal plan.", destination: nil) }
            do { dialog = try await add(proposal) }
            catch {
                let message = Task.isCancelled || error is CancellationError
                    ? "The request was cancelled. Check the meal plan before trying again."
                    : "I couldn't update the meal plan."
                return ReplyOutcome(dialog: message, destination: nil)
            }
            // A completed write is not rolled back by cancelling its next navigation step.
            do { try Task.checkCancellation() }
            catch { return ReplyOutcome(dialog: dialog, destination: nil) }
        }
        do { try Task.checkCancellation() }
        catch { return ReplyOutcome(dialog: proposal == nil ? "Cancelled." : dialog, destination: nil) }
        switch navigation {
        case .none: return ReplyOutcome(dialog: dialog, destination: nil)
        case .clarification(let question):
            return ReplyOutcome(dialog: proposal == nil ? question : dialog + " " + question, destination: nil)
        case .destination(let target):
            let opening: String
            switch target {
            case .recipe(let name): opening = "I'll open \(name) in your browser."
            case .mealPlan(let date): opening = "I'll open the meal plan for \(date) in your browser."
            }
            return ReplyOutcome(dialog: proposal == nil ? opening : dialog + " " + opening, destination: target)
        }
    }

    /// Reduce any stray model markdown to plain text Siri can read cleanly. The voice-surface
    /// instructions already tell the model to avoid markdown; this is belt-and-suspenders for
    /// when it slips (bold, lists, links, code spans) so the dialog isn't read with literal
    /// asterisks and backticks.
    static func plainSpoken(_ text: String) -> String {
        func sub(_ s: String, _ pattern: String, _ replacement: String) -> String {
            s.replacingOccurrences(of: pattern, with: replacement, options: .regularExpression)
        }
        var s = text
        s = sub(s, "!\\[([^\\]]*)\\]\\([^)]*\\)", "$1")        // images -> alt text
        s = sub(s, "\\[([^\\]]+)\\]\\([^)]*\\)", "$1")          // links -> link text
        s = sub(s, "(?m)^[ \\t]*([-*+]|\\d+[.)]|#{1,6}|>)[ \\t]+", "") // list/heading/quote markers
        s = sub(s, "\\*\\*|__|~~|`+", "")                        // bold / strike / code fences
        s = sub(s, "\\*([^*\\n]+)\\*", "$1")                     // *italic* -> italic
        s = sub(s, "(?<![A-Za-z0-9])_([^_\\n]+)_(?![A-Za-z0-9])", "$1") // _italic_ but not intra_word_names
        s = sub(s, "\\s+", " ")                                  // collapse newlines/runs of space
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
