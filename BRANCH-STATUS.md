# Branch Status: ingredient-text-fidelity

**Created:** 2026-08-02
**Design Doc:** none — defect fix found while measuring the cookbook import
**Current Stage:** testing
**Last Rebased:** 2026-08-02 (branched from `2798992`)

## Overview

The 145 EPUB cookbook recipes imported today carried **no nutrition at all** — 0 of
145 had calories — so every one of them was invisible to day totals, the macro
suggester, and the new Cook Now ranking. Backfilling them exposed why the numbers
would have been untrustworthy anyway: **680 ingredient lines failed to resolve**, and
half of those were not ingredients.

This branch fixes the readers, not the importer. `epub_parser` was already correct.

## Dependencies

- None. Touches `lib/recipe_parser.py` and `backfill_nutrition.py` only; no overlap
  with `phase-2/close-the-loops` or `move-cook-by-drag`.

## Acceptance criteria

- [x] A bolded, quantity-less table row is not read as an ingredient
- [x] An emphasised *real* ingredient (`**flaky sea salt**`, 2 tbsp) still is
- [x] A quantity-less real ingredient (`kosher salt, to taste`) still is
- [x] A recipe grouped under `###` sub-headings contributes every row to nutrition
- [x] Zero new ruff findings vs main (7 = 7, all pre-existing)
- [x] Corpus measurably improves, and every apparent regression is explained

---

## Stages

### Planning
- [x] Conflict check completed — `git worktree list`, no file overlap
- [x] Branch and worktree created

### Dev
- [x] Tests written first (superpowers:test-driven-development) — watched both fail
- [x] Core implementation complete
- [x] All tests passing — 3861 passed, 1 skipped
- [x] No new linting errors — ruff 7 on branch, 7 on main, identical set
- [x] Code follows project patterns
- [ ] LaunchAgent restarted (required ON MERGE — `com.kitchenos.api` holds `lib/*`
      in memory, and `lib/recipe_parser.py` changed)

### Testing
- [x] Unit tests pass — 3861 passed, 1 skipped
- [x] Manual verification — full-corpus dry run on branch vs main, same data
- [x] Edge cases verified — bold-with-amount, unbolded-quantity-less, `****`,
      section ending at the next h2
- [ ] e2e suite not yet run

### Docs
- [ ] CLAUDE.md invariant updated (the group-header rule is new and belongs there)
- [ ] docs/plans/INDEX.md entry

### Review
- [ ] Code reviewed

### Ready
- [x] Branched from current main (`2798992`)

---

## Measured effect

Full-corpus `--dry-run --force`, branch vs main, identical vault and DB:

| | main | branch |
|---|---|---|
| Unresolved ingredient lines | 821 | **698** |
| Recipes the engine could read | 397 | **398** |
| Mean coverage | 0.830 | 0.840 |
| Clearing the 0.8 trust bar | 256 | **265** |

57 recipes gained coverage; 7 lost it. **All 7 losses are corrections, not
regressions** — each had a section heading that was resolving to a real food, so the
old figure counted a heading as a successfully-resolved ingredient. Cold Tofu With
Coconut-Ginger-Lime Crisp is the clearest: `**coconut-ginger-lime crisp**` scored
15 g / 12 kcal, so coverage read 0.50 and the recipe carried 6 phantom kcal/serving.
It now reads 0.46, and is honest.

Live corpus after the real `--force` run:

| | session start | now |
|---|---|---|
| Recipes with calories | 254 / 403 | **399 / 403** |
| Trustworthy (`macro_eligible`) | 184 | **219** |
| Cookbook imports with calories | 0 / 145 | **144 / 145** |
| Cookbook imports trustworthy | 0 | **31** |

## Notes

**Why the fix is in the reader and not the importer.** `epub_parser.SUBHEAD_MARKER`
already tags every group header, and `import_epub.py:178` filters on it. The marker
just doesn't survive being written to a flat markdown table — the template has no
other way to render a group. So the information was there and was thrown away at the
file boundary; the reader is the only place that can recover it, and fixing it there
fixes all seven consumers at once instead of one.

**Still open — the other half of the 680.** ~217 lines are ingredient *text* defects
baked into the imported files: amount-parser range splits ("to 1/2 teaspoon red
pepper flakes"), leading package parentheticals ("(15-ounce/425 g) can chickpeas"),
and unhandled alternatives ("potato starch or arrowroot"). Fixing
`ingredient_parser.parse_ingredient_best` only helps on **re-import**, so these need
either a re-import or a repair pass (`clean_ingredients.py` is the existing vehicle).
~297 more are genuine resolver misses on clean names (`kosher salt`, `coriander
seeds`, `organic cane sugar`) — food-store coverage, i.e. Phase 3.

**4 recipes still have no nutrition** and are not a nutrition problem: their
`## Ingredients` table has a header row and no data rows. They need re-extraction.
A fifth, Chocolate Peanut Butter Bars, was in this group until this branch — its 6
ingredients were real and simply unreadable.
