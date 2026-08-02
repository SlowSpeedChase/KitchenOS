# Completed: Recipe Write-Safety Follow-ups

**Completed:** 2026-08-01
**Branch:** `recipe-write-backups`
**Closes:** the two follow-ups left open by
[recipe-schema-normalize](2026-08-01-recipe-schema-normalize.md) and
[frontmatter-write-safety](2026-08-01-frontmatter-write-safety.md).

## 1. Backups before overwriting a note

**Scope correction first:** the review that raised this named *five* unguarded
writers. Four of them (`backfill_servings`, `reclassify_dish_type`,
`backfill_short_titles`, `enrich_recipes`) already back up correctly. A census
of every `write_text` in the repo found the real set is three:

| Writer | Why it matters |
|---|---|
| `lib/cook_history.py` | Syncs cook stats into a real recipe automatically, off a cook write, with nobody watching |
| `import_crouton.py` | A filename collision replaces the **whole file**, `## My Notes` included — the one part the user wrote |
| `generate_meal_plan.py --force` | Overwrites a hand-edited plan |

The generated read-only views (`Cook Now.md`, `Use It Up.md`, `Inventory.md`,
the dashboards, `week_view`) are a deliberate exception, not a gap: they are
rewritten from the DB on every relevant change and carry a do-not-edit banner,
so snapshotting them is noise.

Rather than adding `create_backup` at three more call sites and hoping the next
writer knows the convention, **`backup.write_note(path, content)`** makes the
safe path the easy one. It snapshots first, no-ops when the content is
unchanged (so a corpus-wide sync neither fills `.history` with identical copies
nor churns the mtimes sidecar freshness checks read), and returns whether it
wrote. Recorded in `lib/CLAUDE.md`.

## 2. The hand parser now agrees with real YAML

`recipe_parser.parse_recipe_file` is what the schema guard reads recipes
through; `scripts/enrich_recipes.py` and Obsidian's Dataview read the same files
as real YAML. Any key the two see differently is a key being validated in a form
nothing else uses. Measured across the corpus, they disagreed four ways:

| Defect | Effect |
|---|---|
| **Block-style lists** | `line.strip()` ran before the key match, so an indented `- item` looked like a candidate key and a bare `tags:` fell through to the string branch. `tags` and `cssclasses` were `''` on **all 252 files**, `equipment` on 8, `dietary` on 1 — the entire value, invisible |
| **Flow lists** | Split on a bare `,`, so `["large, well-seasoned cast-iron skillet"]` became two items each carrying half a quote. Ten recipes have equipment written that way |
| **Numeric items** | `peak_months` read as `['9','10']` where YAML says `[9,10]` — which is why `meal_planner.html` still maps `parseInt` over it |
| **Quoting** | Only double quotes were stripped, so one single-quoted title kept a leading apostrophe |

`_coerce_scalar` is now shared by plain values, flow items and block items, so
the three cannot drift apart again — they had.

**Deliberately not switched to `yaml.safe_load`.** It resolves `date_added` and
`last_cooked` to `datetime.date`, and every consumer in this repo wants ISO
strings; a wholesale swap would have regressed 252 files to fix a latent
problem. That one divergence is kept, documented, and excluded from the new
guard.

`tests/e2e/test_recipe_corpus_schema.py` now compares both parsers key-by-key
across the whole corpus and fails on any new disagreement. It found the
flow-list defect immediately — that bug was not in the original scope.

## Verification

- 3637 unit tests (was 3610), 125 e2e, corpus still 0 violations / 252, zero new
  ruff errors.
- The parser-agreement guard passes across all 252 files.

## Lessons learned

**Verify a reviewer's scope before acting on it.** "Five writers don't back up"
was wrong in both directions: four of the five were fine, and a census found a
worse offender the list never mentioned (`import_crouton`, which replaces an
entire file rather than editing frontmatter).

**A guard finds the bug you didn't know to look for.** The parser-agreement test
was written to prove the block-list fix worked. It immediately failed on
flow-list comma splitting, which nobody had noticed.

**Divergence is sometimes correct — say so in the test.** The temptation with
two parsers is to make one call the other. Here the hand parser's date handling
is the one every consumer depends on, so the guard excludes dates explicitly
rather than the parser being "fixed" into a regression.

## Follow-ups

None outstanding from the original review. Two smaller notes:

- `require_food_store` floors `fdc_foods` and `fdc_portions` but not
  `portion_ledger` (592 rows) or `food_resolution` (2,446) — a store missing
  only those still passes.
- `templates/recipe_template.py` still writes `peak_months` via its own
  `f"[{', '.join(...)}]"` rather than `frontmatter.scalar`; harmless today
  because the values are ints, but it is the last hand-rolled list emitter.
