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

### KEY FINDING (2026-07-09, from targeted 5-recipe inspection)
Working real recipes line-by-line (not the vault) separated three distinct problems
the aggregate coverage number smeared together:
1. **Energy nutrient ID — FIXED (commit after 63e0b57).** USDA Foundation Foods report
   energy under 2047/2048, not 1008; `_per_100g` read only 1008, so heavy cream / almond
   flour / almond milk resolved with macros but **0 kcal** — the dominant calorie leak,
   invisible to item/grams coverage. Verified end-to-end: heavy cream **0 → 807 kcal** in
   Baked Mac & Cheese; milks 0 → 47. Refreshed the 5 affected cached foods for these recipes.
2. **Grams/portion — partly fixed (Task 2).** Residue like `chia seeds 6 tbsp` still needs
   a density entry.
3. **Wrong food match — OPEN.** `apple` → "Strudel, apple" (493 kcal), `reserved pasta
   water` → "Pasta, dry" (219), `chocolate chips` → a cookie. Resolver ranking, cached bad.
   Biggest remaining accuracy risk; separate from portions/energy.

RESIDUAL on #1 (clarified 2026-07-09): the Atwater fallback works on detail too —
almond flour detail returns 2047=622 and `usda_food_detail` now yields 622. The earlier
"0" for almond flour was a **429 rate-limit** (transient None), not a parse gap.
The genuine residual is narrower: a few USDA **Foundation** records (e.g. `Oil, olive,
extra virgin` 748608, `Oil, canola` 748278) carry **no summary energy AND no summary
fat** at all — only fatty-acid breakdowns — so no parser change recovers them. That is a
**food-resolver quality** problem (pick a caloric sibling), NOT an energy-parse problem.

Merged into problem class #3 (food-match quality) as the next scoped task:
- Wrong semantic match: `apple`→"Strudel, apple", `reserved pasta water`→"Pasta, dry".
- 0-nutrient Foundation pick: `olive oil`→748608 (0 kcal) when SR Legacy `Oil, olive,
  salad or cooking` (171413) has 884.
- **TRAP (do not ship a naive fix):** "prefer any caloric candidate" picks
  `Anchovies, canned in olive oil` (206) for "olive oil" via word overlap. Needs real
  ranking (semantic similarity / LLM resolver / description-mismatch penalty) + a clean
  rate window to measure. Own effort, not a tail-of-session heuristic.

### REMEASURE (2026-07-09, +1h, targeted per your "stop full-vault" note)
Energy-ID fix validated on 5 real recipes (before = 0-kcal-bug state, after = fix +
refreshed cache), cache-only measurement:
- Almond Flour Pancakes 217 → **1012** (+366%; flour was the whole recipe at 0 kcal)
- Cottage Cheese Cookie Dough 764 → 1353 (+77%)
- Baked Mac & Cheese 2637 → 3445 (+31%; heavy cream 0→807)
- Chia Pudding 594 → 642 (+8%); Chili Garlic Noodles 199 → 199 (no bugged foods)

Scope of the bug: **46 / 411 cached usda foods (11%) have the signature** (0 kcal, macros
> 0) — calorie-dense staples (flours, butter, cheeses, beans, oats, lentils, potatoes), so
the vault-wide gain from 0.47 is expected to be large.

OPERATIONAL FINDING: a clean vault-wide number is gated by USDA's borderline ~1k/hr limit
— refreshing all 46 + the meter's live lookups in one burst keeps re-tipping it (the
`STILL 0` false-negatives were throttles, not real zeros). Path forward: **paced**
re-resolution (small batches) or an **offline cache-only meter** (Task R part 2), NOT
another full-vault hammer. Still-visible wrong-match overcounts (apple→strudel 493, pasta
water→pasta 219) remain the separate food-match-quality task.

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
