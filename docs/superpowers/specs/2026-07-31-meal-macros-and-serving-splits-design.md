# Meal macros and fractional serving splits

**Status:** In Progress
**Created:** 2026-07-31
**Updated:** 2026-07-31

---

## Problem

A meal bundle (`vault/Meals/<Name>.meal.md` — a named set of sub-recipes, e.g. "Salmon
Dinner" = salmon + asparagus + rice) has no macros of its own, and its sub-recipe servings
are integers. Two consequences, one of them a silent bug.

**1. A meal on the planner was a macro black hole.** `meal_suggester.day_macro_gap` sums a
day's planned entries by looking each name up in `Recipes/`. A `[[Meal: X]]` entry has no
file there, so it resolved to nothing and contributed **zero** kcal and zero ingredients.
The suggester then believed the day was emptier than it was and steered every macro-aware
suggestion wrong by a whole meal. The same lookup drives the ingredient-overlap scoring, so
a planned meal's ingredients didn't count either. Nothing failed loudly; the numbers were
just quietly wrong.

**2. You couldn't tune a meal to a target.** `SubRecipe.servings` was an `int`, `parseInt`
in the editor, `min="1"` on the input, `Stepper(in: 1...12)` in Swift. So a 4-serving chili
could not put 1.5 servings in one meal and 2 in another — which is the actual way a batch
gets used.

---

## Solution

1. Sub-recipe `servings` becomes a float, and a meal gains a `slot`
   (breakfast/lunch/snack/dinner).
2. `lib/meal_nutrition.py` rolls a meal's calories/macros up from its sub-recipes at read
   time.
3. The suggest endpoint flattens meal entries to their sub-recipes before building
   `planned_meals`, which fixes both halves of bug 1 with one change.
4. `My Macros.md` gains four optional share keys, so a meal's macros can be shown against
   a per-slot share of the daily target rather than the whole day.
5. The planner's meal editor shows per-row contributions and a live total against that
   reference line while you type the split.

**Out of scope, deliberately:** meals do not become serving-ledger citizens. In a *board*
week a meal card still contributes nothing to the day-totals row. Cook-level accounting for
bundles is a separate piece of work.

---

## Design

### Derived at read time, never stored

Per-recipe macros are re-derived whenever `backfill_nutrition.py --force` runs or a
recipe's `servings` is corrected. A rollup stamped into `.meal.md` frontmatter would go
stale silently — no surface would ever notice it was lying. So `meal_nutrition()` writes
nothing, and the invariant is recorded in `CLAUDE.md` so nobody later "optimises" it into
frontmatter.

The rollup composes three existing pieces rather than adding rules:

| Piece | Role |
|---|---|
| `meal_plan_parser.sub_multiplier` | how a sub-recipe's own `servings` scales |
| `serving_ledger.recipe_macros` | safe frontmatter read, degrades to `None` per recipe |
| `nutrition_quality.macro_eligible` | the trust gate the suggester already ranks on |

`macro_eligible` wants index-shaped keys (`nutrition_calories`, `nutrition_coverage`,
`servings`) while `recipe_macros` returns macro-shaped ones, so `recipe_macros` grew an
additive `servings` key rather than the rollup doing a second file read. Its three existing
callers index only the keys they know.

**An untrusted sub-recipe is excluded from the totals and named**, with `incomplete: true`
— never counted as zero, and never at face value. `servings_unknown` is the case that
matters: a recipe with no serving count had its batch divided by 1, so its "per-serving"
macros are whole-recipe totals. Multiplying one of those by 1.5 would add thousands of
phantom kcal, which is worse than admitting the number is unknown.

### Read forgiving, write strict

`meal_loader.list_meals` wraps each file parse in `except Exception: continue`, so raising
on a bad `servings` wouldn't surface an error — it would make the meal *vanish* from every
surface. So the loader normalises (`0`, `-2`, `"lots"`, `null` → `1.0`; an unrecognised
`slot` → `dinner`, the same posture as `inventory.location_source`), while `/api/meals`
POST/PUT return 400 for the same values from a *client*.

That made a latent bug reachable: the PUT deleted the old file before validating the
payload, so a rejected rename destroyed the meal and saved nothing. Validation now runs
before the delete.

### One authority for the serving arithmetic

`flatten_to_recipes` (planner/suggester) and `shopping_list_generator.extract_recipe_links`
(shopping) were independent copies of `outer * max(1, int(sub.servings or 1))`. Left as
copies, fractional servings would mean the planner honours a 1.5-serving split while the
shopping list quietly buys 1× — an under-buy you discover at the stove. Both now call
`meal_plan_parser.sub_multiplier`.

### Where the numbers come from on each surface

The server owns the trust rules; the browser does the multiply-and-sum locally from the
already-loaded recipe index (`/api/recipes` supplies the four macro fields, coverage and
servings) so the readout moves as you type with no round-trip per keystroke. The server's
`nutrition` replaces it the moment a save returns.

Planner meal cards read `slot`/`nutrition` from the **`/api/meal-plan/<week>` slot JSON**,
not from the `/api/meals` index: `loadMeals()` and `loadMealPlan()` run concurrently in the
planner's `Promise.all`, so a card built from the plan can't assume `mealsByName` is
populated. That race is exactly why the plan endpoint already shipped `sub_recipes` per
slot.

### Per-slot targets

Four *flat* keys in `My Macros.md` — `share_breakfast`, `share_lunch`, `share_dinner`,
`share_snack`. Flat rather than a nested `slot_shares:` block because `parse_recipe_file`
strips each line before matching `^(\w+):\s*(.*)$`, so a nested block's indented children
would parse as top-level keys. Defaults 0.25/0.30/0.35/0.10; when they don't sum to 1.0
within 1% they're rescaled proportionally and `slot_shares_normalized` is exposed so the UI
says so out loud instead of quietly reinterpreting the user's numbers (which also means
someone writing `25/30/35/10` as percentages gets sane shares and an explanation).

