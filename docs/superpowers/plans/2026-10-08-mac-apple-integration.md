# KitchenOS Mac Apple Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the native Mac app publish and reconcile KitchenOS shopping/prep reminders and scheduled cooking with Apple apps, using the same operations from App Intents.

**Architecture:** Python owns source state, revisions, conflict decisions, and the durable operation journal. One Mac owns EventKit access and applies server-authorized work; package-tested Swift orchestration serializes native UI, App Intents, and lifecycle triggers. Existing shopping notes, task sidecars, and the serving ledger retain their authority.

**Tech Stack:** Python 3.11 through `.venv/bin/python`, Flask, SQLite, Swift 5 language mode with Swift tools 6, SwiftUI, App Intents, EventKit, macOS/iOS 26.0, pytest, Swift Testing/XCTest, XcodeGen.

**Spec:** [Approved Mac integration design](../specs/2026-10-08-mac-apple-integration-design.md). Read it alongside this plan.

## Global Constraints

- “One designated Mac owns the Apple integration.”
- “Completion records shopping progress only. It never adds inventory, decrements pantry stock, infers a receipt, or logs cooking.”
- “Markdown remains authoritative for membership, title, quantity, and checked state.”
- “No Apple content goes to an LLM.”
- “Never clear a whole list/calendar. Each mutation verifies ownership of the specific object.”
- “Do not hold DB transactions across EventKit or network operations.”
- “Existing constraints remain: 15-minute start increments; 15–360 minute durations in 15-minute steps; finish by midnight; no cross-week moves; no scheduling cooked rows or bundle members.”
- “First-run permission/destination needs continue in the foreground app.”
- “Keep iOS building and able to show integration status without introducing a second EventKit writer.”
- Keep both deployment floors at **26.0**, use the path helpers and existing API token policy, and preserve all recipe/ledger/inventory invariants in `AGENTS.md`.
- Never use production DB/vault data for mutation tests. Run finish-feature and verification-before-completion before implementation commits; run existing required checks without broad unrelated refactors.

## Review Focus

1. Copy/paste duplicates a hidden shopping ID: no first-match/all-match checkbox update; Task 2 tests duplicate identity and different-food edits.
2. A reminder due date has no time, or crosses a DST change: preserve date-only semantics; Tasks 3 and 6 test both.
3. An exported event moves outside its original query window or changes account ID: uncertain absence is not deletion; Tasks 6–7 test locator recovery and unavailable observations.
4. The app crashes after saving Apple data but before acknowledging it, or overlapping intents run during an await: recover the one object and serialize work; Tasks 1 and 7 test both.
5. An external editor writes between the last hash check and file replacement: do not claim atomic compare-and-swap; Task 2 tests captured recovery content and the documented residual limitation.

## Checkout and delivery boundaries

Planning was performed on `codex/calendar-meal-planning`, with the approved spec committed as `f446386` before its approval-status update. The working tree contains prerequisite calendar/scheduling code and unrelated receipt/config changes. **Do not reset, stash, or commit the entire tree.**

At execution, use using-git-worktrees: inspect attached checkouts, reuse a suitable isolated checkout or create one from the current branch's commit. If creating a new checkout, copy the prerequisite working-tree deltas and untracked files explicitly; normal worktree creation does not copy them. Record a manifest of inherited changes and separate subsequent feature diffs. Required prerequisites are the existing calendar snapshot/schedule code, its API/DB edits, Swift calendar models/views/settings, resources/package change, static planning assets, and their tests. Preserve unrelated edits at their source. Resolve runtime dependencies/data with the existing main-worktree data rules; never run main's code in a branch test.

Before any feature edit, run the relevant prerequisite tests and macOS/iOS build checks below. Fix only prerequisites that block this approved integration, recording them distinctly. No initial connection or deployment may publish historical data, choose destinations, or schedule real meals.

This is one dependent integration, delivered in reviewable slices. Tasks 2–4 depend on Task 1; Task 5 connects them. Tasks 6–7 add the Apple adapter/loop; Tasks 8–10 finish user entrypoints and delivery. Do not run workers concurrently in shared files such as `api_server.py`, `inventory_db.py`, or `project.yml`.

## File structure and shared contracts

| Responsibility | Files |
| --- | --- |
| Versioned DTOs, merge decisions, durable state | New `lib/apple_integration/{__init__,models,merge,store}.py`; extend `lib/inventory_db.py` |
| Recoverable note edits and shopping identity | New `lib/note_mutation.py`, `lib/shopping_note.py`; existing shopping generator/template and two API writers |
| Source adapters and bridge routing | New `lib/apple_integration/{shopping,prep,cooking,service,routes}.py`; existing task extractor and serving ledger |
| Swift DTOs, client, protocol, serialized service | New `KitchenOSKit/Sources/KitchenOSKit/AppleIntegration/{AppleIntegrationModels,AppleIntegrationClient,AppleItemStore,AppleIntegrationService}.swift` |
| EventKit and app lifecycle | New `KitchenOSSiri/Sources/AppleIntegration/{EventKitAppleItemStore,AppleIntegrationCoordinator,AppleIntegrationSettingsView}.swift`, `Sources/AppLifecycle/KitchenOSAppDelegate.swift` |
| Native links and intent entrypoints | New package `KitchenOSDeepLink.swift`, app `Shell/AppRouter.swift`, app `Intents/AppleIntegrationIntents.swift`; existing shell/views/plists |

