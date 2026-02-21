"""Tests for seasonality module"""
import json
from unittest.mock import patch, MagicMock
from lib.seasonality import (
    load_seasonal_config,
    match_ingredients_to_seasonal,
    calculate_season_score,
    get_peak_months,
)


class TestLoadSeasonalConfig:
    def test_loads_config_file(self):
        config = load_seasonal_config()
        assert "ingredients" in config
        assert "region" in config
        assert config["region"] == "texas"

    def test_config_has_expected_produce(self):
        config = load_seasonal_config()
        assert "tomato" in config["ingredients"]
        assert "spinach" in config["ingredients"]

    def test_config_entries_have_peak_months(self):
        config = load_seasonal_config()
        for name, data in config["ingredients"].items():
            assert "peak_months" in data, f"{name} missing peak_months"
            assert isinstance(data["peak_months"], list)
            assert all(1 <= m <= 12 for m in data["peak_months"])


class TestMatchIngredientsToSeasonal:
    """Tests for LLM-based fuzzy matching of ingredients to seasonal produce"""

    @patch("lib.seasonality.requests.post")
    def test_matches_exact_ingredient(self, mock_post):
        """Exact match: 'tomato' -> 'tomato'"""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": json.dumps([
                {"ingredient": "tomato", "matches": "tomato"}
            ])}
        )
        ingredients = [{"amount": "2", "unit": "whole", "item": "tomato"}]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["tomato"]

    @patch("lib.seasonality.requests.post")
    def test_matches_variant_name(self, mock_post):
        """Fuzzy match: 'butternut squash' -> 'butternut squash'"""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": json.dumps([
                {"ingredient": "butternut squash", "matches": "butternut squash"}
            ])}
        )
        ingredients = [{"amount": "1", "unit": "whole", "item": "butternut squash"}]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["butternut squash"]

    @patch("lib.seasonality.requests.post")
    def test_skips_pantry_staples(self, mock_post):
        """Pantry items like oil and flour should not match"""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": json.dumps([])}
        )
        ingredients = [
            {"amount": "2", "unit": "tbsp", "item": "olive oil"},
            {"amount": "1", "unit": "cup", "item": "flour"},
        ]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == []

    @patch("lib.seasonality.requests.post")
    def test_deduplicates_matches(self, mock_post):
        """Multiple ingredients matching same seasonal item should deduplicate"""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": json.dumps([
                {"ingredient": "diced tomato", "matches": "tomato"},
                {"ingredient": "cherry tomato", "matches": "tomato"}
            ])}
        )
        ingredients = [
            {"amount": "1", "unit": "cup", "item": "diced tomato"},
            {"amount": "0.5", "unit": "cup", "item": "cherry tomato"},
        ]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["tomato"]

    @patch("lib.seasonality.requests.post")
    def test_ollama_failure_returns_empty(self, mock_post):
        """On Ollama failure, return empty list (graceful degradation)"""
        mock_post.side_effect = Exception("Connection refused")
        ingredients = [{"amount": "1", "unit": "whole", "item": "tomato"}]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == []


class TestCalculateSeasonScore:
    def test_all_in_season(self):
        """All matched ingredients in season -> high score"""
        seasonal_ingredients = ["tomato", "basil"]
        score = calculate_season_score(seasonal_ingredients, month=5)
        assert score == 2

    def test_none_in_season(self):
        """No matched ingredients in season -> score 0"""
        seasonal_ingredients = ["tomato", "basil"]
        score = calculate_season_score(seasonal_ingredients, month=12)
        # tomato not in season in Dec, basil not in season in Dec
        assert score == 0

    def test_partial_season(self):
        """Some ingredients in season"""
        seasonal_ingredients = ["spinach", "corn"]
        # spinach peaks [1,2,3,4,10,11,12], corn peaks [5,6,7,8,9]
        score = calculate_season_score(seasonal_ingredients, month=3)
        assert score == 1  # only spinach

    def test_empty_ingredients(self):
        """No seasonal ingredients -> score 0"""
        score = calculate_season_score([], month=6)
        assert score == 0

    def test_no_month_uses_current(self):
        """When month is None, uses current month"""
        score = calculate_season_score(["rosemary"], month=None)
        # rosemary is year-round in Texas
        assert score == 1


class TestGetPeakMonths:
    def test_returns_union_of_months(self):
        """peak_months is the union of all matched ingredients' peak months"""
        months = get_peak_months(["tomato", "corn"])
        # tomato: [4,5,6,10,11], corn: [5,6,7,8,9]
        assert sorted(months) == [4, 5, 6, 7, 8, 9, 10, 11]

    def test_empty_ingredients(self):
        months = get_peak_months([])
        assert months == []

    def test_unknown_ingredient_skipped(self):
        """Ingredients not in config are safely skipped"""
        months = get_peak_months(["tomato", "unicorn-fruit"])
        # Only tomato months
        assert sorted(months) == [4, 5, 6, 10, 11]
