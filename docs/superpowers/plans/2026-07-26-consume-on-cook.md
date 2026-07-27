# Consume-on-cook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make marking a recipe cooked actually change inventory — decrementing what can safely be decremented, recording use on containers, and reporting honestly instead of showing a green toast over a no-op.

**Architecture:** One shared unit-compatibility predicate replaces two hand-written rules that disagreed. `pantry.find_match` adopts the head-noun matcher already shipped in `use_it_up`/`cook_now`. A container gate in `lib/cook.py` routes qty-1 rows to a use-stamp (`last_used`/`use_count` columns) instead of a decrement, because inventory holds packages rather than measured quantities.

**Tech Stack:** Python 3.11, SQLite (`data/kitchenos.db`), Flask, pytest, vanilla JS in a Jinja template.

**Design doc:** `docs/superpowers/specs/2026-07-26-consume-on-cook-design.md`

## Global Constraints

- Always run Python via `.venv/bin/python`. Never bare `python`.
- **Never run `consume_recipe`, `save_pantry`, `write_inventory` or `apply_decisions` against the real DB.** Every test uses the `tmp_db` and `tmp_vault` fixtures from `tests/conftest.py`. An `autouse` `_isolate_db` fixture exists, but do not rely on it alone.
- A fresh worktree has **no `.env`** (git-ignored) and **no `vault/`** (in `.git/info/exclude`). Task 0 sets these up. Without them `paths.recipes_dir()` silently falls through to a dead default.
- The vault path must resolve through `lib/paths.py` helpers. Never hardcode one.
- Any code overwriting a recipe file must call `backup.create_backup()` first. (No task here writes recipe files.)
- Editing anything under `lib/`, `templates/` or `prompts/` requires a LaunchAgent restart or the API serves stale code:
  `launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist && launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist`
- Commit message convention: `type: short description`, then a blank line, then `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- `dish_type`, `SECTIONS` and other CLAUDE.md invariants are untouched by this plan. No new browsable page is added, so no `SECTIONS` registration is needed.
- Run the suite with `.venv/bin/python -m pytest tests/ -q`. E2E tests are excluded by default via `pytest.ini`; run them with `-m e2e`.

## File Structure

| File | Responsibility after this plan |
|---|---|
| `lib/ingredient_aggregator.py` | Owns unit vocabulary and conversion. Gains `GENERIC_COUNT` and `unit_compatibility()` — the single authority on whether two units can be subtracted. |
| `lib/pantry.py` | Splits recipe demand against stock and decrements it. Both `split_against_pantry` and `apply_decisions` delegate unit decisions to `unit_compatibility`. `find_match` delegates name matching to the shared head-noun matcher. |
| `lib/use_it_up.py` | Owns the food-name matcher (`_phrase`, `_covers`, `_ATOMIC_FOODS`). Gains 12 compound foods. |
| `lib/inventory_db.py` | Owns schema and SQL. Gains two columns and `stamp_inventory_use()`. |
| `lib/inventory.py` | Owns the `InventoryItem` record. Gains two fields that must round-trip. |
| `lib/cook.py` | Owns cook-time policy: the container gate and the four-outcome classification. |
| `api_server.py` | `/api/cook` gains `@require_token`. |
| `templates/meal_planner.html` | Gains one `renderCookToast(r)` replacing two duplicated blocks. |

---

## Task 0: Worktree setup

**Files:** none committed — environment only.

**Interfaces:**
- Consumes: nothing.
- Produces: a worktree where `.venv/bin/python -m pytest tests/ -q` runs green against the pre-change code.

- [ ] **Step 1: Symlink the git-ignored `.env` and `vault/` from the main checkout**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/consume-on-cook
ln -sfn ../../.env .env
ln -sfn ../../vault vault
ls -l .env vault
```

Expected: both listed as symlinks pointing into `/Users/chaseeasterling/Dev/KitchenOS/`.

- [ ] **Step 2: Link the virtualenv**

```bash
ln -sfn ../../.venv .venv
.venv/bin/python --version
```

Expected: `Python 3.11.x`

- [ ] **Step 3: Establish the pre-change baseline**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: all tests pass. **Record the number** — later tasks compare against it. If anything fails here, stop and report; it is not caused by this plan.

- [ ] **Step 4: Confirm the DB is isolated**

```bash
.venv/bin/python -c "
from lib import inventory_db
print('default db path:', inventory_db.db_path())
"
```

Expected: prints a path ending `data/kitchenos.db`. This is the **production** DB — it is what the `tmp_db` fixture overrides. Never write to it.

No commit for this task.

---

## Task 1: `unit_compatibility()` — one predicate for unit decisions

**Files:**
- Modify: `lib/ingredient_aggregator.py` (add after `get_unit_family`, ~line 55)
- Test: `tests/test_ingredient_aggregator.py`

**Interfaces:**
- Consumes: `get_unit_family(unit: str) -> str`, `COUNT_UNITS: set[str]` — both already in this module.
- Produces:
  - `GENERIC_COUNT: set[str]` — count units that mean "one of whatever this is".
  - `unit_compatibility(pantry_unit: str, recipe_unit: str) -> Optional[str]` returning `"convert"`, `"one_to_one"`, or `None`.

Background: `COUNT_UNITS` already contains `clove(s)`, `slice(s)`, `piece(s)`, `bunch(es)`, `head(s)`, `can(s)`, `package(s)`, `sprig(s)`, `ct`, `count`, `each`, `ea`, `whole`. `get_unit_family("")` returns `"other"`, so the empty unit is handled explicitly rather than via family.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_ingredient_aggregator.py`:

```python
from lib.ingredient_aggregator import GENERIC_COUNT, unit_compatibility


class TestUnitCompatibility:
    def test_same_volume_family_converts(self):
        assert unit_compatibility("cup", "tbsp") == "convert"

    def test_same_weight_family_converts(self):
        assert unit_compatibility("lb", "oz") == "convert"

    def test_volume_against_weight_is_incompatible(self):
        assert unit_compatibility("cup", "oz") is None

    def test_ct_is_generic_against_whole(self):
        # The bug this predicate exists to kill: the shopping list credited
        # `3 ct lime` against `1 whole lime`, but apply_decisions refused it.
        assert unit_compatibility("ct", "whole") == "one_to_one"

    def test_ct_is_generic_against_a_specific_count_unit(self):
        # Cans are used whole, so `2 ct` covers `2 cans` one-for-one.
        assert unit_compatibility("ct", "can") == "one_to_one"

    def test_identical_specific_count_units_match(self):
        assert unit_compatibility("clove", "clove") == "one_to_one"

    def test_two_different_specific_count_units_do_not_match(self):
        assert unit_compatibility("slice", "clove") is None

    def test_empty_pantry_unit_is_generic(self):
        assert unit_compatibility("", "whole") == "one_to_one"

    def test_container_against_measured_amount_is_incompatible(self):
        # `1 ct Mirin` vs `2 tbsp mirin` — the container case, 264 lines of it.
        assert unit_compatibility("ct", "tbsp") is None

    def test_unknown_unit_is_incompatible(self):
        # Extraction garbage: "a sprinkle", "spoonful".
        assert unit_compatibility("ct", "a sprinkle") is None
        assert unit_compatibility("a sprinkle", "ct") is None

    def test_generic_count_is_a_subset_of_count_units_plus_empty(self):
        from lib.ingredient_aggregator import COUNT_UNITS
        assert GENERIC_COUNT - {""} <= COUNT_UNITS
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_ingredient_aggregator.py -q -k UnitCompatibility
```

Expected: collection error — `ImportError: cannot import name 'GENERIC_COUNT' from 'lib.ingredient_aggregator'`.

- [ ] **Step 3: Implement the predicate**

In `lib/ingredient_aggregator.py`, immediately after the `get_unit_family` function, add:

```python
# Count units that mean "one of whatever this is" rather than a specific form.
# `ct` never appears in recipe text — it is the inventory ingest default — so it
# is generic by construction. Kept separate from COUNT_UNITS because `slice` and
# `clove` are count units that are NOT interchangeable with each other.
GENERIC_COUNT = {"", "whole", "ct", "count", "ea", "each", "piece", "pieces"}


