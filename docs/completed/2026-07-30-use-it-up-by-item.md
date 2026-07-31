# Use It Up, By Item Design

**Status:** Done
**Created:** 2026-07-30
**Updated:** 2026-07-30
**Branch:** `use-it-up-by-item`

---

## Problem

> "What I want for the Use It Up is recipes for the things that need to be used up
> **attached to the thing that needs to be used up**, as opposed to in a list at the
> bottom — and I wanna limit it to like the top 5 to 10 recipes that I have stuff for,
> sorted by how much stuff I already have the stuff to make."

Opened live, the panel produced this:

```
AT RISK (2)
🔴 sliced ham off the bone · fridge · exp 2026-07-29
🟡 lime · fridge · exp 2026-07-31

COOK THESE
🍽 Black Bean Dip · uses lime          🍽 Watermelon Feta Salad · uses lime
🍽 Lime Cheesecake · uses lime         🍽 Chipotle Beef Tostadas · uses lime
🍽 Carnitas Batch Cook · uses lime     🍽 Watermelon Agua Fresca · uses lime
🍽 Healthy Key Lime Pie · uses lime    🍽 Tandoori Chicken Arayes · uses lime
🍽 Cilantro Lime Chicken · uses lime   🍽 Mexican Street Corn Salad · uses lime
```

**All ten are lime. The ham — red, already expired — got nothing.** Three separate
defects stacked:

### 1. The ranking's real tiebreak is *shortest recipe name*

`lib/use_it_up.py:252` sorts by `(uses_count, urgency, -len(recipe))`. With one matchable
at-risk item every candidate ties on both `uses_count` and `urgency`, so the list is
ordered by **name length**. Nothing about the ranking reflects whether you could actually
cook the thing.

### 2. The ham can never match anything, because it isn't parsed as ham

`_phrase("sliced ham off the bone")` resolves its head noun to **`bone`**:

```
Phrase(tokens={'off','bone','ham'}, head='bone', core_head='bone')
  vs "ham"        → covers=False
  vs "diced ham"  → covers=False
```

`_core_head` already strips trailing clauses — but only for *ingredient* text, on the
stated assumption that "clean names are already trustworthy". Inventory names are not: a
scan of all 215 live rows finds **`sliced ham off the bone` → `bone`** and **`whey protein
powder (chocolate fudge)` → `fudge`**. So the ham showing no recipes was never "no recipe
uses ham" — the matcher was looking for a food called *bone*.

Two rows out of 215 is not an epidemic, but it is exactly the row the user watched fail,
and it fails **silently**.

### 3. A flat list can't show which item a recipe is for

Even correctly ranked, one list can't answer "what do I do with the ham?" — and when an
item matches nothing, a flat list makes it *invisible* rather than reporting it.

Plus the panel renders 683 px tall in a 1180 px viewport, growing upward over the week
grid and shoving Today's Prep off screen.

---

## Solution

**Invert to item-first.** Each at-risk item becomes a block with its own recipes nested
underneath, ranked by how much of each recipe you already have, capped per item. An item
with no matches says so.

### Ranking: reuse `cook_now`'s coverage, don't write a second one

`lib/cook_now.py` already computes exactly what the user described — `have / total` against
live inventory, with staples counted as always-on-hand — and its own docstring calls itself
"the coverage-ranked complement to `use_it_up` (which ranks by *expiry urgency*)". The two
halves were designed to meet; they just never did.

> **Correction to an earlier claim.** I previously said the wanted ranking already existed
> as `meal_suggester.score_overlap`. It doesn't. That scores overlap with *already-planned
> meals* (buy once, cook twice) — a different, also-useful axis. The pantry coverage the
> user asked for is `cook_now`'s.

`cook_now` already imports its matching machinery *from* `use_it_up`, so the shared
computation goes in `use_it_up` (the lower module) as `recipe_coverage()`, and `cook_now`
calls it. One implementation, one direction of dependency. This matters here specifically:
this repo has already been bitten by two modules hand-writing the same rule
(`unit_compatibility`, where the shopping list credited limes the cook then refused to
spend — see `CLAUDE.md`).

### Structure

