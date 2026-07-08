# KitchenOS — Subsystem C: Apple Intelligence (Design Spec)

**Date:** 2026-06-23
**Status:** Implemented
**Builds on:** the Siri App Intents app (`KitchenOSSiri` + `KitchenOSKit`) and Plan A backend.

## Goal

Add native Apple-Intelligence capabilities to KitchenOS: on-device LLM features via the
Foundation Models framework, an on-device conversational meal-plan assistant, and deeper
Siri/semantic integration. Target Apple-Intelligence-capable devices only.

## Scope & sequence (3 phases, dependency-ordered)

- **C1 — Foundation Models foundation + building blocks.** A `RecipeAI` wrapper over
  `LanguageModelSession` (with availability handling), plus two focused features:
  (a) **recipe summarization** (RecipeDetail → a 2-sentence spoken/visible gist),
  (b) **natural-language → filters** (free text like "something spicy and quick" →
  a `@Generable` struct `{ingredient?, protein?, cuisine?}` that feeds the existing
  `/api/recipes` search). Establishes the on-device LLM layer everything else uses.
- **C2 — On-device meal-plan assistant.** A chat surface backed by a tools-enabled
  `LanguageModelSession`. Tools conform to `Tool` and call the existing backend
  (find recipes, read plan, add to plan w/ confirm) so the model plans over *real* data.
- **C3 — Deeper Siri / semantic search.** Adopt the iOS 27 **App Schemas** approach
  (successor to the `@AssistantIntent` macro — see Open Questions) and make
  `RecipeEntity` an **`IndexedEntity`** so Apple Intelligence can match recipes by
  meaning and answer questions over them. Largely independent of C1/C2.
  > **Update:** the "App Schemas" approach explored here was superseded during
  > implementation — the C3 plan (`docs/superpowers/plans/2026-06-23-siri-foundation-models-phase-c3.md`)
  > settled on **`IndexedEntity`** (via `CSSearchableIndex`/`attributeSet`) as the sole
  > mechanism for C3, not an `@AssistantIntent(schema:)`-based App Schemas domain.

## Constraints

- **Deployment target rises to iOS 26 / macOS 26** (Foundation Models floor). Existing
  App Intents code is unaffected. Gate FM types with `@available(iOS 26, macOS 26, *)`.
- All on-device: the Foundation Models model is local; no network, no API cost. Handle
  `SystemLanguageModel.default.availability` (`.deviceNotEligible`,
  `.appleIntelligenceNotEnabled`, `.modelNotReady`) with graceful fallbacks (e.g. C1's
  NL→filters can fall back to plain keyword search).
- The backend stays the source of truth for recipe data; the on-device model reasons and
  phrases, and reaches data via the existing Flask API (directly in C1's filter feed, via
  `Tool`s in C2).
- **Supersedes** the earlier spec's "AI placement / Foundation Models deferred" note —
  Foundation Models is now in scope (this is that Phase 3).

## Testing

- **Unit-testable (deterministic):** `@Generable` struct decoding from `GeneratedContent`,
  the NL-filter → `/api/recipes` query mapping, and `Tool` argument plumbing — via the
  existing `swift test` + mock patterns.
- **Not unit-testable:** actual model inference (non-deterministic, requires Apple
  Intelligence enabled). Verified on-device by running the app; availability fallbacks are
  unit-tested by injecting an unavailable model.

## Open questions (to research at each phase)

- **C3 App Schemas:** the `@AssistantIntent(schema:)` macro was generalized in the 27
  release (WWDC26 "App Schemas"). Confirm the current macro/protocol before building C3
  by introspecting the App Intents `.swiftinterface` (same method used for the API below).
- Whether a food/recipe **assistant schema domain** exists, or we expose intents generically.
- `IndexedEntity` exact requirements (`indexingKey`, association with `RecipeEntityQuery`).

## Verified Foundation Models API (Xcode 27 SDK, `@available(iOS 26, macOS 26, *)`)

Source: `FoundationModels.framework/.../arm64e-apple-ios.swiftinterface`.

```swift
// Session
final class LanguageModelSession {
    convenience init(model: SystemLanguageModel = .default,
                     tools: [any Tool] = [],
                     instructions: String? = nil)
    // plain text
    func respond(to prompt: String,
                 options: GenerationOptions = .init()) async throws -> Response<String>   // .content : String
    // structured
    func respond<Content: Generable>(to prompt: String,
                 generating type: Content.Type = Content.self,
                 includeSchemaInPrompt: Bool = true,
                 options: GenerationOptions = .init()) async throws -> Response<Content>    // .content : Content
}

// Availability
final class SystemLanguageModel: Sendable {
    static let `default`: SystemLanguageModel
    var availability: Availability      // .available | .unavailable(UnavailableReason)
    var isAvailable: Bool
    enum Availability { case available; case unavailable(UnavailableReason) }
    // UnavailableReason: .deviceNotEligible | .appleIntelligenceNotEnabled | .modelNotReady
}

// Structured output
@Generable(description: String? = nil) struct Foo { @Guide(description: "...") var bar: String }

// Tool calling
protocol Tool<Arguments, Output>: Sendable {
    associatedtype Arguments: ConvertibleFromGeneratedContent   // usually a @Generable struct
    associatedtype Output: PromptRepresentable                  // e.g. String
    var name: String { get }
    var description: String { get }
    func call(arguments: Arguments) async throws -> Output
}
```
