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
| — | — | (none) |

## In Progress

| Date | Doc | Branch | Notes |
|---|---|---|---|
| 2026-07-08 | [ingredient-data-cleaning](ingredient-data-cleaning.md) | `ingredient-grams-coverage` | Lift nutrition-engine grams coverage (measured median **0.58**) — the real blocker under both per-serving macro accuracy and servings inference. Starting with unit/piece-weight/density table gaps (surgical, low-risk). |
| 2026-07-08 | [macro-meal-planner — design](2026-07-08-macro-meal-planner-design.md) · [plan](2026-07-08-macro-meal-planner-plan.md) | `macro-planner-phase-1/servings-backfill` | **PARKED.** Phase 1 (servings backfill) blocked: servings labels are not reliably inferable (see design-doc "Phase 1 finding"). Tooling/estimator built & committed on the branch; resume after grams coverage improves. |

## Done

| Date | Doc | Completed | Notes |
|---|---|---|---|
| — | — | — | See [archive/INDEX.md](archive/INDEX.md) for pre-convention legacy plans. |