### Wire contract owned by Task 1

Use snake_case JSON and matching `CodingKeys` in Swift; model version is integer `1`. Domain is `shopping | prep | cooking`; weeks remain exact ISO keys internally.

- `DueValue = null | {date: YYYY-MM-DD, time: HH:MM|null, timezone: IANA-name|null}`. Date-only values have null time/timezone. A timed value requires both time and timezone. Null explicitly clears an override.
- `SourceItem(logical_id: str, domain: str, week: str, title: str, fields: dict, source_revision: str, state: str)`. `source_revision` is a SHA-256 of canonical relevant source values, not mtime. States: `active`, `retired`, `history`, `conflict`. Reminder fields are `completed` and `due`; cooking fields are `start` (offset-bearing ISO timestamp), `timezone`, `duration_minutes`. Source IDs and route data remain server-side.
- `SyncItem`: source plus `revision: int`, `generation: int`, `token: UUID`, `destination_id: str`, `locator: Locator|null`, `common_fields: dict|null`, `state` (also `suppressed`). Tokens are random and unique per export generation.
- `Locator = {calendar_id: str, item_id: str, external_id: str|null}`. Never use these as logical IDs.
- `Observation = {token, generation, revision, availability: present|missing|unavailable, locator, title, fields, absence_confirmed: bool}`. Only the native adapter may assert a confirmed absence after complete readable-store reconciliation. Invalid all-day/recurring event shapes are reported as conflicts, not coerced.
- `AppleOperation = {operation_id: UUID, token, generation, revision, action: upsert|delete, destination_id, locator, title, fields, expected_apple_hash: str|null}`. Expected Apple hash is checked again immediately before applying; drift returns a new observation instead of overwriting.
- `SyncReport = {created: int, updated: int, deleted: int, queued: int, conflicts: int, unavailable: int, last_success: str|null}`. Never call queued work delivered.
- `BridgeContext = {owner_id: UUID, owner_generation: int}`; mutations include an operation/idempotency UUID and expected item/scope revision. Keep pending work separate from acknowledged common values.
- `ScopeRequest = {domain, week, destination_id, state: active|paused|archived, expected_revision: int}`; `WorkBatch = {context: BridgeContext, items: [SyncItem], operations: [AppleOperation]}`; `OperationAck = {operation_id, outcome: saved|deleted|changed|failed, locator, observed_fields, observed_hash}`. `IntegrationStatus` carries the report plus per-domain permissions/destinations, scope states, and bounded conflict summaries. `ConflictResolution = {conflict_id, choice, expected_revision}`.

Ownership links use **`kitchenos-native://item/<token>`**, with a strict UUID path and no write action. This avoids taking over the older `kitchenos://` helper's registrations. The link resolves source destination through the API; possession of a token is not authorization to mutate anything.

## Task 1: Durable sync contracts, merge decisions, and journal

**Files:** Create `lib/apple_integration/{__init__,models,merge,store}.py`, `tests/test_apple_sync_store.py`, `tests/test_apple_sync_merge.py`; modify `lib/inventory_db.py`, `tests/test_inventory_db.py`.

**Interfaces:** Produce the wire types above; `merge_fields(common: dict, source: dict, apple: dict) -> MergeDecision(source_patch: dict, apple_patch: dict, conflicts: list[str])`; `store.register_owner(owner_id: str) -> BridgeContext`; `store.activate_scope(domain: str, week: str, destination_id: str) -> dict`; `store.refresh_source(item: SourceItem) -> SyncItem`; `store.reserve_operation(item: SyncItem, action: str, expected_apple_hash: str|None) -> AppleOperation`; `store.acknowledge(context: BridgeContext, operation_id: str, locator: Locator|None, observed_fields: dict) -> SyncItem`. All mutating helpers accept optional keyword `conn` to borrow an existing transaction. Produce typed `RevisionConflict`, `OwnershipConflict`, `InvalidPayload`, and `SourceUnavailable` errors. A source adapter throws `SourceUnavailable` for missing/stale/unsafe source data, distinct from a successfully read empty source.

- [ ] **Write failing tests** with fixtures that call the real temporary DB. Pin these assertions:

  ```python
  decision = merge_fields({'completed': False}, {'completed': True}, {'completed': False})
  assert decision.apple_patch == {'completed': True}
  assert decision.source_patch == {} and decision.conflicts == []
  # Repeated reserve/ack with the same operation UUID changes neither generation nor count.
  # Divergent due dates from a common date produce conflicts == ['due'].
  # An old owner/generation/revision cannot acknowledge a replacement item.
  ```

