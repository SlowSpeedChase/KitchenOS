# Subsystem C — Phase C2: On-device meal-plan assistant (Plan)

Spec: `docs/superpowers/specs/2026-06-23-apple-intelligence-subsystem-c-design.md`.
Builds directly on C1 (`RecipeAI`, `RecipeQuery`, `KitchenOSClient.recipes(matching:)`).
Worktree: `~/Dev/KitchenOS-siri` (branch `siri-app-intents`).

## Goal

A conversational, on-device assistant that plans over the user's *real* KitchenOS data
by giving the Foundation Models session **tools** that call the existing backend. v1 is
**read + suggest** (find recipes, read the meal plan, suggest a meal). Writes (add to
plan) stay with the existing confirm-gated `AddRecipeToMealPlanIntent` — a confirmed
write-tool is a deliberate C2.1 follow-up (autonomous writes in a tool loop need a
confirmation surface).

## Components (all reuse C1 + the client)

**Tools** — `KitchenOSKit/Sources/KitchenOSKit/AI/Tools/`, each conforms to `Tool`
(`Arguments: Generable`, `Output == String`), holds an injected `KitchenOSClient`:
- `FindRecipesTool` — `Arguments == RecipeQuery` (direct reuse) → `client.recipes(matching:)` → bulleted list string.
- `MealPlanTool` — `Arguments {day: String?}` → `client.mealPlan(WeekDate.currentWeekID())` → week/day summary string.
- `SuggestMealTool` — `Arguments {day: String, meal: String}` → `client.suggestMeal(...)` → suggestion string.

**`MealPlanAssistant`** — `KitchenOSKit/AI/MealPlanAssistant.swift`, `@MainActor` class.
Holds one `LanguageModelSession(tools:instructions:)` (multi-turn transcript). Instructions
say: use tools for real data, be concise, you can read/suggest but not modify the plan —
tell the user to confirm additions via Siri/the app. `func reply(to: String) async throws -> String`
= `session.respond(to:).content`. Constructed with `KitchenOSClient(config: .resolved())`
by default (mockable for tests).

**Chat UI** — `KitchenOSSiri/Sources/AssistantView.swift`: a messages list + input field +
availability banner (reuses `RecipeAI.availability`). Owns a `MealPlanAssistant`. Add an
"Assistant" tab to the `TabView` (now Assistant / Search / Settings).

## Critical files

- Create: `KitchenOSKit/Sources/KitchenOSKit/AI/Tools/FindRecipesTool.swift`, `MealPlanTool.swift`, `SuggestMealTool.swift`
- Create: `KitchenOSKit/Sources/KitchenOSKit/AI/MealPlanAssistant.swift`
- Create: `KitchenOSSiri/Sources/AssistantView.swift`; modify `KitchenOSSiriApp.swift` (add tab)
- Create tests: `KitchenOSKit/Tests/KitchenOSKitTests/ToolsTests.swift`

## Tests (deterministic — `swift test`)

Reuse `MockURLProtocol` / `KitchenOSClient.mock(...)`:
- Each tool's `call(arguments:)` over a mocked endpoint → asserts it hits the right path and formats the expected string (FindRecipes→`/api/recipes`, MealPlan→`/api/meal-plan/<week>`, Suggest→`/api/suggest-meal`).
- `@Generable` round-trip for `MealPlanTool.Arguments` and `SuggestMealTool.Arguments` (RecipeQuery already covered).
- Not unit-tested (on-device): the model's tool-orchestration and multi-turn chat — verified live.

## Verification

1. `cd KitchenOSKit && swift build && swift test` → green (16 + new).
2. `xcodegen generate && xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` → BUILD SUCCEEDED.
3. On-device: Assistant tab → "what chicken recipes do I have?", "what's on my plan this week?", "suggest a dinner for Friday" → the model calls tools and answers over real data; availability banner when AI off.

## Reuse / setup for C3

`FindRecipesTool`/`RecipeQuery` are the same query path C3's semantic search will refine;
`MealPlanAssistant` is the surface that benefits when C3 makes `RecipeEntity` an
`IndexedEntity`. Confirmed-write tool deferred to C2.1.
