# iOS 27 New Siri — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise KitchenOS to the iOS 27 floor and adopt the new Siri surface — system-driven Spotlight reindex, ingredient keywords in the semantic index, and a multi-turn AskKitchenOS session — over the existing Mac-backed client.

**Architecture:** Siri → App Intent → on-device `LanguageModelSession` + FM Tools → `KitchenOSClient` (unchanged topology). New pieces: an `IdleSessionStore` that keeps one `MealPlanAssistant` alive across intent invocations (iOS 27 exposes no public conversation token — SDK introspection, spec §findings 2), `IndexedEntityQuery` conformance for system-driven reindex, and one backend query param. Slice 2 (on-phone store) is a separate plan.

**Tech Stack:** Swift 6.4 / Xcode 27 (SPM package `KitchenOSKit` + XcodeGen app `KitchenOSSiri`), XCTest, Flask + pytest.

**Spec:** `docs/superpowers/specs/2026-08-12-ios27-new-siri-design.md`

## Global Constraints

- Deployment floor after Task 1: **iOS 27.0 / macOS 27.0** — no `@available(iOS 27…)` gates needed anywhere.
- `.xcodeproj` is gitignored and regenerated — build settings go in `project.yml` ONLY; never the Xcode GUI.
- `AppShortcutsProvider` MUST stay in the app target (`KitchenOSSiri/Sources/KitchenOSShortcuts.swift`) — the metadata processor doesn't harvest App Shortcuts from packages.
- Swift tests: `cd KitchenOSKit && swift test` (72 passing at baseline). Backend tests: `.venv/bin/python -m pytest tests/<file> -v` from the worktree root (venv lives in the main checkout: use `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python`).
- Metadata gate (run after any intent/shortcut change):
  `xcodegen generate && xcodebuild -project KitchenOSSiri.xcodeproj -scheme KitchenOSSiri -destination 'generic/platform=iOS' -derivedDataPath .build-xcode CODE_SIGNING_ALLOWED=NO build` then check `.build-xcode/Build/Products/Debug-iphoneos/KitchenOS.app/Metadata.appintents/extract.actionsdata` lists all 9 intents.
