# Phone Surfaces and Connectivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Today, Plan, Shop and Cook usable on iPhone at home, remotely and for cached reading offline, without replaying writes or duplicating server truth.

**Architecture:** Put endpoint profiles, resolution and safe request dispatch in KitchenOSKit behind one client provider. Reuse the existing kitchen briefing and ledger APIs for native phone surfaces; add only missing read contracts. Layer disposable snapshots beneath observable screen models, keeping domain mutations on the server.

**Tech Stack:** Existing Swift 6 package tooling in Swift 5 language mode; SwiftUI, Foundation/URLSession, Network and WebKit; iOS/macOS 26 deployment targets; Python 3.11 via `.venv/bin/python`, Flask and existing SQLite/vault services. No new third-party dependency.

**Spec:** [Phone surfaces and connectivity](../specs/2026-09-24-phone-surface-and-connectivity-design.md). The user's “continue” after the committed spec authorizes this planning stage. This plan still requires review and execution-method selection.

## Global Constraints

- “Preferred phone/iPad endpoint: `http://Chases-Mac-mini.local:5001`.”
- “Remote fallback: `http://chases-mac-mini.taila69703.ts.net:5001`”
- “at most 2 seconds for local and 4 seconds for remote, including connection and response.”
- “all dispatched writes receive zero automatic retries”
- “The 20 most recently opened recipes, including ingredients and instructions” are the recipe cache bound.
- “No initial screen or page render waits on an LLM.”
- “SQLite remains authoritative for its domain records” and the vault retains its authored recipe/plan roles.
- “Recipe filename/name remains identity; `short_title`/`display_name` remains presentation only.”
- “Small edits use the domain API appropriate to the selected item”; no legacy whole-plan overwrite of cooks/bundles.
- “Tokens remain in Keychain and authorization headers”; never include them in diagnostics, URLs or snapshots.
- “No product code, device settings or services are changed by this documentation task.”
- Keep existing Mac/iPad planning and Siri confirmation flows available. Bind any execution-time preview to `0.0.0.0`; verify its LAN/Tailscale URL before sharing it.

## Review Focus

1. A canceled screen and a still-running Siri read share one resolution: cancellation must not abort the other consumer (Tasks 2–3).
2. A token/server change occurs while an old request is completing: the old response must not populate the new profile's cache (Tasks 4, 10–11).
3. A lost response follows a successful mutation, or a redirect invites resubmission: report an unknown outcome without sending again (Tasks 3, 5, 8, 11).
4. A Sunday cook supplies Monday leftovers, or a bundle member is fractional: show the placement without converting it to an integer or losing its identity (Tasks 7–9).
5. The phone travels across time zones or a DST/week boundary offline: retain the kitchen context and label old snapshots with their actual date/week (Tasks 7, 10–11).

## Delivery, workspace and verification rules

Tasks 1–2 implement spec stage 1; Tasks 3–5 stage 2; Task 6 stage 3; Tasks 7–9 stage 4; Tasks 10–11 stage 5. Task 12 verifies integration and starts the observation record for stage 6. No speculative capture, shopping or cooking feature is approved by stage 6.

Execute in dependency order. Every task uses a focused red/green test cycle, then a reviewable commit. The code below fixes public interfaces, test examples and core algorithms; preserve existing public methods unless explicitly replaced. Keep helpers private unless another task consumes them.

The inspected checkout is `codex/calendar-meal-planning`, with unrelated tracked edits and untracked calendar files. Before execution, follow using-git-worktrees and preserve this baseline. A HEAD-only checkout lacks the calendar code referenced here: use a current-working-tree snapshot when the available worktree mechanism supports it, or deliberately transfer the relevant baseline changes into the isolated checkout and record them separately. Do not stash, revert or commit the user's unrelated work. If that baseline cannot be reproduced safely, resolve the workspace prerequisite before implementing.

Use `git diff` to distinguish baseline changes from this feature at every commit. Stage explicit task files/hunks; never `git add .`. Use the repository's `finish-feature` checklist before feature commits and its commit footer convention. Update `docs/API.md` for changed contracts, `docs/ARCHITECTURE.md` for new components and `docs/OPERATIONS.md` for configuration/diagnostics. Restart `com.kitchenos.api` when deploying changed Python/library code, not merely while running isolated tests.

Commands below run from the execution checkout. Swift tests use injected transport and temporary defaults/cache directories. Python tests use the repository's DB/vault isolation fixtures; never read or modify live kitchen data in a test. Do not claim on-device checks passed from unit tests or a simulator build.

## File structure and ownership

| Files | Responsibility |
| --- | --- |
| `KitchenOSKit/.../ConnectionProfile.swift`, `ConnectionResolver.swift`, `ConnectionPathMonitor.swift` | Settings migration, candidate selection, network invalidation |
| `KitchenOSKit/.../KitchenOSTransport.swift`, `RequestPolicy.swift` | One dispatch policy, error classification, redirects and read retry |
| `KitchenOSKit/.../KitchenOSClientProvider.swift` | Production composition, credentials/profile generation and shared clients |
| Existing `KitchenOSClient*.swift`, `CookingAvailability.swift`, `PlanningCalendar.swift` | Domain operations expressed as endpoint-relative requests |
| `KitchenOSSiri/Sources/Connection/` | Observable connection model, diagnostics and embedded web presentation |
| `lib/phone_reads.py`, `lib/kitchen_briefing.py`, `api_server.py` | Existing briefing enrichment and strictly read-only phone contracts |
| `KitchenOSKit/.../PhoneModels.swift`, `KitchenOSClient+Phone.swift`, `KitchenOSClient+Ledger.swift` | Typed read models and ledger commands |
| `KitchenOSSiri/Sources/Phone/` | Four-tab phone shell, Today/Shop/Cook hubs and focused plan |
| `KitchenOSKit/.../ReadSnapshotStore.swift`, `KitchenReadRepository.swift`, `ReadState.swift` | Disposable cache, freshness and guarded refresh |
| Matching Swift tests and `tests/test_phone_reads.py` | Behavioral coverage; actual test files named in each task |

`KitchenOSKit/.../` in this table means `KitchenOSKit/Sources/KitchenOSKit/`. Task file lists below spell out paths.

---

