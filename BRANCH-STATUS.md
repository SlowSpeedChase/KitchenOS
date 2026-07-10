# Branch Status: nutrition-batch-ledger

**Created:** 2026-07-10
**Design Doc:** docs/plans/nutrition-batch-ledger.md
**Current Stage:** dev
**Last Rebased:** 2026-07-10 (forked from main @ 716e67c)

## Overview

Phase 2 nutrition accuracy (Fable batch/ledger reframe). Move calorie coverage from
0.571 toward ≥0.90. Sequenced so each component lands independently:

- **A — Atwater energy fallback** (~1 hr) ← current
- **B — Bulk FNDDS → local SQLite** (removes runtime USDA + rate limits, supplies portions)
- **C — LLM-drafted resolution ledger** (band-validated, Obsidian review queue; the 0.57→0.9 move)
- **D — metric/guardrails** (spices negligible, calorie-weighted only, recipe sanity flags)

## Dependencies

- None blocking. Phase 1 merged. FDC bulk is public; LLM keys present.

---

## Stages

### Dev
- [x] **Component A — Atwater energy fallback** (TDD, full suite 1142): compute
      `kcal/100g = 4·P + 4·C + 9·F` in `lib/food_db._energy_kcal` when 1008/2047/2048 are
      all absent. Verified against the real cache: **rescues 28 foods** — headline
      **unsalted butter → 734** (in many recipes), apples, green onions. 88 still-0 lack
      summary macros too (oils/water) → Component B/C. Note: Atwater over-counts high-fiber
      foods (apple 106 vs ~52) — underlying record quality, not A's fault; Component D
      recipe-sanity + B/C matching address it. Cached 0-kcal values realize on next
      refresh+backfill (bundled with B/C).
- [~] **Component B — bulk FDC → local SQLite** (in progress):
    - [x] `lib/fdc_local.py`: shared `normalize_food_name` (order-independent, load+query),
          `unit_from_portion`, and the `fdc_foods`/`fdc_portions`/`fdc_foods_fts`/`fdc_meta`
          schema. 9 tests.
    - [x] `scripts/load_fdc_bulk.py`: streaming CSV loader, energy cascade at load (reuses
          `food_db._energy_kcal`), delete-by-data_type idempotent, FTS rebuild, gram-weight
          banding. **Verified on real Foundation (469 foods, 187 portions):** butter→733
          (atwater), milk cup=227g, salt tsp=6.1g; FTS search + rank works.
    - [ ] Load SR Legacy (CSV) + FNDDS (JSON path — 64M not 1.6G CSV) into main DB.
    - [x] Loaded into main DB: Foundation 469 + SR Legacy 7793 + FNDDS 5432 =
          **13694 foods / 36763 portions**.
    - [x] Rewired resolver: `fdc_local.resolve_local` (FTS recall + Python rank with
          head-noun/length/coverage/dataset/kcal-none terms) is now the PRIMARY path in
          `_resolve_food` (after human pins, before legacy cache + network). Ranking
          verified: **apple→"Apple, raw" (not Strudel)**, **olive oil→900 (not 0-kcal)**,
          flour/chocolate-chips/butter all fixed. 4 ranking tests. Full suite 1155.
    - [x] **Measured (offline, apples-to-apples vs pre-B offline):** item 0.503→**0.710**,
          calorie 0.434→**0.580**, food-not-found ~752→**27**. Component B restored
          local-first (zero network) at coverage that previously needed the USDA API.
    - [ ] Loader integration test (tiny synthetic CSV fixture) — TODO.

FINDING: the bottleneck shifted from food-not-found to **portion conversion** (388
food-known/grams-failed). More foods resolve now, but count units (whole/scoop) and foods
without a clean volume portion still fail to_grams. That's the Component C lever (LLM
portion ledger) + a portion-matching pass, always "the 0.57→0.9 move". `food_resolution`-
as-ledger + write-back not yet done (local resolve is deterministic/cheap, re-runs each time).
- [~] **Component C — LLM portion ledger** (in progress):
    - [x] `portion_ledger` table + band validation (grams>0/<2000, volume implied-density
          0.1–2 g/ml, per-unit kcal ceilings) + `ledger_get/put`. 9 tests.
    - [x] `_resolve_grams` reads the ledger deterministically before any LLM (works with
          `portion_provider=none`). Confidence `CONFIDENCE_LEDGER`.
    - [x] `scripts/build_portion_ledger.py` — enumerate food-known/grams-failed (item,unit)
          pairs → LLM estimate (Ollama/Claude) → band-validate → ledger or review queue.
          Sample validated: oil tbsp=14g, protein scoop=30g, can beans=425g, spices tsp=4.2g,
          0 rejected.
    - [x] Full batch DONE (Ollama, 581 pairs → 563 written, 18 to review: bands caught
          "pumpkin 3000g", low-confidence). **FINAL offline coverage: calorie 0.580→0.929,
          item 0.710→0.972, fully-covered 11%→75%, grams-failed 388→12.** 🎯 Target met.
    - [ ] Obsidian review-queue note for out-of-band/no-estimate (currently printed only).
    - [ ] PERF: `_resolve_food`/`_resolve_grams` open an `inventory_db.connect()` per line
          (suite 20s→226s). Cache the connection before merge / full backfill.
- [ ] Component D — metric/guardrails
- [ ] All tests passing / no lint errors / LaunchAgent restarted post-merge

### Testing
- [ ] Unit tests pass
- [ ] Coverage meter before/after per component
- [ ] Golden set (≥9/10 within ±15% per-serving kcal)
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] docs/plans/nutrition-batch-ledger.md — results recorded
- [ ] docs/plans/INDEX.md updated
- [ ] CLAUDE.md / OPERATIONS.md if a new command/invariant is added

### Ready
- [ ] Rebased on main; final test pass; BRANCH-STATUS complete

---

## Acceptance gates (from the design doc)

- Calorie coverage **0.571 → ≥0.90**; grams-failed **322 → <30**; no runtime USDA
  dependency for a normal backfill; ledger human-auditable; golden set ±15% on ≥9/10.

## Notes
- Editing `lib/food_db.py` / `lib/nutrition_engine.py` requires restarting `com.kitchenos.api`.
- Component A is data-quality only (parser); no network, no recipe rewrites. A re-backfill
  to realize it vault-wide is a later step (bundle with Component B/C to avoid extra churn).

## Blocked Items
- (none)
