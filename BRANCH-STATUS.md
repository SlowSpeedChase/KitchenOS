# Branch Status: recipe-schema-normalize

**Created:** 2026-07-31
**Design Doc:** [docs/superpowers/plans/2026-08-01-recipe-schema-normalize.md](docs/superpowers/plans/2026-08-01-recipe-schema-normalize.md)
**Current Stage:** review (implementation complete, corpus normalized)
**Last Rebased:** 2026-08-01 (onto `main` @ fb76b16)

## Overview

Normalize recipe frontmatter drift across the 252 files in
`vault/KitchenOS/Recipes/`, then add a corpus-wide schema test so the drift
can't silently return.

**Implemented 2026-08-01.** `lib/recipe_schema.py` declares the schema,
`scripts/normalize_recipes.py` repairs what it reports, and
`tests/e2e/test_recipe_corpus_schema.py` fails if drift returns. 3508 unit
tests (main: 3450), zero new ruff errors, `scripts/_analysis/` deleted.

The corpus was normalized on 2026-08-01 (16 files) and both corpus tests are
green. See "Corpus run" below, including the incident that produced a third
guard.

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

## Corpus run (2026-08-01)

`--apply` wrote **16 files** (each backed up to `Recipes/.history/`), a second
apply reported 0, and `--check` reports **0 violations across 252 recipes**. The
two corpus tests are green.

Nutrition re-derived for the 3 servings-changed recipes. Per-serving calories
rose exactly as the low-end decision predicts, because the engine was previously
dividing by a range's midpoint:

| Recipe | servings (engine) | kcal |
|---|---|---|
| Creamy Grape Salad Alternative | 5 → 4 | 357 → 446 |
| Healthy Blueberry Apple Oatmeal Cake | 7 → 6 | 221 → 257 |
| Watermelon Feta Salad | 7 → 6 | 169 → 197 |

All three now read identically from `nutrition_engine` and `week_view`, at
coverage 1.0 and `macro_eligible == True`.

### Incident during the run — worth keeping

The first re-derive attempt ran from this worktree without `KITCHENOS_DB`.
`inventory_db.connect()` **created an empty `data/kitchenos.db`**, so the FDC
store had 0 rows, nothing resolved, and the three recipes were rewritten at
coverage 0.33/0.55/0.70 — one at **7 kcal**, down from 357. The run reported
`Updated: 3, Failed: 0`.

Recovered from `Recipes/.history/` and re-derived against the real DB (13,694
`fdc_foods` rows). `backfill_nutrition.require_food_store()` now refuses to run
against an empty store, so this cannot recur silently. Same failure shape as the
two other guards this branch added: **silence that looks like success.**

## Code review (2026-08-01)

Two independent reviewers: a general one on plan alignment and quality, and an
adversarial one tasked only with finding ways to destroy the user's data. Both
returned; every accepted finding is fixed and pinned by a test.

**No Critical issue in the general review.** The adversarial pass found three
data-corruption paths, all reproduced against throwaway corpora, none of which
touched the live corpus — which was exactly its point: each precondition was
asserted in a docstring rather than checked, so the tool's safety was a property
of the data rather than of the code.

| Fixed | Was |
|---|---|
| `split_frontmatter` is line-anchored | split on the *substring* `---`, so a value containing three hyphens truncated the block mid-value and new keys were written into the middle of that string. `templates/recipe_template.py` interpolates raw YouTube titles into `video_title`, so the corpus was one extraction away |
| `remove=` consumes a key's whole value | orphaned indented continuation lines, which PyYAML folds into the *preceding* key |
| legacy key needs its canonical twin | deleted on sight, so an orphan `calories:` lost the file's only calorie figure — the mirror of the `migrate_recipes` bug this branch had already fixed |
| `create_backup` suffixes on collision | second-resolution stamp + `copy2` meant two writes in one second left only a backup of the *damaged* content |
| `require_food_store` opens read-only | went through `connect()`, which *creates* the DB — so the guard rejected the empty database it had just made and left a decoy for every other tool |
| `servings_low_end` refuses to guess | first-integer fallback read `"makes 24 cookies, serves 6"` as **24** |
| `nutrition_unmatched` uses `json.dumps` | `f'"{text}"'` over ingredient text broke on `2" piece ginger` |
| `--apply` exits 1 on unrepaired work | returned 0 while `--check` failed forever on the same file |
| corpus guard detects duplicate keys | `check_frontmatter` takes a dict, so it could not see the artifact `migrate_recipes` used to emit |
| guard marked `corpus`, runs by default | marked `e2e`, so `addopts = -m "not e2e"` meant it never ran |

Also: a servings change now writes `nutrition_needs_review: true` (a console
line scrolls away and never reprints), `--limit` refuses to truncate an explicit
`--only` list, `--only` dedupes, dotfiles are skipped, per-file errors are
contained, and `--check` no longer truncates the recipe name below what `--only`
needs to be pasted.

Verified after the fixes: 3578 unit tests (main 3450), the corpus guard green in
the **default** suite, `--check` clean at 0/252, a dry run reporting 0 changes,
zero new ruff errors, and a purpose-built 4-file corpus confirming the guard
catches a duplicate key, an orphan legacy key and an unrepairable servings —
with `--apply` exiting 1 and the orphan value preserved.

---

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
- [x] Idempotency verified on the live corpus (second apply: 0 files)
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met — `docs/OPERATIONS.md` runbook entry added
- [x] `docs/plans/INDEX.md` updated (In Progress row)
- [x] New invariant recorded in `CLAUDE.md`

### Review
- [x] Requested review (superpowers:requesting-code-review) — two reviewers, general + adversarial data-safety
- [x] Review feedback addressed (3 Critical, 5 Important, 6 Minor; each pinned by a test)

### Ready
- [ ] Rebased on latest main (note: `git fetch` failed on 2026-07-31 — no DNS in
      that session; re-fetch before merging)
- [ ] Final test pass after rebase
- [x] `scripts/_analysis/` deleted
- [ ] BRANCH-STATUS.md fully checked
