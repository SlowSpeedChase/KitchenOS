# Completed: Macro-aware meal suggestion + grid recipe cards

**Completed:** 2026-07-29
**Branch:** `claude/kitchen-os-meal-planning-mw3mme` (PR #35, squash-merged as `a613439`)
**Duration:** 1 day

## Summary
Ships the narrow, unblocked slice of the parked 2026-07-08 macro-meal-planner design: the
single-slot suggester now ranks by macro fit against your remaining daily targets, and two new
printable surfaces (`/plan-week`, `/print/week`) put the week on the fridge. Also lands a
review-oriented `servings` backfill so more of the recipe library is macro-usable at all.

The full weekly bin-packing planner stays parked. This was the part that stopped being blocked
once nutrition-batch-ledger lifted grams coverage from 0.43 → 0.93.

## Key Changes
- **Macro-aware suggester.** `suggest` ranks waste → macro-gap fit → overlap; new
  `lib/nutrition_quality.py:macro_eligible` gates recipes whose macros can't be trusted;
  `/api/suggest-meal` now returns a `macro_context` (target / current / remaining) alongside the
  suggestion, and the suggestion carries per-serving nutrition. (`lib/meal_suggester.py`,
  `api_server.py`, `prompts/meal_suggestion.py`)
- **`/plan-week` — Sunday command center.** Review the week's nutrition and print it.
  (`lib/plan_week.py`, `templates/plan_week.html`)
- **`/print/week` — one printable page**: the week's plan, macros vs targets, shopping list.
  (`lib/print_week.py`, `templates/print_week.html`)
- **Printable grid recipe cards** in the Cooking-for-Engineers style. (`lib/recipe_grid.py`,
  `prompts/recipe_grid.py`, `templates/recipe_card.html`)
- **`scripts/backfill_servings.py`** — fills a missing `servings` from data already in the file,
  fully offline. Two sources, deliberately distinguished:
  - **Stated** ("Serves 4", "Makes 24 cookies") → read from the body and written as plain fact:
    no review flag, and *not* clamped to `SERVINGS_MAX`, since a 24-cookie batch is a real yield.
  - **Estimated** → `servings ≈ batch_kcal / anchor(dish_type)`, clamped 1–12, always flagged
    `servings_inferred` + `servings_needs_review`.

  The clever half is the estimate's premise: a recipe missing `servings` already stores
  *whole-batch* calories, because the engine divided by 1. The corruption itself carries the signal.

## Resolving the duplicate servings-backfill
Two independent implementations existed. This merge settles it:

- **Kept:** PR #35's `scripts/backfill_servings.py`.
- **Retired:** the parked `macro-planner-phase-1/servings-backfill` branch (root
  `backfill_servings.py` + `lib/servings_estimator.py` + `prompts/servings_inference.py`), whose
  body/grams/LLM reconciler **never cleared its own ≥80%-within-±1 calibration gate** — it
  plateaued near 50%, which is why it sat at stage `dev` from 2026-07-08.
- **Grafted forward:** that branch's one unambiguous win, the explicit-yield reader. A recipe that
  states its yield has already answered the question; routing it through the kcal anchor lost
  accuracy *and* would have clamped a stated 24 down to 12.

They were never a git conflict — the files sat at different paths (`backfill_servings.py` vs
`scripts/backfill_servings.py`), so a merge would have silently produced two competing writers
with two different flag vocabularies (`needs_review` vs `servings_needs_review`).

## Verification
- Local `main` was **57 commits ahead of `origin/main`** (the Jul 25–27 consume-on-cook run), so
  GitHub's "CLEAN" status was measured against a stale base. Pushed `main` first, then rebased the
  PR onto the real one — which surfaced a genuine conflict in `tests/test_api_endpoints.py`
  (additive on both sides: bulk-inventory tests vs macro-suggest tests; both kept).
- Full suite green after rebase + graft: **2794 passed, 32 deselected**.
- 28 tests on `scripts/backfill_servings.py`, including the stated-yield reader. Two of them
  caught real regex bugs in the graft: greedy `(\d+)` backtracked to escape the measure-noun
  exclusion, so `Makes 500 g of granola` matched **50** and `Yield: 12 oz` matched **1**. Fixed
  with a `\b` after the digit group.
- `com.kitchenos.api` reloaded (it holds `lib/*` in memory and this PR rewrote three `lib`
  modules) — health `{"status":"ok"}`, and `/`, `/plan-week`, `/print/week`, `/cook-now`,
  `/review`, `/meal-planner` all 200 on the tailnet at `100.111.6.10:5001`.
- New pages propagated per the browsable-page invariant: `generate_web_dashboard.py` rewrote the
  vault launcher note and `sync_safari_bookmarks.py --apply` added both — verified all 11 pages
  present in the Safari `KitchenOS` folder.

## Not Done
- **The weekly bin-packing planner stays parked** — this is the single-slot suggester only.
- **`backfill_servings.py` has not been run against the vault.** It is dry-run by default and
  nothing has been applied yet; the ~103 recipes missing `servings` are still uncorrected.
- `fit_heart` / `fit_steady` remain uncomputable (no fibre or saturated fat in `NutritionData`
  or `fdc_foods`) — unchanged by this work.

## Design Doc
`docs/plans/2026-07-08-macro-meal-planner-design.md` · plan `2026-07-08-macro-meal-planner-plan.md`

## Lessons Learned
- **A PR's "CLEAN" badge is measured against the remote base, not your local one.** 57 unpushed
  commits made a genuinely-conflicting PR look mergeable. Pushing `main` first turned a silent
  semantic collision into an honest, visible one-file conflict.
- **Duplicate work hides at different paths.** Git had nothing to say about two servings backfills
  because they weren't the same file. The check that found it was comparing what the branches
  *did*, not what they *touched*.
- **A calibration gate is only worth having if you let it kill the work.** The parked branch's
  ≥80% gate did its job — it correctly refused to ship a 50%-accurate inference. The mistake would
  have been merging around it rather than taking the simpler heuristic that flags everything.
