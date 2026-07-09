# Design Documents — Live Index

The planning layer of the KitchenOS GitOps two-layer system. Tracks active design docs
through their lifecycle. Superseded/shipped legacy plans are frozen in
[archive/INDEX.md](archive/INDEX.md).

**Status flow:** Vision → Ready → In Progress → Done

- **Vision** — idea captured, not yet fleshed out enough to build.
- **Ready** — acceptance criteria + ADHD check + scope check all pass; may start a branch.
- **In Progress** — has an active branch / `BRANCH-STATUS.md`.
- **Done** — merged; move the row here and archive the summary in `docs/completed/`.

Templates: [`templates/DESIGN-DOC-TEMPLATE.md`](../../templates/DESIGN-DOC-TEMPLATE.md) ·
[`templates/BRANCH-STATUS.md`](../../templates/BRANCH-STATUS.md)

---

## Vision

| Date | Doc | Notes |
|---|---|---|
| — | — | (none) |

## Ready

| Date | Doc | Notes |
|---|---|---|
| 2026-07-09 | [nutrition-portion-resolution](nutrition-portion-resolution.md) | The real lever under macro accuracy. Measured: calorie-weighted coverage **~0.47**, only **7%** of recipes fully covered. Root cause (verified) is portion resolution, not table gaps — 374 quantified, food-known lines fail because `_match_portion` is too narrow, volume units need a density path, and `portion_provider` defaults to `"none"` (no fallback). Supersedes the "leaked-amount" framing of Phase A2. |

## In Progress

| Date | Doc | Branch | Notes |
|---|---|---|---|
| 2026-07-08 | [macro-meal-planner — design](2026-07-08-macro-meal-planner-design.md) · [plan](2026-07-08-macro-meal-planner-plan.md) | `macro-planner-phase-1/servings-backfill` | **PARKED.** Phase 1 (servings backfill) blocked: servings labels are not reliably inferable (see design-doc "Phase 1 finding"). Tooling/estimator built & committed on the branch; resume after grams coverage improves. |

## Done

| Date | Doc | Completed | Notes |
|---|---|---|---|
| 2026-07-08 | [ingredient-data-cleaning](ingredient-data-cleaning.md) | 2026-07-09 | Phase A1 shipped: nutrition-engine grams coverage **0.563 → 0.647** (+8.4 pts, 30-recipe sample) via unit/piece-weight/density/accent table gaps. Full-vault `backfill_nutrition.py --force` applied (228 updated, 0 failed). Phase A2 (leaked amounts) + Phase B deferred, still tracked in the design doc. See [docs/completed/2026-07-09-ingredient-grams-coverage.md](../completed/2026-07-09-ingredient-grams-coverage.md). |
| — | — | — | See [archive/INDEX.md](archive/INDEX.md) for pre-convention legacy plans. |