- [ ] **Run red:** `.venv/bin/python -m pytest -q tests/test_apple_sync_store.py tests/test_apple_sync_merge.py` must fail on missing interfaces, not on personal data access.
- [ ] **Implement contracts and persistence.** Add entirely new tables to `_SCHEMA`: `apple_bridge` (singleton owner/generation/pause), `apple_scopes` (domain/week/destination/status/revision), `apple_items` (logical ID/generation/token/source and common payloads/locator/state/revision), `apple_operations` (UUID/expected revisions/payload/status/result), `apple_conflicts` (item/field/base/source/apple/status), and `apple_file_edits` (operation/path/hashes/before/after/status). Use unique tokens and operation UUIDs; `reserve_operation` reuses outstanding identical work for `(token, generation, revision, action, expected_apple_hash)`. Retain retired generations for stale-callback rejection. Use `write_transaction`; do not add indexes on migrated columns before `_migrate`. Name the acknowledgement retry test `test_ack_retry_keeps_generation`.
- [ ] **Implement three-way field merging.** Unknown keys, malformed dates, nonfinite numbers, duplicate observation tokens, and revision mismatch fail closed. A first export has no common state; finding an unexplained existing marker enters recovery rather than treating it as a blank object. Keep user-title overrides and item suppression distinct from source content. Completed history is detached from future mutations.
- [ ] **Run green:** the new files plus `tests/test_inventory_db.py`. Verify upgrade from the old schema and rollback under concurrent stale writers, crash/retry reservation reuse, and durable pending work after reconnect.
- [ ] **Commit only this slice** after required checks: `feat: add durable Apple sync state`.

## Task 2: Stable shopping rows and recoverable file changes

**Files:** Create `lib/note_mutation.py`, `lib/shopping_note.py`, `lib/apple_integration/shopping.py`, `tests/test_note_mutation.py`, `tests/test_shopping_sync.py`; modify `lib/shopping_list_generator.py`, `templates/shopping_list_template.py`, `api_server.py` (`generate_shopping_list_endpoint`, `api_shopping_list_confirm`), and existing shopping/template/API tests.

**Interfaces:** Consume Task 1's journal/types. Produce `mutate_note(path: Path, expected_hash: str, transform: Callable[[str], str], operation_id: str) -> str` (returns new hash); `recover_note_edits() -> list[str]` (conflicting operation IDs); `ShoppingRow(id: str, kind: str, text: str, completed: bool, identity: str|None)`; `read_shopping_note(week: str) -> ShoppingDocument(rows: list[ShoppingRow], content_hash: str)`; `save_shopping_note(week: str, generated_lines: list[dict], inventory_matches: list[dict], selected_items: list[str]|None=None) -> ShoppingDocument`; adapter `shopping.collect(week: str) -> list[SourceItem]`, `shopping.apply(item: SyncItem, patch: dict, operation_id: str) -> SourceItem`.

- [ ] **Write failing tests:** marker stripping in every existing parser/send path, generated quantity change preserving ID, distinct identical manual rows, preservation on both save endpoints. Include `test_duplicate_markers_never_toggle` and `test_generated_identity_edit_preserves_content_and_conflicts`, with these key checks:

  ```python
  assert before.rows[0].id == regenerated.rows[0].id
  assert regenerated.rows[0].completed is True
  assert reminder_completion_inventory_after == reminder_completion_inventory_before
  # Duplicate marked IDs raise RevisionConflict and leave the file byte-identical.
  # Editing a marked flour row to eggs never carries flour's completion/export identity.
  # A completed quantity change creates shopping_amount_changed, not silent reopening.
  ```

- [ ] **Run red:** `.venv/bin/python -m pytest -q tests/test_note_mutation.py tests/test_shopping_sync.py`.
- [ ] **Implement one row-aware writer** for both API save paths. Derive generated IDs before conversion to display strings using normalized ingredient plus aggregator family; use hidden `<!-- kitchenos-item:<id> -->` markers with validated `gen:`/`manual:` prefixes and bounded IDs. Retain the old parser's `items`, `skipped`, and generated-metadata fields for compatibility. Migrate v1/v2 provenance; preserve manual duplicates, checked rows, and plain inventory bullets. Confirmation may still apply its explicit pantry decisions; generation/Apple activation never calls that spending path.
- [ ] **Implement note mutation/recovery.** Add per-path locks shared by all cooperating writers (including a filesystem advisory lock for separate Python processes), unique sibling temporary files, recoverable input/output bytes in the journal, input-hash checks, and atomic replacement. Recovery accepts current bytes equal to before or after; anything else becomes a conflict. Record only known file paths under configured vault roots. Test an external edit before the final hash check and `test_external_edit_between_check_and_replace_is_not_claimed_recoverable`; never assert recovery of bytes the process could not observe.
- [ ] **Implement the shopping adapter** with stable generations, changed-completed-quantity conflicts, due-date override metadata, deletion/suppression rules, and exact-ID completion. Read paths never perform migration implicitly. Read existing completed history when retiring rows; source payload is unavailable if the note cannot be safely parsed.
- [ ] **Run green:** `.venv/bin/python -m pytest -q tests/test_note_mutation.py tests/test_shopping_sync.py tests/test_shopping_list_template.py tests/test_shopping_list_generator.py tests/test_api_endpoints.py`. Verify file rollback/recovery and unchanged inventory tables.
- [ ] **Commit:** `feat: preserve shopping identity for reminder sync`.

## Task 3: Prep completion and due-date round trips

**Files:** Create `lib/apple_integration/prep.py`, `tests/test_prep_sync.py`; modify `lib/task_extractor.py`, `tests/test_task_extractor.py`.

