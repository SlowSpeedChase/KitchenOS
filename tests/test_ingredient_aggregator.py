from lib.ingredient_aggregator import aggregate_ingredients, GENERIC_COUNT, unit_compatibility


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

    def test_specific_count_against_generic_count_is_one_to_one(self):
        # Mutation test revealed: "or n in GENERIC_COUNT" was unprotected.
        # Pantry row with specific unit (clove) should match recipe with generic (ct).
        assert unit_compatibility("clove", "ct") == "one_to_one"

    def test_generic_specific_count_symmetry_is_order_independent(self):
        # Mutation test revealed: "or n in GENERIC_COUNT" was unprotected.
        # Result must not depend on argument order for generic/specific count pairs.
        assert unit_compatibility("clove", "whole") == "one_to_one"
        assert unit_compatibility("whole", "clove") == "one_to_one"
