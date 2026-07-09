# Completed: Ingredient Grams Coverage (Phase A1)

**Completed:** 2026-07-09
**Branch:** ingredient-grams-coverage
**Duration:** 2 days (started 2026-07-08)

## Summary

Lifted the nutrition engine's **grams coverage** — the fraction of recipe
ingredients the engine can convert to a gram weight — which was the real blocker
under per-serving macro accuracy (and the parked servings-inference work).
Per-recipe inspection showed the losses were mostly lookup-table gaps rather than
parser failures, so the fix was surgical table/unit work, not a rewrite.

Measured on a fixed 30-recipe sample: **0.563 → 0.647 (+8.4 pts)**.

## Key Changes

Four buckets of gap-filling, each test-first:

1. **Informal units** — `spoonful`/`dollop` → tbsp (they carry real macros);
   `a sprinkle`/`pinch`/`dash` kept negligible. Unioned into `INFORMAL_UNITS`.
2. **Piece weights** — unit-aware lookup; added `garlic clove`/`head`, cilantro,
   parsley (`config/piece_weights.json`).
3. **Densities** — heavy cream, red pepper flakes, baking staples, vanilla, milks
   (`config/food_density.json`).
4. **Accents** — `jalapeños` and friends now match in both the food lookup and the
   units table (`lib/units.py`, `lib/ingredient_text.py`).

Files: `lib/units.py`, `lib/ingredient_parser.py`, `lib/ingredient_text.py`,
`config/food_density.json`, `config/piece_weights.json`,
`scripts/grams_coverage_report.py` (new coverage meter),
`tests/test_units_coverage.py` (30 new tests).

## Verification

- Full suite **1127 passed**.
- Full-vault `backfill_nutrition.py --force`: **228 recipes updated, 0 failed**.
- Spot-check: Creamy Lentil 105 → 190 kcal (undercount fixed); Garlic Toast
  unchanged (already clean).
- `com.kitchenos.api` LaunchAgent restarted after the `lib/units.py` edits landed
  on main.

## Design Doc

docs/plans/ingredient-data-cleaning.md

## Deferred (still tracked in the design doc)

- **Phase A2** — amount/unit leaked into item text (`(estimated) 1/2 cup parmesan`,
  `to taste dollop yogurt`). Identified as the single biggest remaining coverage
  lever.
- **Phase B** — `*(inferred)*` / doubled-word item cleanup; long-tail table entries.

## Lessons Learned

- Coverage losses were overwhelmingly **table gaps, not parser bugs** — inspecting
  real recipes before touching code pointed straight at the cheap wins.
- A fixed-sample coverage meter (`scripts/grams_coverage_report.py`) made the work
  measurable and gated the full-vault `--force` on a real improvement.
- Informal quantity words split cleanly into "carries macros" (map to a unit) vs
  "negligible" (zero) — conflating them would either drop real calories or invent
  them.
