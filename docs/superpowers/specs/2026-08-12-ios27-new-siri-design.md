# KitchenOS — iOS 27 New Siri + On-Device Store (Design Spec)

**Date:** 2026-08-12
**Status:** Ready
**Builds on:** Subsystem C (`RecipeAI`, `MealPlanAssistant`, `IndexedEntity` donation) and the
converged multiplatform `KitchenOSSiri` app. Companion plan: `~/.claude/plans/proud-baking-koala.md`
(approved 2026-08-12); phase plans to follow in `docs/superpowers/plans/`.

## Goal

Talk to KitchenOS through the new Siri (iOS 27, Siri AI) in both directions — ask (recipes,
meal plan, inventory, suggestions) and act (add to plan, add inventory) — and put the app on
the fully-on-device trajectory: Siri answers from an on-phone store, the Mac becomes a sync
peer rather than a hard dependency. This is also the recorded answer to the daily-driver
audit's open **Decision D** ("freeze the native app?"): **keep investing** — the native app
is the only possible Siri surface.

Selene follows as a separate later phase in its own repos (thin sketch at the end); KitchenOS
leads and proves the patterns.

## SDK introspection findings (Xcode 27 / iOS 27.0 SDK, verified 2026-08-12)

Method: grep of `AppIntents`, `CoreSpotlight`, `FoundationModels` `.swiftinterface`s in
`iPhoneOS27.0.sdk` — same method as the C3 scope finding. These are **pinned facts**, not
press claims:

1. **`IndexedEntityQuery` is real and exactly as hoped** (`AppIntents.swiftinterface:2467`):
   `reindexEntities(for: [Entity.ID], indexDescription: CSSearchableIndexDescription)` and
   `reindexAllEntities(indexDescription:)`, constrained to `Entity: IndexedEntity`. This is
   the system-driven reindex hook the iOS-26 build deferred.
2. **There is NO public multi-turn conversation API for third-party intents.** The only
   conversation machinery (`_ModelDelegationIntent` macro with `conversationIdentifier`,
   `_ModelDelegationFeatures.systemAssistant/.visualIntelligence/…`) is underscored and
   `@_documentation(visibility: internal)` — Apple-reserved. **Consequence:** AskKitchenOS
   multi-turn is built app-side: a session store keyed on nothing (singleton + idle timeout),
   not on a system conversation token.
3. **There is NO token-streaming intent result.** "Streaming" in iOS 27 App Intents is
   `LongRunningIntent : ProgressReportingIntent` (`performBackgroundTask(options:operation:)`,
   iOS 27) plus snippet views (`SnippetIntent`, `requestConfirmation(snippetIntent:)`, iOS 26+).
   `LanguageModelSession.streamResponse(to:)` → `ResponseStream<String>` is public and fine —
   but its consumer is in-app UI, not Siri dialog. **Consequence:** Siri replies stay
   buffered dialog; we adopt `LongRunningIntent` so Siri shows progress during tool runs.
4. **App Schemas (`AppSchema`, `@AppIntent(schema:)`, `@AppEntity(schema:)`) are public**, and
   the domain sweep still returns **zero** hits for `food|recipe|meal|cook|grocery` — the C3
   decision (IndexedEntity, no assistant schema) stands for KitchenOS.
5. **A `journal` App Schema domain now exists** (`AppSchema.Intent("journal")`:
   Create/Search/Update/Delete JournalEntry + `CreateJournalAudioEntryIntent`; `JournalEntity`
   in AssistantSchemas). Irrelevant to KitchenOS; **directly relevant to the Selene phase** —
   recorded there.
6. `LanguageModel` protocol, `LanguageModelCapabilities`, `LanguageModelExecutor`, and
   `LanguageModelError.contextSizeExceeded(contextSize:tokenCount:)` are public — the tier
   ladder (on-device → PCC → BYOK) has the seams LumenKit's `GenerationTier` expects.
   `ContextOptions`/`reasoningLevel` now flows through a `DynamicProfile` builder
   (`FoundationModels.swiftinterface:707`) — note for the Lumen repo, whose `PCCGenerator`
   uses the older WWDC26-319 shape.
7. `_CoreSpotlight_FoundationModels` overlay is UTType-resolution plumbing only — not a
   semantic-QA API; nothing to adopt.
8. "View Annotations API" (press claim) has no matching public surface in the AppIntents
   interface; closest is the snippet-intent machinery. Treated as N/A.

## Scope & sequence

### Slice 1 — iOS 27 floor + new-Siri upgrade (Mac-backed)

- **S1.1 Floor raise 26 → 27.** `project.yml` `deploymentTarget` and
  `KitchenOSKit/Package.swift` `platforms` → `"27.0"`. No `@available` sweep exists (zero
  annotations in either target). Remove the now-false "requires 27 — future enhancement"
  comment in `RecipeEntity.swift`. Doc sweep: ROADMAP, API.md, CLAUDE.md floor references.
