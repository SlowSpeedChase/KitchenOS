from lib.ingredient_aggregator import aggregate_ingredients


def test_descriptor_variants_consolidate_to_one_line():
    ings = [
        {"amount": "0.25", "unit": "cup", "item": "red onion, thinly sliced"},
        {"amount": "0.5", "unit": "small", "item": "small red onion, (very thinly sliced)"},
        {"amount": "2", "unit": "whole", "item": "2 whole red onion"},
    ]
    out = aggregate_ingredients(ings)
    names = [o["item"] for o in out]
    assert names == ["red onion"]


def test_mayo_alias_merges_before_summing():
    ings = [
        {"amount": "1.29", "unit": "cup", "item": "mayo"},
        {"amount": "0.25", "unit": "cup", "item": "mayonnaise"},
    ]
    out = aggregate_ingredients(ings)
    assert len(out) == 1
    assert out[0]["item"] == "mayonnaise"
    assert out[0]["unit"] == "cup"