### Task 1: Endpoint profiles and migration

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/ConnectionProfile.swift`, `KitchenOSKit/Sources/KitchenOSKit/ConnectionFailure.swift`; modify `KitchenOSKit/Sources/KitchenOSKit/KitchenOSConfig.swift`; create `KitchenOSKit/Tests/KitchenOSKitTests/ConnectionProfileTests.swift`.

**Interfaces:** Produce `ConnectionFailure` below and `ConnectionProfile: Codable, Equatable` with `id: UUID`, `mode: Mode` (`automatic`, `override`, `macLocal`), `localURL: URL`, `remoteURL: URL?`; `ConnectionProfile.load(defaults: UserDefaults, isPhone: Bool) throws -> ConnectionProfile`; `ConnectionProfile.save(to:)`. Use one persisted UUID for the automatic server, independent of selected route. A changed custom-server URL gets a new UUID. Keep the existing `KitchenOSConfig(baseURL:credentials:)` initializer for isolated tests.

- [ ] **1. Write migration tests**, including this fresh-install case:

```swift
func testFreshPhoneUsesAutomaticProfile() throws {
    let name = "ConnectionProfileTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: name)!
    defer { defaults.removePersistentDomain(forName: name) }
    let p = try ConnectionProfile.load(defaults: defaults, isPhone: true)
    XCTAssertEqual(p.mode, .automatic)
    XCTAssertEqual(p.localURL.absoluteString, "http://Chases-Mac-mini.local:5001")
    XCTAssertEqual(p.remoteURL?.absoluteString, "http://chases-mac-mini.taila69703.ts.net:5001")
    XCTAssertEqual(try ConnectionProfile.load(defaults: defaults, isPhone: true).id, p.id)
}
```

Add table cases for absent value, the current IP, either approved hostname, a custom URL, invalid URL and Mac defaults. Normalize hostname case, default port and trailing slash for known-endpoint comparison; do not equate different nonempty paths. Reject userinfo, query/fragment, missing host and non-HTTP(S) schemes. Retain the saved token.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter ConnectionProfileTests`. Expect missing new types.
- [ ] **3. Implement profile migration.** Persist JSON under `kitchenos.connectionProfile.v1` only after validation. Leave the old setting available for migration debugging; once the versioned value exists it wins. A malformed versioned setting surfaces `ConnectionFailure.configuration` rather than silently falling back.

```swift
public enum ConnectionFailure: Error, Equatable {
    case configuration, connectivity, permission, http(Int), invalidHealth, cancelled
}
// Nested in ConnectionProfile:
public enum Mode: String, Codable { case automatic, override, macLocal }
// Known legacy phone defaults enter automatic mode; other valid saved URLs
// enter override mode with remoteURL == nil. Mac defaults enter macLocal.
```

- [ ] **4. Run green:** the command above plus `swift test --package-path KitchenOSKit --filter ConfigTests`.
- [ ] **5. Commit:** `feat: add connection profiles and migrate endpoint settings`.

### Task 2: Resolver, deadlines and network generations

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/ConnectionResolver.swift`, `ConnectionPathMonitor.swift`; create `KitchenOSKit/Tests/KitchenOSKitTests/ConnectionResolverTests.swift`.

**Interfaces:** Consume Task 1's `ConnectionFailure`; produce the following types.

```swift
public enum ConnectionPath: Equatable { case unknown, localAvailable, cellularOnly, unavailable }
public enum ConnectionRoute: String, Codable { case local, remote, override }
public struct ResolvedEndpoint: Equatable {
    public let url: URL
    public let route: ConnectionRoute
    public let generation: UInt64
}
public struct ProbeRecord: Equatable {
    public let endpoint: URL
    public let completedAt: Date
    public let failure: ConnectionFailure?
}
public actor ConnectionResolver {
    // init(profile:path:probe:) takes an async throwing probe(URL, TimeInterval).
    // resolve(excluding: URL? = nil) async throws -> ResolvedEndpoint
    // invalidate(path: ConnectionPath) async
    // records() async -> [ProbeRecord]
}
```

- [ ] **1. Add resolver tests with an injected probe**, using an actor recorder local to the test file:

```swift
func testLocalTransportFailureSelectsRemote() async throws {
    let profile = ConnectionProfile(id: UUID(), mode: .automatic,
        localURL: URL(string: "http://kitchen.local:5001")!,
        remoteURL: URL(string: "http://kitchen.example:5001")!)
    let resolver = ConnectionResolver(profile: profile, path: .localAvailable) { url, budget in
        if url == profile.localURL {
            XCTAssertEqual(budget, 2)
            throw ConnectionFailure.connectivity
        }
        XCTAssertEqual(budget, 4)
    }
    let result = try await resolver.resolve()
    XCTAssertEqual(result.route, .remote)
}
```

Test local success, both unreachable, unknown path, cellular skip, override/macLocal, HTTP/malformed health (no fallback), genuine permission denial, explicit invalidation, simultaneous callers and an obsolete probe finishing last. Use continuations to control ordering, not wall-clock sleeps. One canceled waiter must not cancel resolution for another; the canceled caller still receives cancellation and must not issue its domain request.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter ConnectionResolverTests`.
- [ ] **3. Implement an actor with an incrementing generation and a shared in-flight probe task.** Retain a chosen endpoint only in its generation; recheck generation after every await. Invalidation cancels obsolete probe work and wakes/restarts live callers within the new generation. Exclusion applies only to the recovery attempt. Do not loop over candidates indefinitely.

```swift
var candidates: [(URL, ConnectionRoute, TimeInterval)] = []
if profile.mode == .automatic {
    candidates.append((profile.localURL, .local, 2))
    if let remote = profile.remoteURL { candidates.append((remote, .remote, 4)) }
} else {
    candidates.append((profile.localURL, profile.mode == .macLocal ? .local : .override, 2))
}
// Filter the local candidate for cellular-only paths and the excluded URL.
// Connectivity/permission failure may try the remaining route; HTTP/payload
// errors stop. Unknown/unavailable hints are not proof of server health.
```

`ConnectionPathMonitor` wraps `NWPathMonitor` behind an injectable callback; cellular-only means no available Wi-Fi/wired path, not just “cellular was observed.” Start once per provider and cancel on teardown.

The production probe uses an ephemeral, uncached GET `/health` with no token, no redirect following and both request/resource deadlines. Cancel the underlying URLSession task when its full deadline expires; a timeout race whose losing task keeps running does not satisfy the budget. Validate 2xx and `{status:"ok"}`. Network denial is only reported when supported by a concrete error, not guessed from a timeout.

- [ ] **4. Run green:** resolver and profile tests. Add a deadline test with a never-completing injected transport and a virtual/injected deadline trigger; assert its underlying work is canceled.
- [ ] **5. Commit:** `feat: resolve local and remote connections with bounded probes`.

