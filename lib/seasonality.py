"""Seasonality scoring and ingredient matching for recipes."""

import json
import re
from datetime import date
from pathlib import Path

import requests

from prompts.seasonal_matching import build_seasonal_matching_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "seasonal_ingredients.json"

_config_cache = None

_PANTRY_KEYWORDS = {
    "oil", "flour", "sugar", "salt", "pepper", "butter", "cream",
    "milk", "water", "broth", "stock", "vinegar", "soy sauce",
    "pasta", "rice", "noodle", "bread", "tortilla", "wrap",
    "spice", "seasoning", "powder", "extract", "vanilla",
    "honey", "syrup", "sauce", "ketchup", "mustard", "mayo",
    "nuts", "seeds", "chocolate", "cocoa", "coffee", "tea",
}


def load_seasonal_config() -> dict:
    """Load seasonal ingredients config from JSON file."""
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = json.load(f)
    return _config_cache


def _is_pantry_item(ingredient_text: str) -> bool:
    """Return True if any pantry keyword appears as a whole word in the lowercased text.

    Uses word-boundary matching to avoid false positives like "butter" matching
    inside "butternut" or "pepper" matching inside "bell pepper" when a seasonal
    produce name is the actual item.
    """
    text = ingredient_text.lower()
    for keyword in _PANTRY_KEYWORDS:
        # Use word boundaries so "butter" doesn't match "butternut"
        # and "pepper" only matches standalone "pepper" not "bell pepper"
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return True
    return False


def _keyword_in_text(seasonal_name: str, text: str, claimed: set) -> bool:
    """Check if a seasonal name (or its plural) appears in text.

    Args:
        seasonal_name: A seasonal produce name from config (e.g. "corn", "sweet potato")
        text: The lowercased ingredient text to search in
        claimed: Set of seasonal names already matched for this ingredient.
                 If a longer name in claimed contains this name, skip it
                 to prevent "sweet potato" also matching "potato".

    Returns:
        True if the seasonal name matches in the text
    """
    # Skip if a longer name already claimed contains this name
    for c in claimed:
        if seasonal_name in c and seasonal_name != c:
            return False

    # Check direct substring
    if seasonal_name in text:
        return True

    # Check +s plural
    if f"{seasonal_name}s" in text:
        return True

    # Check +es plural
    if f"{seasonal_name}es" in text:
        return True

    return False


def _filter_modifier_matches(matches: list[str], text: str) -> list[str]:
    """Remove seasonal names that are modifiers of another matched name in the text.

    For example, in "cherry tomatoes", if both "cherry" and "tomato" matched,
    "cherry" is acting as a modifier (adjective) for "tomato" and should be
    removed. A match is considered a modifier if it appears immediately before
    another match (possibly with pluralization) in the text.

    Args:
        matches: List of seasonal names that matched this ingredient
        text: The lowercased ingredient text

    Returns:
        Filtered list with modifier matches removed
    """
    if len(matches) <= 1:
        return matches

    modifiers = set()
    for name_a in matches:
        for name_b in matches:
            if name_a == name_b:
                continue
            # Check if name_a immediately precedes name_b (or its plural) in text
            # e.g. "cherry tomato", "cherry tomatoes"
            for suffix in ["", "s", "es"]:
                pattern = f"{name_a} {name_b}{suffix}"
                if pattern in text or f"{name_a}s {name_b}{suffix}" in text:
                    modifiers.add(name_a)
                    break

    return [m for m in matches if m not in modifiers]


def keyword_match_seasonal(ingredients: list[dict]) -> list[str]:
    """Fast keyword-based matching of ingredients to seasonal produce.

    Matches ingredient item text against seasonal produce names using
    substring matching with plural support. Skips pantry staples.
    Multi-word seasonal names are checked first to prevent partial matches
    (e.g. "sweet potato" is checked before "potato").

    Args:
        ingredients: List of ingredient dicts with 'item' key

    Returns:
        Deduplicated list of matched seasonal produce names
    """
    if not ingredients:
        return []

    config = load_seasonal_config()
    # Sort seasonal names by length descending so multi-word names match first
    seasonal_names = sorted(
        config["ingredients"].keys(), key=len, reverse=True
    )

    seen = set()
    result_list = []

    for ing in ingredients:
        item = ing.get("item", "")
        if not item or not isinstance(item, str):
            continue

        text = item.lower()

        # First try seasonal matching (before pantry filter) so produce
        # names like "bell pepper" aren't incorrectly filtered as "pepper"
        claimed = set()
        ingredient_matches = []

        for name in seasonal_names:
            if _keyword_in_text(name, text, claimed):
                claimed.add(name)
                ingredient_matches.append(name)

        if ingredient_matches:
            # Filter out modifier matches (e.g. "cherry" in "cherry tomatoes")
            filtered = _filter_modifier_matches(ingredient_matches, text)
            for name in filtered:
                if name not in seen:
                    seen.add(name)
                    result_list.append(name)
            continue

        # No seasonal match found - skip if it's a pantry item (no false positives)
        # If it's not a pantry item either, it just contributes 0 matches

    return result_list


def _ollama_match_seasonal(ingredients: list[dict]) -> list[str]:
    """Use Ollama to fuzzy-match recipe ingredients to seasonal produce.

    This is the AI-based fallback used when keyword matching finds nothing.

    Args:
        ingredients: List of ingredient dicts with 'item' key

    Returns:
        Deduplicated list of matched seasonal ingredient names
    """
    config = load_seasonal_config()
    seasonal_names = sorted(config["ingredients"].keys())
    ingredient_items = [ing.get("item", "") for ing in ingredients if ing.get("item")]

    if not ingredient_items:
        return []

    prompt = build_seasonal_matching_prompt(ingredient_items, seasonal_names)

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


def match_ingredients_to_seasonal(ingredients: list[dict]) -> list[str]:
    """Match recipe ingredients to seasonal produce names.

    Tries fast keyword matching first (no API call). Falls back to Ollama
    AI matching only if keyword matching found 0 matches.

    Args:
        ingredients: List of ingredient dicts with 'item' key

    Returns:
        Deduplicated list of matched seasonal ingredient names
    """
    if not ingredients:
        return []

    # Try fast keyword matching first
    keyword_matches = keyword_match_seasonal(ingredients)
    if keyword_matches:
        return keyword_matches

    # Fall back to Ollama if keyword matching found nothing
    return _ollama_match_seasonal(ingredients)


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
