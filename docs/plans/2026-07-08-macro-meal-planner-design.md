# Macro-Targeted Weekly Meal Planner (Servings-Ledger Model) Design

**Status:** In Progress (Phase 1)
**Created:** 2026-07-08
**Updated:** 2026-07-08
**Branch:** `macro-planner-phase-1/servings-backfill`

---

## Problem

The user wants a weekly meal plan that hits daily macro targets (2,300 kcal /
190 g protein / 228 g carbs / 70 g fat, from `My Macros.md` via
`lib/macro_targets.py`) using whole vault recipes on a servings-ledger model:
cook a recipe once, distribute its N servings across the week (eat, leftover,
freeze, trash) so each day's eaten servings sum to target.

Building this surfaced four blocking gaps, verified against the codebase on
2026-07-08:

1. **Servings data gap (root cause).** `lib/nutrition_engine.py` divides batch
   totals by `servings`, defaulting to 1 when missing. 103 of 229 recipes with
   nutrition data have `servings: null`, so their "per-serving" macros are
   whole-batch numbers (e.g. Hash Brown Casserole: 5,144 kcal). Only 126
   recipes have trustworthy per-serving macros. Only 2 of the 103 have a
   parseable "serves N"/"yield" line in the body — most are video/Crouton
   extractions with no yield text, so body parsing alone cannot fix this.
2. **Confidence/validation gap.** `nutrition_confidence` is 0.0 on 225/233
   recipes and `nutrition_needs_review` is absent from all 233 — the current
   gram-based engine has never been run library-wide; stored macros are
   legacy-engine output. The engine already computes sanity flags
   (`KCAL_SANITY_RANGE`, `dominant_line`, coverage, confidence) that nothing
   downstream currently gates on.
3. **Collection gap.** `dish_type: main` covers 72 recipes but only 8 *trusted*
   recipes deliver ≥30 g protein at 300–900 kcal/serving. A macro planner over
   this library will over-repeat a handful of chicken/bean bowls.
4. **No planner.** `generate_meal_plan.py` scaffolds an empty template. No code
   allocates servings across days against macro targets.

Order matters: the planner is garbage-in/garbage-out until per-serving data is
fixed, so data phases precede the planner build.

---

## Solution

Four phases, each independently shippable (< 1 week each):

- **Phase 1 — Servings backfill.** New `backfill_servings.py`: infer `servings`
  for the 103 missing recipes via a deterministic total-grams heuristic
  cross-checked by an LLM (Claude Haiku, Ollama fallback — same tiering as
  receipt parsing); agreement → write, disagreement → review queue. Then re-run
  `backfill_nutrition.py --force` library-wide so every recipe gets honest
  gram-based per-serving macros, confidence, coverage, and review flags.
- **Phase 2 — Validation gates & review loop.** Add a macro-consistency sanity
  check to the engine, define a single `planner_eligible()` predicate
  (servings present + confidence/coverage/sanity gates), extend the existing
  `/nutrition-review` queue to surface servings-inferred and macro-inconsistent
  recipes, and track eligible-recipe count in the dashboard.
- **Phase 3 — Collection enrichment.** Tag/report protein-dense mains, generate
  a gap report (what macro shapes the library lacks), and feed a curated
  acquisition list through the existing `batch_extract.py` Reminders pipeline.
  Target: ≥25 planner-eligible high-protein mains.
- **Phase 4 — The planner.** New `lib/macro_planner.py` allocating cook
  servings across the week (greedy protein-first bin-packing + local repair),
  inventory-aware via `lib/cook_now.py`, freezer banking via the existing
  serving-ledger semantics. Drafts land in `Meal Plans/_Drafts/DRAFT
  YYYY-MM-DD macro-week-YYYY-Www.md`; approval promotes to
  `Meal Plans/YYYY-Www.md` and (optionally) imports into the ledger via the
  existing `/api/week-board/<week>/import-legacy`. Shopping list for gaps via
  the existing pantry-aware shopping-list preview.