`load_slot_shares` is a separate function from `load_macro_targets` — that one has callers
in `print_week`, `nutrition_dashboard` and `api_server`, and none of them should have to
care about slots.

---

## Implementation Notes

| File | Change |
|---|---|
| `lib/meal_nutrition.py` | **new** — the rollup |
| `lib/meal_loader.py` | float servings, `slot`, `normalize_slot`, `:g` render |
| `lib/meal_plan_parser.py` | new `sub_multiplier()`; `flatten_to_recipes` uses it |
| `lib/shopping_list_generator.py` | `extract_recipe_links` uses `sub_multiplier` |
| `lib/serving_ledger.py` | additive `servings` key on `recipe_macros` |
| `lib/macro_targets.py` | new `load_slot_shares()` → `SlotShares` |
| `templates/my_macros_template.py` | emit the four share keys |
| `api_server.py` | meals float/slot/nutrition; slot+nutrition on meal-plan GET; flatten before `planned_meals`; `GET /api/macro-targets` |
| `templates/meal_planner.html` | editor readout + slot picker, card meta, 0.25 steps |
| `KitchenOSKit/…/Models.swift` | `SubRecipe.servings: Double`, `Meal.slot` |
| `KitchenOSSiri/…/MealsView.swift` | 0.25-step stepper, slot picker |

The Swift change is required, not cosmetic: `Meal.init(from:)` decodes `sub_recipes` with
`try?`, so a `1.5` against an `Int` didn't error — one unrepresentable element failed the
whole array and the meal rendered with **zero** sub-recipes in the iOS/macOS app.

**Migration: none.** Integer servings parse as floats unchanged; an absent `slot` defaults
to dinner and isn't written back (so rewriting a pre-slot file leaves it byte-identical); a
`My Macros.md` without share keys behaves exactly as before.

---

## Acceptance Criteria

- [x] `1.5` survives parse → render → parse; `2.0` renders as `2`; `servings: 1` stays omitted
- [x] A garbage `servings` or unknown `slot` on disk normalises instead of losing the meal
- [x] `/api/meals` 400s on `servings <= 0`, unparseable servings, and an unknown slot
- [x] A rejected PUT can't delete the meal it was renaming
- [x] Untrusted sub-recipes are excluded *and* named, with one test per reason
- [x] Fractional sub-servings reach the shopping list unrounded
- [x] `day_macro_gap` counts a planned meal bundle's sub-recipes (regression test)
- [x] Slot shares default, fall back per key, and flag proportional rescaling
- [x] Swift decodes a fractional payload without emptying `subRecipes` *(test written; needs a macOS build to run)*
- [ ] Manual: editor readout tracks typing and the slot picker; `1.5` survives a save/reopen
- [ ] Manual: a legacy-week meal card shows `slot · N kcal` on first paint and doubles at ×2

## ADHD Design Check

- [x] **Reduces friction?** The split's macro effect is visible while you make it, instead
      of requiring a separate dashboard trip afterwards.
- [x] **Visible?** Card meta lines carry the slot and kcal wherever a meal appears.
- [x] **Externalizes cognition?** The per-slot reference line replaces doing
      "what fraction of my day is this?" in your head.
- [x] **Additive, never a chore?** Nothing to maintain — derived on read, no new file to
      keep current, and the share keys are optional.

---

## Links

- Plan: `/root/.claude/plans/here-is-a-draft-starry-lerdorf.md` (session artifact)
- Invariants added: `CLAUDE.md` — read-time derivation, `sub_multiplier` as sole authority
- Prior art: the parked 2026-07-08 macro-planner design ("derived at read time from
  frontmatter — not a stored flag that can go stale")
