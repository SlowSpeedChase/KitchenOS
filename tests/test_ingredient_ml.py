"""Tests for the opt-in ML ingredient parser and its dispatcher."""

import pytest

from lib.ingredient_parser import parse_ingredient, parse_ingredient_best, ml_enabled


class TestMlEnabledFlag:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("KITCHENOS_ML_INGREDIENTS", raising=False)
        assert ml_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "YES", "on"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("KITCHENOS_ML_INGREDIENTS", val)
        assert ml_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "", "no"])
    def test_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("KITCHENOS_ML_INGREDIENTS", val)
        assert ml_enabled() is False


class TestDispatcherDisabled:
    def test_matches_rule_based_when_off(self, monkeypatch):
        monkeypatch.delenv("KITCHENOS_ML_INGREDIENTS", raising=False)
        text = "2 cups all-purpose flour"
        assert parse_ingredient_best(text) == parse_ingredient(text)


# --- ML-dependent tests (skipped if the optional package isn't installed) ---
pytest.importorskip("ingredient_parser")


class TestMlParser:
    def test_basic_line(self):
        from lib.ingredient_ml import parse_ingredient_ml
        r = parse_ingredient_ml("2 cups all-purpose flour")
        assert r["amount"] == "2"
        assert r["unit"] == "cup"
        assert "flour" in r["item"]
        assert r["confidence"] >= 0.8

    def test_fraction_to_decimal(self):
        from lib.ingredient_ml import parse_ingredient_ml
        assert parse_ingredient_ml("1/2 cup sugar")["amount"] == "0.5"

    def test_preparation_extracted(self):
        from lib.ingredient_ml import parse_ingredient_ml
        r = parse_ingredient_ml("1 onion, finely chopped")
        assert r["preparation"] and "chop" in r["preparation"].lower()

    def test_is_available(self):
        from lib.ingredient_ml import is_available
        assert is_available() is True


class TestDispatcherEnabled:
    def test_returns_dropin_shape(self, monkeypatch):
        monkeypatch.setenv("KITCHENOS_ML_INGREDIENTS", "1")
        r = parse_ingredient_best("2 cups all-purpose flour")
        # Same keys as the rule-based parser — a true drop-in.
        assert set(r.keys()) == {"amount", "unit", "item"}
        assert "flour" in r["item"]