def unit_compatibility(pantry_unit: str, recipe_unit: str) -> Optional[str]:
    """How a pantry row's unit relates to a recipe line's unit.

    Returns:
        "convert"    — same volume or weight family; subtract via base units.
        "one_to_one" — count-style; subtract numerically.
        None         — cannot be subtracted without inventing information.

    This is the single authority on the question. `split_against_pantry` and
    `apply_decisions` previously hand-wrote different rules, so the shopping
    list credited `3 ct lime` against `1 whole lime` while the cook path
    refused to spend it. Any future divergence is a bug in one of the callers,
    not a second rule.
    """
    p = (pantry_unit or "").lower().strip()
    n = (recipe_unit or "").lower().strip()

    p_family = get_unit_family(p)
    if p_family in ("volume", "weight") and p_family == get_unit_family(n):
        return "convert"

    p_is_count = p in COUNT_UNITS or p == ""
    n_is_count = n in COUNT_UNITS or n == ""
    if p_is_count and n_is_count:
        if p == n or p in GENERIC_COUNT or n in GENERIC_COUNT:
            return "one_to_one"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_ingredient_aggregator.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lib/ingredient_aggregator.py tests/test_ingredient_aggregator.py
git commit -m "feat: single unit-compatibility predicate

split_against_pantry and apply_decisions each hand-wrote a unit rule and
disagreed: split credited 3 ct lime against 1 whole lime, apply refused to
spend it. One predicate, so a future divergence is a caller bug rather than
a second rule.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Route both pantry functions through the predicate

**Files:**
- Modify: `lib/pantry.py` — `split_against_pantry` count branch (~lines 168-192), `apply_decisions` unit branch (~lines 227-243)
- Test: `tests/test_pantry.py`

**Interfaces:**
- Consumes: `unit_compatibility(pantry_unit, recipe_unit) -> Optional[str]` from Task 1.
- Produces: no new names. Behaviour change — `apply_decisions` now spends anything `split_against_pantry` credits.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pantry.py`:

```python
import itertools

import pytest

from lib.ingredient_aggregator import (
    COUNT_UNITS,
    parse_amount_to_float,
    unit_compatibility,
)
from lib.pantry import apply_decisions, split_against_pantry


def test_ct_pantry_is_spent_by_a_whole_recipe_line():
    """The reported bug: 3 ct lime, recipe wants 1 whole lime."""
    pantry = [{"item": "lime", "amount": "3", "unit": "ct"}]
    updated = apply_decisions(
        [{"item": "lime", "amount": "1", "unit": "whole"}], pantry)
    assert parse_amount_to_float(updated[0]["amount"]) == 2.0


def test_ct_pantry_depletes_to_removal():
    pantry = [{"item": "lime", "amount": "2", "unit": "ct"}]
    updated = apply_decisions(
        [{"item": "lime", "amount": "2", "unit": "whole"}], pantry)
    assert updated == []


# A representative unit from every group that behaves differently, rather than
# the full cross product of ~40 units, which would add 1600 slow cases for no
# extra coverage.
PARITY_UNITS = [
    "", "whole", "ct", "count", "ea", "each", "piece",   # generic count
    "clove", "slice", "can", "bunch", "head", "package",  # specific count
    "cup", "tbsp", "tsp", "qt",                           # volume
    "oz", "lb", "g",                                      # weight
    "a sprinkle", "loaf",                                 # unknown / garbage
]


@pytest.mark.parametrize("p_unit,n_unit", itertools.product(PARITY_UNITS, PARITY_UNITS))
def test_split_credit_implies_apply_can_spend(p_unit, n_unit):
    """Whatever the shopping list credits, the cook path must be able to spend.

    This is the invariant whose absence produced the bug. It is asserted over
    unit pairs rather than by inspecting the predicate, so it still holds if a
    caller stops delegating.
    """
    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    credited = split_against_pantry(
        "thing", "1", n_unit, pantry)["from_pantry"] is not None

    updated = apply_decisions(
        [{"item": "thing", "amount": "1", "unit": n_unit}], pantry)
    if not updated:
        spent = True                      # row removed entirely
    else:
        spent = parse_amount_to_float(updated[0]["amount"]) < 10.0

    assert credited == spent, (
        f"pantry {p_unit!r} vs recipe {n_unit!r}: "
        f"split credited={credited} but apply spent={spent}")


def test_parity_units_cover_every_count_unit_group():
    """Guard: if COUNT_UNITS grows a new *kind* of unit, extend PARITY_UNITS."""
    assert set(PARITY_UNITS) & COUNT_UNITS, "parity list lost its count units"
    assert unit_compatibility("ct", "whole") == "one_to_one"


def test_split_shows_the_pantry_unit_when_the_recipe_unit_is_generic():
    """`generic` was a local set used both to decide compatibility and to pick
    the display unit. It is now GENERIC_COUNT — this pins the display half so
    the swap can't silently change what the shopping list renders."""
    pantry = [{"item": "lime", "amount": "1", "unit": "ct"}]
    split = split_against_pantry("lime", "3", "whole", pantry)
    assert split["from_pantry"] == {"amount": "1", "unit": "ct"}
    assert split["to_buy"] == {"amount": "2", "unit": "ct"}


def test_split_shows_the_recipe_unit_when_it_is_specific():
    pantry = [{"item": "garlic", "amount": "1", "unit": "ct"}]
    split = split_against_pantry("garlic", "3", "cloves", pantry)
    assert split["from_pantry"]["unit"] == "cloves"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_pantry.py -q -k "spent or parity"
```

Expected: `test_ct_pantry_is_spent_by_a_whole_recipe_line` FAILS with `assert 3.0 == 2.0`, and several `test_split_credit_implies_apply_can_spend` cases FAIL with `split credited=True but apply spent=False`.

- [ ] **Step 3: Import the predicate in `lib/pantry.py`**

Change the existing import block at the top of `lib/pantry.py` from:

```python
from lib.ingredient_aggregator import (
    convert_from_base_unit,
    convert_to_base_unit,
    format_amount,
    get_unit_family,
    parse_amount_to_float,
)
```

to:

```python
from lib.ingredient_aggregator import (
    GENERIC_COUNT,
    convert_from_base_unit,
    convert_to_base_unit,
    format_amount,
    get_unit_family,
    parse_amount_to_float,
    unit_compatibility,
)
```

- [ ] **Step 4: Delegate the count branch of `split_against_pantry`**

In `split_against_pantry`, replace this block:

```python
    # count / other: combine if same unit, or if either side is the generic
    # "whole" / empty (the auto-fallback when no unit is parsed). This treats
    # "6 cloves garlic" as covering "10 whole garlic" 1:1, which is correct
    # for almost every count ingredient (cloves, lemons, eggs, onions, ...).
    p_unit_lower = (p_unit or "").lower()
    n_unit_lower = (unit or "").lower()
    generic = {"", "whole"}
    units_compatible = (
        p_unit_lower == n_unit_lower
        or p_unit_lower in generic
        or n_unit_lower in generic
    )
    if units_compatible:
```

with:

```python
    # count / other: 1:1 when the units are the same or either side is generic.
    # This treats "6 cloves garlic" as covering "10 whole garlic" 1:1, which is
    # correct for almost every count ingredient (cloves, lemons, eggs, onions).
    # The rule lives in unit_compatibility so apply_decisions applies the same
    # one — they used to disagree.
    p_unit_lower = (p_unit or "").lower()
    n_unit_lower = (unit or "").lower()
    if unit_compatibility(p_unit, unit) == "one_to_one":
```

**Then fix the one line in the body that referenced the deleted set.** Three lines below, replace:

```python
        out_unit = unit if n_unit_lower not in generic else (p_unit or unit)
```

with:

```python
        out_unit = unit if n_unit_lower not in GENERIC_COUNT else (p_unit or unit)
```

`generic` was a local `{"", "whole"}` used both by the condition and by this
display choice. Deleting it without fixing this line raises `NameError` on the
first count-unit split. `GENERIC_COUNT` is a superset — it also contains `ct`,
`count`, `ea`, `each`, `piece`, `pieces` — so a recipe line whose unit is `ea`
now displays in the pantry row's unit rather than `ea`. That is the intended
reading of "the recipe's unit is generic, so show the pantry's".

`p_unit_lower` is still used further down in the final "different count units"
warning; leave it. If your editor reports `n_unit_lower` as unused after this
change, re-check — it is used on the line you just edited.

- [ ] **Step 5: Delegate the unit branch of `apply_decisions`**

In `apply_decisions`, replace:

```python
            p_family = get_unit_family(p_unit)
            u_family = get_unit_family(used_unit)
            if p_family in ("volume", "weight") and p_family == u_family:
                p_base = convert_to_base_unit(p_amt, p_unit, p_family)
                u_base = convert_to_base_unit(used_amt, used_unit, u_family)
```

with:

```python
            mode = unit_compatibility(p_unit, used_unit)
            if mode == "convert":
                p_family = get_unit_family(p_unit)
                p_base = convert_to_base_unit(p_amt, p_unit, p_family)
                u_base = convert_to_base_unit(used_amt, used_unit, p_family)
