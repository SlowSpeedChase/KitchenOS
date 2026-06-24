# Build Log — Siri / App Intents

Running record of autonomous/assisted build sessions. Newest entries at the top.
Each entry: what ran, what passed/failed, what committed, and anything that blocked.

## How this is used

- **Plan A (overnight-runnable):** `docs/superpowers/plans/2026-06-21-siri-backend-phase0.md`
- The executing run appends one section per task: tests run + result, commit hash,
  and a STOP note if it hits anything outside its scoped permissions.
- Branch: `siri-app-intents`. Nothing is pushed.

---

## Session log

### 2026-06-21 — Plan A (backend Phase 0), assisted hands-off run

**Done & committed (clean, isolated — only `api_server.py` + new test files):**
- Task 1 — ingredient filter on `GET /api/recipes?ingredient=` — `8b7d922`. 4/4 tests pass.
- Task 2 — optional bearer-token auth (`require_token`, localhost-exempt) on the 5
  Siri-facing routes — `6b2edb5`. 5/5 tests pass.
- Targeted regression (api + recipes + recipe_index): **69 passed.**

**Paused before Task 3 (docs) — needs a human decision:**
- The working tree was **already dirty before this session**: ~15 files carry an
  uncommitted **path-migration** changeset (`~/KitchenOS/` & `~/GitHub/KitchenOS/` →
  `~/Dev/KitchenOS/`) across `CLAUDE.md`, `README.md`, `batch_extract.py`,
  `generate_meal_plan.py`, `ingest_receipts.py`, `ops/*.plist`, `requirements.txt`,
  `sync_calendar.py`, `scripts/update_dashboard_canvas.py`. **Not created by this run.**
- My Task 3 doc edits to `CLAUDE.md` (ingredient param + `KITCHENOS_API_TOKEN`) are
  currently **intermingled** with that pre-existing `CLAUDE.md` path edit — so I did
  NOT `git add` it, to avoid bundling unrelated work under a Siri commit.

**Full-suite failures (5) — INVESTIGATED: all pre-existing in committed code, NOT
caused by Plan A or by the uncommitted changeset:**
- Root cause: a **"snack" meal-slot** added to the data model without updating older
  tests.
  - `test_ics_generator` (3): `format_day_summary` now emits `B / L / S / D`; tests
    assert the old `B / L / D`. `lib/ics_generator.py` is unmodified → change is committed.
  - `test_sync_calendar` (1): same snack staleness in `collect_all_days`. The only
    working-tree edit to `sync_calendar.py` is a `setproctitle(...)` line in `__main__`,
    which cannot affect the tested function.
  - `test_normalizer` (1): module and test both unmodified → committed behavior.
- The uncommitted changeset is **path-migration + `setproctitle` (`__main__` blocks
  only)** — it does not touch any tested function.
- Recommendation: these stale tests should be fixed in a separate cleanup, independent
  of the Siri work.

**Resolution (same session):**
- Pre-existing changeset committed on its own — `6082fb3` "chore: migrate paths to
  ~/Dev and set LaunchAgent proctitles" (peeled my doc edits out of CLAUDE.md first so
  they wouldn't bundle).
- Task 3 docs committed clean — `835b08c` "docs: document ingredient filter and
  KITCHENOS_API_TOKEN".
- Stale snack-slot tests fixed — `test: update stale tests for snack slot, MealEntry,
  and unwrapped unknowns`. **Full suite now: 665 passed, 1 skipped, 0 failed.**

**Plan A: COMPLETE.** All three tasks committed; tree clean; full suite green.

### 2026-06-21 — Plan B Phase 1 (KitchenOSKit Swift package), executed on the Mac

Toolchain: Swift 6.4, Xcode 27, macOS 27. All 7 tasks built + committed; `swift test`
green (9 tests).

- Task 1 — package skeleton + CredentialStore (Keychain/in-memory) + KitchenOSConfig.
- Task 2 — Codable models (RecipeSummary/Detail, MealPlan/Day/SlotValue, Suggestion).
- Task 3 — WeekDate ISO week-id helper.
- Task 4 — async KitchenOSClient + MockURLProtocol tests (ingredient query, bearer, HTTP error).
- Task 5 — DayOfWeek/MealSlot AppEnums + RecipeEntity (EntityStringQuery).
- Task 6 — five App Intents. **Platform floor raised to macOS 15 / iOS 18** (tools 6.0,
  Swift 5 language mode) to use the non-deprecated
  `requestConfirmation(actionName:dialog:)` for the add-to-plan confirmation gate.