### Task 3: Safe transport and operation classification

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/RequestPolicy.swift`, `KitchenOSTransport.swift`; modify `KitchenOSClient.swift`, `KitchenOSClient+Inventory.swift`, `KitchenOSClient+Meals.swift`, `KitchenOSClient+Receipts.swift`, `KitchenOSClient+System.swift`, `CookingAvailability.swift`, `PlanningCalendar.swift` in that directory; create `KitchenOSKit/Tests/KitchenOSKitTests/TransportPolicyTests.swift`.

**Interfaces:** `RequestPolicy` cases `readOnly`, `write`, `unclassified`; `KitchenOSTransport.send(path: [String], query: [URLQueryItem], method: String, body: Data?, policy: RequestPolicy) async throws -> Data`. Transport receives resolver, credential store and injectable dispatch closure/session. Extend `KitchenOSError` with `notSent`, `writeOutcomeUnknown`, `configuration`, retaining existing public cases for compatibility; cancellation remains `CancellationError`.

- [ ] **1. Add policy and dispatch-count tests.** Keep deterministic state in a test actor rather than adding concurrent tests around `MockURLProtocol.handler`'s global mutable state. At least one integration test must run through URLSession and the existing mock protocol, with serialized setup/teardown.

```swift
func testPolicyNeverRetriesMutations() {
    XCTAssertTrue(RequestPolicy.readOnly.canRetryConnectivity)
    XCTAssertFalse(RequestPolicy.write.canRetryConnectivity)
    XCTAssertFalse(RequestPolicy.unclassified.canRetryConnectivity)
}
```

For the actual transport, inject a dispatcher that records URL/method/body then throws `URLError(.networkConnectionLost)`. A read sends on local then remote exactly once each; a write sends once and throws `writeOutcomeUnknown`. Parameterize 401, 403, 500, malformed JSON, cancellation and redirect responses; no connectivity retry for those. A 2xx mutation with an undecodable required acknowledgement is unknown, not successful. Cancel after a shared resolve and assert zero domain dispatches for that canceled caller.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter TransportPolicyTests`.
- [ ] **3. Refactor request construction to use relative path components and explicit policy.** Preserve existing endpoint methods' public signatures. Replace extension access to `baseURL`/absolute-URL helpers with relative requests, so a stale base URL cannot defeat resolution.

```swift
public enum RequestPolicy {
    case readOnly, write, unclassified
    var canRetryConnectivity: Bool { if case .readOnly = self { return true }; return false }
}
// Dispatch algorithm: resolve -> check cancellation -> build request -> send.
// On eligible transport failure only: resolve(excluding: first.url) -> send once.
// Rebuild only the origin; preserve path, query, method and body byte-for-byte.
```

Use `URLComponents`/path-component construction to keep Unicode, spaces, `#`, `%`, `?` and slashes in recipe names from becoming query/path injection. Add round-trip request tests. Keep the current 12-second domain request budget. Deny automatic redirects for mutation requests; deny cross-origin redirects for every credentialed request. A redirect never carries credentials to its Location destination.

**Initial read allowlist after source audit:** recipe index/detail; ingredient-based search POST; meal-plan GET (current source returns an in-memory empty week, unlike stale API prose); inventory/pantry reads; meal reads; receipt trip/price reads; cooking-availability reads; the new read methods from Tasks 7–8. Audit nutrition/system health before opting in. `tasks(force:)`, suggestion/AI calls and unknown methods stay unclassified until their side effects are excluded. All mutations, extraction, calendar sync, preview/confirm workflows are non-retrying. Do not classify by verb alone.

For writes, errors after dispatch are unknown unless a documented response proves rejection before mutation. Authentication rejection may retain `.http(401/403)`; conservatively treat server errors and connection loss as unknown. Mark success only after the method's required acknowledgement has decoded. Keep error detail separate from retry permission.

- [ ] **4. Run green:** transport tests and `swift test --package-path KitchenOSKit`. Existing URL/path/body tests must retain their coverage; update only setup needed for the injected fixed-endpoint test client.
- [ ] **5. Commit:** `feat: centralize request dispatch and prevent mutation replay`.

### Task 4: Adopt one provider across app and intents

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/KitchenOSClientProvider.swift`; modify `RecipeEntity.swift`, `RecipeIndexer.swift`, `AI/MealPlanAssistant.swift`, all client-constructing files in `Intents/`; create `KitchenOSSiri/Sources/Connection/ConnectionModel.swift`; modify client consumers in `KitchenOSSiri/Sources/` and `KitchenOSSiriApp.swift`; create `KitchenOSKit/Tests/KitchenOSKitTests/ClientProviderTests.swift`.

**Interfaces:** `KitchenOSClientProvider.shared`; `client() throws -> KitchenOSClient`; `resolver() throws -> ConnectionResolver`; `context() throws -> ConnectionContext`; `reloadConfiguration() throws`; `ConnectionContext: Equatable` contains `profileID: UUID`, `revision: UInt64` (persisted configuration revision, not a secret). `ConnectionModel` is `@MainActor ObservableObject` and observes probe/contact state. Explicit fixed-config `KitchenOSClient` construction remains available for tests only.

- [ ] **1. Write provider tests** with temporary defaults/in-memory credentials: two callers use the same policy/resolver; a custom-profile reload changes context; local/remote resolution does not; a credential change increments revision before returning a new client. Verify a retained old client cannot send a new write after configuration changes. An already dispatched write may finish, but its result carries the old context.

```swift
func testNetworkSwitchDoesNotChangeProfileIdentity() throws {
    let suite = "ClientProviderTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let provider = KitchenOSClientProvider(defaults: defaults,
        credentials: InMemoryCredentialStore(), isPhone: true)
    let first = try provider.context()
    let second = try provider.context()
    XCTAssertEqual(first, second)
}
```

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter ClientProviderTests`.
- [ ] **3. Move production composition into the provider.** Use a lock around synchronous configuration/client access or a main-actor-independent synchronization primitive; do not make Siri depend on a SwiftUI environment or main-app launch. Read current settings on intent entry. Keep existing injected-client overloads on indexer/assistant; make the no-client overload resolve through the provider.

```swift
// Screen replacement (provider injected by init; shared is the default):
private let provider: KitchenOSClientProvider
private func loadRecipes() async throws -> [RecipeSummary] {
    try await provider.client().findRecipes(ingredient: "")
}
// Intent perform() resolves the provider at invocation, then keeps its client
// for that operation. It must not capture a client at intent type initialization.
```

Migrate SmartSearch, Assistant, Cook, Recipes, Meals, Inventory/Pantry, Shopping,
Receipts (including detail), Tasks, Nutrition/SystemHealth, MealPlan/PlannerBoard,
RecipePickerSheet, CookingAvailabilityModel and CookingCalendarSettings. Add
unknown-write outcome messaging to write-capable intents and assistant completion
handlers; a generic “could not update” must not imply the server rolled back. Mac-only
extraction subprocess configuration remains separate. Foreground invalidates
resolution, then refreshes visible data; it never repeats an interrupted write.

- [ ] **4. Run green:** package tests, then audit remaining construction:

```bash
rg -n 'KitchenOSClient\(config: \.resolved\(\)\)|KitchenOSConfig\.resolved\(' KitchenOSKit/Sources KitchenOSSiri/Sources
```

Remaining production URL resolution belongs only in provider/migration internals
or the web/settings callers assigned to Tasks 5–6. Record each remaining match;
a false “zero” requirement must not remove test injection APIs.

- [ ] **5. Commit:** `refactor: share connection policy across native clients and intents`.

