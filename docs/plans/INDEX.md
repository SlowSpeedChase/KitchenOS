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
| — | — | Nothing queued. |

## In Progress

| Date | Doc | Branch | Notes |
|---|---|---|---|
| 2026-07-26 | [consume-on-cook — design](../superpowers/specs/2026-07-26-consume-on-cook-design.md) | `consume-on-cook` | Marking a recipe cooked decrements nothing: 234 of the 236 recipes with parseable ingredients change no inventory, and of 2,634 ingredient lines exactly 2 subtract. Three coupled defects — `split_against_pantry` credits limes that `apply_decisions` refuses to spend, `pantry.find_match` still runs the substring matcher `436597d` deleted everywhere else (11 peanut-butter lines match the `butter` staple), and the UI reads only `consumed` so failure renders as a green toast. Governing constraint: inventory holds **containers, not quantities** (188 of 198 count rows are qty exactly 1.0), so a qty-1 row is use-stamped, never decremented. Target: 18 decrements, 455 use-stamps, zero false decrements. |
| 2026-07-08 | [macro-meal-planner — design](2026-07-08-macro-meal-planner-design.md) · [plan](2026-07-08-macro-meal-planner-plan.md) | `macro-planner-phase-1/servings-backfill` | **PARKED.** Phase 1 (servings backfill) blocked: servings labels are not reliably inferable (see design-doc "Phase 1 finding"). Tooling/estimator built & committed on the branch; resume after grams coverage improves. |

## Done

