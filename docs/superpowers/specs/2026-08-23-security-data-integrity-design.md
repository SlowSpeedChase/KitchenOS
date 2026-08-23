# KitchenOS Security and Data-Integrity Repair

**Status:** Ready for review · **Branch:** `security-data-integrity` · **Date:** 2026-08-23

## Problem

KitchenOS currently has three independent ways to cross a trust boundary or silently
damage its source-of-truth data:

1. The Claude page bridge accepts unauthenticated text and can submit it into the live
   `ko-claude` tmux session. The notes route is the same boundary: saved notes seed the
   next Claude prompt.
2. Recipe and shopping-list handlers derive filesystem paths directly from request
   values. `..` can escape the intended folder and read or overwrite another Markdown
   file in the vault.
3. Receipt and inventory persistence is split across transactions. A replay can stock a
   receipt twice; a failure after recording the trip can permanently skip stock; and
   overlapping read/merge/replace writers can discard one another.

These failures are dangerous precisely because their ordinary path looks successful.
They need fail-closed boundaries and database-enforced atomicity, not more recovery work
for the user.

## Scope and decomposition

This branch is the first independently shippable repair slice:

- hard-disable the entire Claude bridge at the web/API wiring layer;
- constrain every request-derived recipe and shopping-list path;
- make receipt-ledger and inventory additions one atomic operation;
- serialize the remaining inventory read/modify/write operations so they cannot race an
  additive UPSERT.

The full audit is larger than one safe branch and overlaps active work:

- `ios27-new-siri` already changes `project.yml`, `RecipeEntity`, search, AI, and API
  authentication. Apple-client findings will be reconciled against that branch rather
  than duplicated here. Both branches touch `api_server.py`, but the active branch's
  current diff is confined to recipe-search/health wiring; this branch owns disjoint
  Claude, path, and receipt regions. The final rebase must still review that shared file.
- The main checkout has uncommitted retry-cap/dead-letter changes in `batch_extract.py`,
  health modules, and templates. Those remain user-owned and will get their own follow-up
  after this branch; this branch will not copy or commit them.
- Remote-browser authentication, serving-ledger repairs, accessibility, scripts, and
  documentation cleanup are subsequent sibling branches. Each can ship and be reviewed
  independently.

## Design

### 1. Hard-disable the Claude bridge

The bridge is disabled structurally, not by an environment flag:

- Pages are served without `_CLAUDE_BAR_TEMPLATE` injection.
- `/api/claude-send` and both `/api/claude-notes` methods are no longer registered.
- `lib/claude_send.py` and `lib/claude_notes.py` remain in the tree so a future
  authenticated design can reuse their tested mechanics; no production route calls them.
- Direct requests receive Flask's normal 404 response. Returning 404 avoids advertising
  a dormant privileged feature and cannot be mistaken for a temporary, retryable outage.

This includes notes because an attacker who can overwrite the opening note can steer the
next privileged Claude session even if immediate tmux submission is gone.

### 2. Centralize request-derived path validation

Add a small `lib/safe_paths.py` authority with two responsibilities:

- `contained_markdown(root, value)` URL-decodes once, rejects absolute paths and NULs,
  requires a `.md` file, resolves symlinks and `..`, and verifies the resolved candidate
  remains beneath the resolved root.
- `parse_iso_week(value)` accepts only a real ISO week (`YYYY-WNN`) by validating it with
  `date.fromisocalendar`, not regex alone. Shopping-list filenames are constructed only
  from the returned canonical week.

All affected entry points delegate to these helpers:

- `/refresh` and `/reprocess`;
- shopping-list preview and confirmation;
- shopping-list reads used by `/send-to-reminders` and current-list pages.

Invalid input returns 400. A valid but absent contained file returns 404. No error message
echoes a resolved path outside the configured root.

### 3. Give inventory mutations one transaction boundary

`lib/inventory_db.py` becomes the persistence authority for mutations:

- An additive merge uses `INSERT ... ON CONFLICT(name, unit, location) DO UPDATE` inside
  `BEGIN IMMEDIATE`. Quantity sums; purchase date, category, notes, expiry, provenance,
  and recipe attribution retain the existing `lib.inventory.add_items` merge semantics.
- A transaction-aware read/replace primitive acquires `BEGIN IMMEDIATE` before reading
  and commits the corresponding replacement on the same connection. Existing bulk,
  removal, move, expiry, and reconciliation flows use this primitive when they genuinely
  need whole-inventory decisions.
