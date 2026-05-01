"""Tests for lib.pantry."""
import json
from pathlib import Path


from lib import pantry as pantry_module


def test_load_pantry_missing_file_returns_empty(tmp_path: Path):
    assert pantry_module.load_pantry(tmp_path / "missing.json") == []


def test_save_and_load_round_trip(tmp_path: Path):
    items = [
        {"item": "flour", "amount": "5", "unit": "cup"},
        {"item": "olive oil", "amount": "500", "unit": "ml"},
    ]
    path = tmp_path / "pantry.json"
    pantry_module.save_pantry(items, path)
    assert json.loads(path.read_text()) == items
    assert pantry_module.load_pantry(path) == items


def test_save_pantry_drops_blank_items(tmp_path: Path):
    path = tmp_path / "pantry.json"
    pantry_module.save_pantry(
        [{"item": "", "amount": "1", "unit": "x"}, {"item": "salt", "amount": "1", "unit": "tsp"}],
        path,
    )
    loaded = pantry_module.load_pantry(path)
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
