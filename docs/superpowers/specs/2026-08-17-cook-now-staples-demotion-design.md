# Demote all-staples recipes in Cook Now

**Status:** Ready for Implementation · **Branch:** `cook-now-staples-demotion` · **Date:** 2026-08-17

## Problem

Recipes made entirely of pantry staples — homemade pasta (flour, eggs, salt, olive oil),
doughs, spice blends, plain pancakes — sit at ~100% coverage on `/cook-now` permanently.
`recipe_coverage` (`lib/use_it_up.py:276`) credits staples as always-on-hand, and staples
never age out (`seed_pantry_staples` writes them with no `expires`), so an all-staples
recipe's coverage never changes: it is a permanent squatter at the top of a list whose job
is to answer "what should I make right now." It is almost never that answer.

This is the same pathology the meal-tier and nutrition factors already fixed for muffins
and frosting — a recipe ranking high for a reason that doesn't track "should" — arriving
through a different door: not *what kind* of dish it is, but *why* it counts as ready.

## Approach

A seventh multiplicative score factor in `lib/cook_now.py`, exactly parallel to the
existing banked-recipe demotion: when **every** ingredient in a recipe is a staple, its
score is multiplied by `_ALL_STAPLES_WEIGHT = 0.25`. Recipes with even one non-staple
ingredient are completely untouched.

Decisions, and what they ruled out:

| Decision | Rejected alternative |
|---|---|
| Automatic detection from the staple list | A manual `hide_from_cook_now` frontmatter flag — violates "additive, never a chore"; every offender has to be noticed and flagged by hand |
| Demote hard, keep in the list | Excluding entirely — an all-staples recipe is still a true answer to "what *could* I cook" (same philosophy as `_BANKED_WEIGHT`), and fresh-pasta night is real |
| All-staples boolean | A staple-*share* ramp — the staple list contains the whole spice rack, so a real curry sits at 60–70% staples and would be wrongly penalized; the boolean has no tunable to get wrong |
| Count staples inside `recipe_coverage`'s existing pass | A second classification pass in `cook_now` — `_ingredient_phrase` is the expensive part and the page has a 135 ms budget; and coverage semantics must not fork from the single authority |

The boolean is not a threshold on a continuous quantity — it is the fact "does this recipe
contain any real ingredient at all," which is exactly the complaint. The failure direction
is safe by construction: an ingredient that fails to parse counts as a non-staple, so a
data gap makes a recipe *less* likely to be demoted, never buried ("a data gap must not
bury a real recipe").

## Design

### Part 1 — `recipe_coverage` reports the staple count

`lib/use_it_up.recipe_coverage` returns a 5-tuple: `(have, total, missing, uses_at_risk,
staple_count)`. The staple test already runs for every ingredient; the only change is
hoisting it out of the short-circuit `or` so its result can be counted:

```python
is_staple = _is_staple(phrase, staple_sets)
if is_staple:
    staple_count += 1
if not (is_staple or _matches(phrase, inv_phrases)):
    missing.append(ing)
```

Same single pass, no extra ingredient parse. Both unpacking call sites update in the same
commit:

- `lib/cook_now.py:297` — consumes the new field (Part 2).
- `lib/use_it_up.py:334` (`suggest`) — discards it. An all-staples recipe cannot appear in
  Use It Up anyway: `suggest` ranks recipes per at-risk item, and `at_risk_items` skips
  staples, so no staple is ever the at-risk item a recipe must contain.

`staple_count` counts ingredients matched by `_is_staple`, whether or not they also match
an inventory row — staples are real inventory rows now, so most do both. The count means
"credited by the staple rule," not "absent from stock."

### Part 2 — the demotion factor in `cook_now.generate`

```python
# A recipe made entirely of staples is perpetually "ready" — staples never
# age out, so its coverage never moves and it squats at the top of a list
# being asked "what should I make". Demoted rather than hidden, same
# philosophy as _BANKED_WEIGHT: fresh-pasta night is real, so it stays
# findable by scrolling. One real ingredient is enough to escape — then the
# recipe only ranks high when that ingredient is actually on hand, which is
# a legitimate claim on the top of the list.
_ALL_STAPLES_WEIGHT = 0.25
```

- `all_staples = staple_count == total` (`total >= 1` is guaranteed — empty ingredient
  lists are skipped before scoring).
- The score gains `* (_ALL_STAPLES_WEIGHT if all_staples else 1.0)`, beside the banked
  term.
- The payload gains `"all_staples": bool`, following the module's "reported, not just
  used" convention — a surface can explain the order rather than presenting it as given.

0.25 (vs banked's 0.5) is deliberate: a banked recipe is demoted for a reason that expires
(the freezer empties), an all-staples recipe never stops being all-staples. At 0.25,
homemade pasta at full coverage (1.0 × meal 1.0 × 0.25 = 0.25 before the other factors)
sinks below any real main with more than about a third of its list on hand — and the
module already treats "missing more than half" as where a suggestion stops being
actionable, so nothing useful is displaced.

### What propagates for free

`/cook-now`, `GET /api/cook-now`, the generated `Cook Now.md` note, and the Kitchen Today
card all render from `cook_now.generate`, so all inherit the demotion with no further
changes. The new payload key is additive; `cook_now.html` needs no edit. No UI change —
the demotion is pure reordering.

## Testing

Extend existing files; no new test modules.

| Test | What it pins |
|---|---|
| `tests/test_cook_now.py` | An all-staples recipe at 100% coverage scores below a real main at 50% coverage; a recipe with one non-staple ingredient gets no demotion (score identical with the factor removed); `all_staples` present and correct in every payload entry |
| `tests/test_cook_now.py` | `_ALL_STAPLES_WEIGHT < _BANKED_WEIGHT` — the ordering argument above, pinned |
| `tests/test_use_it_up.py` | The 5-tuple: `staple_count` correct for a mixed list, `0` for no staples, `== total` for all staples; `have`/`total`/`missing`/`uses_at_risk` unchanged for the same inputs |

## Acceptance Criteria

- [ ] An all-staples recipe (100% coverage) ranks below every real main with ≥50% coverage
      on `/api/cook-now` against the fixture inventory.
- [ ] A recipe with exactly one non-staple ingredient has the same score as before this
      change.
- [ ] Every `/api/cook-now` entry carries `all_staples`.
- [ ] `Cook Now.md` regenerates without error and reorders accordingly.
- [ ] Full test suite green.

## Out of Scope

- A manual per-recipe override flag (add later only if the boolean misjudges a real case).
- Any staple-share threshold or ramp.
- A UI badge for demoted recipes (`all_staples` is in the payload if one is ever wanted).
- Use It Up, the meal suggester, and the shopping list — untouched.
- Editing the staple list itself (`config/pantry_staples.json`).