### Task 5: Resolve embedded web origins without replaying edits

**Files:** Modify `KitchenOSSiri/Sources/MealPlan/PlanningCalendarWebView.swift`, `KitchenOSKit/Sources/KitchenOSKit/PlanningWebPolicy.swift`; create `KitchenOSSiri/Sources/Connection/ConnectedWebSheet.swift`, `KitchenOSKit/Sources/KitchenOSKit/WebReloadState.swift`, `KitchenOSKit/Tests/KitchenOSKitTests/WebReloadStateTests.swift`.

**Interfaces:** `WebReloadState` stores `loadedOrigin: URL?`, `requiresReload: Bool`, `mutationMayBePending: Bool`; `networkChanged()` marks a warning without changing origin; `confirmReload(origin:)` applies only after explicit user confirmation. `ConnectedWebSheet(path: String, query: [URLQueryItem])` resolves through the provider before creating its WKWebView. Initial allowed paths: `/meal-planner`, `/receipt-paste`, `/review`, `/system-health`.

- [ ] **1. Pin reload behavior:**

```swift
func testNetworkChangeDoesNotReplaceInteractiveOrigin() {
    let origin = URL(string: "http://kitchen.local:5001")!
    var state = WebReloadState(loadedOrigin: origin)
    state.networkChanged()
    XCTAssertEqual(state.loadedOrigin, origin)
    XCTAssertTrue(state.requiresReload)
}
```

Add a pending-mutation case, canceling the reload confirmation, a cross-origin link,
a redirect after POST and cleanup/recreation of auth scripts. Preserve the existing
same-origin fetch authorization tests.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter WebReloadStateTests`.
- [ ] **3. Move web creation behind an async loading shell.** Reuse PlanningWebPolicy's origin checks and nonpersistent WKWebView store. A network change shows a banner; only a confirmed reload recreates the view and auth script. Generalize allowed top-level paths explicitly, never to every HTTP URL.

```swift
.confirmationDialog("Reload this page? Unsaved changes may be lost.",
                    isPresented: $confirmReload) {
    Button("Reload page", role: .destructive) { Task { await reloadFromProvider() } }
    Button("Keep page", role: .cancel) {}
}
```

`reloadFromProvider()` resolves a new endpoint, discards the prior web instance,
and creates a fresh GET to the requested allowed path. It does not call `reload()`
on a history entry that might resubmit a form. Route external links externally
without auth; do not silently replay JavaScript fetch calls. Treat all open
interactive pages as possibly dirty rather than inventing unreliable dirty detection.

- [ ] **4. Run green:** WebReloadState/PlanningCalendar tests and build both app destinations (commands in Task 12). Manually exercise a page with unsaved text through a simulated connection warning.
- [ ] **5. Commit:** `feat: share web connection setup and require explicit page reloads`.

### Task 6: Connection diagnostics and device setup

**Files:** Create `KitchenOSSiri/Sources/Connection/ConnectionDiagnosticsView.swift`; modify `SettingsView.swift`, `Connection/ConnectionModel.swift`, `KitchenOSSiri/Info-iOS.plist`, `docs/OPERATIONS.md`, `docs/ARCHITECTURE.md`; create `KitchenOSKit/Sources/KitchenOSKit/ConnectionDiagnostics.swift`, `KitchenOSKit/Tests/KitchenOSKitTests/ConnectionDiagnosticsTests.swift`.

**Interfaces:** `ConnectionDiagnostics.message(for: ConnectionFailure) -> String` provides
classified user guidance. `ConnectionDiagnostics` is an immutable sanitized projection of profile mode, selected route/host, last success, probe history and classified failure. `ConnectionModel.testConnection()` forces resolver invalidation and a probe. It displays liveness separately from the most recent authenticated API result.

- [ ] **1. Write redaction/classification tests:**

```swift
func testConnectivityFailureDoesNotAssertVPNIsOff() {
    let message = ConnectionDiagnostics.message(for: .connectivity)
    XCTAssertFalse(message.contains("VPN is off"))
    XCTAssertTrue(message.contains("Tailscale"))
}
```

Pin 401 copy to credentials, cancellation to no error banner, malformed health to
service/configuration, and permission to Settings guidance. Assert serialized
report output never contains an injected token or URL userinfo.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter ConnectionDiagnosticsTests`.
- [ ] **3. Replace Settings' independent health request and raw single-URL default.** Present Automatic/Custom selection, resolved route, last contact and “Test connection.” Save token/profile through provider APIs, increment context before subsequent requests, and notify the cache invalidation hook added in Task 10.

```xml
<key>NSLocalNetworkUsageDescription</key>
<string>KitchenOS connects to your Mac on your local network to read recipes and manage your kitchen.</string>
```

Keep the working ATS configuration until both approved HTTP hosts pass device
checks; do not broaden it or assume a hostname exception is equivalent to IP
access. Document Tailscale On Demand on Wi-Fi and cellular, permissions, server
availability and recovery. Never claim KitchenOS can toggle the VPN itself.

- [ ] **4. Run green:** diagnostics tests; `plutil -lint KitchenOSSiri/Info-iOS.plist`; app builds. Record physical-device checks as pending until actually run.
- [ ] **5. Commit:** `feat: expose connection diagnostics and local network setup`.

### Task 7: Reuse the briefing and expose missing read-only data

**Files:** Modify `lib/kitchen_briefing.py`, `lib/task_extractor.py`, `lib/serving_ledger.py`, `api_server.py`, `.env.example`, `docs/API.md`; create `lib/phone_reads.py`, `tests/test_phone_reads.py`; extend `tests/test_kitchen_briefing.py`, `tests/test_api_kitchen_briefing.py`, `tests/test_api_auth.py`, `tests/test_api_ledger.py`.

**Interfaces:** `phone_reads.kitchen_context(now: datetime | None = None) -> dict`; `phone_reads.saved_shopping_list(week: str) -> dict`; `task_extractor.read_tasks(week: str) -> dict` reads sidecars without extracting or writing. Keep `kitchen_briefing.build(today=None)` compatible and enrich its response additively. Register authenticated `GET /api/shopping-list/<week>` and `GET /api/tasks/<week>/cached`. No new HTML page is needed.

The existing `/api/briefing/kitchen` already removes the need for a new Today aggregate endpoint. Its current fields remain intact; add `context`, stable action identifiers and the safe cached `prep` section. Preserve existing plate deduplication semantics for older consumers while adding placement references under each plate row, rather than multiplying the old rows.

```json
{
  "context": {
    "date": "2026-09-24", "week": "2026-W39", "timezone": "America/Chicago",
    "generated_at": "2026-09-24T12:00:00-05:00"
  },
  "prep": {
    "state": "available", "source": "sidecar", "generated_at": null,
    "tasks": []
  }
}
```

