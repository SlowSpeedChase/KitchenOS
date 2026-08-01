# Branch Status: recipe-schema-normalize

**Created:** 2026-07-31
**Design Doc:** none yet — findings captured below, promote to `docs/plans/` if this grows
**Current Stage:** planning (paused before any code was written)
**Last Rebased:** 2026-07-31 (branched from `origin/main` @ fd480e7)

## Overview

Normalize recipe frontmatter drift across the 252 files in
`vault/KitchenOS/Recipes/`, then add a corpus-wide schema test so the drift
can't silently return.

**Nothing has been implemented yet.** This branch contains only this status file
and the two throwaway profiling scripts under `scripts/_analysis/`. Resume at
"Next action" below.

## Dependencies

- None. Does not touch `data/kitchenos.db` or any `lib/` module, so no
  LaunchAgent restart is implied by the current scope.
- Runs against the live vault, so any write path needs `lib/backup.create_backup`
  first (same as `migrate_recipes.py` does).

---

## Findings (complete — this analysis does not need redoing)

Profiled all 252 files. The skeleton is uniform: every file has frontmatter, 30
keys appear at 100%, and every file has an H1 title plus `## Ingredients`,
`## Instructions`, `## Equipment`, `## My Notes` at the same heading level.
25 distinct key-sets exist, but most of that spread is optional-by-design.

### In scope — agreed fixes

**1. Non-numeric `servings` (3 files).** The other 249 are plain integers.
`lib/serving_ledger.py` coerces with bare `float()` in five places, so these can throw.

```
Creamy Grape Salad Alternative.md        servings: 4-6 servings (estimated)
Healthy Blueberry Apple Oatmeal Cake.md  servings: 6-8
Watermelon Feta Salad.md                 servings: 6-8 as a side dish
```

**DECIDED (user, 2026-07-31): take the low end of the range.** So `6-8` → `6`,
`4-6 servings (estimated)` → `4`, `6-8 as a side dish` → `6`. Also mark
`servings_inferred: true` + `servings_needs_review: true` — reusing the keys
11 files already carry, per the "honest about inference" principle in CLAUDE.md.
Low end means fewer servings means *higher* per-serving calories, which is the
conservative direction for macros.

**2. Legacy flat nutrition keys (13 files).** `calories` / `fat` / `carbs`
survive alongside the canonical `nutrition_*` keys. All have `date_added` in
2026-05 or 2026-06, so they postdate the last `migrate_recipes.py` run.

> **CRITICAL — do not just re-run `migrate_recipes.py` on these.**
> `rename_nutrition_keys` (migrate_recipes.py:40) rewrites `^calories:` to
> `nutrition_calories:`, but these files **already have** `nutrition_calories:`.
> The rename would produce two identical YAML keys in one document. This was
> inferred from reading the code; **write a failing test proving it before
> changing anything.**

The two families genuinely disagree — the legacy values look like
whole-recipe totals, not per-serving:

```
Watermelon Feta Salad.md      calories: 3058   vs  nutrition_calories: 169
3010 Blueberry Banana Smoothie.md  calories: 593  vs  nutrition_calories: 465
Borscht Recipe With Meat.md   calories: null   vs  nutrition_calories: 536
```

Proposed handling: `nutrition_*` wins (it is FDC-sourced —
`nutrition_source: "fdc"` on 244 of 252). Drop the legacy key. Only carry a
legacy value across when the canonical one is null — and of the 13, `calories`
is a number on 9 and null on 4, while `carbs`/`fat` were null everywhere sampled.

**4. Stray one-off keys (3 files).**

```
Chocolate Peanut Butter Bars.md   recipe_url: "https://feelgoodfoodie.net/recipe/chocolate-peanut-butter-bars/"
10-Minute Chili Garlic Noodles.md enrich_none: ["protein"]
Cabbage Steaks.md                 enrich_none: ["protein"]
```

**DECIDED (user, 2026-07-31): drop `recipe_url`.** Note what this costs — it is
*not* a duplicate of `source_url`. That file's `source_url` is the YouTube short;
`recipe_url` is the creator's own recipe page, and it exists nowhere else in the
corpus. Dropping it discards that URL. The vault is not in git, so the only
recovery path is the `lib/backup.create_backup` snapshot the normalizer takes
before writing — make sure that runs. **Never fold it into `source_url`.**

