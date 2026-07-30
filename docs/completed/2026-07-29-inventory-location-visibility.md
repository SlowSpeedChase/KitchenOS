# Completed: Inventory location visibility

**Completed:** 2026-07-29
**Branch:** `inventory-location-visibility` (17 commits, 24 files, +3459/−74)
**Duration:** 3 days (started 2026-07-26)

## Summary
`/review` now shows where each item is stored, groups the list by location, and records on every
row *how* that location was decided — so a machine guess stays visibly distinguishable from a
placement you confirmed. Correcting a location teaches `config/storage_locations.json`, so the
same wrong guess stops recurring.

The organising idea is that a placement carries provenance, not just an address. A new
`place_item()` router owns the tier ladder and returns `(location, source)`; the tier is stored per
row in `inventory.location_source`.

## Key Changes
- **`place_item()` router** (`lib/storage_locations.py`) — exact `by_item` override → longest
  word-subset `by_item` match → category rule → `pantry`. Two rules are deliberate and documented:
  **longest matching key wins** (otherwise `milk` would eventually capture `milk chocolate chips`
  as `by_item` grows with every correction), and **the catch-all category is not an answer** (a
  location derived from `other` reports `default`, because that is the categoriser shrugging).
- **`inventory.location_source`** — nullable on purpose. A NULL or unrecognised value normalizes
  to `default`, which renders as unsure, so anything escaping the backfill asks to be reviewed
  rather than posing as confirmed. The failure direction is always toward being asked again.
- **`/review` rows show location + `last_used` / `use_count`**, grouped by location
  (`templates/review.html`). The use-stamps were shipped write-only by `consume-on-cook` — no view
  read them until now.
- **Unresolved locations are marked in the generated `Inventory.md` view.**
- **Correcting a location teaches the table.** A hand-correction stamps the row `manual` *and*
  writes the override, so future purchases of that item file correctly.
- **Provenance captured at every creation site** — `api_server.py`, `lib/receipt_ingest.py`,
  `lib/receipt_paster.py`, `ingest_csa.py`.
- **Two new invariants in `CLAUDE.md`** (`location_source` is provenance not address; teaching the
  table is a write, so tests must be isolated from it) plus the `KITCHENOS_STORAGE_TABLE` env var.

## What the review round caught
Ten findings, all reproduced before being fixed. The two that mattered most:

- **Critical — the backfill was not atomic with the `ALTER`, and never retried.** `ALTER TABLE`
  commits on its own; the backfill `UPDATE`s committed later. A crash in between left the column
  present with every row NULL, and a creation-triggered backfill then never ran again — stranding
  the whole table on `default` permanently, with no migration script to rerun. Fixed by triggering
  on the NULLs instead of on having just added the column, which is self-healing and also covers
  two processes racing the first migration.
- **`save_item_override` could wipe the curated table.** One hand-edit typo plus one move reduced
  29 `by_item` keys and 10 `by_category` rules to a single entry, because `load_table` hands back
  empty tiers for an unparseable file and the save then persisted them. Now it refuses to write
  over a table that exists but doesn't parse — and the move still commits, because a config-write
  failure must not sink the row change.