`prep.state` is `available`, `missing`, `stale` or `unavailable`. An empty fresh
sidecar is available with zero tasks. A stale sidecar may return its tasks only
with state `stale`. Do not mark them done from stale data. Each plate row adds
`placements: [{cook_id, placement_id, count, bundle_id}]`; `count` is a number,
not an integer. `next` adds `task_id` and recipe identity when it names prep;
verdict display names must not replace the recipe identity used for routing.

Also extend `serving_ledger.week_board` additively with `placed_cooks`: cooks
from other weeks with slot placements in the requested week. Reuse
`placements_for_week` and `get_cook`, deduplicate by cook ID and leave the existing
`cooks` field unchanged for existing web clients. Native clients union the two
arrays by ID and display only placements matching the requested week. This
prevents a Monday plan from silently omitting Sunday leftovers. Read-only
foreign placements link to their recipe; moving their parent cook remains an
advanced action because it belongs to another week.

The saved shopping response is `{week, state, markdown, items, skipped,
source_modified_at}`. `items` and `skipped` reuse `parse_shopping_list_file`;
`markdown` preserves the exact saved list, including inventory-match notes.
Missing file is `{state:"missing", markdown:null, items:[], skipped:0,
source_modified_at:null}` with 200, not a generated empty list. Read errors
return a service error, not “missing.” Reject invalid weeks with 400 through
`parse_iso_week` and existing path helpers.

- [ ] **1. Write side-effect and contract tests**, using temporary files and
  monkeypatched data loaders; this example needs no real DB/vault:

```python
def test_cached_prep_never_extracts(monkeypatch):
    from lib import task_extractor
    monkeypatch.setattr(task_extractor, 'load_cached_tasks', lambda week: None)
    def forbidden(*args, **kwargs):
        raise AssertionError('read initiated extraction')
    monkeypatch.setattr(task_extractor, 'extract_tasks', forbidden)
    result = task_extractor.read_tasks('2026-W39')
    assert result['state'] == 'missing'
    assert result['tasks'] == []
```

Add tests that hash the temporary DB and snapshot the temporary vault before/after
reads; existing test DB setup may migrate before the baseline hash. Patch LLM
entry points to raise. Cover missing/corrupt/stale sidecar, fractional placement,
Sunday-to-Monday leftover, unavailable inventory, recipe-index failure, invalid
weeks, plain inventory-note bullets, duplicate purchase strings and 401 from
both newly gated routes. Assert no call to shopping generation/confirmation.

- [ ] **2. Run red:** `.venv/bin/python -m pytest tests/test_phone_reads.py tests/test_kitchen_briefing.py tests/test_api_kitchen_briefing.py -q`.
- [ ] **3. Implement thin read adapters and additive briefing fields.** Use the
  existing briefing loaders once per request; do not perform loopback HTTP or
  call Flask view functions from domain code. Promote a safe cached-task wrapper
  instead of copying the freshness comparison into another module.

```python
def read_tasks(week: str) -> dict:
    cached = load_cached_tasks(week)
    if cached is None:
        return {'state': 'missing', 'source': 'sidecar',
                'generated_at': None, 'tasks': []}
    return {'state': 'available' if _is_cache_fresh(week, cached) else 'stale',
            'source': 'sidecar', 'generated_at': cached.get('generated_at'),
            'tasks': cached.get('tasks', [])}
```

Validate sidecar payload types before returning them; malformed payloads become
`unavailable`. File timestamps are UTC ISO strings; a corrupt read is not cached
as a successful empty response. For a sidecar refreshed during a read, ensure
its mtime and content refer to the same read, or return stale/unavailable.

`kitchen_context` uses `ZoneInfo(os.getenv('KITCHENOS_TIMEZONE', 'America/Chicago'))`
and an injected aware `now`. Document that this default matches the current
kitchen deployment and must match the server's kitchen timezone; invalid settings
produce a configuration error. When no explicit date query is supplied, compute
briefing's date using that context; preserve explicit date queries as historical
context, not today's data. Test DST transitions and differing phone time zones.
No time-based “current meal” inference is needed: named meal slots satisfy the
spec when reliable timing is absent.

- [ ] **4. Run green:** the above tests plus `tests/test_task_extractor.py`,
  `tests/test_shopping_list_generator.py`, `tests/test_api_auth.py`.
- [ ] **5. Commit:** `feat: expose safe phone reads with kitchen context and freshness`.

