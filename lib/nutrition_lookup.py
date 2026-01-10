"""Nutrition lookup from external APIs."""

import json
import os
from dataclasses import dataclass
from typing import Optional

import requests

from lib.nutrition import NutritionData


NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"
USDA_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

NUTRITION_PROMPT = """Estimate the total nutrition for these ingredients combined.
Return ONLY a JSON object with these exact keys: calories, protein, carbs, fat.
Values should be integers representing the total for all ingredients.

Ingredients:
{ingredients}

JSON response:"""

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


def estimate_with_ai(ingredients: list[str]) -> Optional[NutritionLookupResult]:
    """Estimate nutrition using Ollama AI.

    Args:
        ingredients: List of ingredient strings (e.g., ["1 cup flour", "2 eggs"])

    Returns:
        NutritionLookupResult or None if estimation fails
    """
    prompt = NUTRITION_PROMPT.format(ingredients="\n".join(f"- {i}" for i in ingredients))

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )

        if response.status_code != 200:
            return None

        data = response.json()
        response_text = data.get("response", "")

        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1

        if json_start == -1 or json_end == 0:
            return None

        nutrition_json = json.loads(response_text[json_start:json_end])

        nutrition = NutritionData(
            calories=int(nutrition_json.get("calories", 0)),
            protein=int(nutrition_json.get("protein", 0)),
            carbs=int(nutrition_json.get("carbs", 0)),
            fat=int(nutrition_json.get("fat", 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="ai")

    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError):
        return None


def calculate_recipe_nutrition(
    ingredients: list[dict],
    servings: int
) -> Optional[NutritionLookupResult]:
    """Calculate total nutrition for a recipe.

    Tries Nutritionix first, then USDA, then AI estimation.

    Args:
        ingredients: List of ingredient dicts with amount, unit, item
        servings: Number of servings in recipe

    Returns:
        NutritionLookupResult with per-serving values, or None if all fail
    """
    total = NutritionData.empty()
    source = "nutritionix"
    failed_ingredients = []

    for ing in ingredients:
        ingredient_str = f"{ing.get('amount', '1')} {ing.get('unit', '')} {ing.get('item', '')}".strip()

        # Try Nutritionix first
        result = lookup_nutritionix(ingredient_str)

        # Fall back to USDA
        if result is None:
            result = lookup_usda(ing.get("item", ""))
            if result:
                source = "usda" if source == "nutritionix" else source

        if result:
            total = total + result.nutrition
        else:
            failed_ingredients.append(ingredient_str)

    # If any ingredients failed, try AI for the whole list
    if failed_ingredients:
        ai_result = estimate_with_ai(failed_ingredients)
        if ai_result:
            total = total + ai_result.nutrition
            source = "ai"
        elif not any(lookup_nutritionix(f"{i.get('amount', '1')} {i.get('unit', '')} {i.get('item', '')}".strip()) or lookup_usda(i.get("item", "")) for i in ingredients):
            # All ingredients failed
            return None

    # Divide by servings for per-serving values
    if servings > 0:
        per_serving = total * (1 / servings)
    else:
        per_serving = total

    return NutritionLookupResult(nutrition=per_serving, source=source)