Also fixed: the backfill claimed the router placed 5 `frozen` rows it didn't (now stamped `manual`
where stored ≠ resolved); the `?` unsure marker broke the paste round-trip; there was no way to
*confirm* a guess that happened to be right (an unsure row now offers a `✓ <loc>` chip, which is
also what makes `move_item`'s already-there branch reachable); 4 tests read a config the product
now writes; and two isolation layers silently overrode each other.

## Verification
- Rebased onto `origin/main` at `6a2e818` — two conflicts, both additive-on-both-sides and both
  kept: `tests/test_api_endpoints.py` (macro-suggest tests vs the placement-provenance test) and
  `docs/plans/INDEX.md` (the branch carried a stale copy of the macro-planner row, dropped in
  favour of main's current one).
- **Unit suite: 2827 passed** (main's baseline is 2798, so +29).
- **E2E: 36 passed, 3 xfailed, 1 xpassed** — matching the branch's own claim exactly.
- `ruff check` findings on branch-touched files are **byte-identical to main's** — 3 in the
  branch's file set, all pre-existing, none introduced.
- **The migration was dry-run against a copy of the live 222-row DB** before anything touched
  production: `location_source` present, **0 NULLs**, split **199 category / 11 item / 5 manual /
  7 default** — exactly what the branch predicted. The 5 `manual` rows are the frozen ones the
  review round found (caramelized onions, diced fried potatoes, frozen bananas, frozen french
  bread, frozen yeast rolls) — stored in the freezer while `by_item` names another shelf.
- **The Critical fix was proven by reproducing the failure**, not taken on trust: added the column
  to a DB copy and left all 222 rows NULL, then opened it with a plain `connect()` — it recovered
  to 0 NULLs and the correct split.
- Live DB backed up to `~/kitchenos-db-backups/` before the production migration.

## Not Done — carried forward
Four findings were deliberately left out of scope. The first is the significant one:

1. ~~**The iOS app stamps every added row `manual` from a Picker default, so the branch's central
   promise is false for app-added rows.**~~ **RESOLVED 2026-07-29** — see
   `docs/completed/2026-07-29-ios-auto-location.md`. `KitchenOSSiri/.../InventoryView.swift` had
   `@State private var location = "pantry"` and always serialised it, so `/api/inventory/add`
   always took the explicit branch and never consulted the router — recording a form default the
   user never touched as a *confirmed* placement, the one direction `CLAUDE.md` forbids. Fixed
   client-side as predicted: the Picker gained an **Auto** default and the add path now uses a
   `NewInventoryItem` whose `location` is `String?`, encoded by omission.
2. **`KitchenOSKit` doesn't decode `location_source`**, so the native inventory screen can't render
   the `?` that `/review` and `Inventory.md` both show. Not a regression, but three views now
   disagree about what is known.
3. **An exact `by_item` hit and a fuzzy token-subset hit both report `item`.** That is what let the
   5 frozen rows read as confidently placed. The deeper hazard isn't key length — it's that
   `by_item` unconditionally beats `by_category`, and every correction adds a key that more names
   will accidentally token-contain. A distinct source for a fuzzy hit would make that growth
   visible instead of silent.
4. **`load_table()` re-reads and re-parses the JSON on every `place_item` call** — 222 file reads
   during the backfill, one per line during receipt ingest. Pre-existing and the file is ~1 KB, so
   cosmetic until it isn't.

## Design Doc
`docs/superpowers/specs/2026-07-26-inventory-location-visibility-design.md` ·
plan `docs/superpowers/plans/2026-07-26-inventory-location-visibility.md`

## Lessons Learned
- **"Migration ran" and "migration finished" are different states, and only one of them is
  observable.** The Critical bug was invisible in every normal run; it needed someone to ask what
  happens if the process dies between two commits. Keying the backfill off the *data* it produces
  rather than off the schema change makes the answer self-correcting.
- **A feature that writes config needs test isolation in as many layers as there are ways to reach
  it.** The in-process fixture wasn't enough because the e2e harness runs `api_server.py` as a
  subprocess an in-process patch can't touch — and the real `config/storage_locations.json` was
  observed being rewritten by both before the second layer existed.
- **Being honest about uncertainty means picking the failure direction on purpose.** A NULL
  normalizing to `default`/unsure — rather than to a confident-looking value — is why an escaped
  row gets asked about instead of quietly lying. Finding #1 is the same principle violated from
  the client side, which is why it reads as a real defect rather than a missing nicety.

---

## Appendix: the full review-findings table

Preserved verbatim from the branch's `BRANCH-STATUS.md`, which is deleted at merge (main must never carry one). Each finding was reproduced before any code changed.

| Finding | Evidence | Fix |
|---|---|---|
| **Critical** — backfill not atomic with the ALTER, never retried | injected a crash: column present, all 222 rows NULL, and no later connect ever backfilled → every row reads `default` permanently, no script to rerun | trigger on the NULLs, not the ALTER; self-healing, also covers two processes racing the first migration |
| backfill claimed the router placed rows it didn't | 5 live `frozen` rows sit in the freezer while `by_item` names another shelf | stamp `manual` when stored ≠ resolved; live split is now 199 category / 11 item / 5 manual / 7 default |
| `save_item_override` could wipe the curated table | one hand-edit typo + one move reduced 29 `by_item` keys and 10 `by_category` rules to a single entry | refuse to write over an unparseable file; the move still commits and warns |
| the `?` marker broke the paste round-trip | `normalize_location("pantry?")` → `other`, and the non-empty cell also recorded `manual` — wrong shelf, falsely confirmed, duplicate row, no error | shared `UNSURE_MARKER`; a marked cell keeps its shelf and stays `default` |
| no way to confirm a guess that was right | the chip loop skips the row's own location, so the 7 unsure rows show `?` forever and the only escape teaches a wrong override first | an unsure row offers a `✓ <loc>` chip — which is also what makes the `move_item` already-there branch reachable |
| 4 tests read a config the product now writes | moving bananas on `/review` would break the unit suite | fixture tables |
| the already-there behaviour was undefended, 2 tests misnamed | one compared an object to itself | renamed + a real no-op test |
| two isolation layers, one silently overriding the other | `table_path()` reads the env var before the attribute | env var is the only knob; no attribute patches remain |
