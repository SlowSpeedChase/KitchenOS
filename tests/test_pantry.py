"""Tests for lib.pantry."""
import itertools

import pytest

from lib import pantry as pantry_module
from lib.ingredient_aggregator import (
    COUNT_UNITS,
    VOLUME_UNITS,
    WEIGHT_UNITS,
    parse_amount_to_float,
    unit_compatibility,
)
from lib.pantry import apply_decisions, split_against_pantry


def test_load_pantry_empty_inventory_returns_empty(tmp_vault, tmp_db):
    assert pantry_module.load_pantry() == []


def test_save_and_load_round_trip(tmp_vault, tmp_db):
    items = [
        {"item": "flour", "amount": "5", "unit": "cup"},
        {"item": "olive oil", "amount": "500", "unit": "ml"},
    ]
    pantry_module.save_pantry(items)
    loaded = sorted(pantry_module.load_pantry(), key=lambda e: e["item"])
    assert loaded == items


def test_save_pantry_drops_blank_items(tmp_vault, tmp_db):
    pantry_module.save_pantry(
        [{"item": "", "amount": "1", "unit": "x"}, {"item": "salt", "amount": "1", "unit": "tsp"}],
    )
    loaded = pantry_module.load_pantry()
    assert len(loaded) == 1
    assert loaded[0]["item"] == "salt"


def test_find_match_exact():
    pantry = [{"item": "Flour", "amount": "5", "unit": "cup"}]
    assert pantry_module.find_match("flour", pantry)["item"] == "Flour"


def test_find_match_substring():
    pantry = [{"item": "all-purpose flour", "amount": "5", "unit": "cup"}]
    match = pantry_module.find_match("flour", pantry)
    assert match["item"] == "all-purpose flour"


def test_find_match_returns_none():
    assert pantry_module.find_match("saffron", [{"item": "salt", "amount": "1", "unit": "tsp"}]) is None


def test_split_no_match_returns_full_to_buy():
    result = pantry_module.split_against_pantry("saffron", "1", "tsp", [])
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "1", "unit": "tsp"}


def test_split_pantry_fully_covers_same_unit():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    result = pantry_module.split_against_pantry("flour", "1", "cup", pantry)
    assert result["from_pantry"] == {"amount": "1", "unit": "cup"}
    assert result["to_buy"] is None


def test_split_pantry_partial_cover_same_family():
    # pantry has 1 cup (= 48 tsp); recipe asks 100 tsp → buy 52 tsp
    pantry = [{"item": "sugar", "amount": "1", "unit": "cup"}]
    result = pantry_module.split_against_pantry("sugar", "100", "tsp", pantry)
    assert result["from_pantry"] == {"amount": "48", "unit": "tsp"}
    assert result["to_buy"] == {"amount": "52", "unit": "tsp"}
    assert result["warning"] is None


def test_split_pantry_unit_conversion_within_volume():
    # pantry has 500ml; recipe asks 1 cup (~236.6 ml).
    pantry = [{"item": "olive oil", "amount": "500", "unit": "ml"}]
    result = pantry_module.split_against_pantry("olive oil", "1", "cup", pantry)
    assert result["to_buy"] is None  # pantry covers
    assert result["from_pantry"] == {"amount": "1", "unit": "cup"}


def test_split_cross_family_warns_and_does_not_subtract():
    # Recipe in tsp (volume), pantry in oz (weight) → warn, no subtraction.
    pantry = [{"item": "honey", "amount": "8", "unit": "oz"}]
    result = pantry_module.split_against_pantry("honey", "2", "tsp", pantry)
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "2", "unit": "tsp"}
    assert "different units" in (result["warning"] or "")


def test_split_pantry_no_amount_assumed_full():
    pantry = [{"item": "salt", "amount": "", "unit": ""}]
    result = pantry_module.split_against_pantry("salt", "1", "tsp", pantry)
    assert result["to_buy"] is None


def test_split_recipe_no_amount_assumed_full():
    pantry = [{"item": "salt", "amount": "1", "unit": "lb"}]
    result = pantry_module.split_against_pantry("salt", "", "to taste", pantry)
    assert result["to_buy"] is None


def test_apply_decisions_subtracts_within_family():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    decisions = [{"item": "flour", "amount": "1", "unit": "cup"}]
    updated = pantry_module.apply_decisions(decisions, pantry)
    assert updated[0]["amount"] == "4"


def test_apply_decisions_removes_when_depleted():
    pantry = [{"item": "flour", "amount": "1", "unit": "cup"}]
    decisions = [{"item": "flour", "amount": "1", "unit": "cup"}]
    updated = pantry_module.apply_decisions(decisions, pantry)
    assert updated == []


