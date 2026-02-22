"""Prompt template for seasonal ingredient matching via Ollama."""

import json

SEASONAL_MATCHING_PROMPT = """Given these recipe ingredients:
{ingredient_items}

And these seasonal produce items:
{seasonal_names}

Return ONLY the matches as a JSON array of objects:
[{{"ingredient": "butternut squash", "matches": "butternut squash"}}]

Rules:
- Match fresh produce ingredients to their closest seasonal item
- Match variants generously: "baby spinach" -> "spinach", "cherry tomato" -> "tomato", "sweet corn" -> "corn", "fresh peaches" -> "peach"
- Skip obvious pantry staples (oil, flour, sugar, salt, spices, sauces, grains, pasta, rice, dried herbs)
- If an ingredient contains a produce name, match it (e.g., "ears fresh corn" -> "corn")
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
