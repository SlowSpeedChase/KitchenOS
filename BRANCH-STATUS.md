# Branch Status: recipe-schema-normalize

**Created:** 2026-07-31
**Design Doc:** [docs/superpowers/plans/2026-08-01-recipe-schema-normalize.md](docs/superpowers/plans/2026-08-01-recipe-schema-normalize.md)
**Current Stage:** review (implementation complete; the corpus write is awaiting approval)
**Last Rebased:** 2026-08-01 (onto `main` @ fb76b16)

## Overview

Normalize recipe frontmatter drift across the 252 files in
`vault/KitchenOS/Recipes/`, then add a corpus-wide schema test so the drift
can't silently return.

**Implemented 2026-08-01.** `lib/recipe_schema.py` declares the schema,
`scripts/normalize_recipes.py` repairs what it reports, and
`tests/e2e/test_recipe_corpus_schema.py` fails if drift returns. 3508 unit
tests (main: 3450), zero new ruff errors, `scripts/_analysis/` deleted.

**One step is outstanding:** `scripts/normalize_recipes.py --apply` has not been
run against the live vault — the write was blocked pending approval. Until it
runs, the two corpus tests are RED against the real 43 violations, which is
also the proof the guard detects drift.

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

> **CORRECTED 2026-08-01: nothing throws.** This entry claimed
> `lib/serving_ledger.py` coerces with a bare `float()` "in five places, so these
> can throw". Those `float()` calls are all on SQLite rows, not frontmatter. The
> frontmatter reader is `lib/week_view.py:135`, and it sits inside
> `except Exception: return 4.0`. The real defect is silent disagreement:
> `nutrition_engine._parse_servings` reads `"6-8"` as the **midpoint 7**,
> `week_view` reads it as **4.0**, and `nutrition_quality.macro_eligible` only
> tests for `None`, so it certifies the recipe as trustworthy while the other two
> disagree by up to 75%.

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

> **FIXED 2026-08-01.** `rename_nutrition_keys` rewrote `^calories:` to
> `nutrition_calories:` on files that **already have** that key, producing two
> identical YAML keys. It now declines on any collision, pinned by
> `tests/test_migrate_recipes.py`.
>
> **Severity corrected.** The original note (and a mid-session claim) said this
> would replace 169 kcal/serving with the 3058 whole-recipe total. It would not:
> all 13 files are legacy-*first*, so the renamed line lands in the earlier
> position and PyYAML's last-wins rule keeps the canonical value. What it
> actually produced was **malformed frontmatter** — `yaml.safe_load` tolerates
> the duplicate, a strict parser raises on it — and the value survived only by
> ordering luck. A canonical-first file *would* have been corrupted, which is
> the case `test_a_canonical_first_file_would_otherwise_be_corrupted` pins.

The two families genuinely disagree — the legacy values look like
whole-recipe totals, not per-serving:

```
Watermelon Feta Salad.md      calories: 3058   vs  nutrition_calories: 169
3010 Blueberry Banana Smoothie.md  calories: 593  vs  nutrition_calories: 465
Borscht Recipe With Meat.md   calories: null   vs  nutrition_calories: 536
```

Handling: `nutrition_*` wins (it is FDC-sourced — `nutrition_source: "fdc"`
on 244 of 252). Drop the legacy key.

**No carry-across logic was needed.** This entry proposed carrying a legacy
value over "when the canonical one is null". Measured across the corpus on
2026-08-01: there are **zero** such cases — every one of the 13 files has a
non-null canonical value. It is a pure delete, and the conditional was never
written (YAGNI).

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

**RESOLVED 2026-08-01: `enrich_none` is kept, and it is on 18 files, not 2.**
Locating its writer answered it, as predicted. `scripts/enrich_recipes.py:353`
writes it and `docs/OPERATIONS.md:380` specifies it: a sticky record of fields
that have *no* value, which cannot live in the field itself because `protein` is
rendered as an Obsidian tag and `dietary: []` can't distinguish "nothing
applies" from "never asked". It is optional-by-design, exactly like
`short_title`, and is now declared in `lib/recipe_schema.OPTIONAL_KEYS`. It was
never drift.

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

## What was built

1. **`lib/recipe_schema.py`** — the schema in one place: `REQUIRED_KEYS` (30),
   `OPTIONAL_KEYS`, `LEGACY_NUTRITION_KEYS`, `DROPPED_KEYS`, `check_frontmatter()`
   and `servings_low_end()`. Pure, no I/O. Allowlists measured, not designed.
2. **`migrate_recipes.rename_nutrition_keys`** — declines to rename onto an
   existing key (7 tests).
3. **`scripts/normalize_recipes.py`** — `--check` / dry-run default / `--apply`,
   line-surgical through `lib.frontmatter` (the shared editor
   `backfill_nutrition.py` already uses), `create_backup` before every write,
   idempotent. Refuses an empty corpus rather than reporting it clean.
4. **`backfill_nutrition.py --only NAME`** — re-derive named recipes, since a
   servings correction invalidates exactly the files it touched.
5. **`tests/e2e/test_recipe_corpus_schema.py`** — the anti-recurrence guard.

Line-surgical vs YAML round-trip was decided as the branch predicted:
`lib.frontmatter.rewrite()` already existed as the shared line editor, so a
second one would have been free to disagree with it.

## Outstanding

- [ ] `scripts/normalize_recipes.py --apply` against the live vault (blocked
      pending approval — writes 16 files, each backed up to `Recipes/.history/`).
- [ ] Then `backfill_nutrition.py --force --only` for the 3 servings-changed
      recipes, or they ship a serving count contradicting their own macros.
- [ ] Then the 2 corpus tests go green.

## Reproducing the analysis

`scripts/_analysis/` has been deleted (its findings are captured above and in the
plan). The live equivalent is the tool itself:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/recipe-schema-normalize
KITCHENOS_VAULT=/Users/chaseeasterling/Dev/KitchenOS/vault/KitchenOS \
  ../../.venv/bin/python scripts/normalize_recipes.py --check
```

`KITCHENOS_VAULT` must be set explicitly from a worktree: `lib/paths.py` reads
`.env` relative to its own repo root, and `.env` is git-ignored so it exists only
in the main checkout.

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
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] `tests/test_recipe_schema.py` (30 tests) + `tests/e2e/test_recipe_corpus_schema.py`
- [x] Failing test proving the `migrate_recipes.py` duplicate-key hazard
- [x] `scripts/normalize_recipes.py` — dry-run default, backup, idempotent
- [x] All tests passing (3508, main 3450)
- [x] No *new* linting errors (branch and main both report 155; the repo baseline is not clean)

### Testing
- [x] Unit tests pass
- [x] Dry-run diff reviewed: 16 files, 43 violations, no UNREPAIRED/SKIPPED
- [ ] BLOCKED: idempotency on the live corpus — needs the apply to run first (unit-tested)
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met — `docs/OPERATIONS.md` runbook entry added
- [x] `docs/plans/INDEX.md` updated (In Progress row)
- [x] New invariant recorded in `CLAUDE.md`

### Review
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed

### Ready
- [ ] Rebased on latest main (note: `git fetch` failed on 2026-07-31 — no DNS in
      that session; re-fetch before merging)
- [ ] Final test pass after rebase
- [x] `scripts/_analysis/` deleted
- [ ] BRANCH-STATUS.md fully checked
