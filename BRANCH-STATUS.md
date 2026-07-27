# Branch Status: inventory-location-visibility

**Created:** 2026-07-26
**Design Doc:** docs/superpowers/specs/2026-07-26-inventory-location-visibility-design.md
**Impl Plan:** docs/superpowers/plans/2026-07-26-inventory-location-visibility.md
**Current Stage:** review
**Last Rebased:** 2026-07-27 (onto main @ `ffc742d`, post-`consume-on-cook`)

## Overview

Show each inventory item's storage location on `/review`, group the list by location, and
record on every row *how* its location was decided — so a machine guess stays
distinguishable from a placement you confirmed. Correcting a location teaches
`config/storage_locations.json`, so the same wrong guess stops recurring.

A new `place_item()` router in `lib/storage_locations.py` owns the tier ladder
(hand-curated item override → category rule → nothing matched) and returns both a
location and its provenance, stored per row in a new `inventory.location_source` column.

**Scope added at the rebase:** Task 5 also surfaces `last_used` / `use_count` in the same
`/review` subline. `consume-on-cook` shipped those columns but left them write-only — no
view reads them — and Task 5 already rewrites the one function where they belong.

## Dependencies

- **Rebased onto `consume-on-cook`**, which is merged to `main`. That branch touched
  `lib/inventory.py`, `lib/inventory_db.py`, `api_server.py` and the same test files, so
  the plan's Task 2 find/replace blocks were refreshed against current `main`.
  `templates/review.html` and `lib/storage_locations.py` are untouched by it — Tasks 1, 5
  and 6 apply exactly as written.
- No other unmerged branch conflicts. `macro-planner-phase-1` is parked and touches
  nutrition/servings only.

Conflict-check method: `git log main..<branch> --name-only`. Do **not** use
`git diff main..<branch>` — it also lists files where the branch is merely *behind* main,
which produces false conflicts.

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans)
- [x] Plan refreshed against the post-`consume-on-cook` baseline

### Dev
- [x] Tests written first (superpowers:test-driven-development) — RED observed per task
- [x] Core implementation complete — Tasks 1–9
- [x] All tests passing — **2744** unit (baseline 2715; +22 planned, +7 more from the
      review round), 36 e2e + 3 xfail + 1 xpass (was 28)
- [x] No linting/type errors — `ruff check` clean on everything authored. The 4 findings
      across branch-touched files (`E722`/`E741` in `api_server.py`, `F401` in
      `ingest_csa.py` and `tests/test_storage_locations.py`) are all pre-existing and
      confirmed present on `main`.
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — **owed at merge**;
      the plist runs the *main* checkout, so a restart from this worktree loads nothing

### Testing
- [x] Unit tests pass
- [x] Integration tests pass — `tests/e2e/test_location_visibility.py`, 6 new Playwright
      tests; full e2e run twice consecutively to confirm order-independence
- [ ] Manual testing completed — **not done on purpose.** The migration and backfill are
      verified against *copies* of the live DB (222 rows → 199 category / 16 item / 7
      default). Touching the real DB and vault should be the reviewer's deliberate call.
- [x] Edge cases verified — longest-key-wins, catch-all-is-not-an-answer, NULL reads as
      default, merge keeps the stronger source, freeze confirms without teaching, a failed
      config write still commits the move, header counts match labelled rows
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table — `docs/API.md` (`/api/inventory` row shape
      + `/review` behaviour), `docs/ARCHITECTURE.md` (the placement router), `CLAUDE.md`
      (two invariants + the new env var)
- [x] README updated (if interface changed) — n/a, README documents no API routes
- [x] docs/plans/INDEX.md updated
- [x] Code comments where needed

### Review
- [x] Requested review (superpowers:requesting-code-review)
- [x] Review feedback addressed — 1 Critical + 6 Important + 3 Minor fixed across
      4 commits; every finding reproduced before being fixed. Summary below.
- [ ] Changes approved

**What review caught.** Each was verified independently before any code changed:

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

### Ready
- [ ] Rebased on latest main
- [ ] Final test pass after rebase
- [ ] BRANCH-STATUS.md fully checked
- [ ] Ready for merge

---

## Notes

**Worktree is set up.** `.env`, `.venv` and `vault` are symlinked from the main checkout;
`data/kitchenos.db` is a **copy** (never a symlink) so nothing writes through to
production. The e2e harness needs that copy to exist.

**Closure obligation.** `main` must not carry a `BRANCH-STATUS.md` — delete this file when
the branch merges. The `cook-now-meal-type-filter` branch missed this once and
`consume-on-cook` inherited a stale status file as a result.

**`location_source` is provenance, not address.** `InventoryItem.merge_key()` stays
`(name, unit, location)`. Adding `location_source` to it would fragment rows.

**Only `default` renders as unsure.** A NULL or unknown value normalizes to `default`, so
anything that escapes the backfill surfaces for review rather than posing as confirmed.

## Found in review, deliberately NOT fixed here

1. **The iOS app stamps every added row `manual` from a Picker default.**
   `KitchenOSSiri/Sources/Inventory/InventoryView.swift` has
   `@State private var location = "pantry"` and always serialises it, so
   `/api/inventory/add` always takes the explicit branch and never consults the
   router. A form default the user never touched is recorded as a confirmed
   placement — the one direction `CLAUDE.md` forbids. **The branch's central
   promise is false for app-added rows.** The server can't distinguish this
   without breaking the web/MCP contract, so the fix is client-side: make
   `location` optional with an "Auto" default that omits the key. Swift work, a
   different tier from this branch, but it should be next.
2. **`KitchenOSKit` doesn't decode `location_source`,** so the native inventory
   screen can't render the `?` that `/review` and `Inventory.md` both show. Not a
   regression, but the three views now disagree about what is known.
3. **An exact `by_item` hit and a fuzzy token-subset hit both report `item`.**
   That's what let the five `frozen` rows read as confidently placed. The deeper
   hazard isn't key length — it's that `by_item` unconditionally beats
   `by_category`, and every correction adds a key more names will accidentally
   token-contain. A distinct source for a fuzzy hit would make that growth
   visible instead of silent.
4. **`load_table()` re-reads and re-parses the JSON on every `place_item` call**
   — 222 file reads during the backfill, one per line during receipt ingest.
   Pre-existing (`resolve_location` did the same) and the file is ~1 KB, so this
   is cosmetic until it isn't.

## Blocked Items

- None.
