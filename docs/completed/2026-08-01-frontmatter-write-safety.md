# Completed: Frontmatter Write Safety

**Completed:** 2026-08-01
**Branch:** `frontmatter-write-safety`
**Follows:** [recipe-schema-normalize](2026-08-01-recipe-schema-normalize.md) — this
closes the loose end that branch's review left open.

## Summary

`recipe-schema-normalize` made the corpus guard catch a shredded recipe file.
Nothing stopped the extractor from *writing* the title that shreds it.

Every field a recipe carries is untrusted — `title`, `video_title` and
`source_channel` come straight from the YouTube API, the rest from an LLM
extraction — and three writers had each hand-rolled the same
`f'"{value}"'`:

| Writer | Fields |
|---|---|
| `templates/recipe_template.py` | `title`, `source_url`, `source_channel`, `video_title`, `recipe_source`, `confidence_notes`, and everything through `quote_or_null` |
| `scripts/enrich_recipes.py` | its own `yaml_scalar`, strings **and** list items |
| `backfill_nutrition.py` | `nutrition_source`, `serving_size` |

So `The 9" Skillet` produced a recipe whose frontmatter did not parse, `---`
could end the document mid-value, and a newline could inject a whole key — a
video titled `Chili\nservings: 999` really did land as frontmatter.

## Key changes

- **`lib/frontmatter.scalar()`** is now the one authority. Strings go through
  `json.dumps`, whose output is always a valid YAML double-quoted scalar and can
  never contain a bare line break. Non-strings keep their YAML type, because
  quoting a serving count turns it into a string and trips the schema check.
- The three local copies delegate to it (`enrich_recipes.yaml_scalar` is now
  literally `frontmatter.scalar`).
- **`video_title` needed splitting.** It is both a frontmatter scalar and a
  markdown link *label*, and JSON-escaping the label would print backslashes at
  the reader. The template passes `video_title_yaml` and `video_title_label`
  separately, so the Korean/Japanese bracket fix (`[감자치즈빵] …`) survives
  unchanged. `title` has the same two-context split (frontmatter + `# heading`).
- **`require_food_store` now floors `fdc_portions` too.** A food list with no
  gram weights resolves nothing — the same silent garbage the guard exists to
  prevent, one table over.

## Verification

- **Rendering an ordinary recipe is byte-identical to `main`**, so this causes
  no churn on re-extraction; only hostile input behaves differently.
- End-to-end: a recipe generated with `title`, `video_title` and
  `source_channel` all containing quotes, `---` and a newline key-injection
  attempt parses cleanly, carries no duplicate key, has no injected `servings`,
  and keeps its body intact.
- 3610 unit tests (was 3579), 125 e2e, corpus still 0 violations / 252, zero new
  ruff errors.

## Lessons learned

**Look for the writer, not just the reader.** The previous branch hardened
everything that *reads* a recipe file and added a guard that detects a broken
one. The bug was in what *writes* them — and the guard would have reported the
damage after the fact, on data with no other copy.

**One escaping bug is three.** Finding `f'"{value}"'` in one place is a prompt to
grep for it everywhere; three writers had independently invented the same
mistake over the same untrusted data. The fix is a shared authority, which is
the pattern this repo already uses for `unit_compatibility`,
`extract_ingredients_section` and `sub_multiplier`.

**A value used in two contexts needs two escapings.** `video_title` was escaped
correctly for one of its two uses, which is why the bug survived a previous
review of that exact line.

## Follow-ups (still open, from the previous branch)

- `lib/recipe_parser.parse_recipe_file` is a hand-rolled line parser that
  disagrees with `yaml.safe_load` (which `scripts/enrich_recipes.py` uses) on
  indented, hyphenated and quoted keys.
- Five recipe writers still do not back up before writing:
  `lib/cook_history.py`, `scripts/backfill_servings.py`,
  `scripts/reclassify_dish_type.py`, `scripts/backfill_short_titles.py`,
  `scripts/enrich_recipes.py`.