- Commit format: `type: short description` + the Claude co-author trailer (see repo CLAUDE.md).
- Editing `api_server.py` requires a `com.kitchenos.api` LaunchAgent restart **at deploy time on the Mac** (main checkout serves prod; the worktree edit doesn't go live until merged + restarted).

---

### Task 1: Floor raise to iOS 27 / macOS 27

**Files:**
- Modify: `project.yml` (deploymentTarget block, ~line 13)
- Modify: `KitchenOSKit/Package.swift` (platforms line)
- Modify: `KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift:41-44` (stale comment)

**Interfaces:**
- Consumes: nothing.
- Produces: the 27.0 floor every later task assumes (no `@available` gates needed).

- [ ] **Step 1: Raise the two floors**

In `project.yml`, change:

```yaml
    deploymentTarget:
      macOS: "27.0"
      iOS: "27.0"
```

In `KitchenOSKit/Package.swift`, change the platforms line to:

```swift
    platforms: [.macOS("27.0"), .iOS("27.0")],
```

(Keep the existing string-literal form — this toolchain's PackageDescription has no `.v27` enum case; same reason the 26 floor used strings, per `docs/history/SIRI_BUILD_LOG.md:126`.)

- [ ] **Step 2: Replace the stale 27-gated comment**

In `RecipeEntity.swift`, replace the comment block at lines 41–44 (beginning `// Note: RecipeEntity conforms to IndexedEntity`) with:

```swift
// RecipeEntity conforms to IndexedEntity (semantic index) above. Indexing is driven both
// manually via RecipeIndexer (app launch + Settings button) and by the system through the
// IndexedEntityQuery conformance below (iOS/macOS 27 floor).
```

(The conformance it references lands in Task 4 — the comment is accurate once this branch merges as a whole; if committing this task alone bothers the reviewer, phrase it "…and, from Task 4, by the system…" — but the branch merges atomically.)

- [ ] **Step 3: Verify package builds and tests pass**

Run: `cd KitchenOSKit && swift build && swift test 2>&1 | tail -3`
Expected: `Build complete!`, `Executed 72 tests, with 0 failures`.

- [ ] **Step 4: Verify the app builds and intents extract**

Run from worktree root:

```bash
xcodegen generate
xcodebuild -project KitchenOSSiri.xcodeproj -scheme KitchenOSSiri -destination 'generic/platform=iOS' -derivedDataPath .build-xcode CODE_SIGNING_ALLOWED=NO build 2>&1 | tail -3
python3 -c "import json; d=json.load(open('.build-xcode/Build/Products/Debug-iphoneos/KitchenOS.app/Metadata.appintents/extract.actionsdata')); print(len(d['actions']), 'actions')"
```

Expected: `BUILD SUCCEEDED`; 9 actions.

- [ ] **Step 5: Commit**

```bash
git add project.yml KitchenOSKit/Package.swift KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift
git commit -m "feat: raise deployment floor to iOS 27 / macOS 27"
```

---

### Task 2: Backend — `include_ingredients=1` on GET /api/recipes

**Files:**
- Modify: `api_server.py` (`api_recipes()`, ~line 409)
- Test: `tests/test_api_recipes_ingredient.py`

**Interfaces:**
- Consumes: existing `_recipe_ingredient_cache` / `get_recipe_index(path, include_ingredients=True)` (`api_server.py:88-90`, `lib/recipe_index.py:33`).
- Produces: `GET /api/recipes?include_ingredients=1` → full index, each row carrying `ingredient_items: [str]`. Task 3's Swift client depends on this exact param name and shape. Route stays `@require_token`-gated; `KNOWN_UNGATED` untouched.

- [ ] **Step 1: Make the fake index honor the flag, then write the failing tests**

In `tests/test_api_recipes_ingredient.py`, replace the monkeypatched lambda inside `_reset_caches_and_index` so the fake behaves like the real loader (only includes `ingredient_items` when asked):

```python
    def fake_index(path, include_ingredients=False):
        if include_ingredients:
            return FAKE_INDEX
        return [{k: v for k, v in r.items() if k != "ingredient_items"} for r in FAKE_INDEX]

    monkeypatch.setattr(api_server, "get_recipe_index", fake_index)
```

Append two tests:

```python
def test_include_ingredients_param_returns_ingredient_items(client):
    resp = client.get("/api/recipes?include_ingredients=1")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 3
    assert all("ingredient_items" in r for r in rows)


def test_default_index_omits_ingredient_items(client):
    resp = client.get("/api/recipes")
    assert resp.status_code == 200
    assert all("ingredient_items" not in r for r in resp.get_json())
```

- [ ] **Step 2: Run to verify the new test fails**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_api_recipes_ingredient.py -v`
Expected: `test_include_ingredients_param_returns_ingredient_items` FAILS (`ingredient_items` missing — the param is ignored today); the other five PASS.

- [ ] **Step 3: Implement the param**

In `api_server.py` `api_recipes()`, insert between the `ingredient` branch and the plain-index branch (i.e. right after the `if ingredient:` block returns, before `if _recipe_cache["data"] is None`):

```python
    if request.args.get("include_ingredients", "").strip() in ("1", "true"):
        cache = _recipe_ingredient_cache
        if cache["data"] is None or (now - cache["timestamp"]) > RECIPE_CACHE_TTL:
            cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH, include_ingredients=True)
            cache["timestamp"] = now
        return jsonify(cache["data"])
```

Also update the route docstring's "Optional query param" section to document both params.

- [ ] **Step 4: Run the file and the auth suite**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_api_recipes_ingredient.py tests/test_api_auth.py -v 2>&1 | tail -5`
Expected: all PASS (the route was already gated; no `KNOWN_UNGATED` change).

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_api_recipes_ingredient.py
git commit -m "feat: include_ingredients=1 returns the full recipe index with ingredients"
```

---

### Task 3: Swift — ingredient keywords into the Spotlight donation

**Files:**
- Modify: `KitchenOSKit/Sources/KitchenOSKit/KitchenOSClient+Search.swift`
- Modify: `KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift` (entity fields + attributeSet)
- Modify: `KitchenOSKit/Sources/KitchenOSKit/RecipeIndexer.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/RecipeSearchTests.swift`, `KitchenOSKit/Tests/KitchenOSKitTests/RecipeEntityIndexTests.swift`

**Interfaces:**
- Consumes: Task 2's `include_ingredients=1`; `RecipeSummary.ingredientItems` (already decodes `ingredient_items` — `Models.swift:8,16`); internal `KitchenOSClient.getJSON(_:)` helper; `MockURLProtocol` + `KitchenOSClient.mock()` test pattern.
- Produces: `KitchenOSClient.allRecipes(includeIngredients: Bool) async throws -> [RecipeSummary]`; `RecipeEntity.ingredientItems: [String]?` folded into `attributeSet.keywords`. Task 4's reindex delegates to the updated `RecipeIndexer.reindexAll`.

- [ ] **Step 1: Write the failing client test**

Append to `RecipeSearchTests.swift`:

```swift
    func testAllRecipesIncludeIngredientsSendsParamAndDecodes() async throws {
        MockURLProtocol.handler = { request in
            let comps = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!
            XCTAssertEqual(comps.path, "/api/recipes")
            XCTAssertTrue(comps.queryItems?.contains(URLQueryItem(name: "include_ingredients", value: "1")) ?? false)
            let body = #"[{"name": "Butter Chicken", "cuisine": "Indian", "protein": "chicken", "ingredient_items": ["chicken thighs", "garam masala"]}]"#
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    Data(body.utf8))
        }
        let recipes = try await KitchenOSClient.mock().allRecipes(includeIngredients: true)
        XCTAssertEqual(recipes.first?.ingredientItems, ["chicken thighs", "garam masala"])
    }
