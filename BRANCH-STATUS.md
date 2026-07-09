# Branch Status: portion-resolution

**Created:** 2026-07-09
**Design Doc:** docs/plans/nutrition-portion-resolution.md
**Current Stage:** dev
**Last Rebased:** 2026-07-09 (forked from main @ 92143ce)

## Overview

Phase 1 (deterministic, offline) of nutrition portion resolution: make the existing
FDC-portion / density machinery actually land for the **374 quantified, food-known lines**
that currently fail `to_grams()`. No LLM in Phase 1.

Baseline (measured 2026-07-09, full vault): item coverage **0.632**, calorie-weighted
coverage **~0.47**, fully-covered recipes **7%** (16/228), grams-failed-on-known-food **374**.

Phase 2 (gated LLM fallback) is a separate follow-up branch.

## Dependencies

- None blocking. `USDA_FDC_API_KEY` present. No overlap with the parked
  `macro-planner-phase-1/servings-backfill` worktree (that consumes accurate macros;
  this produces them).

---

## Stages

### Dev
- [ ] **Tests written first** (superpowers:test-driven-development)
- [ ] **Task 0 — baseline meter:** promote scratch validator → `scripts/calorie_coverage_report.py`
      (item coverage, fully-covered %, est. calorie coverage, grams-failed-by-bucket).
      Locks in the 0.47 / 374 baseline for before/after.
- [ ] **Task 1 — spices → negligible-by-food:** food-keyed seasoning set (or shared
      spice density ≈ 2.3 g/tsp). ~474 lines, ~0 kcal impact — correctness + de-noise.
- [ ] **Task 2 — widen `_match_portion`:** unit synonyms (tbsp/tablespoon, tsp, cup,
      piece/whole/each); ignore non-household labels (`RACC`, gram-only); match by unit family.
- [ ] **Task 3 — volume→density path:** when unit family is volume and no household
      portion matches, convert via `density_g_per_ml` (record) → `config/food_density.json`.
      Extend density coverage for the common volume foods in the residue.
- [ ] **Task 4 — re-fetch detail for portion-less records:** the ~183/1819 (10%) cached
      records lacking portions (portions live on `usda_food_detail`, not search).
- [ ] Core implementation complete
- [ ] All tests passing
- [ ] No linting/type errors
- [ ] LaunchAgent restarted after lib/ edits (post-merge to main)

### Testing
- [ ] Unit tests pass
- [ ] `backfill_nutrition.py --force` applied; coverage report before/after
- [ ] Golden set: ~10 hand-labeled recipes, per-serving kcal within ±15% on ≥8/10
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] docs/plans/nutrition-portion-resolution.md — Phase 1 results recorded
- [ ] docs/plans/INDEX.md updated
- [ ] CLAUDE.md / OPERATIONS.md if a new command/invariant is added

### Ready
- [ ] Rebased on main; final test pass; BRANCH-STATUS complete

---

## Acceptance gates (Phase 1 slice of the design-doc criteria)

- Grams-failed-on-known-food **374 → materially down** (LLM-free ceiling; the residue
  that genuinely needs LLM is Phase 2 — record how many remain).
- Est. calorie coverage **0.47 → up** (target ≥0.80 is the full two-phase goal).
- Fully-covered recipes **7% → up**.

## Notes
- Editing `lib/units.py` / `lib/nutrition_engine.py` / `config/*.json` requires restarting
  `com.kitchenos.api` (holds `lib/*` in memory).
- Phase 1 stays deterministic/offline. Do NOT flip `portion_provider` off `"none"` here —
  that's Phase 2, gated to quantified material rows only.

## Blocked Items
- (none)
