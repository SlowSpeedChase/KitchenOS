"""Tests for ingredient parser module"""

import pytest
from lib.ingredient_parser import normalize_unit, is_informal_measurement, INFORMAL_UNITS, parse_amount


class TestNormalizeUnit:
    """Tests for unit normalization"""

    def test_tablespoon_variants(self):
        """Normalizes tablespoon variants to tbsp"""
        assert normalize_unit("tablespoon") == "tbsp"
        assert normalize_unit("tablespoons") == "tbsp"
        assert normalize_unit("tbsp") == "tbsp"
        assert normalize_unit("tbs") == "tbsp"

    def test_teaspoon_variants(self):
        """Normalizes teaspoon variants to tsp"""
        assert normalize_unit("teaspoon") == "tsp"
        assert normalize_unit("teaspoons") == "tsp"
        assert normalize_unit("tsp") == "tsp"

    def test_weight_units(self):
        """Normalizes weight units"""
        assert normalize_unit("pound") == "lb"
        assert normalize_unit("pounds") == "lb"
        assert normalize_unit("lb") == "lb"
        assert normalize_unit("lbs") == "lb"
        assert normalize_unit("ounce") == "oz"
        assert normalize_unit("ounces") == "oz"
        assert normalize_unit("gram") == "g"
        assert normalize_unit("grams") == "g"

    def test_volume_units(self):
        """Normalizes volume units"""
        assert normalize_unit("cup") == "cup"
        assert normalize_unit("cups") == "cup"
        assert normalize_unit("milliliter") == "ml"
        assert normalize_unit("milliliters") == "ml"

    def test_count_units(self):
        """Normalizes count units"""
        assert normalize_unit("clove") == "clove"
        assert normalize_unit("cloves") == "clove"
        assert normalize_unit("head") == "head"
        assert normalize_unit("bunch") == "bunch"
        assert normalize_unit("sprig") == "sprig"

    def test_unknown_unit_passthrough(self):
        """Unknown units pass through unchanged"""
        assert normalize_unit("widget") == "widget"
        assert normalize_unit("") == ""

    def test_case_insensitive(self):
        """Handles mixed case"""
        assert normalize_unit("Tablespoon") == "tbsp"
        assert normalize_unit("CUP") == "cup"

    def test_single_letter_abbreviations(self):
        """Handles T/t convention"""
        assert normalize_unit("T") == "tbsp"
        assert normalize_unit("t") == "tsp"


class TestInformalMeasurements:
    """Tests for informal measurement handling"""

    def test_pinch_variants(self):
        """Detects pinch-type measurements"""
        assert is_informal_measurement("a pinch") is True
        assert is_informal_measurement("a smidge") is True
        assert is_informal_measurement("a dash") is True
        assert is_informal_measurement("a sprinkle") is True

    def test_handful_variants(self):
        """Detects handful-type measurements"""
        assert is_informal_measurement("a handful") is True
        assert is_informal_measurement("a splash") is True

    def test_taste_variants(self):
        """Detects taste-type measurements"""
        assert is_informal_measurement("to taste") is True
        assert is_informal_measurement("as needed") is True

    def test_vague_quantities(self):
        """Detects vague quantities"""
        assert is_informal_measurement("some") is True
        assert is_informal_measurement("a few") is True
        assert is_informal_measurement("a couple") is True

    def test_case_insensitive(self):
        """Handles mixed case"""
        assert is_informal_measurement("A Pinch") is True
        assert is_informal_measurement("TO TASTE") is True

    def test_rejects_standard_units(self):
        """Rejects standard measurement units"""
        assert is_informal_measurement("cup") is False
        assert is_informal_measurement("tablespoon") is False
        assert is_informal_measurement("1/2 cup") is False

    def test_informal_units_list(self):
        """INFORMAL_UNITS contains expected entries"""
        assert "a pinch" in INFORMAL_UNITS
        assert "to taste" in INFORMAL_UNITS
        assert "a sprinkle" in INFORMAL_UNITS


class TestParseAmount:
    """Tests for amount parsing"""

    def test_whole_numbers(self):
        """Parses whole numbers"""
        assert parse_amount("1") == "1"
        assert parse_amount("12") == "12"

    def test_fractions(self):
        """Parses fractions as decimals"""
        assert parse_amount("1/2") == "0.5"
        assert parse_amount("1/4") == "0.25"
        assert parse_amount("3/4") == "0.75"

    def test_mixed_fractions(self):
        """Parses mixed fractions"""
        assert parse_amount("1 1/2") == "1.5"
        assert parse_amount("2 1/4") == "2.25"

    def test_decimals_passthrough(self):
        """Decimal strings pass through"""
        assert parse_amount("0.5") == "0.5"
        assert parse_amount("1.25") == "1.25"

    def test_ranges(self):
        """Ranges preserved as strings"""
        assert parse_amount("3-4") == "3-4"
        assert parse_amount("2-3") == "2-3"

    def test_word_numbers(self):
        """Converts word numbers to digits"""
        assert parse_amount("one") == "1"
        assert parse_amount("two") == "2"
        assert parse_amount("three") == "3"
        assert parse_amount("One") == "1"

    def test_empty_returns_one(self):
        """Empty/None returns '1' as default"""
        assert parse_amount("") == "1"
        assert parse_amount(None) == "1"
