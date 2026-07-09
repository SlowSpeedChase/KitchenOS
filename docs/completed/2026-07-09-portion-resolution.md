# Completed: Nutrition Portion Resolution — Phase 1

**Completed:** 2026-07-09
**Branch:** portion-resolution
**Duration:** 1 day
**Design doc:** docs/plans/nutrition-portion-resolution.md

## Summary

Set out to fix per-serving macro accuracy (trustworthy on only 7% of the vault;
calorie-weighted coverage ~0.47). Targeted per-recipe inspection reframed the problem:
the dominant leak was **food-data quality**, not portion conversion. Shipped five fixes.

## Key Changes

1. **FDC household portions in the volume path** (`lib/units.py`) — `to_grams` tried only
   density for volume units and ignored the FDC portions already on the record. +179
   previously-unresolved volume lines (offline-measured).
2. **USDA 429 backoff** (`lib/food_db.py`) — `usda_search`/`usda_food_detail` swallowed
   HTTP 429 into `[]`/`None`, so throttled-but-resolvable foods looked "not found" and
   corrupted backfills. Added `_get_json` with exponential backoff.
3. **Energy nutrient-ID fix (dominant)** (`lib/food_db.py`) — USDA Foundation Foods report
   energy under 2047/2048 (Atwater), not 1008; `_per_100g` read only 1008, so foods like
   heavy cream / almond flour / milks resolved with macros but **0 kcal** — invisible to
   item/grams coverage. Read 1008 → 2047 → 2048.
4. **Offline (cache-only) resolution mode** (`lib/nutrition_engine.py`) + `--offline` on
   the new `scripts/calorie_coverage_report.py` — rate-limit-immune measurement.
5. **Caloric-sanity guard** (`lib/nutrition_engine.py`) — `_prefer_caloric_match` rescues a
   0-kcal Foundation pick (oils/butter/produce) with a caloric sibling, Jaccard-ranked to
   avoid matching "olive oil" to "Anchovies, canned in olive oil".

Also: `scripts/calorie_coverage_report.py` (calorie-weighted coverage meter, the gate).

## Verification

- Full suite **1139 passed / 1 skipped**; every fix TDD (RED→GREEN).
- Energy fix validated on 5 real recipes (before = 0-kcal-bug state, after = fix +
  refreshed cache): Almond Flour Pancakes 217→1012 (+366%), Cottage Cheese Cookie Dough
  764→1353, Baked Mac & Cheese 2637→3445 (heavy cream 0→807), Chia Pudding 594→642.
- Scope of the energy bug: 46/411 cached usda foods (11%), all calorie-dense staples.

## Lessons Learned

- **Targeted beats vault-wide.** Line-by-line inspection of 5 recipes found the dominant
  bug (energy IDs) in minutes; repeated full-vault runs only exhausted the USDA rate limit
  and produced throttled false-negatives.
- **"Resolved" ≠ "has calories."** Item/grams coverage hid the biggest leak (0-kcal
  foods). Calorie-weighted measurement is the metric that matters.
- USDA's ~1k/hr limit is the real operational bottleneck for backfill/measurement; needs
  paced resolution or an offline meter, and 429 backoff so real foods aren't dropped.

## Follow-ups (tracked in the design doc)

- Vault-wide `--force` re-backfill in a fresh rate window → true calorie-coverage number.
- Food-match depth: synonym normalization, semantic mismatch (apple→strudel), stemming.
- Spice-negligible-by-food; food-not-found tail.
- Vision: [purchase-based-nutrition.md](../plans/purchase-based-nutrition.md).