**Interfaces:** Consume Task 1/2 types and file journal. Produce `prep.collect(week: str) -> list[SourceItem]`, `prep.apply(item: SyncItem, patch: dict, operation_id: str) -> SourceItem`. Extend `mark_task_done(week: str, task_id: str, done: bool=True, *, expected_hash: str|None=None, operation_id: str|None=None)` preserving existing callers/return behavior. All sidecar writers use one per-week mutation lock and the shared recoverable writer.

- [ ] **Write failing tests** for done/un-done, regeneration preserving same IDs, moved-task retirement, and `test_due_override_does_not_move_meal`:

  ```python
  assert after['task_id'] == before['task_id']
  assert after['done'] is True
  assert moved_task_id != before['task_id']
  assert due_override == {'date': '2026-11-01', 'time': None, 'timezone': None}
  # A stale source hash refuses the completion, and due changes do not move the meal.
  ```

- [ ] **Run red:** `.venv/bin/python -m pytest -q tests/test_prep_sync.py`.
- [ ] **Implement safe sidecar updates.** Serialize `_save_sidecar`, regeneration's final merge, and `mark_task_done`; run any model extraction outside the lock, then re-read/merge current done flags under the lock. Preserve the `sidecar_mtime >= plan_mtime` freshness rule. Polling collects a fresh cache only; missing/stale task data requests refresh, never retires every reminder. Explicit activation may invoke the existing bounded generation path once; periodic reconciliation must not repeatedly invoke an LLM.
- [ ] **Implement adapter fields.** Initial due dates come from actual task dates. Persist Apple due overrides as sync metadata, including explicit null clearing. Treat date-only and timed dates distinctly. Mark retired-ID reminders for safe cleanup or conflict without carrying completion to new IDs.
- [ ] **Run green:** `.venv/bin/python -m pytest -q tests/test_prep_sync.py tests/test_task_extractor.py tests/test_note_mutation.py`.
- [ ] **Commit:** `feat: reconcile prep reminders safely`.

## Task 4: Calendar writeback through ledger transactions

**Files:** Create `lib/apple_integration/cooking.py`, `tests/test_cooking_sync.py`; modify `lib/serving_ledger.py`, `api_server.py` (schedule/delete-schedule), `tests/test_cook_schedule.py`.

**Interfaces:** Produce `unschedule_cook(cook_id: int, *, conn: sqlite3.Connection|None=None) -> dict`; extend `schedule_cook` with optional borrowed `conn` while preserving all existing parameters/results. Refactor shared internals instead of duplicating move/capacity rules. Produce `cooking.collect(week: str) -> list[SourceItem]`, `cooking.apply(item: SyncItem, patch: dict, operation_id: str, *, conn=None) -> SourceItem`.

- [ ] **Write failing tests:** use existing `cook()`/`args()` fixtures and temporary inventory snapshots.

  ```python
  before = sl.get_cook(cook_id)
  sl.unschedule_cook(cook_id)
  assert sl.get_cook(cook_id) == before
  assert sl.schedules_for_week('2026-W39') == []
  # Retrying unschedule is a no-op; a missing cook is a typed validation failure.
  # Calendar moves preserve scale, cooked_at, home counts and unrelated leftovers.
  ```

- [ ] **Run red:** `.venv/bin/python -m pytest -q tests/test_cooking_sync.py tests/test_cook_schedule.py`.
- [ ] **Implement transaction borrowing** using the established owner/borrower pattern. Recompute the source revision under the same `BEGIN IMMEDIATE` transaction that validates and updates the cook; bridge item revision/journal updates participate in that transaction. Existing standalone callers retain owned transactions. Regenerate meal-plan views after commit and record recoverable pending view work before declaring success.
- [ ] **Implement adapter validation and lifecycle.** Bind logical ID to cook ID, retain meal slot, convert instants using its IANA timezone, and delegate scheduling to the one ledger authority. Reject cross-week/all-day/recurring/invalid-duration edits as conflicts. Detect cooked/source-deleted/history states before applying stale observations. Deleting an event calls only unschedule. No automatic placement is added to an already scheduled cook.
- [ ] **Run green:** `.venv/bin/python -m pytest -q tests/test_cooking_sync.py tests/test_cook_schedule.py tests/test_serving_ledger.py tests/test_api_ledger.py tests/test_planning_calendar.py tests/test_cooking_windows.py`. Include spring/fall DST, simultaneous ordinary cook edits, no self-blocking reservations, and rollback of stale writeback.
- [ ] **Commit:** `feat: support safe Calendar cooking writeback`.

## Task 5: Authenticated bridge API and existing send entrypoints

**Files:** Create `lib/apple_integration/service.py`, `lib/apple_integration/routes.py`, `tests/test_apple_integration_api.py`; modify `api_server.py`, `shopping_list.py`, `lib/mcp_tools.py` only if response handling requires it, `tests/test_api_auth.py`, sender/API tests, `docs/API.md`.

**Interfaces:** `register_routes(app, require_token) -> None`; service `activate(domain: str, week: str, destination_id: str) -> SyncReport`, `work(context: BridgeContext) -> dict`, `observe(context: BridgeContext, observations: list[Observation], request_id: str) -> list[AppleOperation]`, `acknowledge(context: BridgeContext, operation_id: str, result: dict) -> SyncReport`, `resolve_conflict(conflict_id: str, choice: str, expected_revision: int) -> SyncReport`. Compose adapters from Tasks 2–4; no second merge algorithm in Swift.

