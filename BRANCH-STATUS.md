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
    - [ ] Rewire resolver: FTS recall → Python rank (bm25 + dataset_rank + token_coverage −
          length_penalty − kcal_none_penalty; kills apple→strudel) → local macros/portions.
          `food_resolution` becomes the ledger (`source='fdc'`).
    - [ ] Loader integration test (tiny synthetic CSV fixture).
- [ ] Component C — LLM resolution ledger
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
