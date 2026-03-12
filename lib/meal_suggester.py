"""Meal suggestion engine — ingredient overlap scoring with AI reasoning."""

import json
import os
from pathlib import Path
from typing import Optional

import requests

try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:
    anthropic_client = None

PANTRY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pantry_staples.json"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 200

OVERLAP_THRESHOLD = 0.5

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


def suggest_with_claude(
    planned_meals: list[dict],
    candidates: list[dict],
    day: str,
    meal: str,
) -> Optional[dict]:
    """Ask Claude to pick the best candidate or suggest a new idea.

    Args:
        planned_meals: List of dicts with day, meal, name, ingredients
        candidates: Ranked list from rank_candidates()
        day: Target day (e.g., "Tuesday")
        meal: Target meal (e.g., "dinner")

    Returns:
        Dict with name, reason, is_new_idea, new_ingredients_needed, or None on failure
    """
    if anthropic_client is None:
        return None

    from prompts.meal_suggestion import SUGGEST_PROMPT

    planned_text = "\n".join(
        f"- {m['day']} {m['meal']}: **{m['name']}** (ingredients: {', '.join(m['ingredients'])})"
        for m in planned_meals
    )

    candidate_text = "\n".join(
        f"- **{c['name']}** (overlap: {c['score']:.0%}, shared: {', '.join(c['shared_ingredients'])})"
        for c in candidates[:10]
    )

    prompt = SUGGEST_PROMPT.format(
        planned_meals=planned_text,
        candidates=candidate_text,
        day=day,
        meal=meal,
    )

    try:
        message = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            return None

        result = json.loads(raw[json_start:json_end])
        return {
            "name": result.get("name", ""),
            "reason": result.get("reason", ""),
            "is_new_idea": result.get("is_new_idea", False),
            "new_ingredients_needed": result.get("new_ingredients_needed", []),
        }

    except Exception:
        return None


def suggest_for_empty_week(
    recipe_summaries: list[dict],
    day: str,
    meal: str,
) -> Optional[dict]:
    """Ask Claude to suggest a starting recipe when the week is empty.

    Args:
        recipe_summaries: List of dicts with name, cuisine, protein
        day: Target day
        meal: Target meal

    Returns:
        Suggestion dict or None
    """
    if anthropic_client is None:
        return None

    from prompts.meal_suggestion import SUGGEST_EMPTY_WEEK_PROMPT

    summaries_text = "\n".join(
        f"- {r['name']} ({r.get('cuisine', 'unknown')} / {r.get('protein', 'unknown')})"
        for r in recipe_summaries[:50]
    )

    prompt = SUGGEST_EMPTY_WEEK_PROMPT.format(
        recipe_summaries=summaries_text,
        day=day,
        meal=meal,
    )

    try:
        message = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            return None

        result = json.loads(raw[json_start:json_end])
        return {
            "name": result.get("name", ""),
            "reason": result.get("reason", ""),
            "is_new_idea": result.get("is_new_idea", False),
            "new_ingredients_needed": result.get("new_ingredients_needed", []),
        }

    except Exception:
        return None


def suggest_meal(
    recipes_dir: Path,
    planned_meals: list[dict],
    day: str,
    meal: str,
    skip_index: int = 0,
) -> Optional[dict]:
    """Top-level orchestrator: suggest a meal for an empty slot.

    Pipeline:
    1. If no meals planned -> ask Claude for a starting recipe (or return None)
    2. Collect planned ingredient names
    3. Load recipe library with ingredients
    4. Score and rank candidates
    5. If top candidate score >= threshold -> return it directly
    6. Else -> ask Claude to pick from candidates
    7. skip_index allows cycling through candidates (for "try another")

    Args:
        recipes_dir: Path to Obsidian Recipes folder
        planned_meals: List of dicts with day, meal, name, ingredients
        day: Target day name
        meal: Target meal type
        skip_index: Skip this many top candidates (for retry)

    Returns:
        Dict with name, score, reason, shared_ingredients, is_new_idea, or None
    """
    from lib.recipe_index import get_recipe_index

    pantry = load_pantry_staples()

    # Load all recipes with ingredients
    all_recipes = get_recipe_index(recipes_dir, include_ingredients=True)

    # Names already in the plan
    planned_names = {m["name"] for m in planned_meals}

    # Empty week -- ask Claude or return None
    if not planned_meals:
        summaries = [
            {"name": r["name"], "cuisine": r.get("cuisine"), "protein": r.get("protein")}
            for r in all_recipes
        ]
        claude_result = suggest_for_empty_week(summaries, day, meal)
        if claude_result:
            claude_result["score"] = 0.0
            claude_result["shared_ingredients"] = []
        return claude_result

    # Collect all planned ingredient names (normalized)
    planned_items = set()
    for m in planned_meals:
        for item in m.get("ingredients", []):
            planned_items.add(normalize_ingredient(item))

    # Score and rank
    ranked = rank_candidates(
        all_recipes, planned_items, pantry,
        limit=20, exclude_names=planned_names,
    )

    if not ranked:
        return None

    # Apply skip_index for "try another"
    if skip_index >= len(ranked):
        return None

    top = ranked[skip_index]

    # Tier decision
    if top["score"] >= OVERLAP_THRESHOLD:
        # High overlap -- use directly
        reason_items = ", ".join(top["shared_ingredients"][:3])
        planned_names_str = ", ".join(
            f"{m['day']}'s {m['name']}" for m in planned_meals
            if set(normalize_ingredient(i) for i in m.get("ingredients", []))
            & set(top["shared_ingredients"])
        )
        top["reason"] = f"Shares {reason_items} with {planned_names_str}" if planned_names_str else f"Shares {reason_items}"
        top["is_new_idea"] = False
        top["new_ingredients_needed"] = []
        return top

    # Low overlap -- try Claude
    claude_result = suggest_with_claude(planned_meals, ranked[skip_index:], day, meal)
    if claude_result:
        match = next((r for r in ranked if r["name"] == claude_result["name"]), None)
        if match:
            claude_result["score"] = match["score"]
            claude_result["shared_ingredients"] = match["shared_ingredients"]
        else:
            claude_result["score"] = 0.0
            claude_result["shared_ingredients"] = []
        return claude_result

    # Claude unavailable -- fall back to top scored candidate
    top["reason"] = f"Shares {', '.join(top['shared_ingredients'][:3])}" if top["shared_ingredients"] else "Best available match"
    top["is_new_idea"] = False
    top["new_ingredients_needed"] = []
    return top
