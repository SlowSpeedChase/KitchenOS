# Make consume-on-cook actually work

**Date:** 2026-07-26
**Branch:** `consume-on-cook`

## Problem

Marking a recipe cooked is supposed to decrement its ingredients from inventory.
It does not. A read-only dry run across the whole library:

**234 of the 236 recipes that have parseable ingredients would decrement
nothing** (the library is 239 `.md` files; 3 yield no ingredient lines). Of 2,634
ingredient lines, exactly 2 subtract.

| Outcome | Lines | Share |
|---|---|---|
| Skipped as a staple (correct, by design) | 1,179 | 44.8% |
| `not_tracked` — no inventory match | 1,082 | 41.1% |
| Matched an inventory row, units wouldn't convert | 371 | 14.1% |
| Actually decrements | 2 | 0.1% |

The reported symptom — marking biscuits cooked changed nothing — is the ordinary
case, not an edge case.

### Three defects, in dependency order

**1. `split_against_pantry` and `apply_decisions` disagree about units.** Same
module, two hand-written compatibility rules:

```python
inv = [{"item": "lime", "amount": "3", "unit": "ct"}]
split_against_pantry("lime", "1", "whole", inv)
#   -> {'from_pantry': {'amount': '1', 'unit': 'whole'}, 'to_buy': None, 'warning': None}
apply_decisions([{"item": "lime", "amount": "1", "unit": "whole"}], inv)
#   -> [{'item': 'lime', 'amount': '3', 'unit': 'ct'}]      # unchanged
```

`split_against_pantry` (`lib/pantry.py:171-192`) treats `""`/`whole` as generic and
compatible with any count unit. `apply_decisions` (`lib/pantry.py:240`) requires
exact unit-string equality or a same-family volume/weight pair. The shopping list
credits you for the limes; the cook refuses to spend them.

**2. `find_match` still uses the substring matcher that `436597d` deleted
everywhere else.** Commit `436597d` (2026-07-25) replaced bare bidirectional token
containment with head-noun matching in `lib/use_it_up.py`, `lib/recipe_matcher.py`
and `lib/cook_now.py` — measured at 54 false positives removed, no true match
regressed. `lib/pantry.find_match` was missed. It still produces
`lemon → Lemon pepper seasoning` (5 lines) and **11 peanut-butter lines → the
seeded `butter` staple row** — `_is_staple` correctly refuses to call peanut butter
"butter", then `find_match` matches it anyway.

**3. The UI reports failure as success.** `lib/cook.py` returns `not_tracked`,
`unconvertible` and `skipped_staples`; `templates/meal_planner.html` reads only
`r.consumed` and otherwise shows a green *"Marked cooked — nothing tracked to
decrement"*. The logic is duplicated verbatim at ~1983-1990 and ~2505-2512.

### The constraint that governs the whole design

**Inventory is containers, not quantities.** 188 of 198 count-family rows have
quantity exactly `1.0` — that is one *package*, not one item. Only 5 rows have
qty > 1 (lime 5, Onions 2, cauliflower 2, canned coconut milk 2, canned
black-eyed peas 2). The weight rows are containers too: 15 of 17 `oz` rows are
literally `1.0 oz` — `1.0 oz bacon`, `1.0 oz shredded cheese`.

So "make count units subtract" is actively dangerous. Applied naively it lets
`3 whole bay leaves` delete the `1 ct Bay leaves` jar and one 84 g cheese line
delete the shredded-cheese bag.

## Decisions

Made by the user during design; these govern the rest of the document.

1. **Purpose is "know when it runs out"**, not accurate remaining amounts. The
   depletion *event* matters — an item leaving Cook Now and landing on the
   shopping list. Exact remainders do not.
2. **Containers: record use, don't guess.** Cooking with `1 ct Mirin` must not
   change the quantity. Stamp that the row was used and when. No post-cook
   prompting — `~/Dev/CLAUDE.md` and `CLAUDE.md` both require inventory features
   to self-clean and never demand manual upkeep.
3. **`/api/cook` gets `@require_token`** in this branch.
4. **No package→grams bridge.** Rejected on measurement, see Out of Scope.

## Approach

Three changes that must ship together, plus honest reporting.

**Why together:** fixing the unit predicate without fixing the matcher starts
decrementing the peanut-butter and lemon false matches — today they are inert
only because the units happen not to convert. The matcher fix is what makes the
predicate fix safe.

