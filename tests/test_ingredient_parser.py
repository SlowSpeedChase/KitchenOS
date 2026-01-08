"""Tests for ingredient parser module"""

import pytest
from lib.ingredient_parser import normalize_unit


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
