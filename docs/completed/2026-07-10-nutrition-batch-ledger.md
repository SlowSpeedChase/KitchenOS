# Completed: Nutrition Batch Ledger — Phase 2 (core)

**Completed:** 2026-07-10
**Branch:** nutrition-batch-ledger
**Design doc:** docs/plans/nutrition-batch-ledger.md
**Origin:** 2026-07-09 Fable strategic consult (batch/ledger reframe)

## Summary

Phase 1 got calorie coverage to 0.47 but stalled: the leak was portion conversion +
food-match quality, and the engine depended on the rate-limited USDA API at runtime.
Fable reframed it as a **batch** problem — resolve the finite corpus once, materialize it,
consume deterministically. Executed as three components; **offline calorie coverage went
0.434 → 0.929**, and the engine now runs with zero network calls.

## Result (offline, apples-to-apples)

| Metric | Pre-Phase 2 | Shipped |
|---|---|---|
| Calorie-weighted coverage | 0.434 | **0.929** |
| Item coverage | 0.503 | **0.972** |
| Fully-covered recipes | ~7% | **75%** |
| grams-failed (food known) | — | **12** (from 388) |
| food-not-found | ~752 | 27 |

All headline acceptance criteria met: calorie ≥0.90, grams-failed <30, no runtime USDA
dependency, band-validated auditable ledger.

## Key Changes

- **A — Atwater energy fallback** — `lib/food_db._energy_kcal` derives kcal from macros
  when a food reports no summary energy (oils/butter). Rescued 28 real foods (butter→734).
- **B — bulk FDC → local SQLite** — `lib/fdc_local.py` (schema, shared order-independent
  `normalize_food_name`, `unit_from_portion`, FTS5 + Python ranking, `resolve_local`),
  `scripts/load_fdc_bulk.py` (streaming CSV + FNDDS JSON, energy cascade at load, idempotent).
  13,694 foods / 36,763 portions. Wired as the primary resolver in `_resolve_food`. Fixed the
  semantic mismatches (apple→"Apple, raw" not Strudel; olive oil→900 not 0-kcal). Removed the
  runtime USDA dependency and the whole rate-limit class of problems.
- **C — LLM portion ledger** — `portion_ledger` table + band validation (grams>0/<2000,
  volume implied-density 0.1–2 g/ml, per-unit kcal ceilings), `scripts/build_portion_ledger.py`
  (enumerate grams-failed pairs → Ollama estimate → band-validate → ledger or review queue).
  `_resolve_grams` reads it deterministically (`method=ledger`). 563 written, 18 to review.
- **perf** — `inventory_db.read_conn()` thread-local cached connection (suite 226s → 14s).

## Verification

- Full suite **1164 passed / 1 skipped**; every component TDD.
- Ledger confirmed in-engine: 2 tbsp neutral oil 0→237 kcal, 1 scoop protein 0→123, 1 can
  beans 0→1467 (all `method=ledger`).
- Bands caught real errors (pumpkin "3000g implausibly large" → review, not written).

## Lessons Learned

- **Batch beats runtime.** A finite, static corpus is a table to materialize once, not a
  parser to perfect. The LLM as a one-time table generator (band-validated) + deterministic
  consumption is the durable shape.
- **"Resolved" ≠ "has calories" ≠ "has grams."** Three distinct failure layers (food match,
  energy parse, portion convert) that a single coverage number smears together — measure
  calorie-weighted, and separate the buckets.
- Local bulk data (FNDDS portions) removes an entire class of operational pain (rate limits).

## Follow-ups

- Component D: spices→negligible, recipe-level sanity flags (per-serving 100–1500 kcal).
- Wire the review queue (18 items) to an Obsidian note; golden-set ±15% validation.
- `--force` re-backfill to write the improved macros into recipe frontmatter.
- Loader integration test; periodic FDC bulk refresh.
- Vision: [purchase-based-nutrition.md](../plans/purchase-based-nutrition.md).