**Rejected — a curated alias file.** Extending `_ATOMIC_FOODS` covers the worst
offenders with no new config surface to maintain, and the residual wrong matches
can only ever produce a timestamp (see the container gate), never a quantity
change.

## Design

### Part 1 — One unit-compatibility predicate

New in `lib/ingredient_aggregator.py`, which already owns `COUNT_UNITS`,
`get_unit_family` and the conversion tables:

```python
GENERIC_COUNT = {"", "whole", "ct", "count", "ea", "each", "piece", "pieces"}

def unit_compatibility(pantry_unit: str, recipe_unit: str) -> Optional[str]:
    """"convert" | "one_to_one" | None."""
```

- `"convert"` — `get_unit_family(p) == get_unit_family(n)` and the family is
  `volume` or `weight`. Subtract via base units.
- `"one_to_one"` — both units are in `COUNT_UNITS ∪ {""}`, **and** either they are
  case-folded equal or at least one side is in `GENERIC_COUNT`. Subtract
  numerically. This is `split_against_pantry`'s existing `{"", "whole"}` rule
  widened to the `ct`/`each`/`piece` family. `ct` never appears in recipe text —
  it means exactly "a generic count" — so `2 cans coconut milk` against
  `2 ct Canned coconut milk` becomes 1:1, which is right because cans are used
  whole. `slices` vs `loaves` still returns `None`.
- otherwise `None`.

Both `split_against_pantry` and `apply_decisions` route their count logic through
it. A parity test asserts the invariant that produced this bug: **whatever split
credits, the cook path can spend.**

This widens the shopping-list split slightly — a `ct` pantry row now credits
against `bunch`/`can` recipe lines. That is the same 1:1 semantics split already
applies to `whole`, and it is semantically correct.

### Part 2 — The container gate (`lib/cook.py`)

**A row whose merged quantity is exactly `1.0` never decrements. It gets a
use-stamp instead.** "Merged" means the quantity `load_pantry()` reports, which
sums rows sharing the same `(name, unit)` across storage locations — so two
half-used `1 ct` jars in different cupboards read as `2.0` and are eligible to
decrement, which is correct.

This lives in `lib/cook.py`, deliberately **not** in the predicate or in
`apply_decisions` — those also serve the shopping-list *confirm* flow, where the
decisions are user-approved and must be honored.

Rationale: `qty == 1.0` is the ingest default and means "one package" in 188 of
198 count rows. `qty != 1.0` means someone counted or weighed — 5 limes, 1.96 lb
tangelos, or a row already partly decremented. The asymmetry decides it: a missed
depletion self-heals through the existing expiry prune, while a wrongly deleted
jar does not and pollutes the shopping list.

Per-line classification:

```
_is_staple(phrase)?                              -> skipped_staples
find_match fails                                 -> not_tracked
unit_compatibility is None
  OR amount unparseable
  OR merged qty == 1.0                           -> use_recorded   (stamp)
compatible AND qty != 1.0                        -> decision       (decrement)
```

`consume_recipe` also stops calling `save_pantry` unconditionally. Today every
cook triggers a full inventory DELETE+INSERT and regenerates `Inventory.md` and
`Cook Now.md` — including the 234 recipes that change nothing. Skip the save when
there are no decisions.

### Part 3 — `find_match` adopts the head-noun matcher

`lib/pantry.find_match` becomes: exact name match →
`ingredient_normalizer.normalize_name()` → `use_it_up._covers()` (the `436597d`
matcher — note `lib/buffer_gaps.py` defines an unrelated `_covers`). The
character-substring fallback is deleted.

Two additions are required, because the shipped matcher has a hole:
`_STOPWORDS` collapses `shredded cheese` to `{cheese}` and `Canned corn` to
`{corn}`, and `436597d` applied the head-noun test only when the *inventory* side
is the longer one. When inventory is the shorter side, plain containment still
stands — so every cheese matches `shredded cheese`, and corn syrup matches a can
of corn. **This hole is live in `cook_now` today**: Cook Now currently credits
corn-syrup coverage from a corn can.

1. **Extend `_ATOMIC_FOODS`** (`lib/use_it_up.py` — `436597d`'s own extension
   point) with: `cream cheese, cottage cheese, goat cheese, feta cheese, corn
   syrup, corn tortilla, corn meal, cornmeal, coconut yogurt, cherry juice, corn
   starch, cornstarch`. Verified to preserve `potato starch or cornstarch →
   Cornstarch`. Fixes Cook Now and Use It Up for free.