---

## Design

### Phase 1 — Servings backfill

**Inference cascade** (per recipe with `servings: null`):

1. **Body parse (cheap, rare):** regex for `serves|servings|yield(s)|makes N`
   in the body. Verified to hit only ~2 recipes, but it's free and exact.
2. **Deterministic grams heuristic:** run the existing nutrition engine to get
   `RecipeNutritionResult.total` and total resolved grams; estimate
   `servings ≈ total_grams / typical_serving_grams[dish_type]` (e.g. main ≈
   400 g, dessert ≈ 100 g, side ≈ 150 g, soup ≈ 350 g — constants tuned
   against the 126 recipes that *have* servings, which form a free golden
   set).
3. **LLM estimate:** prompt (new `prompts/servings_inference.py`, same module
   pattern as `prompts/food_resolution.py`) with title, dish_type, and the
   ingredient table; ask for an integer servings + one-line rationale.
   Claude Haiku when `ANTHROPIC_API_KEY` is set, `mistral:7b` via the
   `_ollama_json` pattern otherwise — mirrors the receipt-parser tiering.
4. **Reconcile:** heuristic and LLM within ±1 (or ±25%) → accept the LLM
   integer, `servings_confidence: high`. Disagree → write the heuristic value,
   `servings_confidence: low`, `needs_review: true` (escalate-only, matching
   `backfill_nutrition.py` semantics). Never leave `servings` null after the
   run — a flagged estimate beats a silent ÷1.

**Frontmatter written:** `servings: N`, `servings_inferred: true`,
`servings_confidence: high|low`, `servings_method: body|grams|llm|reconciled`.
Uses the `rewrite_frontmatter` de-dup machinery from `backfill_nutrition.py`
(extract it to `lib/` or import it), `backup.create_backup()` before every
write, `--dry-run/--limit/--force` flags to match house style.

**Human review loop:** the run prints a review table (recipe, heuristic, LLM,
chosen, confidence) and low-confidence rows appear in the Phase 2 review
queue. User fixes `servings` by hand in Obsidian where wrong; re-running
`backfill_nutrition.py --force <changed>` re-derives macros. Calibration gate
before trusting the tool: run it in check-mode against the 126 recipes that
already have servings and require ≥80% within ±1.

**Then:** `backfill_nutrition.py --force` over all 229 recipes (needs a real
`USDA_FDC_API_KEY`; resolutions are cached in `inventory_db`, so cost is
one-time).

### Phase 2 — Validation gates

- **New sanity flag in `nutrition_engine.py`:** `macro_mismatch` when
  `|4P + 4C + 9F − kcal| / kcal > 0.25` per serving (catches bad resolutions
  the kcal range check misses). Feed it into the existing `sanity_flags` /
  `needs_review` composition.
- **Single eligibility predicate** `planner_eligible(fm) -> (bool, reasons)`
  in a new `lib/nutrition_quality.py`: servings present and ≥1; kcal within
  `KCAL_SANITY_RANGE`; `nutrition_confidence ≥ 0.5`; `nutrition_coverage ≥
  0.8`; no `macro_mismatch`. Derived at read time from frontmatter — **not** a
  stored flag that can go stale. The planner, and only the planner, consumes
  it; nothing else changes behavior.
- **Review queue extension:** `/api/nutrition-review/recipes` ranking already
  surfaces worst-first; add servings-inferred/low-confidence reasons to the
  queue payload so the existing UI shows them.
- **Reporting:** `scripts/ingredient_quality_report.py`-style counter of
  planner-eligible recipes (overall and mains) so progress is visible.

### Phase 3 — Collection enrichment

- **Audit script** `scripts/recipe_gap_report.py`: classify eligible recipes
  into macro shapes (protein-dense main ≥30 g P / 300–900 kcal; high-protein
  breakfast ≥25 g P; protein snack ≥15 g P / ≤300 kcal; carb-side; etc.) and
  write a generated `Dashboards/Recipe Gaps.md` view (do-not-edit banner,
  standard generated-view pattern).
