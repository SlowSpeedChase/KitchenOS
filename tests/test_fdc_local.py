"""Tests for lib/fdc_local.py — local FDC store (schema + name normalization)."""

from lib.fdc_local import normalize_food_name, unit_from_portion


class TestNormalizeFoodName:
    # Order-independent (bag-of-words, sorted) so "heavy cream" == "Cream, heavy".
    def test_lowercases_strips_punctuation_and_numbers(self):
        assert normalize_food_name("Cottage Cheese, lowfat, 2% milkfat") == \
            "cheese cottage lowfat milkfat"

    def test_drops_filler_stopwords(self):
        # "raw", "granulated" carry no matching signal.
        assert normalize_food_name("Apples, raw, with skin") == "apple skin with"
        assert normalize_food_name("Granulated white sugar") == "sugar white"

    def test_singularizes_tokens(self):
        assert normalize_food_name("Almonds") == "almond"
        assert normalize_food_name("Blueberries") == "blueberry"

    def test_same_normalizer_matches_recipe_item_to_fdc_desc(self):
        # The whole point: a recipe item and the FDC description normalize equal.
        assert normalize_food_name("heavy cream") == normalize_food_name("Cream, heavy")
        assert normalize_food_name("heavy cream") == "cream heavy"

    def test_collapses_whitespace_and_empty(self):
        assert normalize_food_name("  Butter,  salted  ") == "butter salted"
        assert normalize_food_name("") == ""
        assert normalize_food_name(None) == ""

    def test_does_not_over_singularize_short_or_double_s(self):
        assert normalize_food_name("gas") == "gas"
        assert normalize_food_name("molasses") == "molasses"


class TestUnitFromPortion:
    def test_maps_known_measure_unit(self):
        assert unit_from_portion("cup", "") == "cup"
        assert unit_from_portion("tablespoon", "") == "tbsp"
        assert unit_from_portion("teaspoon", "") == "tsp"

    def test_undetermined_falls_back_to_modifier(self):
        # measure_unit.name is often the literal "undetermined"; the real unit is
        # in the modifier text.
        assert unit_from_portion("undetermined", "1 cup, shredded") == "cup"
        assert unit_from_portion("undetermined", "1 medium") is None  # no volume unit

    def test_none_when_unparseable(self):
        assert unit_from_portion("undetermined", "1 serving") is None