- **S1.2 Ingredient keywords in the Spotlight donation** (ROADMAP "pending polish" (a)).
  Backend: extend the already-gated `GET /api/recipes` with `include_ingredients=1`
  (reuses `get_recipe_index(…, include_ingredients=True)` + `_recipe_ingredient_cache`;
  **no new route**, `KNOWN_UNGATED` untouched). Swift: `KitchenOSClient.allRecipes(includeIngredients:)`
  (`RecipeSummary.ingredientItems` already decodes it), fold into `attributeSet.keywords`,
  `RecipeIndexer.reindexAll` fetches with ingredients.
- **S1.3 System-driven reindex** (ROADMAP (b), slice-1 half). `RecipeEntityQuery` conforms to
  `IndexedEntityQuery` (keeps `EntityStringQuery`), delegating to `RecipeIndexer`. Launch-time
  reindex + Settings button stay as belt-and-suspenders. Honest caveat until S2: freshness =
  last run with the Mac reachable.
- **S1.4 AskKitchenOS multi-turn + progress.** New `AI/AssistantSessionStore.swift`:
  `@MainActor` singleton holding the live `MealPlanAssistant` (which owns the
  `LanguageModelSession` + transcript) across intent invocations, idle-discard ~5 min
  (finding 2 rules out a system token — singleton is the design, not a fallback).
  `AskKitchenOSIntent` adopts `LongRunningIntent` + progress so Siri shows activity during
  tool calls (finding 3). Optional polish: a `SnippetIntent` recipe card on proposals.
  The propose → `requestConfirmation` → `confirm` write path is unchanged.
- **S1.5 App Shortcuts phrase review + on-device verification.** AskKitchenOS becomes the
  flagship phrase set; verify on device whether new Siri still requires `.applicationName`
  in every phrase (behavioral, not SDK-answerable). Full demo script in Testing.
- **S1.6 Docs + decision record.** Decision D → keep investing (audit doc + ROADMAP); strike
  polish gaps (a)/(b); API.md Siri section.

### Slice 2 — On-phone SwiftData store (offline Siri; queued writes)

New `KitchenOSKit/Sources/KitchenOSKit/Store/`:

- **S2.1 Models + container.** `@Model` `LocalRecipe` (name = id; index fields + `detailJSON`
  blob so Summarize/Nutrition answer offline), `LocalInventoryItem`, `LocalMealWeek`/`Day`,
  `PendingOperation`, `SyncState`. `KitchenStore`: `ModelActor` over the container
  (Application Support; in-memory for tests); converts to/from the existing structs so
  nothing above the data layer changes types.
- **S2.2 `KitchenDataSource` protocol + `LocalFirstDataSource`.** Protocol = exactly today's
  read surface + `addRecipe`/`addInventoryItem`. Reads serve from `KitchenStore`, falling
  through to `KitchenOSClient` when a domain never synced. Writes: optimistic local apply +
  enqueue + immediate flush attempt. Injected into `MealPlanAssistant`, the 5 FM tools, the
  non-AI intents, and `RecipeEntityQuery` (offline entity resolution). Siri inventory adds
  **omit `location`** (the `NewInventoryItem` optional-location invariant — a defaulted
  location would fabricate a user confirmation).
- **S2.3 `SyncEngine` + cadence.** `syncAll()`: flush queue **first**, then full-refresh pull
  (recipes+ingredients, inventory, current+next week — corpus is small, the API has no
  `updated_since`, deltas are not worth their failure modes), then reindex Spotlight **from
  the local store** (repoint `RecipeIndexer` — reindex stops needing the Mac). Triggers:
  launch, `scenePhase == .active`, `BGAppRefreshTask` (`com.kitchenos.siri.refresh`;
  identifiers + background modes go in committed `Info-iOS.plist`, never the regenerated
  project). Design stays correct with foreground-only sync — BG refresh is an optimization,
  free-team 7-day expiry is the operational reality.
