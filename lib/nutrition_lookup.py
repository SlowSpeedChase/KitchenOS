"""Nutrition lookup from external APIs."""

import os
from dataclasses import dataclass
from typing import Optional

import requests

from lib.nutrition import NutritionData


NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"
USDA_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# USDA nutrient IDs
NUTRIENT_CALORIES = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_CARBS = 1005
NUTRIENT_FAT = 1004


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


def lookup_usda(ingredient: str) -> Optional[NutritionLookupResult]:
    """Look up nutrition data from USDA FoodData Central.

    Args:
        ingredient: Ingredient name to search

    Returns:
        NutritionLookupResult or None if lookup fails
    """
    # Extract just the food name (remove quantities)
    words = ingredient.split()
    food_name = " ".join(w for w in words if not w.replace(".", "").replace("/", "").isdigit())

    params = {
        "query": food_name,
        "pageSize": 1,
        "dataType": ["Foundation", "SR Legacy"],
    }

    try:
        response = requests.get(USDA_URL, params=params, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        foods = data.get("foods", [])

        if not foods:
            return None

        food = foods[0]
        nutrients = {n["nutrientId"]: n.get("value", 0) for n in food.get("foodNutrients", [])}

        nutrition = NutritionData(
            calories=int(nutrients.get(NUTRIENT_CALORIES, 0)),
            protein=int(nutrients.get(NUTRIENT_PROTEIN, 0)),
            carbs=int(nutrients.get(NUTRIENT_CARBS, 0)),
            fat=int(nutrients.get(NUTRIENT_FAT, 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="usda")

    except (requests.RequestException, KeyError, ValueError):
        return None
