# Macro-Targeted Weekly Meal Planner — Implementation Plan

**Design doc:** `docs/plans/2026-07-08-macro-meal-planner-design.md`
**Created:** 2026-07-08

Phases ship independently, in order. Each phase = one GitOps branch
(`macro-planner-phase-N/<name>`), its own BRANCH-STATUS.md, TDD per stage
conventions. Data phases (1–2) MUST land before the planner (4); 3 can overlap
with 4 but 4's acceptance run requires 3's output.

---

## Phase 1 — Servings backfill (est. 2–3 days)

### Tasks

1. **`prompts/servings_inference.py`** (new) — prompt builder returning JSON
   `{servings: int, rationale: str}` given title, dish_type, ingredient table.
   Mirror `prompts/food_resolution.py` style.
2. **`lib/servings_estimator.py`** (new) —
   - `estimate_from_body(body) -> Optional[int]` (serves/yield/makes regex)
   - `estimate_from_grams(total_grams, dish_type) -> Optional[int]` with a
     `TYPICAL_SERVING_GRAMS` table; grams come from
     `calculate_recipe_nutrition(...).line_items` totals
   - `estimate_with_llm(...)` — Claude Haiku if `ANTHROPIC_API_KEY` else
     Ollama `_ollama_json` pattern (see `lib/food_resolver.py:68`)
   - `reconcile(heuristic, llm) -> (servings, confidence, method)`
3. **`backfill_servings.py`** (new, top-level) — flags `--dry-run`, `--limit`,
   `--force`, `--calibrate`. `--calibrate` runs the estimator against the 126
   recipes that already have `servings` and prints accuracy (gate: ≥80%
   within ±1 before any write run). Writes `servings`,
   `servings_inferred: true`, `servings_confidence`, `servings_method` via the
   frontmatter rewrite + `create_backup()` pattern; `needs_review` escalate-only.
   Reuse/extract `rewrite_frontmatter` from `backfill_nutrition.py` (move to
   `lib/frontmatter.py` if importing across top-level scripts is awkward).
4. **Tests** — `tests/test_servings_estimator.py` (regex cases, grams table,
   reconcile matrix, LLM mocked), `tests/test_backfill_servings.py`
   (frontmatter round-trip on fixtures, dry-run no-write, backup created).
5. **Execution (operator steps, documented in the run log):**
   `--calibrate` → review → `--dry-run` → run → spot-check low-confidence
   list → `.venv/bin/python backfill_nutrition.py --force` (all 229) →
   restart `com.kitchenos.api` LaunchAgent.
6. **Docs** — `docs/OPERATIONS.md` new-command entry; CLAUDE.md Key
   Functions/doc table check per `finish-feature` skill.

### Acceptance criteria

- [ ] `--calibrate` reports ≥80% within ±1 on known-servings recipes
- [ ] After run: 0 recipes with nutrition data and `servings: null`
- [ ] Every inferred recipe carries `servings_inferred` + confidence + method
- [ ] `backfill_nutrition.py --force` completed; no recipe with
      `nutrition_needs_review` missing; per-serving kcal >2,500 count drops
      from 11 to ~0 (any survivor is flagged, not silent)
- [ ] All tests pass; dry-run modifies nothing

## Phase 2 — Validation gates & review loop (est. 1–2 days)

### Tasks

1. **`lib/nutrition_engine.py`** — add `macro_mismatch` sanity flag
   (|4P+4C+9F − kcal|/kcal > 0.25 per serving) into `sanity_flags` /
   `needs_review` composition (around lines 417–431).
2. **`lib/nutrition_quality.py`** (new) — `planner_eligible(fm) ->
   (bool, list[str])` implementing the gates (servings ≥1, kcal in
   `KCAL_SANITY_RANGE`, confidence ≥ `REVIEW_CONFIDENCE`, coverage ≥
   `COVERAGE_REVIEW_THRESHOLD`, no macro_mismatch). Import engine constants —
   no magic-number copies.
3. **`api_server.py`** — extend `/api/nutrition-review/recipes` queue items
   with servings-inferred / low-servings-confidence / macro-mismatch reasons;
   surface in `templates/nutrition_review.html` reason chips.
4. **`scripts/recipe_quality_report.py`** (new or extend
   `ingredient_quality_report.py`) — counts of eligible recipes overall / by
   dish_type; prints the ineligible-reasons histogram.
5. **Tests** — `tests/test_nutrition_quality.py`; extend engine tests for the
   new flag. Restart LaunchAgent after `lib/` edits.

### Acceptance criteria

- [ ] `planner_eligible` unit-tested against fixture frontmatter (each gate)
- [ ] Review UI shows the new reasons; queue ranks them
- [ ] Report runs and prints eligible counts (baseline recorded in the doc)

## Phase 3 — Collection enrichment (est. 1–2 days tooling + ongoing intake)

### Tasks