`enrich_none: ["protein"]` is still open, but it is a code question, not a user
question: locate its writer in the enrichment path before deciding. It may be
meaningful state rather than debris.

### Out of scope (deliberately)

- **Two nutrition sections in 19 files.** `templates/recipe_template.py` emits
  both `## Nutrition (per serving)` (line 182, computed from FDC) and
  `### Nutritional Info` (line 375, the source's own claimed numbers, appended
  into My Notes). Different levels, different provenance, no cross-check. This
  is template behavior, not file drift — a separate decision.
- **173 files with no body nutrition section**; data lives in frontmatter only.
  Correlates with era: the 122 `crouton_import` files (Jan–Feb 2026) have none;
  `ai_extraction` (Mar onward) writes them.
- **Quoted vs bare scalars** (`dish_type` 189/63, `recipe_source` 250/2). YAML
  parses both identically — cosmetic, only visible to grep-based tooling.
- **Time-string formats** (`"15 minutes"` vs `"20 min"` vs a `"(estimated)"`
  suffix). Real, but nothing does math on them today.
- **Optional-by-design keys — leave alone.** `short_title` on 70 (the long-name
  fix), `fit_*` on 249, cook-tracking keys on ~10 cooked recipes,
  `nutrition_unmatched` on 106, `banner` on 64. All confirmed intentional
  against CLAUDE.md.

---

## Next action (start here)

1. Read `lib/recipe_parser.py` to see how frontmatter is parsed, and decide
   **line-surgical edits vs YAML round-trip**. Strong prior: line-surgical, like
   `migrate_recipes.py` — a round-trip through a YAML lib would reformat all 252
   files and bury the real change in noise.
2. ~~Servings low-end vs midpoint; `recipe_url` keep-or-drop~~ — **both answered
   by the user 2026-07-31: low end, and drop `recipe_url`.** Only `enrich_none`
   remains, and that resolves by reading the enrichment code, not by asking.
3. Write `tests/test_recipe_schema.py` **first** (TDD): the corpus-wide check
   that fails on drift. It is the deliverable that prevents recurrence, and it
   defines the schema the normalizer must satisfy.
4. Then `scripts/normalize_recipes.py`: `--dry-run` default, `create_backup`
   before writing, idempotent (running twice is a no-op).

## Reproducing the analysis

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/recipe-schema-normalize
../../.venv/bin/python scripts/_analysis/profile_recipes.py   # key/heading census
../../.venv/bin/python scripts/_analysis/cluster.py           # variants by era + value shapes
```

Both read the live vault read-only. Delete `scripts/_analysis/` before merge.

---

## Stages

### Planning
- [x] Findings documented (above)
- [x] Conflict check completed — `chore/ingredient-audit` has uncommitted work in
      the main worktree touching `lib/nutrition_engine.py`, `lib/resolution_guard.py`,
      `scripts/purge_unvetted_resolutions.py`; no overlap with this scope
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Open questions resolved with the user (2026-07-31: servings → low end;
      `recipe_url` → drop). `enrich_none` still needs its writer located.
- [ ] Implementation plan written (superpowers:writing-plans)

### Dev
- [ ] Tests written first (superpowers:test-driven-development)
- [ ] `tests/test_recipe_schema.py` — corpus-wide drift check
- [ ] Failing test proving the `migrate_recipes.py` duplicate-key hazard
- [ ] `scripts/normalize_recipes.py` — dry-run default, backup, idempotent
- [ ] All tests passing
- [ ] No linting errors (`ruff`)

### Testing
- [ ] Unit tests pass
- [ ] Dry-run diff reviewed against all 252 files
- [ ] Idempotency verified (second run is a no-op)
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] Doc obligations met per CLAUDE.md table (new script → `docs/OPERATIONS.md`)
- [ ] `docs/plans/INDEX.md` updated
- [ ] New invariant recorded in `CLAUDE.md` if the schema check becomes load-bearing

### Review
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed

### Ready
- [ ] Rebased on latest main (note: `git fetch` failed on 2026-07-31 — no DNS in
      that session; re-fetch before merging)
- [ ] Final test pass after rebase
- [ ] `scripts/_analysis/` deleted
- [ ] BRANCH-STATUS.md fully checked
