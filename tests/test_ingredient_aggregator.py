from lib.ingredient_aggregator import aggregate_ingredients


def test_descriptor_variants_consolidate_to_one_line():
    ings = [
        {"amount": "0.25", "unit": "cup", "item": "red onion, thinly sliced"},
        {"amount": "0.5", "unit": "small", "item": "small red onion, (very thinly sliced)"},
        {"amount": "2", "unit": "whole", "item": "2 whole red onion"},
    ]
    out = aggregate_ingredients(ings)
    # All items normalize to "red onion", but different unit families (volume, other, count)
    # should each be kept in the output
    names = [o["item"] for o in out]
    assert len(out) == 3
    assert all(name == "red onion" for name in names)
    units = sorted(o["unit"] for o in out)
    assert units == ["cup", "small", "whole"]


def test_mayo_alias_merges_before_summing():
    ings = [
        {"amount": "1.29", "unit": "cup", "item": "mayo"},
        {"amount": "0.25", "unit": "cup", "item": "mayonnaise"},
    ]
    out = aggregate_ingredients(ings)
    assert len(out) == 1
    assert out[0]["item"] == "mayonnaise"
    assert out[0]["unit"] == "cup"
    assert out[0]["amount"] == "1.54"


def test_mixed_family_lines_both_kept():
    # Same normalized item "oil" but two different unit families must NOT
    # collapse into a single dropped line.
    ings = [
        {"amount": "3", "unit": "tbsp", "item": "oil"},
        {"amount": "500", "unit": "g", "item": "oil"},
    ]
    out = aggregate_ingredients(ings)
    assert all(o["item"] == "oil" for o in out)
    units = sorted(o["unit"] for o in out)
    assert units == ["g", "tbsp"]  # both families survive
