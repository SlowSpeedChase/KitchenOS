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
    """Tests for match_ingredients_to_seasonal (keyword first, Ollama fallback)"""

    def test_matches_exact_ingredient_via_keyword(self):
        """Exact match via keyword: 'tomato' -> 'tomato' (no Ollama needed)"""
        ingredients = [{"amount": "2", "unit": "whole", "item": "tomato"}]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["tomato"]

    def test_matches_variant_name_via_keyword(self):
        """Keyword match: 'butternut squash' -> 'butternut squash' (no Ollama needed)"""
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

    def test_deduplicates_matches(self):
        """Multiple ingredients matching same seasonal item should deduplicate"""
        ingredients = [
            {"amount": "1", "unit": "cup", "item": "diced tomato"},
            {"amount": "0.5", "unit": "cup", "item": "cherry tomato"},
        ]
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["tomato"]

    def test_keyword_match_avoids_ollama(self):
        """When keyword matching succeeds, Ollama is not called even if it would fail"""
        ingredients = [{"amount": "1", "unit": "whole", "item": "tomato"}]
        # No mock needed -- keyword matching handles this without Ollama
        result = match_ingredients_to_seasonal(ingredients)
        assert result == ["tomato"]

    @patch("lib.seasonality.requests.post")
    def test_ollama_failure_returns_empty_when_no_keyword_match(self, mock_post):
        """On Ollama failure with no keyword matches, return empty list (graceful degradation)"""
        mock_post.side_effect = Exception("Connection refused")
        # Use ingredients that won't keyword-match any seasonal name
        ingredients = [{"amount": "1", "unit": "whole", "item": "dragon fruit"}]
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