```

and replace the following line:

```python
            elif (p_unit or "").lower() == (used_unit or "").lower():
```

with:

```python
            elif mode == "one_to_one":
```

Note the `convert` branch now passes `p_family` for both conversions. That is correct and was already implied — `unit_compatibility` returns `"convert"` only when both units share a family, so `u_family` and `p_family` were always equal here.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_pantry.py -q
```

Expected: all pass, including all 484 parity cases.

- [ ] **Step 7: Run the full suite — this change touches the shopping list**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: pass count is the Task 0 baseline plus the new tests. **If a shopping-list test fails, do not "fix" it by narrowing the predicate.** Read the failure: a `ct` pantry row now credits against `bunch`/`can` recipe lines, which is intended. Report the failure with its assertion and stop.

- [ ] **Step 8: Commit**

```bash
git add lib/pantry.py tests/test_pantry.py
git commit -m "fix: apply_decisions spends what split_against_pantry credits

Both now delegate to unit_compatibility. A parity test over representative
unit pairs asserts the invariant directly, so it holds even if a caller
stops delegating.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Extend `_ATOMIC_FOODS` to close the compound-food hole

**Files:**
- Modify: `lib/use_it_up.py:36-44` (the `_ATOMIC_FOODS` tuple)
- Test: `tests/test_use_it_up.py`

**Interfaces:**
- Consumes: `_content_tokens` (already imported in `use_it_up`).
- Produces: no new names. `_covers()` gets stricter for 12 compound foods.

Background: `436597d` made containment reach the head noun *when the containing phrase is a clean inventory name*. But `_STOPWORDS` reduces `shredded cheese` to `{cheese}` and `Canned corn` to `{corn}`, so when the inventory name is the **shorter** side plain containment still stands. Verified empirically: today `_covers(_phrase("Canned corn"), _ingredient_phrase("light corn syrup"))` is `True`, and every `X cheese` matches `shredded cheese`. This is live in Cook Now right now.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_use_it_up.py`:

```python
from lib.use_it_up import _covers, _ingredient_phrase, _phrase


class TestCompoundFoodsDoNotMatchTheirHeadNoun:
    """`_STOPWORDS` reduces 'shredded cheese' to {cheese} and 'Canned corn' to
    {corn}, so without an atomic entry every cheese and every corn product
    matches them. 436597d only closed the direction where the inventory name is
    the longer phrase."""

    def test_cream_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("cream cheese"))

    def test_cottage_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("cottage cheese"))

    def test_goat_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("goat cheese"))

    def test_corn_syrup_is_not_canned_corn(self):
        assert not _covers(_phrase("Canned corn"),
                           _ingredient_phrase("light corn syrup"))

    def test_corn_tortillas_are_not_canned_corn(self):
        assert not _covers(_phrase("Canned corn"),
                           _ingredient_phrase("corn tortillas"))


class TestCompoundExtensionKeepsTrueMatches:
    def test_cornstarch_still_matches_a_noisy_ingredient_line(self):
        assert _covers(_phrase("Cornstarch"),
                       _ingredient_phrase("potato starch or cornstarch"))

    def test_prep_note_variants_still_match(self):
        assert _covers(_phrase("Basil"), _ingredient_phrase("basil leaves"))

    def test_existing_atomic_foods_still_hold(self):
        assert not _covers(_phrase("butter"),
                           _ingredient_phrase("peanut butter"))
        assert _covers(_phrase("peanut butter"),
                       _ingredient_phrase("creamy peanut butter, softened"))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_use_it_up.py -q -k "Compound"
```

Expected: the five `TestCompoundFoodsDoNotMatchTheirHeadNoun` tests FAIL (each asserts `not True`). The three `TestCompoundExtensionKeepsTrueMatches` tests PASS already — they are regression guards, and they must still pass after Step 3.

- [ ] **Step 3: Extend the tuple**

In `lib/use_it_up.py`, replace:

```python
_ATOMIC_FOODS: tuple[frozenset, ...] = tuple(
    _content_tokens(name) for name in (
        "peanut butter", "almond butter", "cashew butter", "apple butter",
        "cocoa butter", "coconut milk", "almond milk", "oat milk", "soy milk",
        "coconut cream", "butter beans", "cream of tartar",
    )
)
```

with:

```python
_ATOMIC_FOODS: tuple[frozenset, ...] = tuple(
    _content_tokens(name) for name in (
        "peanut butter", "almond butter", "cashew butter", "apple butter",
        "cocoa butter", "coconut milk", "almond milk", "oat milk", "soy milk",
        "coconut cream", "butter beans", "cream of tartar",
        # A second class of compound: these do not lie about their head noun,
        # but the inventory rows they collide with reduce to a single generic
        # token ("shredded cheese" -> {cheese}, "Canned corn" -> {corn}), so
        # plain containment matched every cheese and every corn product.
        "cream cheese", "cottage cheese", "goat cheese", "feta cheese",
        "corn syrup", "corn tortilla", "corn meal", "cornmeal",
        "coconut yogurt", "cherry juice", "corn starch", "cornstarch",
    )
)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_use_it_up.py -q
```

Expected: all pass, including both regression guards.

- [ ] **Step 5: Run the full suite — this changes Cook Now coverage**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: green. `cook_now` and `use_it_up` both consume `_covers`, so a coverage-count assertion may move. If one fails, report the test name and both numbers — do not adjust the expected number without saying so.

- [ ] **Step 6: Commit**

```bash
git add lib/use_it_up.py tests/test_use_it_up.py
git commit -m "fix: compound foods no longer match single-token inventory rows

_STOPWORDS reduces 'shredded cheese' to {cheese} and 'Canned corn' to {corn},
and 436597d only required a head-noun hit when the inventory phrase was the
longer side. So every X cheese matched shredded cheese, and Cook Now credited
corn-syrup coverage from a can of corn.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `find_match` adopts the shared matcher

**Files:**
- Modify: `lib/pantry.py` — imports, and `find_match` (~lines 103-116)
- Test: `tests/test_pantry.py`

**Interfaces:**
- Consumes: `_phrase`, `_ingredient_phrase`, `_covers` from `lib.use_it_up`; the Task 3 `_ATOMIC_FOODS` extension and its atomic-block refinements.
- Produces: no new names. `find_match` keeps its signature `find_match(item_name: str, pantry: list[dict]) -> Optional[dict]`.

Import safety, already verified: `lib.pantry` is **not** in `lib.use_it_up`'s transitive import closure, and the only module-level import of `lib.pantry` anywhere in `lib/` is `lib/cook.py`. A module-level `from lib.use_it_up import ...` in `pantry.py` therefore cannot cycle.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pantry.py`:

```python
from lib.pantry import find_match


class TestFindMatch:
    def test_exact_name_wins(self):
        pantry = [{"item": "lime", "amount": "3", "unit": "ct"},
                  {"item": "lime juice", "amount": "1", "unit": "oz"}]
        assert find_match("lime", pantry)["item"] == "lime"

    def test_prep_note_variant_matches(self):
        pantry = [{"item": "Capers", "amount": "1", "unit": "ct"}]
        assert find_match("capers, drained", pantry)["item"] == "Capers"

    def test_parenthetical_noise_does_not_produce_a_wrong_match(self):
        # AMENDED: the plan originally normalized ingredient text first and
        # asserted this line matched `Avocado oil`. Normalizing strips
        # parentheses, which is where alternatives live, so it is not done —
        # see Step 3. What matters is that the noise inside the parenthetical
        # cannot produce a WRONG match: `corn` must not pull in `Canned corn`.
        pantry = [{"item": "Canned corn", "amount": "1", "unit": "ct"}]
        assert find_match("oil (for softening corn tortillas)", pantry) is None

    def test_an_alternatives_list_still_matches_a_named_alternative(self):
        # Normalizing would collapse this line to "almond butter" and lose the
        # peanut alternative entirely.
        pantry = [{"item": "Peanut butter", "amount": "1", "unit": "ct"}]
        assert find_match(
            "almond butter (or peanut, walnut, or cashew butter, or tahini)",
            pantry)["item"] == "Peanut butter"

    def test_generic_ingredient_does_not_match_a_compound_row(self):
        # The substring matcher gave `lemon` -> `Lemon pepper seasoning`.
        pantry = [{"item": "Lemon pepper seasoning", "amount": "1", "unit": "ct"}]
        assert find_match("lemons", pantry) is None

    def test_peanut_butter_does_not_match_the_butter_staple(self):
        # 11 ingredient lines in the real library hit this.
        pantry = [{"item": "butter", "amount": "1", "unit": "ct"}]
        assert find_match("peanut butter", pantry) is None

    def test_compound_row_still_matches_its_own_ingredient(self):
        pantry = [{"item": "Peanut butter", "amount": "1", "unit": "ct"}]
        assert find_match("creamy peanut butter", pantry)["item"] == "Peanut butter"

    def test_no_match_returns_none(self):
        pantry = [{"item": "flour", "amount": "1", "unit": "ct"}]
        assert find_match("dragon fruit", pantry) is None

    def test_empty_name_returns_none(self):
        assert find_match("", [{"item": "flour", "amount": "1", "unit": "ct"}]) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_pantry.py -q -k FindMatch
```