2. **Normalize ingredient text with `ingredient_normalizer.normalize_name()`
   before matching** — strips parentheticals and post-comma prep clauses. Kills
   `cooking oil (for enchilada red sauce) → Canned enchilada sauce`, and makes the
   cook path and shopping-list path see the same input shape, since
   `split_against_pantry` already receives normalized aggregates.

Measured on the library: **~120 lines correctly rescued, 36 false pairs removed**;
match pairs go 217 → 301. Two true matches are lost to the head rule
(`cayenne → Cayenne pepper`, `fennel → Fennel seed`); both are stamp-only jar rows,
and recovering them by adding `seed` to `_PART_WORDS` would reintroduce
`yellow mustard → Yellow mustard seed`. Accepted.

Residual wrong matches survive (`parmesan cheese → shredded cheese`,
`chicken breasts → Canned chicken breast`, `fresh dill → Dried dill weed`). Under
the container gate they can only ever produce a timestamp, never a quantity
change, because every one of those rows is a qty-1 container.

A stricter inventory-superset-only variant was measured and rejected: it removes
the false positives but also kills 138 working matches (`lime juice → lime`,
`basil leaves → Basil`, `capers, drained → Capers`).

**Blast radius:** `find_match` is shared with the shopping-list split. Net
positive — 36 false credits removed (you will now correctly buy lemons). New
credits are added that could under-buy (`parmesan cheese` credited from
`shredded cheese`), but the split is a preview the user confirms, and Cook Now
already makes this exact claim. The four surfaces (`cook_now`, `use_it_up`,
shopping split, consume) currently disagree three ways; after this they agree.

### Part 4 — Use tracking

Two columns on `inventory`, via the idempotent `_MIGRATIONS` dict in
`lib/inventory_db.py`:

- `last_used TEXT` — ISO timestamp, nullable
- `use_count INTEGER NOT NULL DEFAULT 0`

**Columns, not a joined table:** `inventory.id` is not stable.
`replace_inventory_rows()` is DELETE-all + re-INSERT on every `write_inventory()`,
so anything foreign-keyed to it breaks under the existing write pattern.

**The trap:** the columns must also be added to `_INVENTORY_COLS`, to the
`InventoryItem` dataclass, and to the `read_inventory()` mapping. Miss any one and
the next receipt ingest or prune silently wipes every stamp. A round-trip test
covers exactly this.

Stamping goes through a new targeted
`inventory_db.stamp_inventory_use(refs: list[tuple[str, str]], when: str)` —
`UPDATE ... SET last_used = ?, use_count = use_count + 1 WHERE lower(name) = ? AND
lower(unit) = ?`. No read-modify-replace cycle, no view regeneration. Decremented
rows get stamped too; `last_used` means "a cook touched this row".

### Part 5 — Honest reporting

`consume_recipe` gains `use_recorded: [{item, unit}]` and drops `unconvertible`.

One `renderCookToast(r)` in `templates/meal_planner.html` replaces both duplicated
blocks and renders all four outcomes, capping each list at ~4 with "+n more":

> `Cooked — lime 2 → 3 left · used: bacon, Mirin · not tracked: dragon fruit +2 · 4 staples assumed`

Depleted rows are emphasized (`lime — used up`) because the depletion event is the
product. *"Marked cooked — nothing tracked to decrement"* only when all four lists
are empty.

### Part 6 — `/api/cook` token gate

Add `@require_token`, matching `/api/cooks`. It mutates inventory and is currently
open to any tailnet caller.

No behaviour change today: `KITCHENOS_API_TOKEN` is unset, so `require_token` is a
no-op. When a token is set, remote browser cooks will 401 because
`meal_planner.html` sends no `Authorization` header — but that page already
PATCHes the gated `/api/cooks`, so this introduces no new inconsistency.

## Expected outcome

Measured across all 239 recipes with the full design applied:

| Outcome | Lines |
|---|---|
| Staple | 1,179 |
| **Decrement** | **18** |
| **Use-stamp** | **455** (90 distinct rows) |
| `not_tracked` | 982 |

**199 of 239 recipes report something, up from 2 of 236. Zero false decrements.**
The 18 decrements are the 16 lime lines and 2 pumpkin lines. Butter Biscuits
reports `bacon: use recorded` instead of silence.

## Files

