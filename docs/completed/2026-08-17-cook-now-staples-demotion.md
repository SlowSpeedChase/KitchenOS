# Completed: cook-now-staples-demotion

**Completed:** 2026-08-17
**Branch:** `cook-now-staples-demotion` (merged fast-forward to `0007223`)
**Duration:** same day
**Spec:** `docs/superpowers/specs/2026-08-17-cook-now-staples-demotion-design.md`
**Plan:** `docs/superpowers/plans/2026-08-17-cook-now-staples-demotion.md`

## Summary

Recipes made entirely of pantry staples were permanent squatters at the top of Cook Now:
staples count as always-on-hand and never age out, so homemade pasta (flour, eggs, salt,
olive oil) sat at 100% coverage forever — ranked **#1 in the live library** — while never
being the answer to "what should I make."

The fix is a seventh multiplicative score factor, exactly parallel to the banked-recipe
demotion: `recipe_coverage` (the single coverage authority in `lib/use_it_up.py`) now
reports how many ingredients the staple rule credited, in its existing single pass
(5-tuple: `have, total, missing, uses_at_risk, staple_count`), and `lib/cook_now.py`
multiplies by `_ALL_STAPLES_WEIGHT = 0.25` when `staple_count == total`. Demoted, never
hidden — fresh-pasta night is real, so the recipe stays findable by scrolling. One real
ingredient escapes entirely: then the recipe only ranks high when that ingredient is
actually on hand, which is a legitimate claim on the top of the list.

Decisions that shaped it:

- **All-staples boolean, not a staple-share ramp.** The staple list contains the whole
  spice rack, so a real curry sits at 60–70% staples; a share threshold would wrongly
  penalize spice-heavy dinners, and the boolean has no tunable to get wrong.
- **0.25 vs banked's 0.5, pinned by test** (`_ALL_STAPLES_WEIGHT < _BANKED_WEIGHT`): a
  banked demotion expires when the freezer empties; an all-staples recipe never stops
  being all-staples.
- **Failure direction is structural:** an unparseable ingredient produces an empty-token
  phrase, `_is_staple` returns False, and the recipe *escapes* the demotion — a data gap
  can never bury a real recipe.
- Payload gains `all_staples` (reported, not just used, per the module convention);
  `docs/API.md`'s `/api/cook-now` row was stale since the ranking factors landed and got
  its full field list fixed in passing. Kitchen Today's "ready" count deliberately stays
  un-gated — that card asks "could," not "should" — now said in a comment at the site.

## Measured

| | before | after |
|---|---|---|
| Homemade Pasta (100% coverage, 4/4 staples) | rank **1** | rank **301** |
| Crispy Spiced Garlic (100% coverage) | top ranks | rank **387** |
| All-staples recipes in the 406-recipe ranking | squatting on top | **2 total, both sunk** |
| Live `/api/cook-now` top 5 | led by pasta dough | all real meals, `all_staples: false` |

Tests 4008 → 4018 (10 new: 5 direct `recipe_coverage` contract tests incl. the
staple-also-in-inventory case, 5 demotion tests incl. a ratio test that pins the weight
exactly by holding every other factor equal). Full suite green on merged main; the 9
warnings are pre-existing (`epub_parser` XMLParsedAsHTMLWarning), verified identical at
base. Live smoke after LaunchAgent restart: API top 5 all real meals, `Cook Now.md`
regenerated clean.

## Process

Subagent-driven: 3 tasks, each TDD'd, per-task spec+quality reviews all clean on first
pass; final whole-branch review verdict ready-to-merge with only cosmetic triage. Ledger
in `.superpowers/sdd/progress.md`.
