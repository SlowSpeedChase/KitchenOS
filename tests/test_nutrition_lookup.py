"""Tests for nutrition lookup APIs."""

from unittest.mock import patch, Mock

import requests

from lib.nutrition_lookup import lookup_nutritionix, lookup_usda, estimate_with_ai, NutritionLookupResult
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


class TestEstimateWithAi:
    def test_parses_ollama_response(self):
        mock_ollama_response = {
            "response": '{"calories": 200, "protein": 5, "carbs": 40, "fat": 2}'
        }

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_ollama_response
            )
            result = estimate_with_ai(["1 cup flour", "2 eggs"])

        assert result is not None
        assert result.nutrition.calories == 200
        assert result.source == "ai"

    def test_returns_none_on_invalid_json(self):
        mock_ollama_response = {"response": "I cannot determine the nutrition."}

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_ollama_response
            )
            result = estimate_with_ai(["mystery ingredient"])

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.side_effect = requests.RequestException("Connection failed")
            result = estimate_with_ai(["1 cup flour"])

        assert result is None


class TestCalculateRecipeNutrition:
    def test_sums_ingredients_and_divides_by_servings(self):
        from lib.nutrition_lookup import calculate_recipe_nutrition

        ingredients = [
            {"amount": "2", "unit": "cups", "item": "flour"},
            {"amount": "3", "unit": "whole", "item": "eggs"},
        ]

        with patch("lib.nutrition_lookup.lookup_nutritionix") as mock_nx:
            mock_nx.side_effect = [
                NutritionLookupResult(NutritionData(400, 10, 80, 2), "nutritionix"),
                NutritionLookupResult(NutritionData(210, 18, 3, 15), "nutritionix"),
            ]
            result = calculate_recipe_nutrition(ingredients, servings=2)

        assert result.nutrition.calories == 305
        assert result.nutrition.protein == 14
        assert result.nutrition.carbs == 41
        assert result.nutrition.fat == 8
        assert result.source == "nutritionix"

    def test_falls_back_to_usda(self):
        from lib.nutrition_lookup import calculate_recipe_nutrition

        ingredients = [{"amount": "1", "unit": "cup", "item": "flour"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda") as mock_usda:
                mock_usda.return_value = NutritionLookupResult(
                    NutritionData(364, 10, 76, 1), "usda"
                )
                result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result.source == "usda"

    def test_falls_back_to_ai(self):
        from lib.nutrition_lookup import calculate_recipe_nutrition

        ingredients = [{"amount": "1", "unit": "cup", "item": "mystery"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda", return_value=None):
                with patch("lib.nutrition_lookup.estimate_with_ai") as mock_ai:
                    mock_ai.return_value = NutritionLookupResult(
                        NutritionData(100, 5, 20, 2), "ai"
                    )
                    result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result.source == "ai"

    def test_returns_none_when_all_fail(self):
        from lib.nutrition_lookup import calculate_recipe_nutrition

        ingredients = [{"amount": "1", "unit": "cup", "item": "unknown"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda", return_value=None):
                with patch("lib.nutrition_lookup.estimate_with_ai", return_value=None):
                    result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result is None