```

- [ ] **Step 2: Run to verify it fails to compile**

Run: `cd KitchenOSKit && swift test 2>&1 | tail -5`
Expected: compile error — `allRecipes(includeIngredients:)` does not exist.

- [ ] **Step 3: Implement the client method**

In `KitchenOSClient+Search.swift`, replace the existing `allRecipes()` with:

```swift
    /// The full recipe index. With `includeIngredients`, each summary carries its
    /// `ingredient_items` (feeds the Spotlight keyword donation).
    func allRecipes(includeIngredients: Bool = false) async throws -> [RecipeSummary] {
        guard includeIngredients else { return try await findRecipes(ingredient: "") }
        var comps = URLComponents(url: baseURL.appendingPathComponent("/api/recipes"),
                                  resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "include_ingredients", value: "1")]
        return try await getJSON(comps.url!)
    }
```

- [ ] **Step 4: Write the failing entity tests**

Append to `RecipeEntityIndexTests.swift`:

```swift
    func testAttributeSetFoldsIngredientsIntoKeywords() {
        let e = RecipeEntity(id: "Butter Chicken", cuisine: "Indian", proteinName: "chicken",
                             ingredientItems: ["chicken thighs", "garam masala"])
        XCTAssertEqual(e.attributeSet.keywords,
                       ["Indian", "chicken", "chicken thighs", "garam masala"])
        XCTAssertEqual(e.attributeSet.contentDescription, "Indian · chicken")
    }

    func testAttributeSetIngredientsOnlyStillSetsKeywords() {
        let e = RecipeEntity(id: "Mystery Dish", ingredientItems: ["tofu"])
        XCTAssertEqual(e.attributeSet.keywords, ["tofu"])
        XCTAssertNil(e.attributeSet.contentDescription)
    }