Endpoints under `/api/apple-integration`:

| Method/path | Contract |
| --- | --- |
| `POST /owner` | Register/reconnect one localhost Mac; reject replacement until explicitly disconnected/quiescent |
| `DELETE /owner` | Disconnect the quiescent current writer, preserve objects, invalidate its generation |
| `PUT /settings` | Set global paused state using expected settings revision |
| `PUT /scopes/<domain>/<week>` | Activate/pause/archive selected destination, expected revision |
| `GET /status` | Domain permission reports, counts, pending/conflict summaries, last success |
| `GET /work` | Desired active items, pending ops, and scopes for registered local bridge |
| `POST /observations` | Bounded observations + owner context + request UUID; source merges and returned Apple operations |
| `POST /operations/<uuid>/ack` | Save/delete/failure result plus current locator/observed hash |
| `POST /conflicts/<uuid>/resolve` | `keep_kitchenos`, `keep_apple`, `keep_manual`, or `restore` as applicable; expected revision |
| `POST /items/<token>/restore` | Explicitly restore a suppressed item with expected revision and new generation |
| `POST /items/remove-owned` | Explicit bounded token list; reserve verified per-object deletion operations |
| `GET /links/<token>` | Read-only typed destination `{domain, week, source_id, state}` for native deep links |

- [ ] **Write failing API tests** with remote/local clients: bad bearer is 401, nonlocal owner/work/observation/ack calls are rejected even with the general token, malformed JSON is 400, stale revision is 409, oversized JSON is 413. Configure a test API token; preserve the existing decorator's documented behavior rather than accidentally changing all API auth.
- [ ] **Run red:** `.venv/bin/python -m pytest -q tests/test_apple_integration_api.py`.
- [ ] **Implement version-1 routes** using the existing `register_routes(app, require_token)` pattern, 2 MiB request limits and at most 5,000 items per complete batch. Oversized/incomplete batches fail atomically; never treat truncation as deletion. Add local bridge checks independently of remote token checks. Validate the URL path week/domain against payloads and never accept caller-selected file paths.
- [ ] **Implement observation application.** Re-read source revisions; merge by field, journal imports, reserve outbound ops, and advance common fields only after verified application. Permission failures and uncertain absence create unavailable status. Handle suppression, retired generations, completed history, moved locators, display overrides, and all conflict choices. Keep an existing object's user-selected destination when updating other fields; configured defaults select destinations for new exports, not a command to move existing objects back. Archiving/disconnecting leaves Apple data; explicit remove-owned requests use the same verified per-item operations.
- [ ] **Unify send entrypoints.** `/send-to-reminders`, `/api/prep/reminders`, and the CLI enqueue native scope work when configured; otherwise retain argv-safe fallback. Never fall back to AppleScript just because the native owner is offline/paused. Existing legacy items have no proven ownership and are not auto-adopted or deleted. Gate touched sender, shopping-confirm, and task-done routes; update only their auth allowlist entries and test the non-`/api/` sender explicitly. Add truthful queued/delivered fields without breaking legacy success consumers.
- [ ] **Run green:** `.venv/bin/python -m pytest -q tests/test_apple_integration_api.py tests/test_api_auth.py tests/test_api_endpoints.py tests/test_reminders.py` plus the new adapter tests. Verify no Apple subprocess runs in native mode and no personal event text enters logs/prompts.
- [ ] **Commit:** `feat: expose authenticated Apple integration API`.

## Task 6: Swift client contract and EventKit adapter

**Files:** Create package `AppleIntegration/AppleIntegrationModels.swift`, `AppleIntegrationClient.swift`, `AppleItemStore.swift`; app `AppleIntegration/EventKitAppleItemStore.swift`; tests `AppleIntegrationClientTests.swift`, `AppleIntegrationModelsTests.swift`, `FakeAppleItemStore.swift` under `KitchenOSKit/Tests/KitchenOSKitTests`; modify `KitchenOSSiri/Info-macOS.plist`.

**Interfaces:** Swift Codable/Sendable equivalents of Task 1 DTOs. `AppleIntegrationClient.init(client: KitchenOSClient)` exposes async throwing `registerOwner(_ id: UUID) -> BridgeContext`, `setScope(_ request: ScopeRequest) -> SyncReport`, `status() -> IntegrationStatus`, `work(context: BridgeContext) -> WorkBatch`, `observe(_ observations: [Observation], context: BridgeContext, requestID: UUID) -> [AppleOperation]`, `acknowledge(_ ack: OperationAck, context: BridgeContext) -> SyncReport`, `resolve(_ resolution: ConflictResolution) -> SyncReport`, `setPaused(_ paused: Bool, expectedRevision: Int) -> SyncReport`, `disconnect(context: BridgeContext) -> SyncReport`, `restore(token: UUID, expectedRevision: Int) -> SyncReport`, and `removeOwned(tokens: [UUID], expectedRevision: Int) -> SyncReport`.

