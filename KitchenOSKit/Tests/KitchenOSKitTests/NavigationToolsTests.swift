import XCTest
@testable import KitchenOSKit

final class NavigationToolsTests: XCTestCase {
    override func tearDown() { MockURLProtocol.handler = nil }
    private func tool(_ store: PendingWebDestinationStore) -> OpenWebDestinationTool {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let now = calendar.date(from: DateComponents(year: 2026, month: 10, day: 15, hour: 12))!
        return OpenWebDestinationTool(client: .mock(), store: store, now: { now }, calendar: calendar)
    }
    private func recipes(_ json: String) {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recipes")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(json.utf8))
        }
    }
    func testNamedRecipeRecordsCanonicalIdentityUsingReadOnlyLookup() async throws {
        recipes(#"[{"name":"Rice & Beans (Family)","display_name":"Rice & Beans","ingredient_items":[]}]"#)
        let store = PendingWebDestinationStore()
        store.begin(request: "Show Rice & Beans")
        _ = try await tool(store).call(arguments: .init(kind: "recipe", recipeName: "rice & beans", day: nil, weekOffset: nil))
        XCTAssertEqual(store.take(), .destination(.recipe(name: "Rice & Beans (Family)")))
        XCTAssertEqual(store.take(), .none)
    }
    func testUnknownAndAmbiguousRecipesClearTheTarget() async throws {
        for (name, json) in [("Missing", #"[{"name":"Beans","ingredient_items":[]}]"#), ("Beans", #"[{"name":"Red Beans","display_name":"Beans","ingredient_items":[]},{"name":"Black Beans","display_name":"Beans","ingredient_items":[]}]"#)] {
            recipes(json)
            let store = PendingWebDestinationStore()
            store.begin(request: "Show \(name)")
            _ = try await tool(store).call(arguments: .init(kind: "recipe", recipeName: name, day: nil, weekOffset: nil))
            guard case .clarification = store.take() else { return XCTFail("Must clarify rather than open a guessed recipe") }
        }
    }
    func testFridayAndTomorrowResolveCivilDatesWithoutNetworkOrUI() async throws {
        for (day, expected) in [("Friday", "2026-10-16"), ("tomorrow", "2026-10-16")] {
            let store = PendingWebDestinationStore()
            store.begin(request: "Open \(day)'s meals")
            _ = try await tool(store).call(arguments: .init(kind: "meal_plan", recipeName: nil, day: day, weekOffset: 0))
            XCTAssertEqual(store.take(), .destination(.mealPlan(date: expected)))
        }
    }
    func testAmbiguousNextFridayCannotBeNormalizedIntoAGuess() async throws {
        let store = PendingWebDestinationStore()
        store.begin(request: "Show next Friday's meals")
        _ = try await tool(store).call(arguments: .init(kind: "meal_plan", recipeName: nil, day: "2026-10-23", weekOffset: nil))
        guard case .clarification = store.take() else { return XCTFail("Ambiguous next weekday must clarify") }
    }
    func testNewInvocationOpenThatDoesNotInheritPreviousRecipe() async throws {
        let store = PendingWebDestinationStore()
        store.begin(request: "Open Beans")
        store.set(.recipe(name: "Beans"))
        store.begin(request: "Open that")
        _ = try await tool(store).call(arguments: .init(kind: "recipe", recipeName: "Beans", day: nil, weekOffset: nil))
        guard case .clarification = store.take() else { return XCTFail("No cross-invocation selection") }
    }
    func testOrdinaryQuestionsCannotRecordNavigationEvenIfModelCallsTool() async throws {
        let store = PendingWebDestinationStore()
        store.begin(request: "What's planned for Friday?")
        _ = try await tool(store).call(arguments: .init(kind: "meal_plan", recipeName: nil, day: "Friday", weekOffset: nil))
        XCTAssertEqual(store.take(), .none)
    }
    func testConflictingTargetsStayClarificationUntilNextReply() {
        let store = PendingWebDestinationStore()
        store.begin(request: "Show Beans and Monday")
        store.set(.recipe(name: "Beans"))
        store.set(.mealPlan(date: "2026-10-12"))
        store.set(.recipe(name: "Beans"))
        guard case .clarification = store.take() else { return XCTFail("Never use last-writer wins") }
        store.begin(request: "Open Beans")
        store.set(.recipe(name: "Beans"))
        store.clear()
        XCTAssertEqual(store.take(), .none)
    }
    func testLookupFailureClearsPreviouslyRecordedNavigation() async {
        let store = PendingWebDestinationStore()
        store.begin(request: "Open Beans")
        store.set(.recipe(name: "Beans"))
        MockURLProtocol.handler = { _ in throw URLError(.notConnectedToInternet) }
        do {
            _ = try await tool(store).call(arguments: .init(kind: "recipe", recipeName: "Beans", day: nil, weekOffset: nil))
            XCTFail("Failed lookup should throw")
        } catch { }
        XCTAssertEqual(store.take(), .none)
    }
    @MainActor func testInvalidMealProposalCannotOpenAsThoughWriteSucceeded() async {
        let outcome = await AskKitchenOSIntent.finish(
            reply: "Opening", proposal: .init(recipe: "Beans", day: "Friday", meal: "invalid"),
            navigation: .destination(.recipe(name: "Beans")),
            confirm: { _ in XCTFail("Invalid meal should not prompt") },
            add: { _ in XCTFail("Invalid meal should not write"); return "I didn't recognize the meal" })
        XCTAssertNil(outcome.destination)
    }
    func testCancelledNavigationToolClearsPendingTargetWithoutLookup() async {
        let store = PendingWebDestinationStore()
        store.begin(request: "Show Beans")
        store.set(.recipe(name: "Beans"))
        MockURLProtocol.handler = { _ in XCTFail("Cancelled tool should not look up recipes"); throw URLError(.cancelled) }
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            do {
                _ = try await self.tool(store).call(arguments: .init(kind: "recipe", recipeName: "Beans", day: nil, weekOffset: nil))
                XCTFail("Cancelled tool must throw")
            } catch { XCTAssertTrue(error is CancellationError) }
        }
        await task.value
        XCTAssertEqual(store.take(), .none)
    }
    @MainActor func testVoiceOnlyToolRegistration() {
        let store = PendingWebDestinationStore()
        let voice = MealPlanAssistant.tools(client: .mock(), surface: .voice, proposals: ProposalStore(), navigation: store)
        let chat = MealPlanAssistant.tools(client: .mock(), surface: .chat, proposals: ProposalStore(), navigation: store)
        XCTAssertTrue(voice.contains { $0.name == "openWebDestination" })
        XCTAssertFalse(chat.contains { $0.name == "openWebDestination" })
    }
    @MainActor func testDeclinedConfirmationClearsProposalAndSkipsWrite() async {
        struct Declined: Error {}
        var declined: [String] = []
        let outcome = await AskKitchenOSIntent.finish(
            reply: "Ready", proposal: .init(recipe: "Beans", day: "Friday", meal: "dinner"),
            navigation: .destination(.recipe(name: "Beans")),
            confirm: { _ in throw Declined() },
            add: { _ in XCTFail("Declined confirmation must not write"); return "Added Beans." },
            decline: { proposal in declined.append(proposal.recipe) })
        XCTAssertEqual(declined, ["Beans"])
        XCTAssertNil(outcome.destination)
        XCTAssertFalse(outcome.dialog.contains("Added Beans"))
    }
    @MainActor func testCancellationAtEntryDoesNotConfirmWriteOrNavigate() async {
        let task = Task { @MainActor in
            withUnsafeCurrentTask { $0?.cancel() }
            return await AskKitchenOSIntent.finish(
                reply: "Ready", proposal: .init(recipe: "Beans", day: "Friday", meal: "dinner"),
                navigation: .destination(.recipe(name: "Beans")),
                confirm: { _ in XCTFail("Cancelled invocation must not ask to confirm") },
                add: { _ in XCTFail("Cancelled invocation must not write"); return "Added Beans." })
        }
        let outcome = await task.value
        XCTAssertNil(outcome.destination)
    }
    @MainActor func testCancellationAfterConfirmationDoesNotWriteOrNavigate() async {
        let task = Task { @MainActor in
            return await AskKitchenOSIntent.finish(
                reply: "Ready", proposal: .init(recipe: "Beans", day: "Friday", meal: "dinner"),
                navigation: .destination(.recipe(name: "Beans")),
                confirm: { _ in withUnsafeCurrentTask { $0?.cancel() } },
                add: { _ in XCTFail("Cancellation after confirmation must stop the write"); return "Added Beans." })
        }
        let outcome = await task.value
        XCTAssertNil(outcome.destination)
        XCTAssertFalse(outcome.dialog.contains("Added Beans"))
    }
    @MainActor func testCancellationAfterSuccessfulWritePreservesSuccessButDropsNavigation() async {
        let task = Task { @MainActor in
            return await AskKitchenOSIntent.finish(
                reply: "Ready", proposal: .init(recipe: "Beans", day: "Friday", meal: "dinner"),
                navigation: .destination(.recipe(name: "Beans")),
                confirm: { _ in },
                add: { _ in withUnsafeCurrentTask { $0?.cancel() }; return "Added Beans." })
        }
        let outcome = await task.value
        XCTAssertNil(outcome.destination)
        XCTAssertEqual(outcome.dialog, "Added Beans.")
    }
    @MainActor func testCombinedAddAndShowOnlyOpensAfterSuccessfulConfirmationAndWrite() async {
        let proposal = PendingMealAddition(recipe: "Beans", day: "Friday", meal: "dinner")
        let destination = WebDestination.mealPlan(date: "2026-10-16")
        var events: [String] = []
        let result = await AskKitchenOSIntent.finish(reply: "A proposal", proposal: proposal, navigation: .destination(destination), confirm: { _ in events.append("confirm") }, add: { _ in events.append("write"); return "Added Beans." })
        XCTAssertEqual(events, ["confirm", "write"])
        XCTAssertEqual(result.destination, destination)
        XCTAssertTrue(result.dialog.contains("Added Beans"))
    }
    @MainActor func testDeclinedOrFailedWriteDoesNotOpenOrClaimSuccess() async {
        enum Failure: Error { case denied }
        let proposal = PendingMealAddition(recipe: "Beans", day: "Friday", meal: "dinner")
        var writes = 0
        let declined = await AskKitchenOSIntent.finish(reply: "Opening it", proposal: proposal, navigation: .destination(.recipe(name: "Beans")), confirm: { _ in throw Failure.denied }, add: { _ in writes += 1; return "Added" })
        XCTAssertEqual(writes, 0)
        XCTAssertNil(declined.destination)
        XCTAssertFalse(declined.dialog.contains("Opening"))
        let failed = await AskKitchenOSIntent.finish(reply: "Added it", proposal: proposal, navigation: .destination(.recipe(name: "Beans")), confirm: { _ in }, add: { _ in throw Failure.denied })
        XCTAssertNil(failed.destination)
        XCTAssertFalse(failed.dialog.contains("Added"))
    }
}
