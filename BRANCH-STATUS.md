# Branch Status: ingredient-grams-coverage

**Created:** 2026-07-08
**Design Doc:** docs/plans/ingredient-data-cleaning.md
**Current Stage:** dev
**Last Rebased:** 2026-07-08

## Overview

Lift nutrition-engine **grams coverage** (measured median 0.58 across the vault) —
the blocker under both per-serving macro accuracy and (parked) servings inference.
Per-recipe inspection shows losses are mostly lookup-table gaps. Order of attack:

1. Informal units not recognized (`a sprinkle`, `spoonful`) — INFORMAL_UNITS /
   real-unit mapping.  ← current
2. Missing piece weights (`garlic clove`, `garlic head`, `cilantro`).
3. Missing densities (`heavy cream`, `red pepper flakes`).
4. Food-not-found aliases (plurals/spellings).

Amount-leaked-into-item (Phase A2 of the plan) comes later. Measure with a
fixed-sample coverage meter; full-vault `backfill_nutrition.py --force` only once
coverage climbs meaningfully.

## Dependencies

- None. Servings work (`macro-planner-phase-1/servings-backfill`) is parked pending
  this branch.

---

## Stages

### Dev
- [ ] Tests written first (superpowers:test-driven-development)
- [ ] Bucket 1: informal units
- [ ] Bucket 2: piece weights
- [ ] Bucket 3: densities
- [ ] Bucket 4: food-not-found aliases
- [ ] LaunchAgent restarted after lib/units.py edits (API holds it in memory)

### Testing
- [ ] Unit tests pass
- [ ] Coverage meter shows a meaningful climb from 0.58 baseline
- [ ] Spot-check macros on a sample after `backfill_nutrition.py --force`

### Docs
- [ ] docs/plans/INDEX.md updated
- [ ] CLAUDE.md / OPERATIONS.md if a new command/invariant is added

### Ready
- [ ] Rebased on main; final test pass; BRANCH-STATUS complete

---

## Notes

- Editing `lib/units.py` / `config/*.json` requires restarting `com.kitchenos.api`.
- `spoonful`/`dollop` carry real macros (~tbsp) → map to a unit, don't zero them;
  `a sprinkle`/`pinch`/`dash` are genuinely negligible.

## Blocked Items
- (none)