`@MainActor public protocol AppleItemStore` exposes `authorization(for: AppleDomain) -> AppleAuthorization`, `requestAccess(for:) async throws -> AppleAuthorization`, `destinations(for:) async throws -> [AppleDestination]`, `createDestination(name: String, domain: AppleDomain) async throws -> AppleDestination`, `observe(_ items: [SyncItem]) async throws -> [Observation]`, `apply(_ operation: AppleOperation) async throws -> OperationAck`. Add `availabilitySnapshot(firmID: String, flexibleID: String, excludingOwnedTokens: Set<UUID>) async throws -> PlanningCalendarSnapshot` for the shared calendar reader. Only DTOs cross actors; never `EKEvent`/`EKReminder`.

- [ ] **Write failing package tests** for exact wire JSON, auth headers, 409/413 mapping, null due clearing, `dueDateOnlyDoesNotShiftOnDST` using `2026-11-01`, malformed dates, and `locatorRecoveryOutsideWeekDoesNotDelete`. Fake store records write calls and permission requests without opening EventKit.
- [ ] **Run red:** `swift test --package-path KitchenOSKit --filter AppleIntegration`.
- [ ] **Implement DTO/client/protocol** using current SDK documentation. Keep source-revision strings and export generations unchanged; dates are civil-date or instant types according to the contract, never ambiguously inferred from locale.
- [ ] **Implement the macOS-only EventKit adapter.** Its main-actor facade delegates all instance access to one private serial worker owning one `EKEventStore`; synchronous event queries must not block the UI. Full permissions are requested only from explicit foreground setup; add the correct Reminders usage description. Resolve `calendarItem(withIdentifier:)`, then `calendarItems(withExternalIdentifier:)`, then exact ownership markers across readable destinations before creation. Preserve foreign objects, notes, title overrides, alarms, and unrelated fields. Re-read/check expected Apple hash just before save. Marker duplicates/loss, unreadable sources, unexpected recurrence, and out-of-window unlocatable events report recovery/unavailable rather than confirmed deletion. EventKit truncates range queries beyond four years; never infer global absence from such a query. Map confirmed deletion only with a complete successful lookup of the previously visible owned item; uncertain identity asks for review.
- [ ] **Run green** package tests and both platform builds in Task 10. Check that the iOS target excludes writer implementation and that package tests never request personal-store access. Adapter field mapping and real EventKit persistence receive dedicated-destination acceptance in Task 10; compilation alone is not claimed as that verification.
- [ ] **Commit:** `feat: add native EventKit item adapter`.

## Task 7: Serialized reconciliation and Mac lifecycle

**Files:** Create package `AppleIntegration/AppleIntegrationService.swift`, tests `AppleIntegrationServiceTests.swift`; app `AppleIntegration/AppleIntegrationCoordinator.swift`, `AppLifecycle/KitchenOSAppDelegate.swift`; modify `CookingCalendarSettings.swift`, `KitchenOSSiriApp.swift`, and relevant planning-calendar Swift tests.

**Interfaces:** `public actor AppleIntegrationService` initialized with the API client, `any AppleItemStore`, and injected clock/backoff dependencies; `perform(_ command: AppleIntegrationCommand) async throws -> SyncReport`; `reconcile(trigger: AppleIntegrationTrigger) async throws -> SyncReport`. Commands are `activate(domain,week,destination)`, `sync`, `setPaused(value,revision)`, `archive(domain,week)`, `resolve(conflict,choice,revision)`, `disconnect`, `restore(token,revision)`, and `removeOwned(tokens,revision)`; triggers are launch, wake, foreground, eventStoreChanged, periodic, domainChanged. App `@MainActor AppleIntegrationCoordinator.shared` owns the service/store, observable status, foreground setup, and `start()`/`stop()`.

- [ ] **Write failing fake-store tests:** `saveBeforeAckIsRecoveredOnce` simulates crash after successful save/before ack; `overlappingCommandsStaySerial` overlaps two intent commands; repeated notifications settle without another revision; errors in one domain permit the other to finish; paused/offline owners never invoke fallback or create from stale work.

  ```swift
  #expect(fakeStore.createCount(for: token) == 1)
  #expect(fakeStore.maximumConcurrentWrites == 1)
  #expect(report.queued > 0 && report.created == 0) // disconnected server
  ```

- [ ] **Run red:** `swift test --package-path KitchenOSKit --filter AppleIntegrationServiceTests`.
- [ ] **Implement an explicit serial command queue.** An actor alone is insufficient because actor methods reenter across `await`. Use one retained worker task, queued command continuations, and a dirty/rescan flag for coalesced triggers; resolve every caller's outcome accurately. Sequence fresh server work → complete Apple observation → server merge/reserved work → Apple apply → acknowledgement. Retry with injected bounded delays of 1, 2, 4, 8, 16, then 30 seconds; cancellation/pause leaves recoverable operations.
- [ ] **Consolidate lifecycle/store ownership.** Inject the same store into the existing calendar reader or narrow it behind the coordinator; do not retain two stores/five-minute loops. Move startup out of `AppShell().task` to a macOS application delegate, listen for wake/activation/EventKit changes, and retain one 300-second periodic task until app termination. Preserve existing localhost guard, permission-loss clears, six-hour snapshot expiry, and calendar-selection semantics. Filter verified owned cooking tokens from both detailed and compatibility availability reads.
- [ ] **Run green:** service/package planning-calendar tests. Use fake clock tests for wake, shutdown, debounce, backoff ceiling, and closing the last window without stopping the coordinator. Actual window/Siri lifecycle is checked in Task 10.
- [ ] **Commit:** `feat: reconcile Apple items throughout Mac app lifecycle`.

