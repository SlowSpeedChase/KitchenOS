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

    public func perform() async throws -> some IntentResult & ProvidesDialog {
        guard RecipeAI.isReady else {
            return .result(dialog: "The KitchenOS assistant needs Apple Intelligence enabled.")
        }

        let assistant = await MealPlanAssistant(surface: .voice)
        let reply: String
        do {
            reply = Self.plainSpoken(try await assistant.reply(to: request))
        } catch KitchenOSError.unreachable {
            return .result(dialog: "I can't reach KitchenOS right now.")
        } catch {
            return .result(dialog: "Something went wrong reaching the assistant.")
        }

        // No write proposed — just speak the answer.
        guard let proposal = await assistant.pendingProposal() else {
            return .result(dialog: IntentDialog(stringLiteral: reply))
        }

        // A plan change was proposed: confirm via Siri before writing (the only write path).
        do {
            try await requestConfirmation(
                actionName: .add,
                dialog: "Add \(proposal.recipe) to \(proposal.day) \(proposal.meal)?"
            )
        } catch {
            // User declined the change — keep the assistant's answer, skip the write.
            return .result(dialog: IntentDialog(stringLiteral: reply))
        }

        do {
            let confirmation = try await assistant.confirm(proposal)
            return .result(dialog: IntentDialog(stringLiteral: confirmation))
        } catch {
            return .result(dialog: "I couldn't update the meal plan.")
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
