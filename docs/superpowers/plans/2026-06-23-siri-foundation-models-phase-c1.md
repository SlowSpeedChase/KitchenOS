# Subsystem C — Phase C1: Foundation Models foundation + building blocks (Plan & Record)

Spec: `docs/superpowers/specs/2026-06-23-apple-intelligence-subsystem-c-design.md`.
Status: **implemented** (builds + `swift test` green; on-device verification pending).

## Goal

Introduce the on-device LLM layer (Apple Foundation Models) as a shared gateway for
Subsystem C, plus two proving features: recipe **summarization** and natural-language
**→ filters** feeding the existing recipe search. Maximize reuse; no backend changes.

## What was built

**Deployment target** raised to iOS 26 / macOS 26 (Foundation Models floor):
`KitchenOSKit/Package.swift` uses `platforms: [.macOS("26.0"), .iOS("26.0")]` (the `.v26`
enum case is unavailable in this toolchain — string platform versions are required);
`project.yml` deploymentTarget → 26.0.

**Shared components (KitchenOSKit):**
- `AI/RecipeAI.swift` — single Foundation Models gateway. `availability` maps
  `SystemLanguageModel.default.availability` → `AIAvailability` (with user-facing reasons);
  `isReady`; `summarize(RecipeDetail) -> String` and `parseQuery(String) -> RecipeQuery`
  via `LanguageModelSession`. C2 will add a tools-enabled session here; C3 reuses gating.
- `AI/RecipeQuery.swift` — `@Generable` filter struct `{ingredient?, protein?, cuisine?}`
  with a pure, unit-tested `matches(RecipeSummary)` predicate and `isEmpty`.
- `KitchenOSClient+Search.swift` — `recipes(matching:)` reuses `findRecipes` (empty
  ingredient → full index) + local protein/cuisine filtering.

**App Intents (KitchenOSKit/Intents):**
- `SummarizeRecipeIntent` — `RecipeEntity` → `recipeDetail` → `RecipeAI.summarize`;
  falls back with a message if `!RecipeAI.isReady`.
- `SmartFindRecipesIntent` — free-text `query` → `parseQuery` + `recipes(matching:)`;
  **degrades to `findRecipes(ingredient:)`** when Apple Intelligence is off. Returns
  `[RecipeEntity]` like `FindRecipesByIngredientIntent` so results chain into add-to-plan.

**App (KitchenOSSiri):**
- Root is now a `TabView` (Smart Search + existing Settings).
- `SmartSearchView` — availability banner + text field → parse/search → results; per-row
  on-device `Summarize`. The home for C2's chat later.
- `KitchenOSShortcuts` gains "Smart Find" and "Summarize" phrases (7 App Shortcuts total).

## Tests (deterministic, `swift test` — 16 green)

- `RecipeQueryTests` — `matches()` (ingredient/protein/cuisine, case-insensitive, empty
  matches all) and `@Generable` round-trip (`generatedContent` ↔ `init(_:)`).
- `RecipeSearchTests` — `recipes(matching:)` over `MockURLProtocol`: sends
  `?ingredient=…` and applies local protein/cuisine filtering.
- Not unit-tested (non-deterministic, needs Apple Intelligence): live `summarize`/
  `parseQuery` inference and availability gating — verified on-device.

## Verification

- `cd KitchenOSKit && swift build && swift test` → 16 passed.
- `xcodegen generate && xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build`
  → BUILD SUCCEEDED; metadata shows all 7 intents + 7 autoShortcuts + the `RecipeQuery` generable.
- On-device (pending): Smart Search "something with eggplant" → results; row → summary;
  Siri "Summarize a KitchenOS recipe" and "Find a KitchenOS recipe"; fallback when AI off.

## Reuse / cohesion into C2–C3

`RecipeAI` is the lone AI entry point; `RecipeQuery` + `matches` + `recipes(matching:)`
become C2's "find" `Tool`; `SmartSearchView` hosts C2's chat; C3 reuses availability and
may later add a backend protein/cuisine param or `IndexedEntity` indexing.
