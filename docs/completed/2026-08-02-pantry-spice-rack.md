# Completed: pantry-spice-rack

**Completed:** 2026-08-02
**Branch:** `pantry-spice-rack` (merged `fac4f72`)
**Duration:** same day

## Summary

`config/pantry_staples.json` held 26 entries and almost no spices. So cumin (44 recipes),
garlic powder (43), onion powder (33), cinnamon (29), coriander (25), smoked paprika (24) and
turmeric (23) were all treated as real shopping items — counted as genuine *shared shopping*
between any two recipes that used them, and eligible for a shopping list you would never
actually buy from.

This is the other half of the `_is_pantry` fix in `ec0ede0`. That one taught the **matcher**
that "garlic cloves" is garlic; this one fixes the **data** it matches against.

**The two are deliberately separate.** Garlic powder is a staple by having its *own* entry,
never by matching `garlic`. Crediting them against each other is the compound-food defect the
audit recorded, where a shopping list dropped fresh garlic because the powder was in stock.

## Measured

| | before | after |
|---|---|---|
| Staple entries | 26 | **50** |
| Ingredient lines credited as on-hand | 1677 / 4769 | **2132 / 4769** |
| Spice-driven plate pairings | 41 | **0** |

Top overlap drivers before: `cumin` 16, `coriander` 17, `onion powder` 8. After: no spice
appears at all — the remaining drivers are `lemon`, `ginger`, `nutritional yeast`, `parsley`,
all of which are genuinely shopped for.

Seeded 7 new perpetual inventory rows (cayenne, cumin, dried oregano, bay leaf, coriander
seeds, cumin seeds, maple syrup); 41 entries were already stocked. Every staple row verified
to carry no `expires`, so `prune_expired` cannot eat them. Verified live after restart:
`garlic powder` → 0 matches, `cumin` → 0, `onion powder` → 0, while `lime` → 11 and
`lemon` → 33.

## The two entries that were dropped

**"lemon juice" and "lime juice" were proposed and rejected.** `_is_staple` uses `_covers`,
which matches on token containment *in either direction*, so a `"lime juice"` entry makes a
plain `Lime` row a staple. Staples are excluded from `at_risk_items` entirely and carry no
expiry — so fresh citrus would have silently stopped ageing out and stopped being decremented
on cook. Five existing tests failed on exactly that, which is how it was caught.

This cost the credit for `freshly squeezed lemon juice` (21 recipes) and `lemon juice` (16).
That is the right trade: bottled juice being a staple is not worth making fresh lemons
invisible to the waste tracker.

## A pre-existing offender, now on the record

The new guard found one case that predates this change: **`onion` covers `Green Onion`**, so
scallions have never aged out and have never appeared in Use It Up. Real, but with its own
blast radius — changing how `onion` matches touches every onion row in the pantry — so it is
recorded in `TestStaplesMustNotSwallowPerishables.KNOWN_PREEXISTING` rather than fixed here.
A second test asserts the offender still exists, so the allowance fails the moment someone
fixes it and cannot quietly outlive the problem it documents.

## Side effect worth knowing

`score_overlap` is `|shared| / |non-staple items in the candidate|`, so shrinking the
denominator raises every score. Median non-staple lines per recipe is now **6**, and 107 of
400 recipes have **≤ 3** — which is why single-ingredient pairings rose (49 → 70) even though
the pairings are now made of real shopping items rather than seasoning.

The fraction is the wrong normalisation for short ingredient lists. Not addressed here;
`compose_plates` is still unwired to any surface, so nothing user-facing depends on it.

## Lessons learned

**Two staple matchers exist and they do not agree.** `meal_suggester._is_pantry` (exact,
suffix, or staple-plus-form-noun) and `use_it_up._is_staple` (bidirectional token containment
via `_covers`). A config entry is evaluated by both. The juice case is invisible if you only
reason about the first one.

**The failure direction is asymmetric.** A missing staple costs you a redundant line on a
shopping list. A wrong staple means an ingredient is never bought and never flagged as
expiring — you find out at the stove. That asymmetry is why the additions were restricted to
things that live in a jar for a year.

3883 tests on the branch; 3929 on merged main alongside the concurrent freezer-rotation work.