def test_apply_decisions_does_not_mutate_input():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    pantry_copy = [dict(e) for e in pantry]
    pantry_module.apply_decisions([{"item": "flour", "amount": "1", "unit": "cup"}], pantry)
    assert pantry == pantry_copy


def test_apply_decisions_skips_unmatched_item():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    updated = pantry_module.apply_decisions(
        [{"item": "saffron", "amount": "1", "unit": "tsp"}], pantry
    )
    assert updated == pantry


def test_split_count_whole_wildcard_pantry_covers():
    # Pantry "6 cloves garlic" should cover recipe "5 whole garlic" 1:1.
    pantry = [{"item": "garlic", "amount": "6", "unit": "cloves"}]
    result = pantry_module.split_against_pantry("garlic", "5", "whole", pantry)
    assert result["from_pantry"] == {"amount": "5", "unit": "whole"}
    assert result["to_buy"] is None
    assert result["warning"] is None


def test_split_count_whole_wildcard_partial_cover():
    # Pantry "6 cloves" partially covers recipe "10 whole" → buy the rest.
    pantry = [{"item": "garlic", "amount": "6", "unit": "cloves"}]
    result = pantry_module.split_against_pantry("garlic", "10", "whole", pantry)
    assert result["from_pantry"] == {"amount": "6", "unit": "cloves"}
    assert result["to_buy"] == {"amount": "4", "unit": "cloves"}
    assert result["warning"] is None


def test_split_count_ct_alias_classifies_as_count():
    # "ct" is now in COUNT_UNITS, so pantry "5 ct" + recipe "5 whole" combine.
    pantry = [{"item": "lemons", "amount": "5", "unit": "ct"}]
    result = pantry_module.split_against_pantry("lemons", "5", "whole", pantry)
    assert result["from_pantry"] == {"amount": "5", "unit": "whole"}
    assert result["to_buy"] is None
    assert result["warning"] is None


def test_split_count_distinct_units_still_warns():
    # Slices vs cloves are both count but neither is "whole" — must still warn.
    pantry = [{"item": "bread", "amount": "1", "unit": "loaf"}]
    result = pantry_module.split_against_pantry("bread", "2", "slices", pantry)
    # "loaf" is not in COUNT_UNITS → cross-family warning fires upstream.
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "2", "unit": "slices"}
    assert result["warning"]


def test_load_pantry_reads_inventory_db(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items
    from lib.pantry import load_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Butter", quantity=1, unit="lb", location="fridge"),
        InventoryItem(name="Butter", quantity=0.5, unit="lb", location="freezer"),
    ])
    pantry = load_pantry()
    by_item = {e["item"]: e for e in pantry}
    assert by_item["Flour"]["amount"] == "5"
    assert by_item["Flour"]["unit"] == "lb"
    assert by_item["Butter"]["amount"] == "1.5"  # summed across locations


def test_save_pantry_decrements_and_removes(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, read_inventory
    from lib.pantry import load_pantry, save_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Sugar", quantity=2, unit="lb"),
    ])
    # simulate apply_decisions output: flour reduced, sugar used up
    save_pantry([{"item": "Flour", "amount": "3", "unit": "lb"}])
    items = {it.name: it for it in read_inventory()}
    assert items["Flour"].quantity == 3.0
    assert "Sugar" not in items
    assert load_pantry() == [{"item": "Flour", "amount": "3", "unit": "lb"}]


def test_save_pantry_inserts_new_items(tmp_vault, tmp_db):
    from lib.inventory import read_inventory
    from lib.pantry import save_pantry
    save_pantry([{"item": "Olive oil", "amount": "16", "unit": "oz"}])
    items = read_inventory()
    assert items[0].name == "Olive oil"
    assert items[0].location == "pantry"
    assert items[0].source == "manual"


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


_ALL_PARITY_PAIRS = list(itertools.product(PARITY_UNITS, PARITY_UNITS))

# Independent reference for "should p_unit (pantry) and n_unit (recipe) be
# treated as convertible" — deliberately reimplemented from the same
# underlying tables rather than built by calling unit_compatibility()
# itself. split_against_pantry and apply_decisions both delegate to that one
# function, so if its *logic* ever regresses (e.g. the count branch stops
# recognizing "ct"/"whole" as compatible), both callers would agree to
# refuse it — and a pair list filtered through the same broken function
# would just quietly drop that pair instead of failing a test. Mirroring the
# classification here keeps the pair list, and therefore the assertion
# below, independent of whether unit_compatibility is currently correct.
_GENERIC = {"", "whole", "ct", "count", "ea", "each", "piece", "pieces"}


