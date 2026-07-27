# Branch Status: inventory-location-visibility

**Created:** 2026-07-26
**Design Doc:** docs/superpowers/specs/2026-07-26-inventory-location-visibility-design.md
**Impl Plan:** docs/superpowers/plans/2026-07-26-inventory-location-visibility.md
**Current Stage:** dev
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
- [ ] Tests written first (superpowers:test-driven-development)
- [ ] Core implementation complete
- [ ] All tests passing — baseline `2715`, target `2737`
- [ ] No linting/type errors
- [ ] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — **owed at merge**;
      the plist runs the *main* checkout, so a restart from this worktree loads nothing

### Testing
- [ ] Unit tests pass
- [ ] Integration tests pass (Playwright, `tests/e2e/test_location_visibility.py`)
- [ ] Manual testing completed
- [ ] Edge cases verified
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
- [ ] README updated (if interface changed)
- [ ] docs/plans/INDEX.md updated
- [ ] Code comments where needed

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