- **S2.4 `QueueFlusher` + offline behavior.** FIFO ops replayed against **fresh** server
  state — for meal-plan adds that means a fresh GET→modify→PUT at flush time, never a stored
  `MealPlan` blob (the stale-full-plan-PUT clobber is this repo's most-defended invariant).
  Capped backoff; permanent 4xx failures surface in Settings, never silently dropped.
  Conflict policy: slot-level last-writer-wins (household of one; documented). Offline
  dialogs: answers append "as of <relative time>" when stale > ~1 day; writes confirm
  "Added — I'll sync it to your Mac when it's reachable."
- **S2.5 Local `MealSuggester`.** Deterministic port of `lib/meal_suggester.py`'s
  ingredient-overlap + macro-gap ranking over `KitchenStore`; the FM session frames it
  conversationally. `SuggestMealTool`/`SuggestForMealPlanIntent` re-point (API fallback when
  the store is empty). `/api/suggest-meal` stays on the server for the web planner.

**Stays Mac-only (by design):** extraction pipeline, receipts/CSA ingest, nutrition
backfill, shopping-list generation + Reminders handoff, prep tasks, the web planner, all
generated vault views.

## Security

- **Set `KITCHENOS_API_TOKEN` for real.** `require_token` is a no-op today (env unset).
  Generate a token into the git-ignored `.env`, restart `com.kitchenos.api`, store it on the
  phone via the existing `KeychainCredentialStore` (Settings field + Bearer header already
  wired). Localhost stays exempt — Mac app and web UI unaffected.
- **Gate what Siri writes** (with S2): move `/api/inventory/add|remove|update` behind
  `@require_token` and delete them from `KNOWN_UNGATED` (the pinned auth test enforces the
  bookkeeping both directions). Any new route ships gated; S1.2 adds none.
- **Transport:** Tailscale (WireGuard) is the encryption; ATS `NSAllowsArbitraryLoads` stays,
  with its hard-won comment (re-adding `NSAllowsLocalNetworking` breaks the Tailscale-IP
  call). Future hardening option, not in scope: `tailscale cert` + HTTPS.

## Testing

- **Deterministic (`swift test`):** ingredient keywords in `attributeSet`;
  `include_ingredients` param encoding (MockURLProtocol); session-store idle-discard and
  reuse semantics; proposal flow against a fake client; S2 — store round-trips
  (in-memory container), `LocalFirstDataSource` local-hit / fall-through / offline-stale,
  `SyncEngine` flush-before-pull ordering, **the clobber test** (enqueue add → mutate fake
  server → flush → the PUT contains both changes), `QueueFlusher` retry/backoff/permanent
  failure, `MealSuggester` parity against the Python fixtures.
- **Backend (pytest):** `include_ingredients=1`; auth-test updates for newly gated routes.
- **Metadata gate (every slice):** `xcodegen generate && xcodebuild … CODE_SIGNING_ALLOWED=NO`
  then assert all 9 intents in `Metadata.appintents/extract.actionsdata`.
- **On-device demo script (not simulable — Siri AI, semantic index, BG tasks):**
  1. "Ask KitchenOS what's on my meal plan this week" — spoken answer, real data.
  2. Follow up without re-invoking: "what about Thursday dinner?" — session continuity.
  3. "Suggest something high-protein with the chicken I have" — progress during tool calls.
  4. "Add it to Thursday dinner" — spoken confirmation → row visible on the web planner.
  5. Spotlight fuzzy search, then an ingredient appearing in no title — S1.2 proof.
  6. (S2) Airplane mode: repeat 1/3/5 from the local store; 4 → queued-write dialog;
     reconnect → the add lands and no scale on the week is lost.
  7. Settings: token present, "Sync now", last-synced display, `/health` probe.

## Risks

1. **Beta API drift** — the load-bearing shapes are now pinned by introspection (above);
   re-verify on each Xcode 27 beta bump. AskKitchenOS remains correct with plain buffered
   dialog if `LongRunningIntent` misbehaves.
2. **Free-team 7-day expiry** — nothing may *require* background execution.
3. **Stale-write clobber** — op-log queue + dedicated clobber test; never PUT queued state.
4. **Spotlight semantic-index opacity** — keep the manual reindex button; S2 removes the
   Mac dependency from reindexing.
5. **`project.yml` regeneration** — build settings only in `project.yml`; BG identifiers and
   modes only in committed `Info-iOS.plist`.
6. **Answer-quality honesty** — `fit_*` and some nutrition fields are flagged inference
   (`needs_review`); voice answers must not over-assert them.

## Later phase — Selene (separate repos; thin by intent)

Gated on the SeleneApp migration (selene roadmap #1). Order: Tier-1 nav intents + Spotlight
donation of title/essence only → `AskSeleneIntent` over bearer-authed `GET /api/search` →
LumenKit in-process retrieval later (LumenKit has no retrieval API today; embeddings stay
server-side on nomic). Deltas this spec adds to the existing Selene docs:

1. Reuse the S1.4 patterns proven here (session store, `LongRunningIntent`, `.voice`
   instruction split) as working code, not fresh research.
2. **Finding 5 (journal App Schema domain) is new information for Selene:** evaluate
   `@AppIntent(schema:)`/`@AppEntity(schema:)` adoption for note capture/search intents
   (`CreateJournalEntryIntent`, `SearchJournalEntriesIntent`, audio entries) before
   defaulting to plain `IndexedEntity` — this may give Siri-native note capture for free.
3. Compose LumenKit's `GenerationTier` for the ask path (on-device → PCC → BYOK); verify
   whether FM `Tool`s ride along across tiers or only final synthesis escalates. Note
   finding 6's `ContextOptions`/`DynamicProfile` shape change for `PCCGenerator`.
4. `CaptureThoughtIntent` → `POST /webhook/api/drafts` (bearer; capture never depends on
   inference) with the same pending-queue treatment — a thought spoken offline is never lost.
