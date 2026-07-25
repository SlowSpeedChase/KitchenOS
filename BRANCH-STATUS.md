# Branch Status: inventory-truth-fixes

**Created:** 2026-07-25
**Design Doc:** none — bugfix branch, found while reviewing inventory/recipes
**Current Stage:** review
**Last Rebased:** 2026-07-25 (branched from main @ 6173d41, 0 behind)

## Overview

Three defects found while asking "what can I actually cook right now?". The
generated `Inventory.md` was empty while the DB held 219 items, and `Cook Now.md`
was ranking almost entirely desserts.

1. **`write_inventory` had two sources of truth.** It rendered `Inventory.md`
   from the caller's list but called `cook_now.write_note()`, which re-reads the
   DB. A stale/empty caller list shipped an empty `Inventory.md` next to a
   populated `Cook Now.md`. Now both render from the committed DB.

2. **Token matching produced false positives.** `_matches`/`_is_staple` used a
   bare bidirectional subset test, so any single-token ingredient matched every
   longer inventory name containing that word — "eggs" matched *Lo mein egg
   noodles*, "butter" matched *Peanut butter*, "lemon" matched *Lemon pepper
   seasoning*, "avocado" matched *Avocado oil*. Containment into a **clean**
   name (inventory row / staple) must now reach that name's head noun. Free-text
   ingredient strings stay on plain containment, since their trailing words are
   prep notes ("butter (melted)"), not a different food.

3. **Staples were an invisible assumption.** `config/pantry_staples.json`
   credited butter/milk/eggs/garlic/onion as on-hand without them existing in
   inventory, so recipes read 100% that couldn't be made. `seed_pantry_staples()`
   materializes them as perpetual, never-expiring rows (`source: staple`) — the
   assumption stays, but it is now visible and auditable in `Inventory.md`.

## Dependencies

- None.

---

## Stages

### Planning
- [x] Design doc exists and approved — n/a, bugfix; scope confirmed with user
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete
- [x] All tests passing — 1426 passed, 1 skipped
- [x] No linting/type errors
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — **required on merge**

### Testing
- [x] Unit tests pass — 1426 passed, 1 skipped
- [x] Integration tests pass — full suite
- [x] Manual testing completed — ranked the real 219-item DB against all 236
      recipes, before vs after
- [x] Edge cases verified — see below

Manual verification (real data, read-only):
- 60 recipes lost inflated coverage; 54 distinct false-positive ingredients gone.
- Zero false negatives remain. Ones caught and fixed during the pass:
  `butter (melted)` / `unsalted butter, softened` (prep notes),
  `Coriander powder` ↔ `ground coriander` and `Dried dill weed` ↔ `dill`
  (form words), `Peanut butter` ↔ `creamy peanut butter jif...` and
  `Canned coconut milk` ↔ `coconut milk (chilled)` (atomic over-blocking).
- Known, accepted minor misses: `chipotle powder` vs *Chipotle chili powder*,
  `cayenne` vs *Cayenne pepper*, `coarse cornmeal` vs *Yellow cornmeal mix*.
  Fixing these needs modifier-aware matching; deliberately out of scope.

### Docs
- [ ] Repo doc obligations — CLAUDE.md invariant for the DB-rendered view
- [ ] docs/plans/INDEX.md updated

### Review
- [ ] Requested review (superpowers:requesting-code-review)

### Ready
- [ ] Rebased on latest main
- [ ] Final test pass after rebase

## Follow-ups (not in this branch)

- **Root cause of the empty write is still unknown.** The fix makes the view
  self-correcting, but nothing identified *which* caller passed an empty list at
  17:08 on 2026-07-25 (DB mtime was 12:41, so it never reached the DB).
- `tmp_vault` is opt-in while `tmp_db` is autouse in `tests/conftest.py`. The
  current suite is clean, but a test calling `write_inventory()` without
  `tmp_vault` would write into the real Obsidian vault.
