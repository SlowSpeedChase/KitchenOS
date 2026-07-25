# Branch Status: bulk-inventory-editing

**Created:** 2026-07-25
**Design Doc:** docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md
**Impl Plan:** docs/superpowers/plans/2026-07-25-bulk-inventory-editing.md
**Current Stage:** review
**Last Rebased:** 2026-07-25 (branched from main @ 51f0007)

## Overview

Mass select + edit on `/review`: checkboxes + Select All, a sticky selection bar
mirroring a row's own `Remove / +3d / +7d / ⋮` controls, and one
`POST /api/inventory/bulk` doing a single read-modify-write instead of N.

Also fixes item addressing on the bulk path. The DB's uniqueness key is
`(name, unit, location)`, but every existing endpoint addresses rows by
`(name, location)` — and handles the disagreement inconsistently: `remove_item`
deletes *every* match while `set_expiry` / `set_category` / `extend_expiry` /
`move_item` update only the *first*. Latent on one item, data loss on fifteen.

Deliverables (6 tasks):
1. Pure `_apply_*` mutators in `lib/inventory.py` — mutate in memory, no I/O
2. `bulk_apply(action, refs, **params)` — one read, one write, `merge_key()` addressing
3. Single-item functions rewritten as thin wrappers over the same helpers
   (`freeze_item` collapses from 3 write cycles to 1)
4. `POST /api/inventory/bulk` + `_serialize_item` extracted from `_item_response`
5. Selection UI in `templates/review.html` — generalized `openMenu(target, anchor)`
6. Verification against the running server + `docs/API.md`

## Dependencies

- None blocking. `web-home-page` (the design doc's stated predecessor) merged to
  main on 2026-07-25 @ 51f0007.
- No conflict with the other active worktrees: `macro-planner-phase-1` (parked,
  nutrition/servings) and `inventory-scan-and-extend` (its `/review` +
  `/api/inventory/extend` work is already present on main).

---

## Stages

### Planning
- [x] Design doc exists and approved — "Ready" in docs/plans/INDEX.md since 2026-07-25
- [x] Conflict check completed (no overlapping work) — `git worktree list`, INDEX "In Progress"
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete — tasks 1-5
- [x] All tests passing — 1453 passed, 1 skipped (baseline on main was 1405)
- [x] No linting/type errors
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — **deferred to
      post-merge**, see Notes: the agent's `WorkingDirectory` is the main worktree, so
      reloading it here would serve main's code, not this branch's

### Testing
- [x] Unit tests pass — 1453 passed, 1 skipped
- [x] Integration tests pass (if applicable) — full e2e suite green:
      22 passed, 2 xfailed, 2 xpassed (both xpasses pre-existing, real-vault state)
- [x] Manual testing completed — **automated instead.** All five steps of the Task 6
      phone script are now browser tests in `tests/e2e/test_bulk_inventory.py`; the
      plan's premise that the repo has no JS harness was wrong
- [x] Edge cases verified — merge-on-move (two locations → one summed row),
      5-row remove + undo round trip, heterogeneous selection offering every chip
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table — `docs/API.md` (new endpoint contract)
- [x] README updated (if interface changed) — n/a, no user-facing install/usage change
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

- **Baseline:** 1405 tests passing on main @ 51f0007. The plan adds ~35.
- **No new page route**, so the `SECTIONS` / bookmark-sync invariant in CLAUDE.md
  does not apply — `/review` is already registered.
- **Scope guard:** the single-item routes keep `(name, location)` addressing and
  their current semantics. Their tests pin that behavior; migrating them is an
  explicit out-of-scope follow-up.
- **`InventoryItem` is a plain dataclass**, so `==` is by value. Removal from the
  working list must be by identity — hence `_drop()`. Using `list.remove()` here
  would be a real bug, not a style preference.
- The concurrent-writer lost-update TODO at `lib/inventory.py:308` is narrowed by
  this work (one write instead of N) but **not closed**. Still needs
  `INSERT … ON CONFLICT` in one transaction.

### Scope added after the plan (user-directed, 2026-07-25)

Two changes landed on this branch beyond the original 6 tasks. Both were asked
for directly after the bulk work was already review-ready.

1. **`+3d` / `+7d` are now cumulative** (`fix:` commit). Reported as "the add
   time buttons do nothing". They weren't broken — `_apply_extend` set
   `expires = today + N` outright, so a second tap changed nothing and `+3d`
   after `+7d` moved the date *backward*. On an inventory of mostly 2027 dates,
   `+7d` also quietly pulled an item ten months closer. Now each row advances
   from its own expiry, falling back to today only when the row has lapsed or
   has no date — which keeps the guard the old behaviour existed for. The list
   also re-sorts after an expiry change and flashes moved rows; a rescued item
   previously stayed pinned in the expired block, which was most of why the tap
   looked inert. This changes semantics for the **single-item** route too, not
   just bulk — it is shared code.
2. **Sort by date added** (`feat:` commit). `purchased` is treated as the
   date-added stamp per the user's call, so no migration. `add_items` stamps it
   on row creation but **not** on merge, so re-running the pantry-staples seed
   can't make old stock look new. 166 of the 217 existing rows predate the
   stamp; they sort last and read `added unknown` rather than being backfilled
   with invented dates.

### Deviations from the plan (for the reviewer)

1. **Task 6 Step 2 (reload the LaunchAgent) was not run.** `com.kitchenos.api` has
   `WorkingDirectory = ~/Dev/KitchenOS` — the *main* worktree — so reloading it serves
   main, not this branch. The step is correct but belongs after the merge, not here.
   Verification used the e2e harness's own isolated server instead.
2. **Task 6 Step 3 (manual phone script) was automated.** The plan said "there is no JS
   test harness in this repo"; `tests/e2e/` is exactly that — a Playwright harness
   driving a real server against copies of the vault and DB. All five steps are now
   tests, so they keep passing after the merge instead of being hand-checked once. The
   217 lines of new page JS had never been executed in a browser before this.
3. **Task 6 Step 4's `###` block did not match `docs/API.md`.** That file is a
   one-row-per-route table, so the endpoint is documented as a table row carrying the
   same contract. The `/review` row was updated too, and the section's stale "62 routes"
   header corrected to 75 (verified against `app.url_map`, which the table already
   matched row-for-row).

### Found, not fixed — needs a scope call

Undo cannot restore a **deliberately cleared** expiry. The page's undo replays removed
rows through `POST /api/inventory/add`, and `add_items` auto-fills a shelf-life expiry
whenever `expires is None` — so an item whose expiry was cleared via "🚫 Remove
expiration" comes back dated (measured: a pantry item returned with an expiry a year
out). `POST /api/inventory/bulk` is **not** at fault; its `removed` payload carries the
null faithfully.

Pre-existing on main — the single-row remove path replays identically — but bulk widens
it from one row to a whole selection. Pinned as a **strict** xfail
(`test_undo_restores_a_deliberately_cleared_expiry`) so it flips to a failure the day
it's fixed rather than being forgotten. A real fix needs a way to add a row with an
explicitly null expiry, which is a contract decision beyond this branch.

---

## Blocked Items

None.
