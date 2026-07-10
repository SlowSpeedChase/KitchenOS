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
| 2026-07-09 | [purchase-based-nutrition](purchase-based-nutrition.md) | Use the user's actual purchases to override generic USDA with **branded** label nutrition (more personal + serving-gram data). Blocked: receipts carry no nutrition (only identify the product → still needs OFF/branded lookup) and `purchases`/`inventory` are currently 0 rows. Augments, doesn't replace, the USDA engine. Revisit once receipt ingest is flowing. |

## Ready

| Date | Doc | Notes |
|---|---|---|
| — | — | (none) |

## In Progress

| Date | Doc | Branch | Notes |
|---|---|---|---|
| 2026-07-08 | [macro-meal-planner — design](2026-07-08-macro-meal-planner-design.md) · [plan](2026-07-08-macro-meal-planner-plan.md) | `macro-planner-phase-1/servings-backfill` | **PARKED.** Phase 1 (servings backfill) blocked: servings labels are not reliably inferable (see design-doc "Phase 1 finding"). Tooling/estimator built & committed on the branch; resume after grams coverage improves. |

## Done

| Date | Doc | Completed | Notes |
|---|---|---|---|
| 2026-07-10 | [nutrition-batch-ledger](nutrition-batch-ledger.md) | 2026-07-10 | **Phase 2 core shipped** (Fable batch/ledger reframe). Offline calorie coverage **0.434 → 0.929**, item 0.503 → 0.972, fully-covered 11% → 75%, grams-failed 388 → 12; engine now fully offline (no runtime USDA). A (Atwater) + B (bulk FDC local store, 13.7k foods) + C (LLM portion ledger, band-validated). Component D + review-queue-note + golden-set + vault re-backfill are follow-ups. See [docs/completed/2026-07-10-nutrition-batch-ledger.md](../completed/2026-07-10-nutrition-batch-ledger.md). |
| 2026-07-09 | [nutrition-portion-resolution](nutrition-portion-resolution.md) | 2026-07-09 | **Phase 1 shipped.** 5 fixes (FDC volume portions, 429 backoff, energy nutrient-ID, offline meter, caloric-sanity guard). Dominant bug was food-data quality, not portions: energy under Atwater IDs → 0-kcal foods. Verified +31–366% on 5 recipes. Follow-ups (vault re-backfill, food-match depth) tracked in the doc. See [docs/completed/2026-07-09-portion-resolution.md](../completed/2026-07-09-portion-resolution.md). |
| 2026-07-08 | [ingredient-data-cleaning](ingredient-data-cleaning.md) | 2026-07-09 | Phase A1 shipped: nutrition-engine grams coverage **0.563 → 0.647** (+8.4 pts, 30-recipe sample) via unit/piece-weight/density/accent table gaps. Full-vault `backfill_nutrition.py --force` applied (228 updated, 0 failed). Phase A2 (leaked amounts) + Phase B deferred, still tracked in the design doc. See [docs/completed/2026-07-09-ingredient-grams-coverage.md](../completed/2026-07-09-ingredient-grams-coverage.md). |
| — | — | — | See [archive/INDEX.md](archive/INDEX.md) for pre-convention legacy plans. |