## Task 8: Native settings, conflicts, and safe deep links

**Files:** Create package `KitchenOSDeepLink.swift`, tests `KitchenOSDeepLinkTests.swift`; app `Shell/AppRouter.swift`, `AppleIntegration/AppleIntegrationSettingsView.swift`; modify `Shell/AppShell.swift`, `SettingsView.swift`, `Shopping/ShoppingListView.swift`, `Tasks/TasksView.swift`, `MealPlan/PlanningCalendarWebView.swift`, `KitchenOSSiriApp.swift`, both Info plists, package `PlanningWebPolicy.swift`, and planning-calendar focus handling in `static/planning-calendar.js` if needed.

**Interfaces:** `KitchenOSDeepLink.item(token: UUID)` with failable URL initializer and `url: URL`; `AppRouter.open(_ link: KitchenOSDeepLink) async` reads `/links/<token>` and selects typed destination. Add `WeekDate.date(forWeekID: String) -> Date?` with round-trip ISO-week validation. Coordinator exposes read-only status/settings bindings and invokes Task 7 commands; both shopping/prep views accept a routed week and optional stable row/task ID.

- [ ] **Write failing tests** for link parse/render, arbitrary schemes/path traversal rejected, repeated links updating an existing view, ISO year boundaries, and missing/archived item destinations. Assert `kitchenos://` is not claimed by the new parser and link opening issues no POST/PUT/DELETE requests.
- [ ] **Run red:** package link/WeekDate/PlanningWebPolicy tests.
- [ ] **Implement native settings and controls.** Separate permission requests, destination pick/create, connect-without-publishing, Send/Sync buttons, pause/archive/disconnect, explicit restore/remove-owned, and readable queued/conflict status. Keep conflict resolution per field/item with current values and clear choices. Show Shopping Amount Changed on the shopping surface; due overrides appear with tasks. Keep keyboard focus and accessible labels on every control and use existing native styling.
- [ ] **Wire source views and links.** Use stable IDs rather than ingredient text in shopping `ForEach`; show saved/checkable rows as well as preview. Route prep to stable task ID and cook to the existing planner calendar with validated `focusCookID`. Register only `kitchenos-native` in plists. Missing history links show an explanatory state rather than writing/recreating anything. iOS can open/read destinations and status; writing/reconciling Apple stores remains Mac-only.
- [ ] **Run green:** full package tests and both platform builds. Verify repeated route handling and URL escaping, conflict action request revisions, denied-permission UI, and no implicit historical publication with a fake coordinator. Use the appropriate accessibility/writing skills when implementing UI.
- [ ] **Commit:** `feat: add native Apple integration controls`.

## Task 9: App Intent actions share the native service

**Files:** Create `KitchenOSSiri/Sources/Intents/AppleIntegrationIntents.swift`; package `AppleIntegration/PlannedCookEntity.swift`, tests `AppleIntegrationIntentParametersTests.swift`; modify `KitchenOSShortcuts.swift` only where needed for discovery/compilation, and client extensions needed for typed cook listing/scheduling.

**Interfaces:** macOS app-target intents `SendShoppingListToRemindersIntent`, `SendPrepTasksToRemindersIntent`, `SyncCookingCalendarIntent`, `ScheduleCookingIntent`, `SyncKitchenOSIntent`. `PlannedCookEntity.id` is the ledger cook ID, never display title. Parameters include a date identifying the week; Schedule Cooking takes existing uncooked single-recipe cook, start date/time, duration, meal, and first-placement servings when required. Thin `perform()` methods invoke the same coordinator/service or validated schedule endpoint followed by reconcile.

- [ ] **Write failing parameter/entity tests** for duplicate recipe display names with distinct cook IDs, ISO week boundaries, a missing/cooked/bundle cook, invalid durations, and required first-placement servings. Define dialog/result mapping for fully synced, queued, partial, conflict, and foreground-setup cases.
- [ ] **Run red:** `swift test --package-path KitchenOSKit --filter AppleIntegrationIntentParametersTests`.
- [ ] **Implement thin intents and typed lookup.** Use current supported foreground continuation for permissions/destination selection. No intent registers a second store/coordinator, performs legacy meal-plan PUT, or claims queued work was delivered. Keep Mac actions discoverable via app-target metadata without assuming automatic App Shortcut phrases on Mac. Respect existing iOS shortcut-count/platform constraints; do not add five iOS-only automatic shortcuts for a Mac writer.
- [ ] **Run green:** package tests, macOS build, and metadata inspection for all five action identifiers. In Task 10 create/run a named Shortcut through the action library and verify its result against actual dedicated destination data; package tests do not prove Siri/Shortcuts launch behavior.
- [ ] **Commit:** `feat: expose Apple integration App Intents`.

## Task 10: Integrated verification, documentation, and installation