- Task 7 — AppShortcutsProvider with Siri phrases.

**Plan B Phase 1: COMPLETE** (builds clean, tests green).

### 2026-06-21 — Plan B Phase 2 scaffold (XcodeGen)

- Installed `xcodegen` (brew). Authored `project.yml` → multiplatform app
  `KitchenOSSiri` (macOS + iOS destinations) linking the local `KitchenOSKit`
  package; custom `Info.plist` with ATS exceptions for the http Tailscale host;
  `SettingsView` (base URL + Keychain token) + `@main` app entry.
- `xcodegen generate` → `KitchenOSSiri.xcodeproj` (gitignored per `*.xcodeproj/`;
  regenerate with `xcodegen generate`). project.yml is the committed source of truth.
- **macOS build verified:** `xcodebuild … -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO`
  → BUILD SUCCEEDED, App Intents metadata extracted.
- Metadata-processor fixes (stricter than the compiler): exhaustive
  `caseDisplayRepresentations` dict literals; removed the `String`-param placeholder
  from the Find shortcut phrase (only AppEntity/AppEnum params allowed in phrases).

### 2026-06-22 — On-device bring-up (iPad) — WORKING

Signed + installed on the iPad (iPad16,10, iOS 27). Sequence of real-device fixes:

1. **Install failed — MissingBundleExecutable:** custom Info.plist lacked
   `CFBundleExecutable` (+ other keys Xcode injects). Added them.
2. **No shortcuts appeared:** `AppShortcutsProvider` was in the KitchenOSKit
   package; Apple only harvests App Shortcuts from the **app target**. Moved it →
   `autoShortcuts` extracted (5).
3. **Spotlight text-entry focus:** added `requestValueDialog` to the ingredient param.
4. **"Can't reach" (1):** `@AppStorage` never persists its UI default, so
   `KitchenOSConfig.resolved()` fell back to **localhost** on the iPad. Made the
   default **platform-aware** → Tailscale IP `100.111.6.10:5001` on iOS.
5. **"Can't reach" (2) — the real one:** ATS. Including `NSAllowsLocalNetworking`
   makes iOS 10+ **ignore** `NSAllowsArbitraryLoads`, blocking the cleartext http
   call to the Tailscale IP ("ATS requires a secure connection"). Removed it;
   `NSAllowsArbitraryLoads` alone now permits it. Also added
   `NSLocalNetworkUsageDescription`.
   - Added an in-app **Test connection** button (raw NSError) — this is what
     surfaced the precise ATS error.

**RESULT: Siri on the iPad found chicken recipes.** Full path verified:
iPad → Tailscale (`100.111.6.10:5001`) → Flask ingredient search → spoken result.

**Still to verify (manual):** the other four intents by voice — GetMealPlan,
SuggestForMealPlan, AddRecipeToMealPlan (confirm-before-write), GetRecipeNutrition;
and the find→add chain. Set `KITCHENOS_API_TOKEN` + app token only if you want remote
auth (localhost is exempt; the iPad sends the token if set).

### 2026-06-23 — Subsystem C, Phase C1 (Foundation Models) — implemented

Plan: `docs/superpowers/plans/2026-06-23-siri-foundation-models-phase-c1.md`.
Verified API first by introspecting the Xcode 27 `FoundationModels.swiftinterface`.

- Raised deployment target to **iOS 26 / macOS 26** (FM floor). Note: PackageDescription
  has no `.v26` enum case in this toolchain — used string platforms `.macOS("26.0")`.
- `RecipeAI` (FM gateway: availability + `summarize` + `parseQuery`), `@Generable`
  `RecipeQuery`, and `KitchenOSClient.recipes(matching:)` (reuses `findRecipes`).
- `SummarizeRecipeIntent` + `SmartFindRecipesIntent` (smart find degrades to plain
  ingredient search when AI is off). App root → `TabView`; new `SmartSearchView`.
- **16 tests green**; iOS build SUCCEEDED; metadata = 7 intents + 7 autoShortcuts.

**On-device verification pending** (needs Apple Intelligence enabled): Smart Search tab,
Siri "Summarize a KitchenOS recipe" / "Find a KitchenOS recipe", and the AI-off fallback.

**Next:** C2 (on-device conversational meal-plan assistant via tools-enabled session) and
C3 (App Schemas + IndexedEntity semantic search) — research the iOS 27 App Schemas API
first (the `@AssistantIntent` macro changed in the 27 release).