| File | Change |
|---|---|
| `lib/ingredient_aggregator.py` | `GENERIC_COUNT`, `unit_compatibility()` |
| `lib/pantry.py` | `find_match` → normalize + `_covers`; both split and apply route through `unit_compatibility` |
| `lib/use_it_up.py` | `_ATOMIC_FOODS` += 12 compounds |
| `lib/cook.py` | drop dead `_content_tokens` import; container gate; `use_recorded`; conditional `save_pantry`; call `stamp_inventory_use` |
| `lib/inventory_db.py` | 2 migrations; `_INVENTORY_COLS`; `stamp_inventory_use()` |
| `lib/inventory.py` | `InventoryItem` fields + `read_inventory()` mapping |
| `api_server.py` | `@require_token` on `/api/cook` |
| `templates/meal_planner.html` | single `renderCookToast(r)`, four outcomes, both call sites |
| `docs/API.md` | `/api/cook` marked 🔒; new response shape |
| `CLAUDE.md` | container-gate invariant |

## Testing

All against `tmp_db` / `tmp_vault` fixtures — never production data.

- **Parity property test:** across `COUNT_UNITS ∪ {""} ∪ volume ∪ weight`,
  `split_against_pantry` credits ⟺ the cook path can spend. This is the test that
  would have caught the original bug.
- **`test_cook.py` scenarios:** lime `5 ct − 2 whole → 3` and depletion at 0;
  Mirin `1 ct + 2 tbsp` → quantity unchanged, `last_used` set, `use_count` 1;
  bay-leaf jar `1 ct + 3 whole` → stamped, **not deleted**; Butter Biscuits'
  garbage unit → `use_recorded`; a no-op cook does not rewrite inventory.
- **Matcher tests:** `lemon` ≠ `Lemon pepper seasoning`; `peanut butter` →
  `Peanut butter`, not `butter`; `cream cheese` ≠ `shredded cheese`;
  `lime juice` → `lime`.
- **Persistence:** `last_used`/`use_count` survive a `write_inventory()`
  round-trip.
- **`test_api_auth.py`:** `/api/cook` 401 remote-without-token, 200 localhost,
  using the existing `REMOTE` pattern with `consume_recipe` monkeypatched.

Existing `tests/test_cook.py` masked this bug by using unit `ct` in its fixture
recipe, which real extraction never emits. Add `whole`-unit cases.

## Acceptance Criteria

- [ ] `apply_decisions` spends anything `split_against_pantry` credits (parity test green)
- [ ] Cooking a recipe with `5 ct lime` and `2 whole limes` leaves 3
- [ ] Cooking a recipe using a `1 ct` jar leaves its quantity untouched and sets `last_used`
- [ ] `last_used`/`use_count` survive a `write_inventory()` round-trip
- [ ] `peanut butter` no longer matches the `butter` staple row
- [ ] Cook Now no longer credits corn-syrup coverage from canned corn
- [ ] The cook toast names all four outcomes; the green "nothing tracked" message appears only when all four are empty
- [ ] `/api/cook` returns 401 for a remote caller when a token is set
- [ ] Full suite green; LaunchAgent reloaded after `lib/` edits

## Out of Scope

- **Package→grams bridging.** Measured and rejected: `portion_ledger` has 0 of 222
  inventory rows covered for their own `(name, unit)` and holds zero `ct` entries;
  only 9 of 190 `ct` rows match a size-carrying purchase, and those matches are
  dominated by `disinfecting wipes`, `vinyl gloves` and dog food. `fdc_portions`
  (36,763 rows) maps *recipe* units to grams, not packages to contents.
- **Designed-for-later, not built:** at receipt ingest, when `purchases.raw_name`
  carries a size (`"…, 10 oz"`), write the inventory row as `10 oz` rather than
  `1 ct`. Such rows then have a real unit and qty ≠ 1, so they graduate into the
  decrement path with no new mechanism. Today's use-stamps stay compatible.
- **Extraction-time unit repair** (`table spoon` → `tbsp`). The container gate
  already routes these to `use_recorded`, which is the correct semantics.
- A curated recipe→inventory alias file.
- A "used up?" tap affordance on the toast — a reasonable fast-follow, but it is
  new interaction surface and this branch is a correctness fix.
- Surfacing `last_used` in `/review` — `inventory-scan-and-extend` is rewriting
  `templates/review.html` with 147 new lines; deferred to avoid the collision.
- Gating the other ungated mutation routes (`/api/inventory/add`, `/api/pantry`
  POST, `/api/shopping-list/confirm`). `docs/API.md` marks inventory routes
  "Ungated" deliberately, so that is a posture decision, not a bug fix.
- `Inventory.md` column changes; container-nag heuristics.