**Files:** Add `tests/test_apple_integration_roundtrip.py`; update `README.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and relevant `AGENTS.md` invariants only as needed. Keep acceptance results in this plan's checkboxes/notes rather than inventing a successful test report.

- [ ] **Write and run failing round-trip fixtures** against the actual Flask API and fake Apple store: activate → one export → Apple completion/move → updated note/ledger → restart/retry → no duplicate. Include one conflict, missing destination, retired generation, owner replacement, and a changed completed quantity. Implement only integration fixes exposed by these tests, then rerun focused failures.
- [ ] **Run backend regression:** `.venv/bin/python -m pytest -q tests/test_apple_sync_store.py tests/test_apple_sync_merge.py tests/test_note_mutation.py tests/test_shopping_sync.py tests/test_prep_sync.py tests/test_cooking_sync.py tests/test_apple_integration_api.py tests/test_apple_integration_roundtrip.py tests/test_inventory_db.py tests/test_shopping_list_template.py tests/test_shopping_list_generator.py tests/test_task_extractor.py tests/test_cook_schedule.py tests/test_serving_ledger.py tests/test_api_auth.py tests/test_api_endpoints.py tests/test_planning_calendar.py tests/test_cooking_windows.py`. Expected: all pass against isolated data. Run existing e2e coverage for any changed browser surface using its worktree-aware harness, and complete finish-feature's required checks.
- [ ] **Build/test native targets:**

  ```sh
  swift test --package-path KitchenOSKit
  xcodegen generate
  xcodebuild build -project KitchenOSSiri.xcodeproj -scheme KitchenOSSiri -destination 'platform=macOS' -derivedDataPath /tmp/kitchenos-apple-integration-macos
  xcodebuild build -project KitchenOSSiri.xcodeproj -scheme KitchenOSSiri -destination 'generic/platform=iOS Simulator' -derivedDataPath /tmp/kitchenos-apple-integration-ios CODE_SIGNING_ALLOWED=NO
  plutil -p /tmp/kitchenos-apple-integration-macos/Build/Products/Debug/KitchenOS.app/Contents/Info.plist
  ```

  Expected: successful tests/builds, macOS minimum version 26.0, correct calendar/reminder descriptions, and `kitchenos-native` registration. Verify effective deployment settings and built plist: the previously installed app advertised 27.0 despite the source's 26.0 floor. Inspect `Contents/Resources/Metadata.appintents/extract.actionsdata` with `.venv/bin/python` and assert all five actions exist; inspect the actual generated structure rather than assuming keys.

- [ ] **Update operating docs** with destination setup, scope activation, progress/conflict language, quit/sleep behavior, token/local-owner boundary, iOS status-only behavior, legacy unowned reminders/ICS coexistence, rollback, and external-editor limitations. Remove obsolete claims that Calendar integration never writes events. Document optional test destinations and cleanup that removes only test-owned objects.
- [ ] **Prepare deployment** after fresh review passes. Back up the SQLite DB via its backup API and the existing native app to timestamped paths; do not copy a live SQLite file alone. Verify signing with `codesign --verify --deep --strict` and record effective entitlements. Deploy API prerequisites and feature code together through the existing checkout/deployment workflow; restart `com.kitchenos.api` after changed library/template code. Do not replace the Safari app at `~/Applications/KitchenOS.app`.
- [ ] **Install the verified bundle** at `~/Applications/KitchenOS Native.app` using the existing native process after backup, then launch it. The concrete bundle copy is `ditto /tmp/kitchenos-apple-integration-macos/Build/Products/Debug/KitchenOS.app "$HOME/Applications/KitchenOS Native.app"`. Obtain sandbox permission for this external-path write if required. Confirm launch, settings, declared platform minimum, health, and that no scope/destination was activated automatically.
- [ ] **Run user-approved live acceptance** in dedicated reminder lists/calendar only after permission to create test items. Verify all five actions in Mac Shortcuts, one reminder completion/reopen, one valid Calendar move/delete, repeat export without duplicates, permission-denied behavior, and sync with all windows closed. Delete only owned test objects after recording results. If permission is not available, report this acceptance as pending; never call the integration fully verified from fake-store tests alone.
- [ ] **Finish the branch** with required feature checklist, fresh review, narrow commits, and the approved integration method. Do not merge unrelated inherited work or publish without applicable authorization. Share a concise summary of implemented behavior, verification, and any remaining live-acceptance limitation.

## Plan self-review

- Spec coverage maps to Tasks 1–10: ownership/scopes and conflicts (1,5), shopping identities and file recovery (2), prep due/completion (3), ledger writes (4), fallback/auth/link resolution (5), EventKit permissions/identity (6), lifecycle/serialization (7), controls/navigation (8), App Intents (9), deployment/acceptance (10).
- Source authority stays in existing domain stores; durable DB payloads are sync baselines/journals, never replacement pantry/nutrition data.
- Shared names/types flow from Task 1 through Task 5 and Swift Task 6; Task 7 owns transport orchestration, while the server owns merge decisions.
- Each Review Focus condition has a named owning task/test. No product code has been written or tested as part of producing this plan.
- Recommended execution: **subagent-driven**, with independent review after each task, because stale callbacks and duplicate ownership can mutate personal tasks/events and the ledger. The tasks depend on stable contracts; do not parallelize dependent implementation work merely to fill agent slots.
