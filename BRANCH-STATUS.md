# Branch Status: ingredient-text-fidelity

**Created:** 2026-08-02
**Design Doc:** none — defect fix found while measuring the cookbook import
**Current Stage:** testing
**Last Rebased:** 2026-08-02 (branched from `2798992`)

## Overview

The 145 EPUB cookbook recipes imported today carried **no nutrition at all** — 0 of
145 had calories — so every one of them was invisible to day totals, the macro
suggester, and the new Cook Now ranking. Backfilling them exposed why the numbers
would have been untrustworthy anyway: **821 ingredient lines could not be converted to grams**, and a
seventh of those were not ingredients at all.

This branch fixes the readers, not the importer. `epub_parser` was already correct,
and so was the cookbook — every fix here recovers data the page already stated.

## Dependencies

- None. Touches `lib/recipe_parser.py`, `lib/gram_equivalent.py`,
  `lib/ingredient_text.py`, `lib/nutrition_engine.py` and `backfill_nutrition.py`; no overlap
  with `phase-2/close-the-loops` or `move-cook-by-drag`.

## Acceptance criteria

- [x] A bolded, quantity-less table row is not read as an ingredient
- [x] An emphasised *real* ingredient (`**flaky sea salt**`, 2 tbsp) still is
- [x] A quantity-less real ingredient (`kosher salt, to taste`) still is
- [x] A recipe grouped under `###` sub-headings contributes every row to nutrition
- [x] A stated package weight glossed in both systems is recovered when the two agree
- [x] A split amount range recovers its stranded unit; a count range does not
- [x] Zero new ruff findings vs main
- [x] Corpus measurably improves, and every apparent regression is explained

---

## Stages

### Planning
- [x] Conflict check completed — `git worktree list`, no file overlap
- [x] Branch and worktree created

### Dev
- [x] Tests written first (superpowers:test-driven-development) — watched each fail
- [x] Core implementation complete
- [x] All tests passing — 3874 passed
- [x] No new linting errors — ruff 7 on branch, 7 on main, identical set
- [x] Code follows project patterns
- [ ] LaunchAgent restarted (required ON MERGE — `com.kitchenos.api` holds `lib/*`
      in memory, and `lib/recipe_parser.py` changed)

### Testing
- [x] Unit tests pass — 3874 passed
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
| Unresolved gram lines | 821 | **599** |
| Stated weights recovered | 414 | **472** |
| Recipes the engine could read | 397 | **399** |
| Mean coverage | 0.830 | **0.859** |
| Clearing the 0.8 trust bar | 256 | **280** |

92 recipes gained coverage; 2 lost it. (After the first commit alone it was 57
gained / 7 lost — the weight and range recoveries lifted 5 of those 7 back above
where they started.) **The losses are corrections, not regressions** — each had a section heading that was resolving to a real food, so the
old figure counted a heading as a successfully-resolved ingredient. Cold Tofu With
Coconut-Ginger-Lime Crisp is the clearest: `**coconut-ginger-lime crisp**` scored
15 g / 12 kcal, so coverage read 0.50 and the recipe carried 6 phantom kcal/serving.
It now reads 0.46, and is honest.

Live corpus after the real `--force` run:

| | session start | now |
|---|---|---|
| Recipes with calories | 254 / 403 | **400 / 403** |
| Trustworthy (`macro_eligible`) | 184 | **235** |
| Cookbook imports with calories | 0 / 145 | **145 / 145** |
| Cookbook imports trustworthy | 0 | **46** |

Remaining eligibility blockers: `low_coverage` 121, `kcal_too_high` 34,
`servings_unknown` 24, `protein_too_high` 21, `kcal_too_low` 20, `no_nutrition` 3.

## Notes

**Why the fix is in the reader and not the importer.** `epub_parser.SUBHEAD_MARKER`
already tags every group header, and `import_epub.py:178` filters on it. The marker
just doesn't survive being written to a flat markdown table — the template has no
other way to render a group. So the information was there and was thrown away at the
file boundary; the reader is the only place that can recover it, and fixing it there
fixes all seven consumers at once instead of one.

**What "unresolved" in the audit column actually means.** It is
`li.grams_method`, not food resolution — the food almost always resolves. So the
599 remaining failures are lines the engine could not convert to grams, and the
two fixes in `c59150b` target exactly that. Worth stating because reading it as
"no food matched" sends you to the wrong subsystem.

**Still open, in priority order.**

1. **~120 low-coverage recipes.** The dominant remaining cause is seasoning with
   no meaningful amount (`kosher salt` 20×, `coriander seeds` 13×) — the food
   resolves, but there is nothing to convert. These arguably belong in the
   "negligible" bucket `to taste` already has, rather than counting against
   coverage. That is a scoring decision, not a parser fix.
2. **Alternatives** ("potato starch or arrowroot powder", 62 rows). Resolution
   currently picks whichever side the matcher likes; `clean_for_matching` keeps
   both. Taking the first alternative is the obvious rule but changes which food
   is chosen, so it wants its own before/after.
3. **Bad food matches**, which this branch does not touch and which coverage
   cannot see: `coriander seeds` resolves to *Seeds, pumpkin seeds (pepitas)*.
   Phase 3, item 17 — `resolution_guard.vet` on the fdc-local path.

**3 recipes still have no nutrition** and it is not a nutrition problem: their
`## Ingredients` table has a header row and no data rows, so extraction produced
an empty recipe. They need re-extraction. Two others were in this group at the
start of the day — Chocolate Peanut Butter Bars (6 real ingredients, unreadable
because of the third-copy regex) and one recovered by the range fix.