```

- [ ] **Step 5: Run to verify they fail to compile**

Run: `swift test 2>&1 | tail -5`
Expected: compile error — no `ingredientItems` parameter.

- [ ] **Step 6: Implement the entity change**

In `RecipeEntity.swift`, add the stored property and thread it through both inits:

```swift
    public var ingredientItems: [String]?

    public init(id: String, cuisine: String? = nil, proteinName: String? = nil,
                ingredientItems: [String]? = nil) {
        self.id = id; self.cuisine = cuisine; self.proteinName = proteinName
        self.ingredientItems = ingredientItems
    }

    public init(_ summary: RecipeSummary) {
        self.id = summary.name; self.cuisine = summary.cuisine; self.proteinName = summary.protein
        self.ingredientItems = summary.ingredientItems
    }
```

Replace the facets block inside `attributeSet` with:

```swift
        let facets = [cuisine, proteinName].compactMap { $0 }
        if !facets.isEmpty {
            set.contentDescription = facets.joined(separator: " · ")
        }
        let keywords = facets + (ingredientItems ?? [])
        if !keywords.isEmpty {
            set.keywords = keywords
        }
```

In `RecipeIndexer.swift`, change the fetch line to:

```swift
        let recipes = try await client.allRecipes(includeIngredients: true)
```

- [ ] **Step 7: Run the full suite**

Run: `swift test 2>&1 | tail -3`
Expected: `Executed 75 tests, with 0 failures` (72 baseline + 3 new).

- [ ] **Step 8: Commit**

```bash
git add KitchenOSKit
git commit -m "feat: donate ingredient keywords to the Spotlight semantic index"
```

---

### Task 4: System-driven reindex — `IndexedEntityQuery` conformance

**Files:**
- Modify: `KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift` (extension at end of file)

**Interfaces:**
- Consumes: `RecipeIndexer.reindexAll()` (Task 3's version); `CSSearchableIndexDescription` (CoreSpotlight, already imported).
- Produces: the OS now refreshes the recipe index on its own schedule. No caller-visible API change.

SDK-pinned signatures (spec §findings 1, `AppIntents.swiftinterface:2467-2469`):
`reindexEntities(for: [Entity.ID], indexDescription: CSSearchableIndexDescription)` and `reindexAllEntities(indexDescription:)`.

- [ ] **Step 1: Add the conformance**

Append to `RecipeEntity.swift`:

```swift
// System-driven reindex hooks (iOS/macOS 27): the OS calls these on its own schedule.
// The corpus is small (~252 recipes) and the server returns the full index in one call,
// so a targeted per-id reindex would cost the same round-trip — both hooks do a full pass.
extension RecipeEntityQuery: IndexedEntityQuery {
    public func reindexAllEntities(indexDescription: CSSearchableIndexDescription) async throws {
        try await RecipeIndexer.reindexAll()
    }

    public func reindexEntities(for identifiers: [String],
                                indexDescription: CSSearchableIndexDescription) async throws {
        try await RecipeIndexer.reindexAll()
    }
}
```

If the compiler rejects these signatures (beta drift since the 2026-08-12 introspection), re-grep the current SDK's `AppIntents.swiftinterface` for `IndexedEntityQuery` and match what it declares — do not guess.

- [ ] **Step 2: Build, test, metadata gate**

Run: `cd KitchenOSKit && swift build && swift test 2>&1 | tail -3`
Expected: 75 tests, 0 failures.

Run from worktree root: the metadata gate from Global Constraints.
Expected: BUILD SUCCEEDED, 9 actions. (The reindex hooks aren't unit-testable — the OS owns the trigger; on-device verification in Task 8.)

- [ ] **Step 3: Commit**

```bash
git add KitchenOSKit/Sources/KitchenOSKit/RecipeEntity.swift
git commit -m "feat: system-driven Spotlight reindex via IndexedEntityQuery"
```

---

### Task 5: Multi-turn AskKitchenOS — `IdleSessionStore` + consumed proposals + `LongRunningIntent`

**Files:**
- Create: `KitchenOSKit/Sources/KitchenOSKit/AI/IdleSessionStore.swift`
- Modify: `KitchenOSKit/Sources/KitchenOSKit/AI/MealPlanAssistant.swift` (`ProposalStore.take`)
- Modify: `KitchenOSKit/Sources/KitchenOSKit/Intents/AskKitchenOSIntent.swift`
- Test: `KitchenOSKit/Tests/KitchenOSKitTests/IdleSessionStoreTests.swift` (new), `KitchenOSKit/Tests/KitchenOSKitTests/ToolsTests.swift` (proposal consumption)

**Interfaces:**
- Consumes: `MealPlanAssistant` (`init(client:surface:)`, `reply(to:)`, `pendingProposal()`, `clearProposal()`, `confirm(_:)`); `ProposalStore` (`set`, `take`).
- Produces: `IdleSessionStore<T: AnyObject>` — `@MainActor`, `init(idleTimeout: TimeInterval = 300)`, `current(now: Date = Date(), make: () -> T) -> T`, `reset()`. `ProposalStore.take()` becomes consuming (returns then clears). `AskKitchenOSIntent` conforms to `LongRunningIntent`.

**Why the proposal change is load-bearing:** today `take()` returns without clearing, and every Siri invocation built a fresh assistant, so a stale proposal died with its instance. With session reuse, a proposal the user *declined* would linger and re-prompt on the next question. `take()` must consume.

- [ ] **Step 1: Write the failing session-store test**

Create `IdleSessionStoreTests.swift`:

```swift
import XCTest
@testable import KitchenOSKit