Expected: `test_generic_ingredient_does_not_match_a_compound_row`,
`test_peanut_butter_does_not_match_the_butter_staple` and
`test_parenthetical_noise_does_not_produce_a_wrong_match` FAIL — all three are
the substring matcher's false positives. The rest pass already, including
`test_an_alternatives_list_still_matches_a_named_alternative`, which is a
regression guard proving the change does not cost that match.

- [ ] **Step 3: Add the imports to `lib/pantry.py`**

Directly below the existing `from lib.ingredient_aggregator import (...)` block, add:

```python
from lib.use_it_up import _covers, _ingredient_phrase, _phrase
```

**AMENDED DURING EXECUTION.** The original plan also imported
`ingredient_normalizer.normalize_name` and ran ingredient text through it before
matching. Do **not** do that. `normalize_name` strips parentheticals, and that
is where ingredient text keeps its *alternatives*: `almond butter (or peanut,
walnut, or cashew butter, or tahini)` collapses to `almond butter`, so a
`Peanut butter` inventory row stops matching a line that explicitly offers
peanut. Measured on this task's own test cases, raw and normalized each miss
exactly one case and both misses are in the safe false-negative direction — raw
misses `Avocado oil` ← `oil (for softening corn tortillas)`, normalized misses
the nut-butter line. Raw wins because it preserves disjunctions, and because
`cook_now` and `use_it_up` already hand `_covers` raw ingredient text, so
normalizing here would have made the cook path inconsistent rather than
consistent.

- [ ] **Step 4: Replace `find_match`**

Replace the whole function:

```python
def find_match(item_name: str, pantry: list[dict]) -> Optional[dict]:
    """Return the first pantry entry whose normalized item matches `item_name`."""
    target = _normalize(item_name)
    if not target:
        return None
    for entry in pantry:
        if _normalize(entry.get("item")) == target:
            return entry
    # fallback: substring match (handles "all-purpose flour" vs "flour")
    for entry in pantry:
        pname = _normalize(entry.get("item"))
        if pname and (pname in target or target in pname):
            return entry
    return None
```

with:

```python
def find_match(item_name: str, pantry: list[dict]) -> Optional[dict]:
    """The pantry entry naming the same food as `item_name`, or None.

    Exact name first, then the head-noun matcher shared with Cook Now and Use
    It Up. The old character-substring fallback is gone: it matched "lemon" to
    "Lemon pepper seasoning" and every peanut-butter line to the "butter"
    staple row, and 436597d already replaced it everywhere else. Ingredient
    text is passed in raw, exactly as `cook_now` and `use_it_up` pass it:
    normalizing first would strip the parentheses that carry a line's
    alternatives ("almond butter (or peanut ...)") and lose real matches.
    """
    target = _normalize(item_name)
    if not target:
        return None
    for entry in pantry:
        if _normalize(entry.get("item")) == target:
            return entry

    phrase = _ingredient_phrase(item_name)
    if not phrase.tokens:
        return None
    for entry in pantry:
        name = entry.get("item") or ""
        if name and _covers(_phrase(name), phrase):
            return entry
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_pantry.py -q
```

Expected: all pass.

- [ ] **Step 6: Run the full suite — `find_match` is shared with the shopping list**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: green. This function is used by `split_against_pantry`, so shopping-list behaviour changes: 36 false credits are removed and some new credits added. If a test fails, report its name and assertion verbatim and stop — do not reintroduce the substring fallback.

- [ ] **Step 7: Commit**

```bash
git add lib/pantry.py tests/test_pantry.py
git commit -m "fix: find_match uses the head-noun matcher, not substrings

436597d replaced bidirectional substring containment in use_it_up,
recipe_matcher and cook_now but missed pantry.find_match, which still gave
lemon -> Lemon pepper seasoning and matched 11 peanut-butter lines to the
butter staple row. Ingredient text is normalized first so this path and the
shopping-list split see the same input shape.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `last_used` / `use_count` columns and `stamp_inventory_use()`

**Files:**
- Modify: `lib/inventory_db.py` — `_INVENTORY_COLS` (~line 115), `_MIGRATIONS` (~line 122), plus a new function
- Modify: `lib/inventory.py` — `InventoryItem` dataclass (~lines 34-44), `read_inventory` (~lines 132-150)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `connect()` from `lib.inventory_db`.
- Produces:
  - `InventoryItem.last_used: Optional[str]`, `InventoryItem.use_count: int`
  - `inventory_db.stamp_inventory_use(refs: list[tuple[str, str]], when: str) -> int` — `refs` are `(name, unit)` pairs, matched case-insensitively; returns the number of rows updated.

**The trap this task exists to avoid:** `write_inventory()` calls `replace_inventory_rows()`, which is `DELETE FROM inventory` followed by a bulk `INSERT` built from `_INVENTORY_COLS`. If a column is added to the schema but not to `_INVENTORY_COLS`, the `InventoryItem` dataclass **and** the `read_inventory()` mapping, then the next receipt ingest or expiry prune silently wipes every stamp. All four must change together.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_inventory.py`:

```python
from lib import inventory_db
from lib.inventory import InventoryItem, add_items, read_inventory, write_inventory


class TestUseStamps:
    def test_new_items_start_unused(self, tmp_db, tmp_vault):
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])
        item = read_inventory()[0]
        assert item.last_used is None
        assert item.use_count == 0

    def test_stamp_sets_timestamp_and_increments_count(self, tmp_db, tmp_vault):
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])
        updated = inventory_db.stamp_inventory_use(
            [("Mirin", "ct")], "2026-07-26T10:00:00")
        assert updated == 1

        item = read_inventory()[0]
        assert item.last_used == "2026-07-26T10:00:00"
        assert item.use_count == 1

    def test_stamping_twice_increments_twice(self, tmp_db, tmp_vault):
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])
        inventory_db.stamp_inventory_use([("Mirin", "ct")], "2026-07-26T10:00:00")
        inventory_db.stamp_inventory_use([("Mirin", "ct")], "2026-07-27T10:00:00")

        item = read_inventory()[0]
        assert item.use_count == 2
        assert item.last_used == "2026-07-27T10:00:00"

    def test_matching_is_case_insensitive_on_name_and_unit(self, tmp_db, tmp_vault):
        add_items([InventoryItem(name="Mirin", quantity=1, unit="CT")])
        assert inventory_db.stamp_inventory_use(
            [("mirin", "ct")], "2026-07-26T10:00:00") == 1

    def test_unknown_ref_updates_nothing(self, tmp_db, tmp_vault):
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])
        assert inventory_db.stamp_inventory_use(
            [("Nonexistent", "ct")], "2026-07-26T10:00:00") == 0

    def test_empty_refs_is_a_noop(self, tmp_db, tmp_vault):
        assert inventory_db.stamp_inventory_use([], "2026-07-26T10:00:00") == 0

    def test_stamps_survive_a_write_inventory_round_trip(self, tmp_db, tmp_vault):
        """write_inventory is DELETE-all + re-INSERT. If last_used/use_count are
        missing from _INVENTORY_COLS, the dataclass, or the read_inventory
        mapping, every stamp is silently wiped by the next receipt ingest."""
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])
        inventory_db.stamp_inventory_use([("Mirin", "ct")], "2026-07-26T10:00:00")

        write_inventory(read_inventory())          # the round trip

        item = read_inventory()[0]
        assert item.last_used == "2026-07-26T10:00:00"
        assert item.use_count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_inventory.py -q -k UseStamps
```

Expected: FAIL — `AttributeError: 'InventoryItem' object has no attribute 'last_used'` and `AttributeError: module 'lib.inventory_db' has no attribute 'stamp_inventory_use'`.

- [ ] **Step 3: Add the columns to the schema plumbing**

In `lib/inventory_db.py`, replace:

```python
_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes", "for_recipe", "expires",
)
```

with:

```python
_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes", "for_recipe", "expires",
    "last_used", "use_count",
)
```

and replace:

```python
_MIGRATIONS = {
    "inventory": (("for_recipe", "TEXT"), ("expires", "TEXT")),
    "purchases": (("for_recipe", "TEXT"),),
    "cooks": (("make_again", "INTEGER"), ("cook_note", "TEXT")),
}
```

with:

```python
_MIGRATIONS = {
    "inventory": (
        ("for_recipe", "TEXT"), ("expires", "TEXT"),
        # Set when a cook uses a row it cannot safely decrement (a container).
        ("last_used", "TEXT"), ("use_count", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "purchases": (("for_recipe", "TEXT"),),
    "cooks": (("make_again", "INTEGER"), ("cook_note", "TEXT")),
}
```

- [ ] **Step 4: Add `stamp_inventory_use`**

In `lib/inventory_db.py`, immediately after `replace_inventory_rows`, add:

```python
def stamp_inventory_use(refs: list[tuple[str, str]], when: str) -> int:
    """Mark inventory rows as used by a cook. Returns the number updated.

    ``refs`` are ``(name, unit)`` pairs, matched case-insensitively. A targeted
    UPDATE rather than the read-modify-write of ``write_inventory()``, so
    marking a recipe cooked does not rewrite all 222 rows or regenerate the
    Inventory.md and Cook Now.md views. A ref naming no row updates nothing —
    that is expected for a row the same cook just depleted and removed.
    """
    if not refs:
        return 0
    conn = connect()
    try:
        total = 0
        with conn:
            for name, unit in refs:
                cur = conn.execute(
                    "UPDATE inventory"
                    " SET last_used = ?, use_count = COALESCE(use_count, 0) + 1"
                    " WHERE lower(name) = ? AND lower(unit) = ?",
                    (when, (name or "").lower().strip(),
                     (unit or "").lower().strip()),
                )
                total += cur.rowcount
        return total
    finally:
        conn.close()
```

- [ ] **Step 5: Add the fields to `InventoryItem`**

In `lib/inventory.py`, replace:

```python
    for_recipe: Optional[str] = None
    expires: Optional[str] = None

    def merge_key(self) -> tuple[str, str, str]:
```

with:

```python
    for_recipe: Optional[str] = None
    expires: Optional[str] = None
    # Written by consume-on-cook when a row is used but cannot safely be
    # decremented (a container). Must round-trip through write_inventory(),
    # which is DELETE-all + re-INSERT.
    last_used: Optional[str] = None
    use_count: int = 0

    def merge_key(self) -> tuple[str, str, str]:
```

- [ ] **Step 6: Add the fields to the `read_inventory` mapping**

In `lib/inventory.py`, replace:

```python
            for_recipe=r["for_recipe"] or None,
            expires=r["expires"] or None,
        )
        for r in inventory_db.fetch_inventory_rows()
```

with:

```python
            for_recipe=r["for_recipe"] or None,
            expires=r["expires"] or None,
            last_used=r["last_used"] or None,
            use_count=int(r["use_count"] or 0),
        )
        for r in inventory_db.fetch_inventory_rows()
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_inventory.py -q
```

Expected: all pass, especially `test_stamps_survive_a_write_inventory_round_trip`.

- [ ] **Step 8: Prove the round-trip test is not vacuous**

Temporarily remove `"last_used", "use_count"` from `_INVENTORY_COLS` and re-run:

```bash
.venv/bin/python -m pytest tests/test_inventory.py -q -k round_trip
```

Expected: FAIL. **Restore the two entries immediately** and re-run to confirm PASS. A round-trip test that passes with the plumbing removed is testing nothing.

- [ ] **Step 9: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 10: Commit**

```bash
git add lib/inventory_db.py lib/inventory.py tests/test_inventory.py
git commit -m "feat: record inventory use with last_used/use_count

Columns rather than a joined table: inventory.id is not stable, because
write_inventory() is DELETE-all + re-INSERT on every call. Both columns are
added to _INVENTORY_COLS, the dataclass and the read_inventory mapping
together — missing any one silently wipes stamps on the next ingest, which
the round-trip test pins.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The container gate and four-outcome classification

**Files:**
- Modify: `lib/cook.py` (whole `consume_recipe`, plus imports)
- Test: `tests/test_cook.py`

**Interfaces:**
- Consumes: `unit_compatibility` (Task 1), the fixed `apply_decisions`/`find_match` (Tasks 2 and 4), `inventory_db.stamp_inventory_use` (Task 5).
- Produces: `consume_recipe(recipe_name, servings=1.0, staples=None, now=None) -> dict` with keys `recipe`, `consumed`, `skipped_staples`, `not_tracked`, `use_recorded`, and `error` on failure. **`unconvertible` is removed.**

**Existing test that must change:** `tests/test_cook.py::TestConsumeRecipe::test_decrements_tracked_non_staples` seeds `spinach` at `quantity=1, unit="ct"` and asserts `depleted is True`. Under the container gate a qty-1 row is use-stamped, never decremented, so that assertion must move to `use_recorded`. This is the intended behaviour change, not a regression.

- [ ] **Step 1: Update the existing test and add the new ones**

In `tests/test_cook.py`, replace the `_seed_inventory` helper:

```python
def _seed_inventory():
    add_items([
        InventoryItem(name="buttermilk", quantity=4, unit="cup", category="dairy"),
        InventoryItem(name="cucumber", quantity=3, unit="ct", category="produce"),
        InventoryItem(name="spinach", quantity=1, unit="ct", category="produce"),
        # flour intentionally absent (it's a staple); dragon fruit absent (untracked)
    ])
```

with:

```python
def _seed_inventory():
    add_items([
        InventoryItem(name="buttermilk", quantity=4, unit="cup", category="dairy"),
        InventoryItem(name="cucumber", quantity=3, unit="ct", category="produce"),
        # spinach is qty 1 — a container. The gate use-stamps it, never
        # decrements it, because in the real inventory 188 of 198 count rows
        # sit at exactly 1.0 and mean "one package".
        InventoryItem(name="spinach", quantity=1, unit="ct", category="produce"),
        # flour intentionally absent (it's a staple); dragon fruit absent (untracked)
    ])
```

Then replace the body of `test_decrements_tracked_non_staples`:

```python
    def test_decrements_tracked_non_staples(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        result = cook.consume_recipe("Test Bake")

        consumed = {c["item"]: c for c in result["consumed"]}
        # buttermilk: 4 cup - 0.25 = 3.75 left
        assert round(consumed["buttermilk"]["after"], 2) == 3.75
        assert consumed["buttermilk"]["depleted"] is False
        # cucumber: 3 - 1 = 2
        assert consumed["cucumber"]["after"] == 2
        # spinach: 1 - 1 = 0 → used up
        assert consumed["spinach"]["depleted"] is True
```

with:

```python
    def test_decrements_tracked_non_staples(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        result = cook.consume_recipe("Test Bake")

        consumed = {c["item"]: c for c in result["consumed"]}
        # buttermilk: 4 cup - 0.25 = 3.75 left
        assert round(consumed["buttermilk"]["after"], 2) == 3.75
        assert consumed["buttermilk"]["depleted"] is False
        # cucumber: 3 - 1 = 2
        assert consumed["cucumber"]["after"] == 2
        # spinach is qty 1 — a container, so it is stamped rather than emptied.
        assert "spinach" not in consumed
        assert any(u["item"] == "spinach" for u in result["use_recorded"])
```

Then add these test classes to `tests/test_cook.py`:

```python
CONTAINER_RECIPE_MD = """\
---
recipe_name: Container Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | tbsp | mirin |
| 3 | whole | bay leaves |
| 2 | whole | limes |
| 1 | whole | table spoon bacon drippings |
"""


def _write_container_recipe():
    rd = paths.recipes_dir()
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "Container Test.md").write_text(CONTAINER_RECIPE_MD, encoding="utf-8")


def _seed_containers():
    add_items([
        InventoryItem(name="Mirin", quantity=1, unit="ct", category="pantry"),
        InventoryItem(name="Bay leaves", quantity=1, unit="ct", category="pantry"),
        InventoryItem(name="lime", quantity=5, unit="ct", category="produce"),
        InventoryItem(name="bacon", quantity=1, unit="oz", category="meat"),
    ])


class TestContainerGate:
    def test_container_quantity_is_never_changed(self, tmp_vault, tmp_db):
        """`1 ct Mirin` used for `2 tbsp` keeps its quantity."""
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test")

        rows = {i.name: i for i in read_inventory()}
        assert rows["Mirin"].quantity == 1

    def test_container_use_is_stamped(self, tmp_vault, tmp_db):
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test", now="2026-07-26T10:00:00")

        rows = {i.name: i for i in read_inventory()}
        assert rows["Mirin"].last_used == "2026-07-26T10:00:00"
        assert rows["Mirin"].use_count == 1

    def test_a_qty_one_jar_is_not_deleted_by_a_count_recipe_line(self, tmp_vault, tmp_db):
        """Without the gate, `3 whole bay leaves` deletes the whole jar."""
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test")

        rows = {i.name: i for i in read_inventory()}
        assert "Bay leaves" in rows
        assert rows["Bay leaves"].quantity == 1

    def test_a_real_count_still_decrements(self, tmp_vault, tmp_db):
        """5 ct lime, recipe wants 2 whole limes → 3 left. The reported bug."""
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")

        consumed = {c["item"]: c for c in result["consumed"]}
        assert consumed["lime"]["after"] == 3
        assert consumed["lime"]["depleted"] is False

    def test_garbage_unit_becomes_a_use_record(self, tmp_vault, tmp_db):
        """"1 whole table spoon bacon drippings" vs `1 oz bacon` — the biscuits case."""
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")

        assert any(u["item"] == "bacon" for u in result["use_recorded"])
        rows = {i.name: i for i in read_inventory()}
        assert rows["bacon"].quantity == 1

    def test_response_has_no_unconvertible_key(self, tmp_vault, tmp_db):
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")
        assert "unconvertible" not in result
        assert set(result) == {
            "recipe", "consumed", "skipped_staples", "not_tracked", "use_recorded"}


class TestNoOpCookDoesNotRewriteInventory:
    def test_no_decisions_means_no_save_pantry(self, tmp_vault, tmp_db, monkeypatch):
        """234 of 236 recipes decrement nothing. Each one used to trigger a full
        DELETE+INSERT of every row plus two vault-note regenerations."""
        _write_container_recipe()
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])

        calls = []
        monkeypatch.setattr(cook, "save_pantry", lambda items: calls.append(items))
        cook.consume_recipe("Container Test")
        assert calls == []