- **Acquisition workflow:** no new pipeline. A curated URL list (user-approved)
  goes into the "Recipies to Process" Reminders list; the existing hourly
  `batch_extract.py` ingests them. Target intake: ~20–25 high-protein savory
  mains biased toward on-hand staples (canned chicken/tuna, eggs, Greek
  yogurt, beans, frozen veg).
- **Definition of done is a number, not a vibe:** ≥25 planner-eligible
  protein-dense mains and ≥6 eligible high-protein breakfasts/snacks.

### Phase 4 — Planner

**Model.** Reuse the serving-ledger vocabulary: the planner proposes a set of
*cooks* (recipe, scale, cook date/meal, servings_produced = recipe servings ×
scale) and *placements* (slot date+meal / freezer / trash). This makes the
draft directly importable into the existing `cooks`/`placements` tables.

**Config** (new frontmatter keys in `My Macros.md`, parsed by an extended
`lib/macro_targets.py`; all defaulted so absence changes nothing):
`meals_per_day: 3`, `snacks_per_day: 1`, `kcal_tolerance: 0.05`,
`protein_floor: true`, `max_cooks_per_recipe_per_week: 1`,
`max_recipe_appearances_per_week: 3`, `leftover_window_days: 3`,
`max_powder_meals_per_day: 1`.

**Algorithm — greedy protein-first with local repair** (not ILP; the search
space is small and explainability matters more than optimality):

