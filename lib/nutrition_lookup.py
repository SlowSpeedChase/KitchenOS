"""Nutrition lookup from external APIs."""

import os
from dataclasses import dataclass
from typing import Optional

import requests

from lib.nutrition import NutritionData


NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"


@dataclass
class NutritionLookupResult:
    """Result from a nutrition lookup."""
    nutrition: NutritionData
    source: str  # "nutritionix", "usda", "ai", "manual"


def lookup_nutritionix(ingredient: str) -> Optional[NutritionLookupResult]:
    """Look up nutrition data from Nutritionix API.

    Args:
        ingredient: Natural language ingredient (e.g., "2 cups flour")

    Returns:
        NutritionLookupResult or None if lookup fails
    """
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    api_key = os.getenv("NUTRITIONIX_API_KEY")

    if not app_id or not api_key:
        return None

    headers = {
        "x-app-id": app_id,
        "x-app-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            NUTRITIONIX_URL,
            headers=headers,
            json={"query": ingredient},
            timeout=10,
        )

        if response.status_code != 200:
            return None

        data = response.json()
        foods = data.get("foods", [])

        if not foods:
            return None

        food = foods[0]
        nutrition = NutritionData(
            calories=round(food.get("nf_calories", 0)),
            protein=round(food.get("nf_protein", 0)),
            carbs=round(food.get("nf_total_carbohydrate", 0)),
            fat=round(food.get("nf_total_fat", 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="nutritionix")

    except (requests.RequestException, KeyError, ValueError):
        return None
