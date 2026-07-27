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
- [x] All tests passing — **2737** unit (baseline 2715, +22 exactly as planned),
      34 e2e + 3 xfail + 1 xpass (was 28)
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
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed
- [ ] Changes approved

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

## Blocked Items

- None.