- The public full replacement remains available only for explicit migration/reconciliation
  callers; ordinary additive receipt/API writes never use it.

`BEGIN IMMEDIATE` deliberately serializes writers before they read. This prevents the
sequence “writer A reads, writer B commits, writer A replaces B's update.” WAL continues
to allow readers while a writer is active.

### 4. Make receipt ingest atomic and idempotent

Introduce one database operation for a receipt submission:

1. Begin an immediate transaction.
2. Insert the trip by unique `source_id`.
3. If it is a duplicate, return `duplicate` without purchases or inventory changes.
4. Insert purchases.
5. UPSERT stock rows using the same connection.
6. Commit once.

Both email/JSON ingestion (`lib/receipt_ingest.py`) and the optional `trip` block on
`POST /api/inventory/add` use this operation. An exception at any step rolls back trips,
purchases, and inventory together.

Inventory routing and expiry calculation happen before the transaction; they are pure
preparation and do not need to hold a database write lock. The derived `Inventory.md` and
Cook Now views regenerate after commit. A view-render failure may make a derived page
stale, but it cannot roll back or duplicate committed source data on retry.

### 5. Preserve external behavior

- The inventory API response keeps its existing `added`, `merged`, and `total` fields.
- Duplicate receipt submissions return a successful no-op status rather than an error.
- Merge identity remains the exact case-insensitive `(name, unit, location)` tuple.
- Source strength, earliest expiry, and recipe attribution behave as they do today.
- No production vault or database is used by tests.

## Error handling

- Invalid request paths fail before any read, backup, subprocess, or write.
- SQLite constraint errors other than duplicate `source_id` propagate and roll back.
- Duplicate detection is based only on the database uniqueness constraint; there is no
  race-prone preflight `trip_exists` check.
- Lock waits use the existing five-second SQLite busy timeout. Exhausting it returns the
  existing server error path and leaves the transaction unchanged.

## Testing

Every implementation task follows red/green TDD.

| Test area | Required evidence |
|---|---|
| Claude bridge | Routes are absent; rendered pages contain no Claude bar; patched tmux/note functions are never called |
| Path containment | `../`, encoded traversal, absolute paths, symlink escape, NUL, non-Markdown, and invalid ISO weeks fail without touching sentinel files |
| Receipt idempotency | Posting one `source_id` twice produces one trip, one purchase set, and one inventory increment |
| Receipt rollback | Injected purchase or inventory failure leaves zero trip, purchase, and stock rows; retry succeeds exactly once |
| Inventory concurrency | Two controlled concurrent additions both survive; a serialized bulk mutation cannot erase an addition |
| Merge compatibility | Existing source-strength, notes, category, earliest-expiry, and `for_recipe` expectations remain unchanged |

Run the focused tests after each task, then the default Python suite and E2E suite for the
branch. No live-vault mutation is part of verification.

## Acceptance criteria

- [ ] No KitchenOS page renders the Claude bridge.
- [ ] `/api/claude-send` and `/api/claude-notes` return 404 for every method and cannot
      call tmux or change `Claude Notes.md`.
- [ ] Every request-derived recipe/shopping path is contained beneath its configured root.
- [ ] Traversal and symlink-escape regression tests demonstrate that outside sentinels are
      unchanged.
- [ ] Replaying a receipt cannot change inventory, purchases, or trip count after its first
      successful commit.
- [ ] Any receipt failure rolls back all three data sets and is safely retryable.
- [ ] Concurrent inventory writers preserve both updates.
- [ ] Existing inventory merge semantics and response contracts remain compatible.
- [ ] Focused, full Python, and E2E suites have no new failures.

## ADHD design check

- **Reduces friction:** duplicate receipts and transient failures repair themselves through
  idempotency; no manual stock reconciliation is introduced.
- **Visible:** unsafe input fails at the request boundary instead of becoming a mysterious
  later vault change.
- **Externalizes cognition:** SQLite uniqueness and transactions remember what completed;
  the user does not need to remember whether a receipt partially ran.
- **Additive, never a chore:** inventory still enters automatically, with fewer recovery
  steps and no new maintenance UI.

## Out of scope

- Re-enabling or redesigning the Claude bridge.
- The new remote-browser authentication/session architecture.
- Adopting the uncommitted retry-cap/dead-letter work from the main checkout.
- Apple-client changes already overlapping `ios27-new-siri`.
- Serving-ledger, accessibility, LaunchAgent script, lint-baseline, and documentation-drift
  follow-ups.
