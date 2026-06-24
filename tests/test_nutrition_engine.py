"""Tests for lib/nutrition_engine.py — the deterministic gram-based engine."""

from unittest.mock import patch

import pytest

from lib.food_db import FoodRecord
from lib.nutrition import NutritionData
from lib.nutrition_engine import calculate_recipe_nutrition


def _rec(desc, cal=0, pro=0, carb=0, fat=0, source="usda", sid="1", portions=None):
    return FoodRecord(
        source=source, source_id=sid, description=desc,
        per_100g=NutritionData(cal, pro, carb, fat),
        portions=portions or [],
    )


def _engine(ingredients, servings, **kw):
    # use_cache/use_llm off by default for deterministic, network-free tests.
    kw.setdefault("use_cache", False)
    kw.setdefault("use_llm", False)
    return calculate_recipe_nutrition(ingredients, servings, **kw)


class TestScaling:
    def test_mass_scales_per_100g(self):
        # 200 g chicken breast @ 165 kcal/100g → 330 kcal.
        with patch("lib.food_db.usda_search", return_value=[_rec("Chicken breast, raw", 165, 31, 0, 3.6)]), \
             patch("lib.food_db.usda_food_detail", return_value=None):
            res = _engine([{"amount": "200", "unit": "g", "item": "chicken breast"}], 1)
        assert res.per_serving.calories == 330
        assert res.per_serving.protein == 62
        assert res.source == "usda"

    def test_volume_uses_density(self):
        # 1 cup olive oil → 236.588 ml * 0.92 g/ml = 217.66 g; oil 884 kcal/100g.
        with patch("lib.food_db.usda_search", return_value=[_rec("Oil, olive", 884, 0, 0, 100)]), \
             patch("lib.food_db.usda_food_detail", return_value=None):
            res = _engine([{"amount": "1", "unit": "cup", "item": "olive oil"}], 1)
        assert res.per_serving.calories == pytest.approx(round(217.66 * 8.84), abs=2)


class TestFloatAccumulation:
    def test_no_per_ingredient_truncation(self):
        # Two lines each contribute 0.6 kcal (60 g * 1 kcal/100g). Old int-per-line
        # math truncated each to 0 → total 0. Float accumulation → 1.2 → rounds to 1.
        rec = _rec("Tiny", 1, 0, 0, 0)
        with patch("lib.food_db.usda_search", return_value=[rec]), \
             patch("lib.food_db.usda_food_detail", return_value=None):
            res = _engine([
                {"amount": "60", "unit": "g", "item": "tiny a"},
                {"amount": "60", "unit": "g", "item": "tiny b"},
            ], 1)
        assert res.total.calories == 1


class TestServings:
    def test_divides_by_servings(self):
        with patch("lib.food_db.usda_search", return_value=[_rec("Rice", 100, 0, 0, 0)]), \
             patch("lib.food_db.usda_food_detail", return_value=None):
            res = _engine([{"amount": "800", "unit": "g", "item": "rice"}], 4)
        assert res.total.calories == 800
        assert res.per_serving.calories == 200
        assert not res.servings_inferred

    def test_null_servings_flags_review(self):
        with patch("lib.food_db.usda_search", return_value=[_rec("Rice", 100, 0, 0, 0)]), \
             patch("lib.food_db.usda_food_detail", return_value=None):
            res = _engine([{"amount": "800", "unit": "g", "item": "rice"}], None)
        assert res.servings_used == 1
        assert res.servings_inferred
        assert res.needs_review
        assert res.per_serving.calories == 800  # whole recipe, but flagged


class TestSourcesAndResolution:
    def test_mixed_source_label(self):
        def fake_usda(q):
            return [_rec("Chicken", 165, 31, 0, 3.6)] if "chicken" in q else []
        def fake_off(q, *a, **k):
            return [_rec("Brand Bar", 350, 30, 40, 10, source="off", sid="x")] if "bar" in q else []
        with patch("lib.food_db.usda_search", side_effect=fake_usda), \
             patch("lib.food_db.usda_food_detail", return_value=None), \
             patch("lib.food_db.off_search", side_effect=fake_off):
            res = _engine([
                {"amount": "100", "unit": "g", "item": "chicken"},
                {"amount": "100", "unit": "g", "item": "protein bar"},
            ], 1)
        assert res.source == "mixed"

    def test_returns_none_when_nothing_resolves(self):
        with patch("lib.food_db.usda_search", return_value=[]), \
             patch("lib.food_db.off_search", return_value=[]):
            res = _engine([{"amount": "1", "unit": "cup", "item": "unobtainium"}], 1)
        assert res is None

    def test_partial_resolution_flags_review(self):
        # One resolves, one doesn't → result returned but needs_review.
        def fake_usda(q):
            return [_rec("Rice", 100, 0, 0, 0)] if "rice" in q else []
        with patch("lib.food_db.usda_search", side_effect=fake_usda), \
             patch("lib.food_db.usda_food_detail", return_value=None), \
             patch("lib.food_db.off_search", return_value=[]):
            res = _engine([
                {"amount": "100", "unit": "g", "item": "rice"},
                {"amount": "1", "unit": "cup", "item": "unobtainium"},
            ], 1)
        assert res is not None
        assert res.total.calories == 100
        assert res.needs_review


class TestSanityCap:
    def test_implausible_grams_skipped(self):
        # A malformed ingredient yields an absurd LLM portion → must not pollute.
        # A second, valid ingredient keeps the recipe resolvable.
        def fake_usda(q):
            if "oil" in q:
                return [_rec("Oil", 884, 0, 0, 100)]
            return [_rec("Rice", 100, 0, 0, 0)]
        with patch("lib.food_db.usda_search", side_effect=fake_usda), \
             patch("lib.food_db.usda_food_detail", return_value=None), \
             patch("lib.food_resolver.estimate_portion_grams_llm", return_value=(5000.0, 0.6)):
            res = calculate_recipe_nutrition(
                [{"amount": "100", "unit": "whole", "item": "weird oil"},
                 {"amount": "100", "unit": "g", "item": "rice"}], 1,
                use_cache=False, portion_provider="ollama",
            )
        # oil: 100 * 5000g = 500000g > cap → skipped, contributes 0, flagged.
        # rice: 100 g → 100 kcal. Recipe total reflects only the rice.
        assert res.total.calories == 100
        oil_line = next(li for li in res.line_items if "oil" in li.item)
        assert oil_line.needs_review
        assert "implausible" in oil_line.note
        assert res.needs_review


class TestLlmPortionFallback:
    def test_llm_estimates_grams_for_count_unit(self):
        # 'whole' count unit, item has no piece weight in config → LLM portion.
        with patch("lib.food_db.usda_search", return_value=[_rec("Dragonfruit", 60, 1, 13, 0)]), \
             patch("lib.food_db.usda_food_detail", return_value=None), \
             patch("lib.food_resolver.estimate_portion_grams_llm", return_value=(200.0, 0.6)):
            res = calculate_recipe_nutrition(
                [{"amount": "1", "unit": "whole", "item": "dragonfruit"}], 1,
                use_cache=False, portion_provider="ollama",
            )
        # 200 g * 60 kcal/100g = 120 kcal
        assert res.total.calories == 120
        assert res.line_items[0].grams_method == "llm"
        assert res.needs_review  # llm portion → flagged
