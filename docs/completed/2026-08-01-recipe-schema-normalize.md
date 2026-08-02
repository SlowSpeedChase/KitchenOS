# Completed: Recipe Schema Normalization

**Completed:** 2026-08-01
**Branch:** `recipe-schema-normalize` (started 2026-07-31)
**Design doc / plan:** [docs/superpowers/plans/2026-08-01-recipe-schema-normalize.md](../superpowers/plans/2026-08-01-recipe-schema-normalize.md)

## Summary

Recipe frontmatter is written by six producers — the extractor, the nutrition
backfill, the fit backfill, the enricher, the short-title backfill and the
cook-history sync — and nothing had ever stated what the union of their output
was allowed to look like. Drift accumulated silently across 252 files.

This declares the schema in one place, repairs the 16 files that departed from
it, and leaves a guard that fails the moment drift returns.

## Key changes

| File | What |
|---|---|
| `lib/recipe_schema.py` (new) | The schema: `REQUIRED_KEYS` (30), `OPTIONAL_KEYS`, `LEGACY_NUTRITION_KEYS`, `DROPPED_KEYS`, `check_frontmatter()`, `servings_low_end()`, `duplicate_keys()`. Pure — no I/O, so the same rules serve the unit tests, the corpus audit and the repair tool. |
| `scripts/normalize_recipes.py` (new) | `--check` / dry-run default / `--apply`. Repairs three classes, reports everything else, exits 1 on work it cannot do. |
| `tests/e2e/test_recipe_corpus_schema.py` (new) | The anti-recurrence guard. Marked `corpus`, so it runs in the **default** suite. |
| `lib/frontmatter.py` | Line-anchored frontmatter split; `remove=` now takes a key's whole multi-line value. |
| `lib/backup.py` | Same-second snapshots no longer clobber each other. |
| `migrate_recipes.py` | `rename_nutrition_keys` declines to rename onto an existing key. |
| `backfill_nutrition.py` | `--only NAME`, `require_food_store()`, `apply_limit()`, `json.dumps` for untrusted ingredient text. |

**Corpus result:** 16 files repaired — 3 servings ranges collapsed to their low
end and flagged for review, 39 legacy nutrition keys deleted across 13 files, 1
`recipe_url` dropped. `--check` reports **0 violations across 252 recipes**, a
second apply is a no-op, and every body is byte-identical to its pre-write
snapshot.

Nutrition was re-derived for the three servings-changed recipes. Per-serving
calories rose exactly as the low-end decision predicts, because the engine had
been dividing by the range's midpoint:

| Recipe | servings (as the engine read it) | kcal |
|---|---|---|
| Creamy Grape Salad Alternative | 5 → 4 | 357 → 446 |
| Healthy Blueberry Apple Oatmeal Cake | 7 → 6 | 221 → 257 |
| Watermelon Feta Salad | 7 → 6 | 169 → 197 |

**Tests:** 3579 unit (main: 3450), 125 e2e passing, zero new ruff errors.

## What the branch's own findings got wrong

The analysis inherited from the paused branch was wrong in three ways, and each
correction changed the work:

1. **The non-numeric `servings` values crash nothing.** The notes claimed
   `serving_ledger` coerces them with a bare `float()` "in five places, so these
   can throw" — those calls are all on SQLite rows. The frontmatter reader is
   `week_view.py:135`, inside `except Exception: return 4.0`. The real defect is
   silent disagreement: `nutrition_engine` reads `"6-8"` as the midpoint **7**,
   `week_view` as **4.0**, and `macro_eligible` only tests for `None` — so it
   certifies the recipe as trustworthy while the other two disagree by 75%.
2. **`enrich_none` is documented sticky state on 18 files**, not debris on 2. It
   is written by `enrich_recipes.py:353` and specified in `docs/OPERATIONS.md`.
   Declared optional, not dropped.
3. **No carry-across logic was needed.** The notes proposed migrating a legacy
   value "when the canonical one is null". Measured: zero such cases. The
   conditional was never written.

## Lessons learned

**Three guards, one shape.** Every guard this branch added is the same failure
mode — *silence that looks like success*: `--only` matching nothing, `--check`
on an empty corpus, and a backfill against an empty food store. Worth reaching
for that pattern by name next time a tool reports a count.

**The empty-DB incident.** The first nutrition re-derive ran from the worktree
without `KITCHENOS_DB`. `data/` is git-ignored, so it exists only in the main
checkout — and `inventory_db.connect()` *created* an empty one. Nothing
resolved, three recipes were rewritten at 0.33/0.55/0.70 coverage (one from 357
kcal to **7**), and the run reported `Updated: 3, Failed: 0`. Recovered from
`Recipes/.history/`. Both `vault/` and `data/` now have explicit guards and a
runbook table.

**Docstrings are not preconditions.** Adversarial review found three
data-corruption paths, all reproduced, *none* of which could affect the corpus
as it stood — because each precondition was asserted in a comment rather than
checked. On a tool meant to be re-run forever over a corpus six producers keep
appending to, safety that is a property of the data will stop holding. The
sharpest: `split_frontmatter` split on the *substring* `---`, and
`templates/recipe_template.py` interpolates raw YouTube titles into
`video_title` — one extraction away from shredding a file.

**Check for the mirror of every asymmetric rule you write.** The branch fixed
`migrate_recipes` to refuse to rename ONTO an existing key, then shipped a
normalizer that deleted a legacy key WITHOUT one — destroying a file's only
calorie value while printing that the replacement was missing. Same rule, other
direction, missed until review.

**Apply your own rule to yourself.** `--apply` returned 0 even when a violation
was unrepairable, while `--check` would fail on it forever — in a tool whose
whole point was catching that pattern elsewhere.

## Follow-ups (not blocking)

- `lib/recipe_parser.parse_recipe_file` is a hand-rolled line parser that
  `strip()`s before matching `^(\w+):`, so it reads an *indented* nested key as
  top-level and cannot see hyphenated or quoted keys. `scripts/enrich_recipes.py`
  reads the same files with `yaml.safe_load`. The schema is validated against a
  different view of the file than one of its own producers, and than Dataview.
- Several recipe writers still do not back up before writing:
  `lib/cook_history.py`, `scripts/backfill_servings.py`,
  `scripts/reclassify_dish_type.py`, `scripts/backfill_short_titles.py`,
  `scripts/enrich_recipes.py`.
- `require_food_store` floors only `fdc_foods`; a partially-loaded store
  (`fdc_portions`, `portion_ledger`, `food_resolution` empty) still passes.
- `templates/recipe_template.py` interpolates `video_title` unescaped.