### Task 8: Typed phone reads and ledger-safe planning commands

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/PhoneModels.swift`, `KitchenOSClient+Phone.swift`, `KitchenOSClient+Ledger.swift`; modify `Models.swift`, `KitchenOSClient+MealPlanEdit.swift`, `Intents/AddRecipeToMealPlanIntent.swift`, `AI/Tools/AddToMealPlanTool.swift`, `AI/MealPlanAssistant.swift`; create `KitchenOSKit/Tests/KitchenOSKitTests/PhoneClientTests.swift`, `LedgerClientTests.swift`; update `MealPlanEditTests.swift`. All unprefixed Swift paths in this task are within `KitchenOSKit/Sources/KitchenOSKit/`.

**Interfaces:** Add Codable/Sendable `KitchenContext`, `KitchenBriefing`,
`CachedPrep`, `SavedShoppingList`, `WeekBoard`, `LedgerCook` and
`LedgerPlacement`. Model only consumed response fields, with optional fields
where the server can omit them. `LedgerCook` includes `id: Int`, `recipe: String`,
`week: String`, `date: String?`, `meal: String?`, `scale: Double`,
`bundleID: String?`, `bundleName: String?`, `placements: [LedgerPlacement]`;
placement includes `id`, `cookID`, `destination`, `date`, `meal`, `count: Double`.
`WeekBoard` holds `week`, `cooks`, `placedCooks` (decoded from `placed_cooks`);
ignore unrelated server fields rather than inventing stored macro models. Decode
a missing `placed_cooks` as an empty array for compatibility, but show a server
capability warning when complete week coverage cannot be established.

Produce client methods `kitchenBriefing()`, `cachedPrep(week:)`,
`savedShoppingList(week:)`, `weekBoard(week:)`, `createCook(recipe:week:date:meal:scale:)`,
`moveCook(id:date:meal:)`, `deleteCook(id:)`, `setCookScale(id:scale:)`,
`moveBundle(id:date:meal:)`, `deleteBundle(id:)` and
`placeBundle(name:week:date:meal:scale:)`. Read methods return the corresponding
models; create/move/scale return decoded `LedgerCook`, bundle commands and delete
return Void after validating their acknowledgements. Use `Double` for scales,
recipe servings and legacy `MealSlotValue.servings`; update affected steppers/tests.

- [ ] **1. Pin routing and fractional values:**

```swift
func testFractionalLegacySlotDecodesWithoutRounding() throws {
    let data = Data(#"{"name":"Rice","servings":0.5,"kind":"recipe"}"#.utf8)
    let value = try JSONDecoder().decode(MealSlotValue.self, from: data)
    XCTAssertEqual(value.servings, 0.5)
}
```

Add mock requests asserting moveCook calls POST `/api/cooks/7/move` and moveBundle
calls POST `/api/bundles/<id>/move`, never PUT `/api/meal-plan/...`. Test 0.5 and
1.5 scales, separate placement count, a bundle member edit, and a lost response
with one dispatch. Decode actual backend fixture shapes in full methods rather
than testing only stand-alone structs.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter 'PhoneClientTests|LedgerClientTests|MealPlanEditTests'`.
- [ ] **3. Add client wrappers through Task 3's transport.** Creation uses the
  existing server-side legacy import hook; it must not first PUT the entire week.
  A cook's batch scale and servings eaten are separate inputs: initial creation
  uses the API's current one-serving placement default; scaling a cook changes
  only its batch scale. Display that distinction. Bundle creation delegates
  member shares to `POST /api/bundles` and never sets them locally.

```swift
func moveCook(id: Int, date: String, meal: MealSlot) async throws -> LedgerCook {
    try await postDecoding(path: "/api/cooks/\(id)/move",
                           object: ["date": date, "meal": meal.rawValue])
}
```

Keep compatibility helpers using existing request signatures where useful, but
ensure they mark writes explicitly. Rewrite `addRecipe(_:day:meal:week:)` to derive
the ISO date from the selected week/day and call createCook. Preserve the explicit
Siri/assistant confirmation gate. Adding to an occupied slot now adds a cook;
do not silently replace existing food. Name this behavior in confirmation copy.
Remove the assistant's legacy whole-plan PUT fallback.

For groups, identity is `(bundle_id, date, meal)`. Do not expose an operation
labeled “move this card” that moves hidden members in other slots; when a bundle
has been split, expose member-level edits and an explicitly labeled whole-bundle
action only if the user can see what it affects. Do not introduce a sequence of
member writes pretending to be atomic.

- [ ] **4. Run green:** package suite and Python `tests/test_api_ledger.py`,
  `tests/test_meal_bundle.py`, `tests/test_shopping_from_cooks.py` if server contracts
  changed. The normal task changes Swift only; existing server behavior is reused.
- [ ] **5. Commit:** `feat: add phone read models and ledger-safe planning commands`.

### Task 9: Focused phone navigation and Today

**Files:** Create `KitchenOSSiri/Sources/Phone/PhoneShell.swift`, `TodayView.swift`,
`TodayModel.swift`, `PhonePlanView.swift`, `PhonePlanModel.swift`, `ShopView.swift`,
`CookHubView.swift`; modify `KitchenOSSiriApp.swift`, `Shopping/ShoppingListView.swift`,
`Tasks/TasksView.swift`, `MealPlan/MealPlanView.swift`, `MealPlan/PlannerBoardView.swift`;
create `KitchenOSKit/Sources/KitchenOSKit/PhoneNavigation.swift`,
`KitchenOSKit/Tests/KitchenOSKitTests/PhoneNavigationTests.swift`.

**Interfaces:** `PhoneTab: String, CaseIterable` is `today, plan, shop, cook`;
`PhoneDestination` routes recipe identity, tasks by week/task ID, inventory by
name, settings and approved advanced-web paths. `TodayModel` loads KitchenBriefing;
`PhonePlanModel` loads WeekBoard plus legacy MealPlan for display fallback and
owns one in-flight mutation at a time. Models take provider/client inputs for
preview/testing, never manufacture URLs.

- [ ] **1. Write routing tests:**

```swift
func testPhoneHasFourFocusedDestinations() {
    XCTAssertEqual(PhoneTab.allCases.map(\.rawValue), ["today", "plan", "shop", "cook"])
}
```

Pin a shortened display name routing to the original recipe name; prep actions
route to their task/week; absent plan produces an Add/Find-food action; partial
briefing failure remains visible; split bundles route member edits correctly.
Add app-level model tests by adding a `KitchenOSAppTests` unit-test target to
`project.yml`, with sources `KitchenOSSiri/Tests` and a dependency on KitchenOSSiri;
create `KitchenOSSiri/Tests/PhoneFlowTests.swift`. Use injected asynchronous loaders
in TodayModel/PhonePlanModel so model tests require no server.

- [ ] **2. Run red:** package navigation tests and the new app unit-test target
  using an installed simulator selected with `xcodebuild -showdestinations`.
  Configure `schemes.KitchenOSSiri.test.targets` in `project.yml` to include
  `KitchenOSAppTests`, then regenerate the project; do not edit the generated
  project file.
- [ ] **3. Build the shell using existing native screens.** iPhone uses PhoneShell;
  keep the existing iPad presentation and Mac AppShell, with access to full
  planning. Preserve Spotlight/OpenRecipeIntent sheets and explicit navigation.

```swift
TabView {
    NavigationStack { TodayView() }.tabItem { Label("Today", systemImage: "sun.max") }
    NavigationStack { PhonePlanView() }.tabItem { Label("Plan", systemImage: "calendar") }
    NavigationStack { ShopView() }.tabItem { Label("Shop", systemImage: "cart") }
    NavigationStack { CookHubView() }.tabItem { Label("Cook", systemImage: "frying.pan") }
}
```

Today renders named meal slots, cached-prep availability, expiry and the immediate
action from the briefing. Keep each section's unavailable state distinct from
empty. Recipe rows open RecipeDetailView, which already renders ingredients and
steps. No automatic summary/LLM call is added. Settings is a toolbar destination;
Assistant is available from Today/Cook without a fifth tab.

Shop starts with the saved shopping-list read, then links inventory, receipt
history and `ConnectedWebSheet(path: "/receipt-paste", query: [])`. Label that
last action “Capture receipt” with an explanation that it uses the existing
photo-to-JSON/paste workflow; do not claim native camera/OCR support exists.
Keep preview/confirm as explicit online actions, separate from reading the saved
list. Show the saved markdown and purchase rows; inventory-match notes remain
plain information. No new checkbox-write API is required in this phase.

CookHub provides recipe search, existing pantry-based CookView and recent-opened
recipes (populated in Task 11). Use an honest empty state before recent history
exists. It links recipe cooking content and advanced tools without duplicating
server ranking logic.

PhonePlan displays the union of local and placed cooks by ID, filtered to the
selected week's placements, with bundle groups and fractional scales.
Offer add, move-within-week, per-cook scale and remove using Task 8's methods.
Cross-week moves and whole-bundle scaling remain advanced workflows. Legacy-only
weeks display parsed meal-plan content, with safe add through the import hook;
use the existing web planner for edits that need legacy conversion. The first
ledger action refreshes the board after success.

Remove whole-plan PUT paths from native MealPlanView/PlannerBoardView for
ledger-backed data: reuse PhonePlanModel's command methods or route the relevant
edit to the connected web planner. Preserve Mac/iPad full calendar planning.
An action must not submit unrelated slots. Dates use WeekDate range labels,
not ISO week IDs in human headings.

- [ ] **4. Run green:** package/app model tests; build iOS and macOS. Check large
  Dynamic Type, VoiceOver names, focus order, loading/errors and one-handed
  navigation on simulator. Apply relevant UI/accessibility skills at execution.
- [ ] **5. Commit:** `feat: add Today Plan Shop and Cook phone navigation`.

### Task 10: Disposable cache and kitchen-context boundaries

**Files:** Create `KitchenOSKit/Sources/KitchenOSKit/ReadSnapshotStore.swift`,
`ReadState.swift`, `KitchenReadRepository.swift`; create
`KitchenOSKit/Tests/KitchenOSKitTests/ReadSnapshotStoreTests.swift`,
`KitchenContextTests.swift`; extend `ClientProviderTests.swift`.

**Interfaces:** `SnapshotKey: Codable, Hashable` cases `today(String)`,
`plan(String)`, `shopping(String)`, `recipe(String)`; `SnapshotEnvelope<T: Codable>`
contains `schemaVersion: Int`, `context: ConnectionContext`, `key: SnapshotKey`,
`fetchedAt: Date`, `sourceModifiedAt: Date?`, `kitchen: KitchenContext`, `value: T`.
`ReadSnapshotStore` is an actor initialized with `directory: URL` and injectable
clock, with generic `load(_:context:as:)`, `save(_:)`, `invalidate(context:)`,
`markStale(keys:)`, `recentRecipeNames(context:)` and `recordRecipeOpened(name:context:)`.
Make ConnectionContext Codable. Staleness markers are cache metadata, never
pending mutations. `KitchenReadRepository` owns store/provider access and exposes
read streams in Task 11.

- [ ] **1. Pin identity/rollover and eviction tests:**

```swift
func testSnapshotKeysKeepRecipeIdentity() {
    XCTAssertNotEqual(SnapshotKey.recipe("Chicken Caldo A"), .recipe("Chicken Caldo B"))
    XCTAssertNotEqual(SnapshotKey.plan("2026-W39"), .plan("2026-W40"))
}
```

Use temporary directories to test write/read after recreating the store, corrupt
JSON, wrong schema, wrong credential revision, old-profile response, 21 opened
recipes evicting the least recently opened, repeated open updating recency,
Unicode filenames and names containing `/../`. A route change keeps snapshots;
a profile/token change invalidates them. Travel the device time zone and test
kitchen midnight, ISO year/week boundaries and DST using KitchenContext.timezone.
Never derive a new context by adding a fixed 24-hour interval.

- [ ] **2. Run red:** `swift test --package-path KitchenOSKit --filter 'ReadSnapshotStoreTests|KitchenContextTests'`.
- [ ] **3. Implement bounded atomic storage.** Use Application Support with backup
  exclusion for disposable cache data. Derive filenames from a cryptographic
  hash of encoded key/context (CryptoKit is a system framework), not recipe text.
  Store no token/hash of token. Credential revision is an opaque counter updated
  by the provider, not reversible secret material.

```swift
let bytes = try JSONEncoder().encode(envelope)
try bytes.write(to: destination, options: .atomic)
// destination is derived from context + encoded SnapshotKey inside the cache root.
```

Writes are conditional on the current provider context: compare before saving
and after network completion. The store must not recreate an invalidated profile
namespace because an old operation arrived late. Persist the current accepted
context/revision and serialize generation checks with writes. Failed decoding or
schema mismatch removes only that cache entry. A disk-full/cache-write error must
not turn a successful server write into a failed/retryable mutation.

Bound recipe snapshots/history to 20 opened identities. Keep the newest
successfully fetched Today date, plan week and shopping week; retain the prior
snapshot until replacement succeeds, with its actual key. History may remember
an opened recipe even before its fetch succeeds, but offline eligibility requires
a valid recipe snapshot. Do not cache search results or inventory as new domains.

- [ ] **4. Run green:** store/context/provider tests. Inspect encoded fixture files
  for only documented fields and verify corrupt entries degrade to cache misses.
- [ ] **5. Commit:** `feat: persist bounded read snapshots with profile isolation`.

### Task 11: Freshness UI, read reconciliation and offline gates

**Files:** Extend `KitchenReadRepository.swift`, `ReadState.swift`,
`KitchenOSClientProvider.swift`; create
`KitchenOSSiri/Sources/Connection/FreshnessView.swift`; modify Phone models/views,
`Recipes/RecipeDetailView.swift`, `Shopping/ShoppingListView.swift`, `Tasks/TasksView.swift`,
`Inventory/InventoryView.swift`, `Inventory/PantryView.swift`, `Meals/MealsView.swift`,
`Receipts/ReceiptsView.swift`, `Connection/ConnectedWebSheet.swift`;
create `KitchenOSKit/Tests/KitchenOSKitTests/KitchenReadRepositoryTests.swift` and
`KitchenOSSiri/Tests/OfflineFlowTests.swift`.

**Interfaces:** `ReadState<T>` contains `value: T?`, `fetchedAt: Date?`,
`freshness: Freshness` (`loading`, `cached`, `live`, `offline`, `stale`),
`error: KitchenOSError?`; cached data with HTTP/auth errors remains `stale`, not
`offline`. `KitchenReadRepository` exposes `today()`, `plan(week:)`,
`shopping(week:)`, `recipe(name:)` as `AsyncStream<ReadState<T>>` with typed payloads
from Tasks 7–8. Plan snapshot payload is `PhonePlanSnapshot: Codable` containing
`board: WeekBoard`, `legacy: MealPlan`; do not serialize native View state.

`MutationAvailability` is `checking`, `online`, `offline`, `blocked`; it gates
mutation controls but does not prove a write will succeed. Provider invalidation
sets `checking`, successful resolution sets `online`, failure sets offline/blocked
according to classification. Existing authorized writes still run through the
transport's before-dispatch checks. An in-flight write is never canceled and
resent merely because this presentation state changes.

- [ ] **1. Add stream/order and mutation-gate tests:**

```swift
func testOfflineReadDoesNotEnableWrites() {
    XCTAssertFalse(MutationAvailability.offline.canMutate)
    XCTAssertFalse(MutationAvailability.checking.canMutate)
    XCTAssertFalse(MutationAvailability.blocked.canMutate)
    XCTAssertTrue(MutationAvailability.online.canMutate)
}
```

Use injected read closures to record emitted states: cached snapshot first, then
live after success; cached then offline after connection failure; cached then
stale+401 after rejection; no cache then unavailable with the real error. Change
profile mid-fetch and assert no value emission/save from the old request. Foreground
at kitchen midnight must not relabel yesterday's payload. Exercise partial Today
sections independently: a live response with stale prep cannot label prep live.

Test successful write + refresh failure (save remains successful, data becomes
stale), unknown write + read refresh (zero replays), cancellation (no offline
banner), cache disk failure, and rapid selection from recipe A to B (A must not
replace B). App tests verify disabled controls actually block actions, not merely
change opacity.

- [ ] **2. Run red:** repository tests and app OfflineFlowTests.
- [ ] **3. Implement cache-first streams and mutation effects.** Capture context
  before loading; emit only while it remains current. Reuse the server's kitchen
  context for current date/week. Until a first context exists, show loading/no
  saved context rather than guessing Today from the phone's time zone. Permit
  read-only access to the prior cached week with its real date label.

```swift
struct FreshnessView: View {
    let label: String
    let fetchedAt: Date?
    var body: some View {
        VStack(alignment: .leading) {
            Text(label)
            if let fetchedAt { Text(fetchedAt, style: .relative) }
        }
        .font(.caption)
        .accessibilityElement(children: .combine)
    }
}
```

Use labels “Saved copy · updating”, “Offline · saved copy”, “Could not refresh”
and “Updated”; show a concrete timestamp in detail. Errors stay visible alongside
usable saved content. For missing Today subsections, honor the server's degraded
labels and prep state. Remove optimistic task/plan mutations that can look
confirmed after an ambiguous response. A temporary busy state is sufficient.

Confirmed or uncertain writes invalidate these keys before read reconciliation:

| Mutation | Mark stale / refresh |
| --- | --- |
| Cook, bundle, placement, plan | Affected weeks' plan and shopping; Today |
| Task completion | Today and cached prep presentation |
| Inventory / receipt commit | Today, current shopping; discard recipe snapshots' inventory-presence annotations |
| Shopping generate/confirm | Current shopping; Today if confirmation spends inventory |
| Profile / token update | All snapshots for the prior context; reload navigation models |

Conservative invalidation is allowed; never attach a pending write to a cache
record. Recipe ingredients/instructions remain readable when inventory annotations
are stale: hide those annotations or label them separately. Ordinary loads of
inventory, receipts and search have no offline cache promise; show unavailable
with links back to saved screens.

Wire recipe-open history to successful navigation, preserving filename identity.
Connect CookHub recent items to that history; only entries with saved detail are
advertised as available offline. Gate all reachable mutation controls, including
Siri actions, assistant-confirmed adds and embedded web entry/reload; already open
web pages show connection loss and do not automatically submit again. Re-enable
only after current resolution succeeds. Explicit user retries are new actions,
not an invisible queue.

- [ ] **4. Run green:** package/app tests, then cold-launch with injected offline
  transport after storing fixtures. Verify recipe instructions, list, plan and
  Today render with visible timestamps and disabled writes.
- [ ] **5. Commit:** `feat: show cached phone reads and reconcile uncertain changes`.

### Task 12: Integration verification and observed-friction handoff

**Files:** Update `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/OPERATIONS.md`,
`README.md`; create `docs/phone-access-validation.md`. Add regression assertions
only to the owning test files above when a new failure is found.

**Interfaces:** No new product interface. Produce a verification record with
revision/build, device/OS, connection mode, scenario, observed result and outstanding
limits. Stage 6 input is a short record of actual repeated taps, failed actions or
confusing states in Shop/Cook/Capture, not a speculative feature backlog.

- [ ] **1. Run automated checks** and record the full exit status:

```bash
swift test --package-path KitchenOSKit
.venv/bin/python -m pytest tests/test_phone_reads.py tests/test_kitchen_briefing.py tests/test_api_kitchen_briefing.py tests/test_api_auth.py tests/test_task_extractor.py tests/test_api_ledger.py tests/test_meal_bundle.py tests/test_shopping_list_generator.py -q
xcodegen generate
xcodebuild build -scheme KitchenOSSiri -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
xcodebuild build -scheme KitchenOSSiri -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO
xcodebuild -showdestinations -scheme KitchenOSSiri
```

Run app tests using the concrete installed simulator destination from the last
command, not an invented device ID. Ensure the generated scheme includes
KitchenOSAppTests, and use that scheme for tests. Follow the repository's full-suite
finish-feature checks before integration. If a baseline failure reproduces
unchanged, record that evidence separately instead of claiming a green suite.

- [ ] **2. Audit production construction and mutation paths:**

```bash
rg -n 'KitchenOSClient\(config: \.resolved\(\)\)|KitchenOSConfig\.resolved\(' KitchenOSKit/Sources KitchenOSSiri/Sources
rg -n 'putMealPlan\(|saveMealPlan\(|URLSession.shared|baseURL' KitchenOSSiri/Sources KitchenOSKit/Sources/KitchenOSKit/Intents
```

Inspect every match. Settings/web/intent consumers must use the provider; data
mutation paths must not send whole-week legacy data over ledger content.
Document legitimate extraction/image transport separately from domain dispatch.
Run `git diff --check` and inspect the final diff against the preserved baseline.

- [ ] **3. Verify on a physical iPhone** with the user-authorized installed build.
  Record results for: home LAN with VPN unavailable; local failure with VPN ready;
  cellular; another Wi-Fi; return home; foreground after sleep; denied local-network
  permission; both routes unavailable; server asleep; wrong token; cold-start Siri;
  route switch while a read is pending; route switch during a write; unsaved web
  edits; cold offline app launch; date/week rollover; fractional/split bundle edits.
  Measure local and fallback latency against the initial 2/4-second probe budgets.
  Check large text and VoiceOver on the four destinations. Do not modify device
  VPN settings without the user's operational authorization; give exact setup
  instructions if direct device access is unavailable.
- [ ] **4. Confirm current server truth after mutations** through fresh reads:
  no duplicate cook/receipt, unchanged unrelated scales/placements, no inventory
  decrement from merely reading/generating the shopping list, and no write after
  an offline tap. Use test fixtures for deliberately induced lost responses;
  avoid manufacturing ambiguous writes against live kitchen inventory.
- [ ] **5. Record rollout and remaining device limitations.** Include measured
  results, timestamp and exact build. Preserve pending device checks as not run,
  never checked boxes. Restart the API only as part of applying the feature to
  the running service, verify its health, then install the app through the
  established build/deploy procedure when authorized.
- [ ] **6. Commit docs:** `docs: record phone connectivity and offline verification`.

## Plan self-review and execution boundary

Coverage: resolver/configuration (1–2), request safety/shared clients (3–5),
diagnostics/VPN instructions (6), backend reuse/context (7), ledger and fractional
identity (8), native navigation/advanced surfaces (9), bounded caching (10),
freshness/offline/reconciliation (11), device verification and stage-6 observation
(12). No public hosting, data-store replacement, queued writes or new LLM renderer
is included.

Before implementation, review this plan and choose **subagent-driven** or
**native** execution. Subagent-driven execution is recommended here because the
transport, web origins, ledger writes and cache generations have distinct failure
modes worth reviewing before later tasks depend on them. Tasks still run in
order; parallel implementation of shared interfaces is not implied.