1. **`scripts/recipe_gap_report.py`** (new) — macro-shape classification of
   eligible recipes; writes generated `Dashboards/Recipe Gaps.md`
   (do-not-edit banner, generated-view pattern).
2. **Curated acquisition list** — user-approved URLs into "Recipies to
   Process" Reminders; existing hourly `batch_extract.py` ingests. New
   extractions get `servings` from source pages far more often (webpage
   scrape path), and Phase 1's tool covers stragglers.
3. **Optional dish_type cleanup** — 13 recipes have `dish_type: null`, 2 have
   non-vocab `Dinner`; normalize via `lib/normalizer.py` vocab route.

### Acceptance criteria

- [ ] Gap report generates and identifies shortage categories
- [ ] ≥25 planner-eligible protein-dense mains (≥30 g P, 300–900 kcal/serving)
- [ ] ≥6 eligible high-protein breakfasts/snacks

## Phase 4 — Macro planner (est. 4–5 days)

### Tasks

1. **`lib/macro_targets.py`** — parse optional planner config keys from
   `My Macros.md` frontmatter (meals_per_day, snacks_per_day, kcal_tolerance,
   protein_floor, max_cooks_per_recipe_per_week,
   max_recipe_appearances_per_week, leftover_window_days,
   max_powder_meals_per_day) with defaults; return alongside `NutritionData`.
2. **`lib/macro_planner.py`** (new) — pure planning core:
   - `build_candidate_pool()` — recipe_index + `planner_eligible` +
     `cook_now.generate()` scores + recency from recent `Meal Plans/*.md` +
     ledger freezer stock (`serving_ledger`)
   - `plan_week(week, targets, config, pool) -> PlanResult` (cooks,
     placements, per-day macro table, warnings) — greedy protein-first +
     bounded repair per the design doc; deterministic given inputs (seedable
     tiebreaks) so tests are stable
   - `render_draft(plan) -> str` — markdown + fenced JSON block
3. **`plan_macro_week.py`** (new, top-level CLI) —
   `--week`, `--dry-run`, `--promote <draft-file>`. Generate → write draft to
   `meal_plans_dir() / "_Drafts"`. Promote → parse JSON block, write
   `YYYY-Www.md`, create ledger cooks/placements (direct `serving_ledger`
   calls; `week_view` re-renders), regenerate index, delete draft. Refuse to
   promote if the week file already exists without `--force`.
4. **Shopping gaps** — aggregate planned-cook ingredients through the existing
   shopping-list preview split (`from_pantry`/`to_buy`) and render a
   "Shopping (gaps)" draft section.
5. **Tests** — `tests/test_macro_planner.py` with fixture recipe pools
   (protein-rich/poor libraries; assert per-day protein floor + kcal
   tolerance, repetition caps, leftover window → freezer overflow, powder
   cap); `tests/test_plan_macro_week.py` (draft path naming stays
   index-invisible, promote round-trip into tmp `KITCHENOS_DB` ledger via
   `tmp_db` fixture, no side effects on generate).
6. **Docs** — `docs/OPERATIONS.md` command entry; `docs/ARCHITECTURE.md`
   feature-semantics paragraph; `docs/workflows/end-to-end.md` step;
   `docs/API.md` only if/when API routes are added (CLI-first initially).

### Acceptance criteria

- [ ] On the real vault + inventory: generated week hits protein ≥ target−10 g
      and kcal within ±5% on ≥6/7 days, warnings on any miss
- [ ] No recipe cooked >1×/week or appearing >3×/week; no planned trash
- [ ] Draft is invisible to index/calendar/tasks (verified by regenerating the
      index with a draft present)
- [ ] Promote writes the week file, populates cooks/placements, and
      `/api/week-board/<week>` reflects the plan; draft removed
- [ ] Shopping-gaps section matches preview-endpoint math on a fixture

---

## Sequencing & dependencies

```
Phase 1 (servings) ──► Phase 2 (gates) ──► Phase 4 (planner)
                                  └─► Phase 3 (collection) ──► Phase 4 acceptance run
```

## Risks

| Risk | Mitigation |
|---|---|
| LLM servings estimates wrong in bulk | Calibration gate on 126 known recipes before writes; disagreement → flag not trust; backups + `--dry-run` |
| `backfill --force` API cost / rate limits | Resolutions cached in `inventory_db`; real `USDA_FDC_API_KEY` required; `--limit` batches |
| Frontmatter corruption on 200+ rewrites | Reuse battle-tested `rewrite_frontmatter` + trailing-newline safeguards + `.history/` backups |
| Stale API code after lib/ edits | LaunchAgent restart step in every phase checklist |
| Planner infeasible days (protein too tight for library) | Warnings + human-closeable gaps in draft; Phase 3 raises the ceiling; snack/filler repair pass |
| Draft accidentally consumed by pipeline | Folder boundary verified (non-recursive glob + week-name regex); test asserts it |
| Ledger double-entry on repeated promote | Promote refuses existing week file without `--force`; import path checks for existing cooks |
