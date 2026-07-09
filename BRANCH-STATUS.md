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
- [x] **Task 0 — baseline meter:** `scripts/calorie_coverage_report.py` committed.
      Baseline: item 0.632, calorie ~0.47, 374 portion failures, 7% fully-covered.
- [x] **Task 2 — FDC portions in the volume path** (TDD, commit `33ee3fc`): `to_grams`
      volume branch used density-only and ignored `usda_portions`. Now falls back to
      `_match_portion`. **Offline-measured: +179 previously-dead volume lines resolved**
      (of 536 volume-unresolved: 179 recovered, 93 record-but-no-portion, 264 no record).
      4 new tests; full suite 1130 passed.
- [x] **Task R (part 1) — USDA 429 backoff** (TDD): `usda_search`/`usda_food_detail`
      now retry HTTP 429 with exponential backoff via `_get_json` instead of swallowing
      it into `[]`. 3 new tests (retry-then-succeed, exhausted→[], non-429 not retried);
      full suite 1132 passed. **Re-backfill in a fresh rate window will now stop dropping
      real foods.**
- [ ] **Task R (part 2) — offline/cache-only meter** so measurement never depends on the
      live API (understates while the window is exhausted). Still pending.
      NOTE: a clean live calorie number needs the ~1h USDA window to reset, then a
      re-backfill (now safe with the backoff), then re-run the meter.
- [ ] **Task 3 — volume→density path** for the 93 record-but-no-portion volume lines
      (RACC-only / no household portion). Reuses the existing volume-density path.
- [ ] **Task 1 — spices → negligible-by-food:** ~0 kcal; de-noise + Phase-2 LLM gating.
      Lower priority (no calorie impact); curate conservatively (avoid `red pepper`
      = bell pepper, `nutritional yeast` = real macros).
- [ ] **Task 4 — food-not-found tail (264):** partly rate-limit casualties (see Task R);
      re-backfill in a fresh window first, then assess the true residual.
- [ ] All tests passing / no lint errors / LaunchAgent restarted post-merge

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
