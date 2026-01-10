"""Tests for nutrition lookup APIs."""

from unittest.mock import patch, Mock

from lib.nutrition_lookup import lookup_nutritionix, lookup_usda, NutritionLookupResult
from lib.nutrition import NutritionData


class TestLookupNutritionix:
    def test_parses_successful_response(self):
        mock_response = {
            "foods": [{
                "nf_calories": 364.42,
                "nf_protein": 10.33,
                "nf_total_carbohydrate": 76.31,
                "nf_total_fat": 0.98,
            }]
        }

        with patch("lib.nutrition_lookup.os.getenv") as mock_getenv:
            mock_getenv.side_effect = lambda key: {
                "NUTRITIONIX_APP_ID": "test_app_id",
                "NUTRITIONIX_API_KEY": "test_api_key",
            }.get(key)
            with patch("lib.nutrition_lookup.requests.post") as mock_post:
                mock_post.return_value = Mock(
                    status_code=200,
                    json=lambda: mock_response
                )
                result = lookup_nutritionix("1 cup flour")

        assert result is not None
        assert result.nutrition.calories == 364
        assert result.nutrition.protein == 10
        assert result.nutrition.carbs == 76
        assert result.nutrition.fat == 1
        assert result.source == "nutritionix"

    def test_returns_none_on_empty_foods(self):
        mock_response = {"foods": []}

        with patch("lib.nutrition_lookup.os.getenv") as mock_getenv:
            mock_getenv.side_effect = lambda key: {
                "NUTRITIONIX_APP_ID": "test_app_id",
                "NUTRITIONIX_API_KEY": "test_api_key",
            }.get(key)
            with patch("lib.nutrition_lookup.requests.post") as mock_post:
                mock_post.return_value = Mock(
                    status_code=200,
                    json=lambda: mock_response
                )
                result = lookup_nutritionix("unknown ingredient xyz")

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.os.getenv") as mock_getenv:
            mock_getenv.side_effect = lambda key: {
                "NUTRITIONIX_APP_ID": "test_app_id",
                "NUTRITIONIX_API_KEY": "test_api_key",
            }.get(key)
            with patch("lib.nutrition_lookup.requests.post") as mock_post:
                mock_post.return_value = Mock(status_code=401)
                result = lookup_nutritionix("1 cup flour")

        assert result is None

    def test_returns_none_on_missing_credentials(self):
        with patch("lib.nutrition_lookup.os.getenv", return_value=None):
            result = lookup_nutritionix("1 cup flour")

        assert result is None


class TestLookupUsda:
    def test_parses_successful_response(self):
        mock_response = {
            "foods": [{
                "fdcId": 123456,
                "description": "Flour, wheat, all-purpose",
                "foodNutrients": [
                    {"nutrientId": 1008, "value": 364},  # calories
                    {"nutrientId": 1003, "value": 10},   # protein
                    {"nutrientId": 1005, "value": 76},   # carbs
                    {"nutrientId": 1004, "value": 1},    # fat
                ]
            }]
        }

        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_usda("flour")

        assert result is not None
        assert result.nutrition.calories == 364
        assert result.nutrition.protein == 10
        assert result.nutrition.carbs == 76
        assert result.nutrition.fat == 1
        assert result.source == "usda"

    def test_returns_none_on_empty_results(self):
        mock_response = {"foods": []}

        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_usda("unknown ingredient xyz")

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=500)
            result = lookup_usda("flour")

        assert result is None