final class Counter { var value = 0 }

@MainActor
final class IdleSessionStoreTests: XCTestCase {
    func testReusesInstanceWithinTimeout() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        var makes = 0
        let a = store.current(now: t0) { makes += 1; return Counter() }
        let b = store.current(now: t0.addingTimeInterval(299)) { makes += 1; return Counter() }
        XCTAssertTrue(a === b)
        XCTAssertEqual(makes, 1)
    }

    func testMakesFreshInstanceAfterIdleTimeout() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        let b = store.current(now: t0.addingTimeInterval(301)) { Counter() }
        XCTAssertFalse(a === b)
    }

    func testTouchExtendsTheWindow() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        _ = store.current(now: t0.addingTimeInterval(200)) { Counter() }
        let c = store.current(now: t0.addingTimeInterval(450)) { Counter() }
        XCTAssertTrue(a === c)   // 450 is only 250 past the last touch at 200
    }

    func testResetForcesFreshInstance() {
        let store = IdleSessionStore<Counter>(idleTimeout: 300)
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let a = store.current(now: t0) { Counter() }
        store.reset()
        let b = store.current(now: t0) { Counter() }
        XCTAssertFalse(a === b)
    }
}
```

- [ ] **Step 2: Run to verify compile failure**

Run: `cd KitchenOSKit && swift test 2>&1 | tail -5`
Expected: compile error — `IdleSessionStore` does not exist.

- [ ] **Step 3: Implement the store**

Create `AI/IdleSessionStore.swift`:

```swift
import Foundation

/// Keeps one live instance across Siri intent invocations so follow-up questions share
/// the model session's transcript. iOS 27 exposes no public conversation identity to
/// third-party intents (SDK introspection, 2026-08-12 — the `_ModelDelegationIntent`
/// machinery is Apple-internal), so continuity is time-based: reuse within `idleTimeout`
/// of the last touch, fresh after. Single user, single device — one slot is enough.
@MainActor
public final class IdleSessionStore<T: AnyObject> {
    private var value: T?
    private var lastUsed: Date = .distantPast
    private let idleTimeout: TimeInterval

    public init(idleTimeout: TimeInterval = 300) {
        self.idleTimeout = idleTimeout
    }

    public func current(now: Date = Date(), make: () -> T) -> T {
        if let v = value, now.timeIntervalSince(lastUsed) < idleTimeout {
            lastUsed = now
            return v
        }
        let v = make()
        value = v
        lastUsed = now
        return v
    }

    public func reset() {
        value = nil
    }
}
```

- [ ] **Step 4: Run to verify the store tests pass**

Run: `swift test 2>&1 | tail -3`
Expected: 79 tests, 0 failures.

- [ ] **Step 5: Write the failing proposal-consumption test**

Append to `ToolsTests.swift`:

```swift
    func testProposalStoreTakeConsumes() {
        let store = ProposalStore()
        store.set(PendingMealAddition(recipe: "Butter Chicken", day: "Thursday", meal: "dinner"))
        XCTAssertNotNil(store.take())
        XCTAssertNil(store.take(), "take() must consume — a declined proposal must not re-prompt on the next turn")
    }
