# Branch Status: ingredient-grams-coverage

**Created:** 2026-07-08
**Design Doc:** docs/plans/ingredient-data-cleaning.md
**Current Stage:** ready
**Last Rebased:** 2026-07-09 (0 behind main)

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
- [x] Tests written first (superpowers:test-driven-development) — 30 coverage tests
- [x] Bucket 1: informal units (spoonful/dollop→tbsp; union INFORMAL_UNITS)
- [x] Bucket 2: piece weights (unit-aware lookup; cilantro/parsley)
- [x] Bucket 3: densities (cream/flakes/baking/vanilla/milks/etc.)
- [x] Bucket 4: accents (jalapeños) — food match + units table
- [x] LaunchAgent restarted after lib/units.py edits (done post-merge to main)

### Testing
- [x] Unit tests pass — full suite 1127 passed
- [x] Coverage meter: 0.563 → 0.647 (+8.4 pts) on a 30-recipe sample
- [x] Spot-check macros after `--force`: Creamy Lentil 105→190 kcal (undercount
      fixed); Garlic Toast unchanged (already clean). Backfill: 228 updated, 0 failed.

### Not in this branch (deferred, tracked in the plan)
- Phase A2: amount/unit leaked into item text ("(estimated) 1/2 cup parmesan",
  "to taste dollop yogurt") — the biggest remaining coverage lever.
- Phase B: `*(inferred)*` / doubled-word item cleanup; long-tail table entries.

### Docs
- [x] docs/plans/INDEX.md updated — row moved to Done
- [x] Archive summary: docs/completed/2026-07-09-ingredient-grams-coverage.md
- [x] CLAUDE.md / OPERATIONS.md — no new command/invariant (grams_coverage_report.py is an ad-hoc measurement script, not an operational command)

### Ready
- [x] Rebased on main; final test pass (1127 passed); BRANCH-STATUS complete

---

## Notes

- Editing `lib/units.py` / `config/*.json` requires restarting `com.kitchenos.api`.
- `spoonful`/`dollop` carry real macros (~tbsp) → map to a unit, don't zero them;
  `a sprinkle`/`pinch`/`dash` are genuinely negligible.

## Blocked Items
- (none)