```

Add `read_inventory` to the existing import line at the top of `tests/test_cook.py` if it is not already there:

```python
from lib.inventory import InventoryItem, add_items, read_inventory
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cook.py -q
```

Expected: the `TestContainerGate` tests FAIL with `KeyError: 'use_recorded'`, and `test_a_qty_one_jar_is_not_deleted_by_a_count_recipe_line` FAILS because the jar is gone.

- [ ] **Step 3: Rewrite `lib/cook.py`**

Replace the imports block:

```python
from lib import paths
from lib.pantry import (
    apply_decisions,
    find_match,
    format_amount,
    load_pantry,
    parse_amount_to_float,
    save_pantry,
)
from lib.recipe_matcher import _content_tokens
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.use_it_up import _ingredient_phrase, _is_staple, _staple_phrases
```

with:

```python
from datetime import datetime

from lib import paths
from lib.ingredient_aggregator import unit_compatibility
from lib.inventory_db import stamp_inventory_use
from lib.pantry import (
    apply_decisions,
    find_match,
    format_amount,
    load_pantry,
    parse_amount_to_float,
    save_pantry,
)
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.use_it_up import _ingredient_phrase, _is_staple, _staple_phrases
```

(The `_content_tokens` import is deleted — it was never called.)

Add this helper above `consume_recipe`:

```python
def _record_use(bucket: list[dict], item: str, unit: Optional[str]) -> None:
    """Append a row to the use-recorded list, deduped by (item, unit).

    A recipe can name the same inventory row twice ("1 tsp cinnamon" in the
    rub and "1/2 tsp" in the glaze); that is one container, used once.
    """
    key = ((item or "").lower(), (unit or "").lower())
    for existing in bucket:
        if ((existing["item"] or "").lower(),
                (existing["unit"] or "").lower()) == key:
            return
    bucket.append({"item": item, "unit": unit})
```

Then replace the whole `consume_recipe` function with:

```python
def consume_recipe(recipe_name: str, servings: float = 1.0,
                   staples: Optional[set] = None,
                   now: Optional[str] = None) -> dict:
    """Apply a cooked recipe to inventory. Returns a four-outcome summary.

    ``servings`` multiplies the amounts (a double batch → 2.0). ``now`` is the
    use-stamp timestamp; defaults to the current time and is injectable for
    tests. Returns::

        {recipe, consumed: [{item, unit, before, after, depleted}],
         skipped_staples: [...], not_tracked: [...],
         use_recorded: [{item, unit}], error?}

    Every ingredient lands in exactly one bucket:

    - ``skipped_staples`` — an assumed-on-hand staple; never tracked.
    - ``not_tracked``     — no inventory row names this food.
    - ``consumed``        — quantity actually decremented.
    - ``use_recorded``    — the row was used but must not be decremented,
      because its units don't convert, its amount is unparseable, or it is a
      container (quantity exactly 1.0).

    The container gate is the load-bearing safety rule: 188 of 198 count rows
    in the real inventory sit at exactly 1.0, meaning "one package". Subtracting
    from those would delete a whole jar of bay leaves for a recipe using three.
    A missed depletion self-heals through the expiry prune; a deleted jar does
    not, and pollutes the shopping list.
    """
    ings = recipe_ingredients(recipe_name)
    if ings is None:
        return {"recipe": recipe_name, "error": "recipe not found",
                "consumed": [], "skipped_staples": [], "not_tracked": [],
                "use_recorded": []}

    staple_sets = _staple_phrases(staples)
    pantry = load_pantry()
    before = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0 for e in pantry}
    units = {e["item"]: e.get("unit") for e in pantry}

    decisions: list[dict] = []
    skipped_staples: list[str] = []
    not_tracked: list[str] = []
    use_recorded: list[dict] = []
    matched: set[str] = set()

    for ing in ings:
        item = (ing.get("item") or "").strip()
        if not item:
            continue
        if _is_staple(_ingredient_phrase(item), staple_sets):
            skipped_staples.append(item)
            continue
        match = find_match(item, pantry)
        if match is None:
            not_tracked.append(item)
            continue

        p_unit = match.get("unit") or ""
        p_qty = parse_amount_to_float(match.get("amount"))
        amt = parse_amount_to_float(ing.get("amount"))
        scaled = amt * servings if amt is not None else None

        if (scaled is None
                or p_qty is None
                or p_qty == 1.0
                or unit_compatibility(p_unit, ing.get("unit") or "") is None):
            _record_use(use_recorded, match["item"], p_unit)
            continue

        decisions.append({
            "item": match["item"],  # exact pantry name so apply_decisions matches
            "amount": format_amount(scaled),
            "unit": ing.get("unit") or "",
        })
        matched.add(match["item"])

    if decisions:
        updated = apply_decisions(decisions, pantry)
        save_pantry(updated)
        after = {e["item"]: parse_amount_to_float(e["amount"]) or 0.0
                 for e in updated}
    else:
        after = before

    consumed = []
    for name in sorted(matched):
        b = before.get(name, 0.0)
        if name not in after:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": 0.0, "depleted": True})
        elif after[name] < b - 1e-9:
            consumed.append({"item": name, "unit": units.get(name),
                             "before": b, "after": after[name],
                             "depleted": False})
        else:
            # Defensive: the gate should have caught this. Report it as use
            # rather than silently claiming a decrement that didn't happen.
            _record_use(use_recorded, name, units.get(name))

    # Stamp AFTER save_pantry — save_pantry is DELETE-all + re-INSERT, so a
    # stamp written before it would be replaced by the pre-cook row values.
    stamp_at = now or datetime.now().isoformat(timespec="seconds")
    refs = [(u["item"], u["unit"] or "") for u in use_recorded]
    refs += [(c["item"], c["unit"] or "") for c in consumed]
    if refs:
        stamp_inventory_use(refs, stamp_at)

    return {"recipe": recipe_name, "consumed": consumed,
            "skipped_staples": skipped_staples, "not_tracked": not_tracked,
            "use_recorded": use_recorded}
