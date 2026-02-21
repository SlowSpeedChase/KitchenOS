"""Seasonality scoring and ingredient matching for recipes."""

import json
from datetime import date
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "seasonal_ingredients.json"

_config_cache = None


def load_seasonal_config() -> dict:
    """Load seasonal ingredients config from JSON file."""
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = json.load(f)
    return _config_cache


def match_ingredients_to_seasonal(ingredients: list[dict]) -> list[str]:
    """Use Ollama to fuzzy-match recipe ingredients to seasonal produce.

    Args:
        ingredients: List of ingredient dicts with 'item' key

    Returns:
        Deduplicated list of matched seasonal ingredient names
    """
    if not ingredients:
        return []

    config = load_seasonal_config()
    seasonal_names = sorted(config["ingredients"].keys())
    ingredient_items = [ing.get("item", "") for ing in ingredients if ing.get("item")]

    if not ingredient_items:
        return []

    prompt = f"""Given these recipe ingredients:
{json.dumps(ingredient_items)}

And these seasonal produce items:
{json.dumps(seasonal_names)}

Return ONLY the matches as a JSON array of objects:
[{{"ingredient": "butternut squash", "matches": "butternut squash"}}]

Rules:
- Only match fresh produce, skip pantry staples (oil, flour, sugar, salt, spices, sauces, grains, pasta, rice, etc.)
- Match variants to the closest seasonal item (e.g. "baby spinach" -> "spinach", "cherry tomato" -> "tomato")
- If no match exists for an ingredient, omit it entirely
- Return an empty array [] if no ingredients match"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        raw = result.get("response", "")
        parsed = json.loads(raw)

        # Handle both bare list and wrapped {"matches": [...]} responses
        if isinstance(parsed, dict):
            matches = parsed.get("matches", parsed.get("results", []))
        elif isinstance(parsed, list):
            matches = parsed
        else:
            return []

        # Extract unique seasonal names
        seen = set()
        result_list = []
        for m in matches:
            if isinstance(m, dict):
                name = m.get("matches", "").strip().lower()
                if name and name in config["ingredients"] and name not in seen:
                    seen.add(name)
                    result_list.append(name)

        return result_list

    except Exception:
        return []


def calculate_season_score(seasonal_ingredients: list[str], month: int = None) -> int:
    """Calculate how many seasonal ingredients are in peak season for given month.

    Args:
        seasonal_ingredients: List of matched seasonal produce names
        month: Month number (1-12). Defaults to current month.

    Returns:
        Count of ingredients currently in peak season
    """
    if not seasonal_ingredients:
        return 0

    if month is None:
        month = date.today().month

    config = load_seasonal_config()
    score = 0
    for name in seasonal_ingredients:
        entry = config["ingredients"].get(name)
        if entry and month in entry["peak_months"]:
            score += 1

    return score


def get_peak_months(seasonal_ingredients: list[str]) -> list[int]:
    """Get union of peak months for all matched seasonal ingredients.

    Args:
        seasonal_ingredients: List of matched seasonal produce names

    Returns:
        Sorted list of month numbers (1-12)
    """
    if not seasonal_ingredients:
        return []

    config = load_seasonal_config()
    months = set()
    for name in seasonal_ingredients:
        entry = config["ingredients"].get(name)
        if entry:
            months.update(entry["peak_months"])

    return sorted(months)
