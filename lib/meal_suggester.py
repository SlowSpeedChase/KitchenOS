"""Meal suggestion engine — ingredient overlap scoring with AI reasoning."""

import json
import os
from pathlib import Path
from typing import Optional

import requests

PANTRY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pantry_staples.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

# Words to strip from ingredient names for normalization
PREP_WORDS = {
    "diced", "minced", "chopped", "sliced", "grated", "shredded",
    "crushed", "ground", "dried", "fresh", "frozen", "canned",
    "finely", "roughly", "thinly", "coarsely",
    "large", "medium", "small", "extra", "boneless", "skinless",
    "low-fat", "nonfat", "whole", "raw",
}


def load_pantry_staples() -> set[str]:
    """Load pantry staples from config file."""
    try:
        with open(PANTRY_CONFIG_PATH) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def normalize_ingredient(item: str) -> str:
    """Normalize an ingredient name for matching.

    Lowercases, strips preparation methods and adjectives.
    """
    item = item.lower().strip()
    words = item.split()
    filtered = [w for w in words if w not in PREP_WORDS]
    return " ".join(filtered) if filtered else item


def score_overlap(
    recipe_items: list[str],
    planned_items: set[str],
    pantry: set[str],
) -> tuple[float, set[str]]:
    """Score a recipe's ingredient overlap with planned meals.

    Args:
        recipe_items: Ingredient item strings from the recipe
        planned_items: Set of normalized ingredient names already planned
        pantry: Set of pantry staple names to exclude

    Returns:
        (score 0.0-1.0, set of shared ingredient names)
    """
    normalized = [normalize_ingredient(item) for item in recipe_items]
    non_pantry = [n for n in normalized if n not in pantry]

    if not non_pantry:
        return 0.0, set()

    shared = {n for n in non_pantry if n in planned_items}
    score = len(shared) / len(non_pantry)
    return score, shared


def rank_candidates(
    candidates: list[dict],
    planned_items: set[str],
    pantry: set[str],
    limit: int = 10,
    exclude_names: set[str] | None = None,
) -> list[dict]:
    """Rank recipe candidates by ingredient overlap.

    Args:
        candidates: List of recipe dicts with 'name' and 'ingredient_items'
        planned_items: Set of normalized ingredient names from planned meals
        pantry: Pantry staples to exclude
        limit: Max candidates to return
        exclude_names: Recipe names to skip (already planned)

    Returns:
        Sorted list of dicts with 'name', 'score', 'shared_ingredients' added
    """
    exclude = exclude_names or set()
    scored = []

    for recipe in candidates:
        if recipe["name"] in exclude:
            continue
        items = recipe.get("ingredient_items", [])
        if not items:
            continue

        score, shared = score_overlap(items, planned_items, pantry)
        scored.append({
            "name": recipe["name"],
            "score": round(score, 3),
            "shared_ingredients": sorted(shared),
            "ingredient_items": items,
        })

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]


def normalize_ingredients_ollama(items: list[str]) -> list[str]:
    """Normalize ingredient names using Ollama, with fallback to simple normalization.

    Args:
        items: Raw ingredient item strings

    Returns:
        List of normalized ingredient names (same length as input)
    """
    from prompts.meal_suggestion import NORMALIZE_PROMPT

    prompt = NORMALIZE_PROMPT.format(
        ingredients=json.dumps(items)
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        if response.status_code != 200:
            return [normalize_ingredient(item) for item in items]

        data = response.json()
        raw = data.get("response", "")

        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(items):
            return [str(n).lower().strip() for n in parsed]

        return [normalize_ingredient(item) for item in items]

    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return [normalize_ingredient(item) for item in items]