```

Also update the module docstring — replace the last paragraph:

```python
Reuses ``pantry.apply_decisions`` — the same unit-aware decrement the
shopping-list confirm uses — over the DB inventory table. Volume/weight amounts
convert within their family (cup → qt); cross-family pairs it can't convert
without density are left untouched and reported.
"""
```

with:

```python
Reuses ``pantry.apply_decisions`` — the same unit-aware decrement the
shopping-list confirm uses — over the DB inventory table. Volume/weight amounts
convert within their family (cup → qt).

Inventory holds *containers*, not measured quantities: 188 of 198 count rows
sit at quantity exactly 1.0, meaning one package. Such a row is never
decremented — it is use-stamped instead (``last_used``/``use_count``), so a
recipe calling for three bay leaves cannot delete the jar.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_cook.py -q
```

Expected: all pass.

- [ ] **Step 5: Prove the container gate is doing the work**

Temporarily change `or p_qty == 1.0` to `or False` in `consume_recipe` and re-run:

```bash
.venv/bin/python -m pytest tests/test_cook.py -q -k "jar_is_not_deleted or container_quantity"
```

Expected: FAIL. **Restore `or p_qty == 1.0`** and confirm PASS. A gate whose removal breaks nothing is not a gate.

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: green. `api_server` returns this dict from `/api/cook`, so an endpoint test asserting `unconvertible` will fail — update it to `use_recorded` and say so in the report.

- [ ] **Step 7: Commit**

```bash
git add lib/cook.py tests/test_cook.py
git commit -m "feat: container gate and four-outcome consume-on-cook

A row at quantity exactly 1.0 is one package, not one unit of measure — 188
of 198 count rows in the real inventory are such rows. Decrementing them
deletes a whole jar for a recipe using three bay leaves, so they are
use-stamped instead. A missed depletion self-heals via the expiry prune; a
deleted jar does not.

Also: unconvertible is replaced by use_recorded, save_pantry is skipped when
nothing decrements (it was rewriting all rows and regenerating two vault
notes on every one of the 234 no-op cooks), and the dead _content_tokens
import is removed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Gate `/api/cook` behind the bearer token

**Files:**
- Modify: `api_server.py` — the `/api/cook` route (~line 2036)
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: the existing `require_token` decorator (`api_server.py:54`).
- Produces: no new names.

Background: `require_token` is a no-op when `KITCHENOS_API_TOKEN` is unset, exempts localhost, and otherwise requires `Authorization: Bearer <token>`. `/api/cooks` is already gated; `/api/cook` is not, so a tailnet caller can decrement inventory unauthenticated.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_auth.py`:

```python
def test_cook_remote_without_token_rejected(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    # Must not reach consume_recipe — this asserts the gate, not the cook path.
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: pytest.fail("consume_recipe reached without a token"))
    resp = client.post("/api/cook", json={"recipe": "Anything"}, **REMOTE)
    assert resp.status_code == 401


def test_cook_localhost_exempt(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: {"recipe": "Anything", "consumed": [],
                         "skipped_staples": [], "not_tracked": [],
                         "use_recorded": []})
    resp = client.post("/api/cook", json={"recipe": "Anything"})
    assert resp.status_code == 200


def test_cook_remote_with_valid_token_allowed(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: {"recipe": "Anything", "consumed": [],
                         "skipped_staples": [], "not_tracked": [],
                         "use_recorded": []})
    resp = client.post(
        "/api/cook", json={"recipe": "Anything"},
        headers={"Authorization": "Bearer secret"}, **REMOTE)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_api_auth.py -q -k cook
```

Expected: `test_cook_remote_without_token_rejected` FAILS — it returns 200 (or reaches the `pytest.fail` stub) instead of 401.

- [ ] **Step 3: Add the decorator**

In `api_server.py`, replace:

```python
@app.route('/api/cook', methods=['POST'])
def api_cook():
```

with:

```python
@app.route('/api/cook', methods=['POST'])
@require_token
def api_cook():
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_api_auth.py -q
```

Expected: all pass.

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add api_server.py tests/test_api_auth.py
git commit -m "fix: gate /api/cook behind the bearer token

It mutates inventory but, unlike /api/cooks, accepted unauthenticated
non-localhost callers. No behaviour change today — KITCHENOS_API_TOKEN is
unset, so require_token is a no-op.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: One cook toast that reports all four outcomes

**Files:**
- Modify: `templates/meal_planner.html` — add `renderCookToast`, replace both duplicated blocks (~1983-1990 and ~2505-2512)
- Test: `tests/e2e/test_cook_toast.py` (create)

**Interfaces:**
- Consumes: the `/api/cook` response shape from Task 6 — `{recipe, consumed, skipped_staples, not_tracked, use_recorded}`.
- Produces: `renderCookToast(r)` — a JS function taking the parsed response and calling the existing `showToast(message, kind)`.

There is no JS unit-test harness in this repo, so the function is covered by a Playwright test plus inspection. E2E tests live in `tests/e2e/`, carry `pytestmark = pytest.mark.e2e`, and are excluded from the default run by `pytest.ini`.

- [ ] **Step 1: Add the shared renderer**

In `templates/meal_planner.html`, immediately **above** the `async function markCooked(recipe, servings, card) {` declaration, add:

```javascript
        // One renderer for both cook call sites. Previously each had its own
        // copy that read only `consumed`, so a cook that decremented nothing —
        // 234 of 236 recipes — showed a green "nothing tracked to decrement"
        // while discarding the three lists that explained why.
        function renderCookToast(r) {
            const cap = (list, fmt) => {
                const shown = list.slice(0, 4).map(fmt);
                const extra = list.length - shown.length;
                return shown.join(', ') + (extra > 0 ? ` +${extra} more` : '');
            };

            const consumed = r.consumed || [];
            const used = r.use_recorded || [];
            const untracked = r.not_tracked || [];
            const staples = r.skipped_staples || [];

            if (!consumed.length && !used.length && !untracked.length && !staples.length) {
                showToast('Marked cooked — nothing tracked to decrement', 'success');
                return;
            }

            const parts = [];
            if (consumed.length) {
                parts.push(cap(consumed, c => c.depleted
                    ? `${c.item} — used up`
                    : `${c.item} ${c.after}${c.unit ? ' ' + c.unit : ''} left`));
            }
            if (used.length) {
                parts.push('used: ' + cap(used, u => u.item));
            }
            if (untracked.length) {
                parts.push('not tracked: ' + cap(untracked, n => n));
            }
            if (staples.length) {
                parts.push(`${staples.length} staple${staples.length === 1 ? '' : 's'} assumed`);
            }
            showToast(`Cooked — ${parts.join(' · ')}`, 'success');
        }
```

- [ ] **Step 2: Replace the first call site**

In `markCooked`, replace:

```javascript
                if (r.error) { showToast(r.error, 'error'); return; }
                const consumed = r.consumed || [];
                if (!consumed.length) {
                    showToast('Marked cooked — nothing tracked to decrement', 'success');
                } else {
                    const parts = consumed.slice(0, 4).map(c =>
                        c.depleted ? `${c.item} (used up)` : `${c.item}: ${c.after}${c.unit ? ' ' + c.unit : ''} left`);
                    showToast(`Cooked — ${parts.join(', ')}`, 'success');
                }
```

with:

```javascript
                if (r.error) { showToast(r.error, 'error'); return; }
                renderCookToast(r);
```

- [ ] **Step 3: Replace the second call site**

Replace:

```javascript
                if (r.error) {
                    showToast(r.error, 'error');
                } else {
                    const consumed = r.consumed || [];
                    if (!consumed.length) {
                        showToast('Marked cooked — nothing tracked to decrement', 'success');
                    } else {
                        const parts = consumed.slice(0, 4).map(c =>
                            c.depleted ? `${c.item} (used up)` : `${c.item}: ${c.after}${c.unit ? ' ' + c.unit : ''} left`);
                        showToast(`Cooked — ${parts.join(', ')}`, 'success');
                    }
                    loadUseItUp().catch(() => {});
                }
```

with:

```javascript
                if (r.error) {
                    showToast(r.error, 'error');
                } else {
                    renderCookToast(r);
                    loadUseItUp().catch(() => {});
                }
```

- [ ] **Step 4: Verify no duplicated toast logic remains**

```bash
grep -c "nothing tracked to decrement" templates/meal_planner.html
```

Expected: `1` (only inside `renderCookToast`).

```bash
grep -c "renderCookToast" templates/meal_planner.html
```

Expected: `3` (one definition, two call sites).

- [ ] **Step 5: Write the browser test**

Create `tests/e2e/test_cook_toast.py`. The fixtures are `live_server`, `page` and `page_errors` (see `tests/e2e/conftest.py`); build URLs with `live_server.url(path)`, never an f-string. `showToast` writes into `document.getElementById('toast')`, so the selector is `#toast`.

```python
"""The cook toast reports every outcome, not just decrements.

Drives renderCookToast directly rather than through a real cook: the point
under test is that a response with an empty `consumed` list still tells you
what happened, which is exactly the case the old duplicated code discarded.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_toast_names_used_and_untracked_items(live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [],
        use_recorded: [{item: 'Mirin', unit: 'ct'}],
        not_tracked: ['dragon fruit'],
        skipped_staples: ['flour', 'salt']
    })""")

    text = page.locator("#toast").inner_text()
    assert "used: Mirin" in text
    assert "not tracked: dragon fruit" in text
    assert "2 staples assumed" in text
    assert "nothing tracked to decrement" not in text
    assert page_errors == []


def test_toast_marks_a_depleted_row_as_used_up(live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [{item: 'lime', unit: 'ct', before: 2, after: 0, depleted: true}],
        use_recorded: [], not_tracked: [], skipped_staples: []
    })""")

    assert "lime — used up" in page.locator("#toast").inner_text()
    assert page_errors == []