| Date | Doc | Completed | Notes |
|---|---|---|---|
| 2026-07-25 | [cook-now-meal-type-filter — design](../superpowers/specs/2026-07-25-cook-now-meal-type-filter-design.md) · [plan](../superpowers/plans/2026-07-25-cook-now-meal-type-filter.md) | 2026-07-25 | Filter Cook Now by meal type. Half data repair, half feature: `dish_type` had drifted (12 one-off values, and `normalizer.py` mapped `"biscuit" → "dessert"`, so savory biscuits were filed as desserts), so a filter built on it would have been wrong in both directions. `VALID_DISH_TYPES` is now derived from `DISH_TYPE_MAP`'s targets, the biscuit rule is deleted so the repair can't rot, and `scripts/reclassify_dish_type.py` (Claude Batches, enum-constrained, dry-run by default) reclassified **63 of 239 recipes, 0 unresolved**. On top of that: `/cook-now` with six chip groups over the 13 values, filtering client-side with Desserts deselected by default. Review caught a non-string `dish_type` that would have 500'd the whole endpoint and a `GROUPS` array that could silently drift from the Python taxonomy. 1476 → 1504 tests, 22 → 25 e2e. See [docs/completed/2026-07-25-cook-now-meal-type-filter.md](../completed/2026-07-25-cook-now-meal-type-filter.md). |
| 2026-07-25 | [bulk-inventory-editing — design](../superpowers/specs/2026-07-25-bulk-inventory-editing-design.md) · [plan](../superpowers/plans/2026-07-25-bulk-inventory-editing.md) | 2026-07-25 | Mass select + edit on `/review` (checkboxes, Select All, sticky action bar) backed by one `POST /api/inventory/bulk` doing a single read-modify-write instead of N, addressed by the real `(name, unit, location)` key rather than the ambiguous `(name, location)`. Mid-branch the `+3d`/`+7d` buttons were also made cumulative — they set `today + N` outright, so a second tap was a no-op and `+3d` after `+7d` moved the date backward — and the list gained an Expiry/Added sort backed by `purchased`. The plan's manual phone script was automated instead: `tests/e2e/` is a Playwright harness the plan said didn't exist. 1426 → 1476 tests. See [docs/completed/2026-07-25-bulk-inventory-editing.md](../completed/2026-07-25-bulk-inventory-editing.md). |
| 2026-07-25 | inventory-truth-fixes (no design doc — bugfix) | 2026-07-25 | `Inventory.md` rendered empty while the DB held 219 items, and Cook Now ranked only desserts. Three fixes: `write_inventory()` now renders from the committed DB instead of the caller's list (it and `cook_now` were two sources in one function); token matching requires containment to reach the head noun of a *clean* name, killing "eggs" ↔ *Lo mein egg noodles* and "avocado" ↔ *Avocado oil* while leaving noisy ingredient text on plain containment; pantry staples are materialized as perpetual `source: staple` rows instead of an invisible assumption. 60 recipes de-inflated, 54 false-positive ingredients gone, 0 regressions. 1404 → 1426 tests. Root cause of the empty write is still unknown. See [docs/completed/2026-07-25-inventory-truth-fixes.md](../completed/2026-07-25-inventory-truth-fixes.md). |
| 2026-07-25 | [web-home-page](../superpowers/specs/2026-07-25-web-home-page-design.md) · [plan](../superpowers/plans/2026-07-25-web-home-page.md) | 2026-07-25 | A web home page at `/` rendered from the `SECTIONS` registry, plus a `ko-home-link` in `_CLAUDE_BAR_TEMPLATE` so every page links back with no per-template edits. `SECTIONS` now feeds three consumers; `HOME` added as the registry root (outside `SECTIONS`, else the page lists itself), which required fixing `desired_bookmarks()` — it built from `SECTIONS` alone, so the home bookmark would never have reached Safari. 1386 → 1405 tests. See [docs/completed/2026-07-25-web-home-page.md](../completed/2026-07-25-web-home-page.md). |
| 2026-07-12 | [photo-receipt-ingest](../superpowers/specs/2026-07-12-photo-receipt-ingest-design.md) | 2026-07-12 | Photograph an HEB receipt in the Claude iOS app → paste the schema JSON at `/receipt-paste` → full trip/inventory pipeline. Shared `lib/receipt_ingest.py:ingest_parsed` (extracted from `process_email`, email path unchanged), content-hash dedup, `POST /api/receipt/paste`. Zero server-side LLM. See [docs/completed/2026-07-12-photo-receipt-ingest.md](../completed/2026-07-12-photo-receipt-ingest.md). |
| 2026-07-10 | [nutrition-batch-ledger](nutrition-batch-ledger.md) | 2026-07-10 | **Phase 2 core shipped** (Fable batch/ledger reframe). Offline calorie coverage **0.434 → 0.929**, item 0.503 → 0.972, fully-covered 11% → 75%, grams-failed 388 → 12; engine now fully offline (no runtime USDA). A (Atwater) + B (bulk FDC local store, 13.7k foods) + C (LLM portion ledger, band-validated). Component D + review-queue-note + golden-set + vault re-backfill are follow-ups. See [docs/completed/2026-07-10-nutrition-batch-ledger.md](../completed/2026-07-10-nutrition-batch-ledger.md). |
| 2026-07-09 | [nutrition-portion-resolution](nutrition-portion-resolution.md) | 2026-07-09 | **Phase 1 shipped.** 5 fixes (FDC volume portions, 429 backoff, energy nutrient-ID, offline meter, caloric-sanity guard). Dominant bug was food-data quality, not portions: energy under Atwater IDs → 0-kcal foods. Verified +31–366% on 5 recipes. Follow-ups (vault re-backfill, food-match depth) tracked in the doc. See [docs/completed/2026-07-09-portion-resolution.md](../completed/2026-07-09-portion-resolution.md). |
| 2026-07-08 | [ingredient-data-cleaning](ingredient-data-cleaning.md) | 2026-07-09 | Phase A1 shipped: nutrition-engine grams coverage **0.563 → 0.647** (+8.4 pts, 30-recipe sample) via unit/piece-weight/density/accent table gaps. Full-vault `backfill_nutrition.py --force` applied (228 updated, 0 failed). Phase A2 (leaked amounts) + Phase B deferred, still tracked in the design doc. See [docs/completed/2026-07-09-ingredient-grams-coverage.md](../completed/2026-07-09-ingredient-grams-coverage.md). |
| — | — | — | See [archive/INDEX.md](archive/INDEX.md) for pre-convention legacy plans. |