1. *Candidate pool:* eligible recipes (Phase 2 predicate), scored =
   w1·inventory coverage (`cook_now.generate()`) + w2·at-risk bonus +
   w3·protein density (g P / 100 kcal) + w4·recency penalty (appeared in last
   2 weeks' plans) − w5·powder reliance.
2. *Skeleton:* 7 days × (breakfast, lunch, dinner, snack). Dinners are the
   anchor: pick 3–4 mains to cook across the week; each cook's servings fill
   its dinner slot plus lunches/dinners on following days within
   `leftover_window_days`; surplus servings beyond the window auto-place to
   `freezer`; `trash` is never planned (waste is a failure mode, not a plan).
   Existing unplaced freezer servings in the ledger are drawable candidates
   with zero cook cost.
3. *Fill:* breakfasts/snacks from eligible breakfast/snack recipes (batch
   cooks like protein oats count as multi-day cooks too). Greedy per day:
   satisfy protein first (the tight constraint at 190 g / 2,300 kcal), then
   check kcal.
4. *Repair pass:* per day, if protein < floor or kcal outside ±tolerance, swap
   the snack or scale a filler (bounded iterations; emit warnings rather than
   loop). Days that can't converge are annotated in the draft ("protein −12 g:
   add a yogurt bowl") — honest-about-inference, human closes the gap.
5. *Constraints:* repetition caps above; no identical dinner on consecutive
   days (soft); ≤1 powder-based meal/day.

**Inventory & shopping.** Selection is *biased* by coverage, not blocked by
it. After selection, aggregate needed ingredients (existing
`shopping_list_generator` / `/api/shopping-list/preview` machinery) and diff
against pantry → a "Shopping (gaps)" section in the draft.

**Output & workflow.**
1. `plan_macro_week.py --week 2026-W29` writes
   `Meal Plans/_Drafts/DRAFT 2026-07-08 macro-week-2026-W29.md`: per-day meal
   tables with per-meal and per-day macro totals vs target, the cook schedule
   (what to cook when, at what scale), freezer movements, shopping gaps, and a
   machine-readable fenced JSON block (cooks + placements) for promotion.
   `_Drafts/` is pipeline-inert (index glob is non-recursive and
   week-name-anchored — verified `lib/meal_plan_index.py:67`).
2. User reviews/redlines in Obsidian.
3. `plan_macro_week.py --promote <draft>` (or an API route later): renders the
   standard weekly markdown to `Meal Plans/YYYY-Www.md`, posts cooks/placements
   to the ledger (then `week_view` re-renders authoritatively), deletes the
   draft. Promotion is the only step with side effects.

No LaunchAgent automation initially — generation is on-demand. The existing
`com.kitchenos.mealplan` daily template job is untouched (it skips existing
files without `--force`).

### Design decisions resolved

| Decision | Recommendation |
|---|---|
| Servings inference | Grams-heuristic × LLM cross-check; body parse first but it only covers ~2 recipes. Never leave null; flag disagreements. Calibrate on the 126 known-servings recipes before writing. |
| LLM choice | Claude Haiku primary, Ollama `mistral:7b` fallback — matches receipt-parser tiering; ~100 one-shot calls, negligible cost. |
| Planner algorithm | Greedy protein-first bin-packing + bounded repair, not ILP. Deterministic, explainable, testable with golden fixtures. |
| Freezer/leftovers | Leftovers auto-fill ≤3 days out; overflow → freezer placements; freezer stock is a zero-cost candidate next week. Ledger semantics reused wholesale. |
| Inventory | `cook_now` coverage + at-risk as scoring signals; shopping-gap section, never a hard block. |
| Powder vs whole food | ≤1 powder-based meal/day (config). Protein density scoring prefers whole-food mains once Phase 3 lands. |
| Meals/day | 3 + 1 snack default, config in `My Macros.md`. |
| Repetition | ≤1 cook/recipe/week, ≤3 appearances/week (leftovers), no consecutive identical dinners (soft). |

---

## Implementation Notes

Companion implementation plan: `docs/plans/2026-07-08-macro-meal-planner-plan.md`
(file-by-file tasks, sequencing, acceptance criteria per phase).

Key existing assets reused: `backfill_nutrition.py` (frontmatter rewrite +
backup pattern), `lib/nutrition_engine.py` (totals, grams, sanity flags),
`/nutrition-review` UI, `scripts/validate_nutrition.py` golden harness,
`lib/cook_now.py`, `lib/serving_ledger.py` + `lib/week_view.py` +
`import-legacy`, `lib/shopping_list_generator.py`, `prompts/` module pattern,
`lib/macro_targets.py`, `lib/recipe_index.py` (already exposes `servings` +
nutrition fields).

Operational cautions: editing `lib/` requires the `com.kitchenos.api`
LaunchAgent restart (stale-code 500s otherwise); `backfill --force` needs a
real `USDA_FDC_API_KEY`; every recipe write goes through
`backup.create_backup()`; all vault paths via `lib/paths.py`.

---

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — per phase, in the implementation plan
- [x] **ADHD check passed** — see below
- [x] **Scope check** — each phase < 1 week; phases are independent ship units
- [x] **No blockers** — Phase 1 needs only existing keys (`ANTHROPIC_API_KEY`
      optional, `USDA_FDC_API_KEY` for the backfill); Phases 2–4 depend only
      on the prior phase

### Acceptance Criteria (summary — full list in the plan doc)

- [ ] 0 recipes with nutrition data and `servings: null`; ≥80% ±1 accuracy on
      the known-servings calibration set
- [ ] Library-wide gram-based backfill complete; planner-eligible predicate
      implemented and surfaced in review UI + report
- [ ] ≥25 planner-eligible protein-dense mains
- [ ] Generated draft hits ≤5% kcal deviation and protein floor on ≥6/7 days
      against current vault + inventory; promotion round-trips into the ledger

### ADHD Design Check

- [x] **Reduces friction?** One command → reviewed draft → one promote step;
      acquisition rides the existing Reminders pipeline
- [x] **Visible?** Draft in Obsidian; gaps/deviations annotated inline;
      Recipe Gaps dashboard note
- [x] **Externalizes cognition?** Macro math, leftover windows, and freezer
      banking are computed and written down, not mentally tracked

---

## Links

- **Branch:** (added when implementation starts — suggested `macro-meal-planner-phase1`)
- **PR:** (added when complete)
