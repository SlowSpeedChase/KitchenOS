"""Prompt template for seasonal ingredient matching via Ollama."""

import json

SEASONAL_MATCHING_PROMPT = """Given these recipe ingredients:
{ingredient_items}

And these seasonal produce items:
{seasonal_names}

Return ONLY the matches as a JSON array of objects:
[{{"ingredient": "butternut squash", "matches": "butternut squash"}}]

Rules:
- Only match fresh produce, skip pantry staples (oil, flour, sugar, salt, spices, sauces, grains, pasta, rice, etc.)
- Match variants to the closest seasonal item (e.g. "baby spinach" -> "spinach", "cherry tomato" -> "tomato")
- If no match exists for an ingredient, omit it entirely
- Return an empty array [] if no ingredients match"""


def build_seasonal_matching_prompt(ingredient_items: list[str], seasonal_names: list[str]) -> str:
    """Build prompt for seasonal ingredient matching.

    Args:
        ingredient_items: List of ingredient item strings from recipe
        seasonal_names: List of seasonal produce names from config

    Returns:
        Formatted prompt string
    """
    return SEASONAL_MATCHING_PROMPT.format(
        ingredient_items=json.dumps(ingredient_items),
        seasonal_names=json.dumps(seasonal_names),
    )