```
suggest() -> {
  "at_risk": [ { name, status, expires, quantity, unit, location,
                 recipes: [ {recipe, display_name, image, have, total,
                             coverage, missing} ]  # capped, coverage-ranked
               } ],
  "suggestions": [...]   # flat, derived — kept so the generated note and
                         # kitchen_today keep working
}
```

`suggestions` becomes a *view* of the grouped data (deduped, item order preserved) rather
than a separately-ranked list, so there is one ranking in the module, not two.

---

## Design

### Head-noun fix

Item names get the same trailing-clause treatment ingredient text already gets, plus a
narrow qualifier-trailer strip:

- **Parentheticals** — `whey protein powder (chocolate fudge)` → `whey protein powder`
- **Trailing `off` / `with` / `without` clauses** — `sliced ham off the bone` → `sliced ham`

**`of` is deliberately excluded.** Stripping it would turn `Cream of tartar` into `cream`
and `Canned cream of chicken soup` into `canned cream`, both of which would then match
every cream in the library. Verified against all 215 live rows: the three `of` names parse
correctly today and must keep doing so.

### Per-item cap

`RECIPES_PER_ITEM = 5`. With the usual 1–3 at-risk items that lands in the 5–15 range the
user asked for, and no single item can flood the panel the way lime did.

### Panel height

Item-first with a cap is already far shorter than 10 flat rows plus headers. The panel also
gets a `max-height` and scrolls internally, so it can never again grow tall enough to push
Today's Prep off the screen — that stays true regardless of how many items are at risk.

---

## Implementation Notes

| File | Change |
|---|---|
| `lib/use_it_up.py` | `recipe_coverage()` (shared); item-name head fix; `suggest()` returns per-item recipes; `render_markdown` goes item-first |
| `lib/cook_now.py` | calls `recipe_coverage()` instead of its own inline loop |
| `api_server.py` | `/api/use-it-up` passes through the new shape |
| `templates/meal_planner.html` | panel renders item-first, capped height, internal scroll |
| `tests/test_use_it_up.py` | per-item grouping, coverage order, the ham case, `of` non-regression |
| `tests/test_cook_now.py` | must stay green — proves the extraction changed nothing |

**Server:** `lib/` edits — LaunchAgent restart required.

---

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below
- [x] **ADHD check passed** — below
- [x] **Scope check** — two `lib/` modules, one template; well under a day
- [x] **No blockers**

### Acceptance Criteria

- [x] Each at-risk item renders with its own recipes beneath it
- [x] An item matching no recipes says so, visibly, instead of vanishing
- [x] `sliced ham off the bone` matches recipes calling for ham
- [x] `Cream of tartar` and `Canned cream of chicken soup` still parse as they do today
- [x] Recipes under an item are ordered by coverage, highest first, capped at 5
- [x] `cook_now`'s output is unchanged — its 20 tests pass untouched
- [x] The panel cannot grow tall enough to push Today's Prep off screen

**Verified live:** the ham went from **0 recipes to 3**, top one at **100% coverage**
(Ham Cheddar Protein Biscuits — everything already on hand). Lime shows its best 5 of 24.
Both panels fit on screen with both expanded (dock 12–649 px in a 1180 px viewport).

3050 unit tests (14 new), 90 e2e, zero new ruff errors.

### The head fix needed two halves

Stripping the qualifier from the *head* alone was not enough, and the live data said so:
`sliced ham off the bone` read `head='ham'` and still matched nothing, because `_covers`
also requires token containment in one direction and `{bone, ham, off}` neither contains
nor is contained by `{deli, ham}`. The clause has to come out of the token set too.
Caught only by running it against the real library — the head-level fix passed a
head-level test.

### ADHD Design Check

- [x] **Reduces friction?** Answers "what do I do with the ham" directly, instead of
      leaving you to scan a list and infer which item each row is for.
- [x] **Visible?** An item with no options becomes *stated* rather than silently absent —
      the failure that hid this bug for a month.
- [x] **Externalizes cognition?** The system holds "which recipes use this, and how much of
      each do I already have", instead of the user holding it.
- [x] **Additive, never a chore?** Derived entirely from inventory + the library; no upkeep.

---

## Links

- Sibling: [planner-shelf-and-tap-to-assign](2026-07-30-planner-shelf-and-tap-to-assign.md)
- Still open: relocating Today's Prep off the planner