def _family(unit: str) -> str:
    if unit in VOLUME_UNITS:
        return "volume"
    if unit in WEIGHT_UNITS:
        return "weight"
    if unit in COUNT_UNITS or unit == "":
        return "count"
    return "other"


def _should_be_compatible(p_unit: str, n_unit: str) -> bool:
    p_family, n_family = _family(p_unit), _family(n_unit)
    if p_family in ("volume", "weight") and p_family == n_family:
        return True
    if p_family == "count" and n_family == "count":
        return p_unit == n_unit or p_unit in _GENERIC or n_unit in _GENERIC
    return False


COMPATIBLE_PAIRS = [
    (p, n) for p, n in _ALL_PARITY_PAIRS if _should_be_compatible(p, n)
]

INCOMPATIBLE_PAIRS = [
    (p, n) for p, n in _ALL_PARITY_PAIRS if not _should_be_compatible(p, n)
]

# Units the aggregator actually classifies into a family, as opposed to the
# unrecognized/garbage units in PARITY_UNITS ("", "a sprinkle", "loaf").
RECOGNIZED_UNITS = COUNT_UNITS | set(VOLUME_UNITS) | set(WEIGHT_UNITS)

RECOGNIZED_INCOMPATIBLE_PAIRS = [
    (p, n) for p, n in INCOMPATIBLE_PAIRS
    if p in RECOGNIZED_UNITS and n in RECOGNIZED_UNITS
]


@pytest.mark.parametrize("p_unit,n_unit", COMPATIBLE_PAIRS)
def test_compatible_units_are_both_credited_and_spendable(p_unit, n_unit):
    """Whatever unit_compatibility says is convertible must be both
    creditable on the shopping list and spendable on the cook path.

    This is the invariant the reported lime bug violated: the shopping list
    credited "3 ct" against a "1 whole" recipe line while the cook path
    refused to spend it, because the two paths hand-wrote different rules.
    """
    # Count pairs ("one_to_one") subtract exact integers, so "1" from a
    # pantry of "10" is always visible. Volume/weight pairs ("convert") go
    # through a base-unit conversion first; a decrement that's tiny in the
    # pantry's own unit (e.g. subtracting a few grams from a "10 lb" row)
    # can round back to "10" in format_amount's 2-decimal display. "10" is
    # large enough to stay visible even for the widest mismatch in
    # PARITY_UNITS (lb vs g, ~453:1).
    amount = "1" if _family(p_unit) == "count" else "10"

    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    credited = split_against_pantry(
        "thing", amount, n_unit, pantry)["from_pantry"] is not None

    updated = apply_decisions(
        [{"item": "thing", "amount": amount, "unit": n_unit}], pantry)
    if not updated:
        spent = True                      # row removed entirely
    else:
        spent = parse_amount_to_float(updated[0]["amount"]) < 10.0 - 0.001

    assert credited and spent, (
        f"pantry {p_unit!r} vs recipe {n_unit!r}: "
        f"credited={credited} spent={spent}")


@pytest.mark.parametrize("p_unit,n_unit", INCOMPATIBLE_PAIRS)
def test_incompatible_units_are_never_spent(p_unit, n_unit):
    """apply_decisions must never subtract across units it cannot convert.

    This is the dangerous direction: silently subtracting, say, "2 g" from a
    "10 lb" row would corrupt inventory with an invented conversion. The old
    parity test only ever checked `credited == spent`, so a caller that
    started spending across incompatible units without also crediting them
    would have slipped through unnoticed.
    """
    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    updated = apply_decisions(
        [{"item": "thing", "amount": "2", "unit": n_unit}], pantry)
    assert updated == pantry


@pytest.mark.parametrize("p_unit,n_unit", RECOGNIZED_INCOMPATIBLE_PAIRS)
def test_recognised_but_incompatible_units_are_not_credited(p_unit, n_unit):
    """Among units the aggregator actually recognizes (count/volume/weight),
    an incompatible pair must not be credited from the pantry either.

    Unrecognized units ("", "a sprinkle", "loaf") are deliberately excluded
    from this pair list: split_against_pantry crediting an unrecognized
    recipe unit against a recognized pantry unit ("you have flour, don't buy
    more") is an intentional convenience, not a bug, even though
    apply_decisions correctly refuses to spend it — that asymmetry is
    exercised by test_incompatible_units_are_never_spent, not this test.
    """
    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    result = split_against_pantry("thing", "1", n_unit, pantry)
    assert result["from_pantry"] is None


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