```

(`PendingMealAddition.init(recipe:day:meal:)` verified against `AI/Tools/AddToMealPlanTool.swift:9`.)

- [ ] **Step 6: Run to verify it fails**

Run: `swift test 2>&1 | tail -5`
Expected: FAIL on the second assertion — `take()` currently returns without clearing.

- [ ] **Step 7: Make `take()` consume**

In `MealPlanAssistant.swift`, `ProposalStore`:

```swift
    func take() -> PendingMealAddition? {
        lock.lock(); defer { lock.unlock() }
        let v = value
        value = nil
        return v
    }
```

Both call sites are verified safe with consuming semantics: `AskKitchenOSIntent.swift:35` calls once and binds the value; `AssistantView.swift:98` stores it into its `pending` state var. Update `pendingProposal()`'s doc comment to say it consumes.

- [ ] **Step 8: Run to verify it passes**

Run: `swift test 2>&1 | tail -3`
Expected: 80 tests, 0 failures.

- [ ] **Step 9: Wire the session store + LongRunningIntent into the intent**

In `AskKitchenOSIntent.swift`, change the struct declaration and `perform()`:

```swift
public struct AskKitchenOSIntent: AppIntent, LongRunningIntent {
```

Add inside the struct:

```swift
    /// One live assistant shared across invocations = Siri follow-ups keep context.
    @MainActor static let voiceSessions = IdleSessionStore<MealPlanAssistant>()
```

Replace the assistant construction line (`let assistant = await MealPlanAssistant(surface: .voice)`) with:

```swift
        let assistant = await Self.voiceSessions.current { MealPlanAssistant(surface: .voice) }
```

Wrap the model call so the OS lets a slow tool-chain run finish (LongRunningIntent, iOS 27):

```swift
        let reply: String
        do {
            let raw = try await performBackgroundTask {
                try await assistant.reply(to: request)
            }
            reply = Self.plainSpoken(raw)
        } catch KitchenOSError.unreachable {
            return .result(dialog: "I can't reach KitchenOS right now.")
        } catch {
            return .result(dialog: "Something went wrong reaching the assistant.")
        }
```

In the declined-confirmation catch (currently `// User declined the change — keep the assistant's answer, skip the write.`), add the clear before returning:

```swift
        } catch {
            // User declined the change — keep the assistant's answer, skip the write.
            await assistant.clearProposal()
            return .result(dialog: IntentDialog(stringLiteral: reply))
        }
```

(`clearProposal` is `@MainActor` via the class; the `await` is required from the nonisolated intent. Note `pendingProposal()` already consumed the value in `take()` — the explicit clear guards the window where the model proposes again mid-decline; it is belt-and-suspenders, keep it.)

**Beta-drift fallback:** if `performBackgroundTask`'s closure signature rejects the throwing async closure (spec pins the shape from the 2026-08-12 interface: `performBackgroundTask<T>(options:operation: @escaping () async throws -> T)`), drop the wrapper and call `try await assistant.reply(to: request)` directly — that is today's shipped behavior and stays correct.

- [ ] **Step 10: Build, full suite, metadata gate**

Run: `swift build && swift test 2>&1 | tail -3` — 80 tests, 0 failures.
Run the metadata gate from Global Constraints — BUILD SUCCEEDED, 9 actions.

- [ ] **Step 11: Commit**

```bash
git add KitchenOSKit
git commit -m "feat: multi-turn AskKitchenOS via idle session store; proposals consume on take"
```

---

### Task 6: App Shortcuts — AskKitchenOS as the flagship phrase set

**Files:**
- Modify: `KitchenOSSiri/Sources/KitchenOSShortcuts.swift` (the `AskKitchenOSIntent` AppShortcut block)

**Interfaces:**
- Consumes: `AskKitchenOSIntent` (unchanged type name).
- Produces: richer invocation phrases only — no code contract.

- [ ] **Step 1: Extend the Ask block's phrases**

Find the `AppShortcut(intent: AskKitchenOSIntent(), …)` block (currently phrases `"Ask \(.applicationName)"`, `"Ask \(.applicationName) about my meals"`, `"Talk to \(.applicationName)"`) and replace its `phrases:` array with:

```swift
            phrases: [
                "Ask \(.applicationName)",
                "Ask \(.applicationName) about my meals",
                "Talk to \(.applicationName)",
                "Ask \(.applicationName) what's for dinner",
                "Ask \(.applicationName) what to cook",
                "Ask \(.applicationName) to plan my week",
            ],
```

(Every phrase keeps the `\(.applicationName)` token — the metadata processor has historically required it; whether the new Siri routes app-less phrasing is a Task 8 on-device observation, not a build-time change.)

- [ ] **Step 2: Metadata gate**

Run the metadata gate from Global Constraints.
Expected: BUILD SUCCEEDED, 9 actions.

- [ ] **Step 3: Commit**

```bash
git add KitchenOSSiri/Sources/KitchenOSShortcuts.swift
git commit -m "feat: natural AskKitchenOS invocation phrases for the new Siri"
```

---

### Task 7: Docs + Decision D record

**Files:**
- Modify: `docs/ROADMAP.md` (floor line; "Native / Siri — pending polish" items (a) and (b))
- Modify: `docs/API.md` (`/api/recipes` params; floor references; the gated-route note)
- Modify: `docs/plans/2026-08-02-daily-driver-audit.md` (Decision D)
- Modify: `docs/ARCHITECTURE.md`, `README.md` (floor references — find with `grep -rn "iOS 26" docs/ README.md CLAUDE.md`)

**Interfaces:** none — prose only.

- [ ] **Step 1: Update the docs**

- ROADMAP: floor becomes iOS 27/macOS 27; mark polish item (a) (ingredient keywords) and the slice-1 half of (b) (system reindex hooks; background *cadence* remains slice 2) as shipped by this branch, pointing at the spec.
- API.md: document `include_ingredients=1` on `GET /api/recipes` (gated, returns `ingredient_items`); sweep floor references.
- Daily-driver audit: under Decision D, record: **D — resolved 2026-08-12: keep at parity and invest.** The native app is the only possible Siri surface; the iOS 27 new-Siri feature (spec `docs/superpowers/specs/2026-08-12-ios27-new-siri-design.md`) builds on it.
- ARCHITECTURE.md / README.md: floor references 26 → 27.

- [ ] **Step 2: Verify no stale floor references remain**

Run: `grep -rn "iOS 26\|macOS 26" docs/ README.md CLAUDE.md KitchenOSKit/Sources KitchenOSSiri/Sources | grep -v history | grep -v "26.0 → 27"`
Expected: no hits outside `docs/history/` (history stays as written).

- [ ] **Step 3: Commit**

```bash
git add docs/ README.md
git commit -m "docs: iOS 27 floor, include_ingredients param, Decision D resolved"
```

---

### Task 8: Token, deploy, on-device verification

**Files:** none in the worktree (ops + user actions). The `.env` edit happens in the **main checkout** (`/Users/chaseeasterling/Dev/KitchenOS/.env`, git-ignored, machine-local).

**Interfaces:**
- Consumes: existing `require_token` (`api_server.py:69`), `KeychainCredentialStore`, Settings token field.
- Produces: a live bearer gate; the deployed build on the iPhone.

- [ ] ~~**Step 1: Set the token and restart the server (Mac, main checkout)**~~
  **SKIPPED — decided 2026-08-12:** activating the token breaks the web planner from
  remote browsers (no browser page sends the bearer header; `/api/meal-plan` is gated).
  Deferred to slice 2, which adds a browser-compatible auth path first. Do NOT run the
  commands below until then. (Kept for reference:)

```bash
TOKEN=$(openssl rand -hex 24)
printf '\nKITCHENOS_API_TOKEN=%s\n' "$TOKEN" >> /Users/chaseeasterling/Dev/KitchenOS/.env
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
echo "$TOKEN"   # keep visible — it goes into the iPhone Settings field
```

Verify the gate is live (from the Mac, simulating a remote caller is covered by tests; functionally):

```bash
curl -s -o /dev/null -w '%{http_code}\n' "http://$(tailscale ip -4):5001/api/recipes"        # expect 401
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" "http://$(tailscale ip -4):5001/api/recipes"  # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5001/api/recipes                    # expect 200 (localhost exempt)
```

**Note:** this is a live-server change. The prod server runs main's `api_server.py`, which already carries `require_token` — setting the env var activates gating for the 38 decorated routes *before* this branch merges. The iPad/iPhone app sends the token once entered in Settings; the browser UI is localhost-exempt. If anything remote breaks unexpectedly, removing the line from `.env` + restart reverts.

- [ ] **Step 2: Deploy the branch build to the iPhone (worktree)**

Per `docs/OPERATIONS.md` §8, from the worktree root:

```bash
xcodegen generate
xcodebuild build -scheme KitchenOSSiri -destination 'platform=iOS,id=AC76BD14-9BDF-50F9-9087-3E7229EBF38D' -allowProvisioningUpdates
xcrun devicectl device install app --device AC76BD14-9BDF-50F9-9087-3E7229EBF38D <path-to-built .app>
```

- [ ] **Step 3: On-device verification (user, iPhone)**

- [ ] ~~Enter the token in KitchenOS → Settings → API token; tap "Test connection" — expect success.~~ **N/A for slice 1** — token activation was skipped in Step 1, so there is no token to enter; the intents reach the API unauthenticated over the tailnet. Do not set one until slice 2.
- [ ] Tap "Reindex recipes" once (seeds the index with ingredient keywords).
- [ ] Say: "Ask KitchenOS what's on my meal plan this week" — spoken answer from real data.
- [ ] Within ~5 minutes, follow up: "what about Thursday dinner?" — the answer uses context from the first question (multi-turn).
- [ ] Say: "Ask KitchenOS to suggest something high-protein with the chicken I have" — completes even if tools take a while (LongRunningIntent).
- [ ] Say: "add it to Thursday dinner" — Siri asks to confirm out loud; confirm; verify the row appears on the web planner.
- [ ] Decline flow: provoke a proposal, decline it, ask an unrelated question — Siri must NOT re-prompt the declined add.
- [ ] Long-session probe: after a long chatty session (many tool-heavy turns), confirm a follow-up still answers — and if it fails once, confirm the NEXT ask recovers (the session resets on failure rather than staying broken).
- [ ] Spotlight: search an ingredient that appears in no recipe title (e.g. "garam masala") — recipes surface.
- [x] Note whether any phrase works without saying "KitchenOS" (observation for the phrase-token question; record in BRANCH-STATUS notes).
  **Answered 2026-08-12 ~21:59 CDT, on-device:** app-less natural phrasing does **not** route. A natural meal-plan question without the app name produced Siri's generic fallback ("I can't search within KitchenOS directly. You'll need to open the app to view your meal plan.") and the intent never executed — no corresponding request in `server.log`, and the wording matches no in-app failure string. This confirms the phrase-token question at Task 6: with no assistant schema (C3), literal App Shortcut phrase match is the only route in, so every invocation must include "KitchenOS". Mitigation: the phrase list was broadened with natural-leaning variants (all keeping the app-name token) in KitchenOSShortcuts.swift.

- [ ] **Step 4: Record results**

Update `BRANCH-STATUS.md` testing checklist with outcomes; move anything broken back to dev with a note.

---

## Deferred to the slice-2 plan (do not build here)

`KitchenStore`/SwiftData models, `KitchenDataSource`/`LocalFirstDataSource`, `SyncEngine`, `QueueFlusher`, `MealSuggester` port, BGAppRefreshTask, gating the inventory mutation routes (`api_inventory_add/remove/update` out of `KNOWN_UNGATED` — they gate when Siri starts writing through them in slice 2).