def test_toast_says_nothing_tracked_only_when_all_lists_are_empty(
        live_server, page, page_errors):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.evaluate("""renderCookToast({
        consumed: [], use_recorded: [], not_tracked: [], skipped_staples: []
    })""")

    assert "nothing tracked to decrement" in page.locator("#toast").inner_text()
    assert page_errors == []
```

- [ ] **Step 6: Run the browser tests**

```bash
.venv/bin/python -m pytest tests/e2e/test_cook_toast.py -q -m e2e
```

Expected: PASS. If a test fails, fix `renderCookToast` — do not weaken the assertions or change the expected strings.

- [ ] **Step 7: Run the full suite plus e2e**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
.venv/bin/python -m pytest tests/e2e/ -q -m e2e 2>&1 | tail -3
```

Expected: both green.

- [ ] **Step 8: Restart the LaunchAgent — a template changed**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 2 && curl -s -o /dev/null -w "health %{http_code}\n" http://localhost:5001/health
```

Expected: `health 200`.

- [ ] **Step 9: Commit**

```bash
git add templates/meal_planner.html tests/e2e/test_cook_toast.py
git commit -m "fix: cook toast reports all four outcomes from one renderer

Both call sites had their own copy that read only \`consumed\`, so the 234
recipes that decrement nothing showed a green success message while the
not_tracked, use_recorded and skipped_staples lists were discarded.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Documentation and branch closure prep

**Files:**
- Modify: `docs/API.md` — the `/api/cook` row
- Modify: `CLAUDE.md` — add the container-gate invariant
- Modify: `BRANCH-STATUS.md` — tick the completed stages

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Update the `/api/cook` row in `docs/API.md`**

The file marks gated routes with a `🔒` after the path in the first column, e.g. `` | `/api/cooks` 🔒 | POST | ... ``. Replace line 64 in full:

```
| `/api/cook` | POST | Mark a recipe cooked: decrement its non-staple ingredients from inventory (true partial-package leftovers). Body `{recipe, servings?}` → consume summary. Optional/additive — inventory still self-cleans via expiry without it. Backs the `cook_recipe` MCP tool. |
```

with:

```
| `/api/cook` 🔒 | POST | Mark a recipe cooked. Body `{recipe, servings?}` → `{recipe, consumed: [{item, unit, before, after, depleted}], use_recorded: [{item, unit}], not_tracked: [...], skipped_staples: [...]}`. Every ingredient lands in exactly one bucket. A row at quantity exactly `1.0` is a container: it is use-stamped (`last_used`, `use_count`) rather than decremented, so a recipe calling for three bay leaves cannot delete the jar. Optional/additive — inventory still self-cleans via expiry without it. Backs the `cook_recipe` MCP tool. |
```

Do **not** change any route-count figure in the header: no route was added or removed.

- [ ] **Step 2: Add the invariant to `CLAUDE.md`**

Append to the "Invariants" bullet list, after the `dish_type` bullet:

```markdown
- **Inventory rows at quantity exactly `1.0` are containers, not counts.** 188 of 198 count-family rows sit at 1.0 because that is the ingest default meaning "one package", and 15 of 17 `oz` rows are a `1.0 oz` package. `lib/cook.py` therefore never decrements a qty-1.0 row on cook — it use-stamps it (`last_used`, `use_count`) instead. Removing that gate deletes a whole jar of bay leaves for a recipe calling for three, and a wrongly deleted row does not self-heal the way a missed depletion does (the expiry prune covers that). `lib/ingredient_aggregator.unit_compatibility` is the single authority on whether two units can be subtracted at all — `split_against_pantry` and `apply_decisions` must both delegate to it, because they once hand-wrote different rules and the shopping list credited limes the cook refused to spend.
```

- [ ] **Step 3: Verify the docs claims are still true**

```bash
grep -n "unit_compatibility" lib/pantry.py lib/ingredient_aggregator.py | head
grep -n "p_qty == 1.0" lib/cook.py
```

Expected: `unit_compatibility` defined in `ingredient_aggregator` and used twice in `pantry`; the gate present in `cook.py`.

- [ ] **Step 4: Tick the BRANCH-STATUS stages**

In `BRANCH-STATUS.md`, mark the Planning, Dev, Testing and Docs checklists complete where genuinely done, and set `**Current Stage:** review`. Leave anything not actually done unticked.

- [ ] **Step 5: Full suite, final**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
.venv/bin/python -m pytest tests/e2e/ -q -m e2e 2>&1 | tail -3
```

Expected: both green.

- [ ] **Step 6: Commit**

```bash
git add docs/API.md CLAUDE.md BRANCH-STATUS.md
git commit -m "docs: container-gate invariant and /api/cook contract

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verification against the real library (after all tasks)

This is a **read-only** check that the measured targets in the spec were hit. It must not write to the DB.

- [ ] **Step 1: Re-run the dry-run census**

```bash
.venv/bin/python - <<'PY'
import collections
from lib.cook import recipe_ingredients
from lib.pantry import find_match, load_pantry
from lib.ingredient_aggregator import parse_amount_to_float, unit_compatibility
from lib.use_it_up import _ingredient_phrase, _is_staple, _staple_phrases
from lib import paths

pantry = load_pantry()
staple_sets = _staple_phrases(None)
tally = collections.Counter()
reporting = 0
for p in sorted(paths.recipes_dir().glob("*.md")):
    ings = recipe_ingredients(p.stem) or []
    per = collections.Counter()
    for ing in ings:
        item = (ing.get("item") or "").strip()
        if not item:
            continue
        if _is_staple(_ingredient_phrase(item), staple_sets):
            per["staple"] += 1
            continue
        m = find_match(item, pantry)
        if m is None:
            per["not_tracked"] += 1
            continue
        p_qty = parse_amount_to_float(m.get("amount"))
        amt = parse_amount_to_float(ing.get("amount"))
        if (amt is None or p_qty is None or p_qty == 1.0
                or unit_compatibility(m.get("unit") or "", ing.get("unit") or "") is None):
            per["use_stamp"] += 1
        else:
            per["decrement"] += 1
    tally.update(per)
    if per["decrement"] or per["use_stamp"] or per["not_tracked"]:
        reporting += 1

for k, v in tally.most_common():
    print(f"  {k:12} {v}")
print(f"  recipes reporting something: {reporting}")
PY
```

Expected, per the spec: roughly **18 decrement, 455 use_stamp, 982 not_tracked, 1179 staple**, and about **199** recipes reporting something. Small drift is fine — the library changes as recipes are added. **A `decrement` count in the hundreds means the container gate is not working; stop and report.**

- [ ] **Step 2: Confirm nothing was written**

```bash
.venv/bin/python -c "
from lib.inventory import read_inventory
rows = read_inventory()
print('inventory rows:', len(rows))
print('rows with a use stamp:', sum(1 for r in rows if r.last_used))
"
```

Expected: 222 rows, and **0 with a use stamp** — the census above is read-only and no real cook has run yet.

---

## Notes for the implementer

- **Where test imports go.** Several tasks show new tests with their `import` lines attached so you can see what they need. Put the imports at the **top** of the target file alongside the existing ones, not mid-file — and merge rather than duplicate. Verified starting points: `tests/test_pantry.py` imports only `from lib import pantry as pantry_module`; `tests/test_ingredient_aggregator.py` only `aggregate_ingredients`; `tests/test_use_it_up.py` only `InventoryItem` and `use_it_up`. So none of the new imports collide, but `tests/test_cook.py` already imports `InventoryItem, add_items` and needs `read_inventory` merged into that same line.
- **Do not "fix" a failing shopping-list test by narrowing the predicate or restoring the substring matcher.** Tasks 2 and 4 deliberately change shopping-list behaviour. Report the failure with its assertion and let the controller decide.
- **Two steps deliberately break the code to prove a test is real** (Task 5 Step 8, Task 6 Step 5). Restore the code immediately after each; do not commit the broken state.
- The `_content_tokens` import in `lib/cook.py:27` is dead — Task 6 deletes it. Do not wire it up.
- `save_pantry` is imported into `lib/cook.py`'s namespace, which is why Task 6's no-op test monkeypatches `cook.save_pantry` rather than `pantry.save_pantry`.
