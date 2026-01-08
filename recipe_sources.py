"""Recipe source extraction: webpage scraping, description parsing, tips extraction"""

import json
import re
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup

from prompts.recipe_extraction import (
    DESCRIPTION_EXTRACTION_PROMPT,
    build_description_prompt,
    TIPS_EXTRACTION_PROMPT,
    build_tips_prompt,
)


# Known recipe domains (no keyword needed)
KNOWN_RECIPE_DOMAINS = [
    "bingingwithbabish.com",
    "seriouseats.com",
    "bonappetit.com",
    "food52.com",
    "smittenkitchen.com",
    "budgetbytes.com",
    "allrecipes.com",
    "epicurious.com",
    "foodnetwork.com",
    "delish.com",
    "tasty.co",
    "thekitchn.com",
]

# Domains to exclude
EXCLUDED_DOMAINS = [
    "patreon.com",
    "instagram.com",
    "twitter.com",
    "facebook.com",
    "tiktok.com",
    "amazon.com",
    "amzn.to",
    "youtube.com",
    "youtu.be",
]

# Keywords that indicate a recipe link
RECIPE_KEYWORDS = [
    "recipe",
    "recipes",
    "full recipe",
    "written recipe",
    "ingredients",
]


def find_recipe_link(description: str) -> Optional[str]:
    """
    Find a recipe URL in a video description.

    Priority:
    1. Explicit label (e.g., "Recipe: https://...")
    2. URL on same line as recipe keyword
    3. URL from known recipe domain

    Returns:
        Recipe URL if found, None otherwise
    """
    if not description:
        return None

    # URL pattern
    url_pattern = r'https?://[^\s<>"\')\]]+'

    lines = description.split('\n')

    # Pass 1: Look for explicit label "Recipe:" or "Full recipe:" at start of line
    for line in lines:
        line_lower = line.lower().strip()
        if line_lower.startswith("recipe:") or line_lower.startswith("full recipe:"):
            urls = re.findall(url_pattern, line)
            for url in urls:
                if not _is_excluded_domain(url):
                    return url

    # Pass 2: Look for URLs on same line as recipe keywords
    for line in lines:
        line_lower = line.lower()
        has_keyword = any(kw in line_lower for kw in RECIPE_KEYWORDS)
        if has_keyword:
            urls = re.findall(url_pattern, line)
            for url in urls:
                if not _is_excluded_domain(url):
                    return url

    # Pass 3: Look for known recipe domains anywhere
    all_urls = re.findall(url_pattern, description)
    for url in all_urls:
        if _is_known_recipe_domain(url) and not _is_excluded_domain(url):
            return url

    return None


def _is_excluded_domain(url: str) -> bool:
    """Check if URL is from an excluded domain"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)


def _is_known_recipe_domain(url: str) -> bool:
    """Check if URL is from a known recipe domain"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in KNOWN_RECIPE_DOMAINS)


def parse_iso_duration(iso_duration: str) -> Optional[str]:
    """Parse ISO 8601 duration to human-readable string."""
    if not iso_duration:
        return None
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
    if not match:
        return iso_duration
    hours, minutes, seconds = match.groups()
    parts = []
    if hours:
        h = int(hours)
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if minutes:
        m = int(minutes)
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    if seconds:
        s = int(seconds)
        parts.append(f"{s} second" + ("s" if s != 1 else ""))
    return " ".join(parts) if parts else None


def _parse_servings(yield_str) -> Optional[int]:
    """Parse servings from recipeYield field."""
    if not yield_str:
        return None
    if isinstance(yield_str, int):
        return yield_str
    if isinstance(yield_str, list):
        yield_str = yield_str[0] if yield_str else ""
    match = re.search(r'(\d+)', str(yield_str))
    return int(match.group(1)) if match else None


def _parse_dietary(diets) -> List[str]:
    """Parse dietary information from suitableForDiet field."""
    if not diets:
        return []
    if isinstance(diets, str):
        diets = [diets]
    result = []
    for diet in diets:
        diet_lower = diet.lower()
        if "vegan" in diet_lower:
            result.append("vegan")
        elif "vegetarian" in diet_lower:
            result.append("vegetarian")
        elif "gluten" in diet_lower:
            result.append("gluten-free")
        elif "dairy" in diet_lower:
            result.append("dairy-free")
    return result


def _split_ingredient_string(ing_str: str) -> tuple:
    """
    Split a combined ingredient string into (quantity, item).

    Handles formats like:
    - "Chicken Breasts, 500 g" → ("500 g", "Chicken Breasts")
    - "Salt, 5 g" → ("5 g", "Salt")
    - "Garlic, 3 cloves" → ("3 cloves", "Garlic")
    - "Heavy cream, to taste" → ("to taste", "Heavy cream")
    - "Lavash bread" → ("", "Lavash bread")
    - "2 cups flour" → ("2 cups", "flour")
    - "Fresh ginger, 1" knob" → ("1\" knob", "Fresh ginger")
    """
    ing_str = ing_str.strip()

    # Remove trailing comma if present (edge case from some sources)
    if ing_str.endswith(','):
        ing_str = ing_str[:-1].strip()

    # Pattern 1: "Item, quantity" (comma-separated with quantity at end)
    # Look for ", " followed by a quantity pattern at the end
    comma_pattern = r'^(.+?),\s+(\d+.*|to taste|a (?:pinch|dash|sprinkle|handful|spoonful).*)$'
    comma_match = re.match(comma_pattern, ing_str, re.IGNORECASE)
    if comma_match:
        item, quantity = comma_match.groups()
        # Normalize inch/quote marks: '1" knob' or '1 " knob' → '1" knob'
        # Also handle Unicode curly quotes ("" '')
        quantity = re.sub(r'(\d)\s*(["\'\u201c\u201d\u2018\u2019])', r'\1"', quantity)
        return (quantity.strip(), item.strip())

    # Pattern 2: "quantity Item" (quantity at start)
    # Match: number + optional fraction + unit + rest
    qty_first_pattern = r'^(\d+(?:\s*/?\s*\d+)?(?:\s*(?:g|kg|ml|l|oz|lb|cup|cups|tbsp|tsp|clove|cloves|bunch|head|inch|"|\'))?)\s+(.+)$'
    qty_match = re.match(qty_first_pattern, ing_str, re.IGNORECASE)
    if qty_match:
        quantity, item = qty_match.groups()
        return (quantity.strip(), item.strip())

    # No quantity found, return as item only
    return ("", ing_str)


def _parse_ingredients(ingredients) -> List[Dict[str, Any]]:
    """Parse ingredients from recipeIngredient field."""
    if not ingredients:
        return []
    result = []
    for ing in ingredients:
        if isinstance(ing, str):
            quantity, item = _split_ingredient_string(ing)
            result.append({"quantity": quantity, "item": item, "inferred": False})
        elif isinstance(ing, dict):
            result.append({
                "quantity": ing.get("amount", ""),
                "item": ing.get("name", str(ing)),
                "inferred": False,
            })
    return result


def _parse_instructions(instructions) -> List[Dict[str, Any]]:
    """Parse instructions from recipeInstructions field."""
    if not instructions:
        return []
    if isinstance(instructions, str):
        return [{"step": 1, "text": instructions, "time": None}]
    result = []
    for i, inst in enumerate(instructions, 1):
        if isinstance(inst, str):
            result.append({"step": i, "text": inst, "time": None})
        elif isinstance(inst, dict):
            text = inst.get("text", inst.get("name", ""))
            result.append({"step": i, "text": text, "time": None})
    return result


def _parse_nutrition(nutrition) -> Optional[str]:
    """Parse nutrition info from nutrition field."""
    if not nutrition or not isinstance(nutrition, dict):
        return None
    parts = []
    if nutrition.get("calories"):
        parts.append(f"Calories: {nutrition['calories']}")
    if nutrition.get("proteinContent"):
        parts.append(f"Protein: {nutrition['proteinContent']}")
    if nutrition.get("carbohydrateContent"):
        parts.append(f"Carbs: {nutrition['carbohydrateContent']}")
    return ", ".join(parts) if parts else None


def parse_json_ld_recipe(json_ld: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a Schema.org Recipe JSON-LD object into our recipe format."""
    recipe = {
        "recipe_name": json_ld.get("name", "Untitled Recipe"),
        "description": json_ld.get("description"),
        "prep_time": parse_iso_duration(json_ld.get("prepTime")),
        "cook_time": parse_iso_duration(json_ld.get("cookTime")),
        "total_time": parse_iso_duration(json_ld.get("totalTime")),
        "servings": _parse_servings(json_ld.get("recipeYield")),
        "difficulty": None,
        "cuisine": json_ld.get("recipeCuisine"),
        "protein": None,
        "dish_type": json_ld.get("recipeCategory"),
        "dietary": _parse_dietary(json_ld.get("suitableForDiet", [])),
        "equipment": [],
        "ingredients": _parse_ingredients(json_ld.get("recipeIngredient", [])),
        "instructions": _parse_instructions(json_ld.get("recipeInstructions", [])),
        "storage": None,
        "variations": [],
        "nutritional_info": _parse_nutrition(json_ld.get("nutrition")),
        "needs_review": False,
        "confidence_notes": "Extracted from structured JSON-LD data on recipe webpage.",
    }
    return recipe


def _is_recipe_type(type_value: Any) -> bool:
    """Check if @type value indicates a Recipe (handles string or array)"""
    if type_value == "Recipe":
        return True
    if isinstance(type_value, list) and "Recipe" in type_value:
        return True
    return False


def _find_recipe_in_json_ld(data: Any) -> Optional[Dict[str, Any]]:
    """Find Recipe object in JSON-LD data (handles @graph arrays and @type arrays)"""
    if isinstance(data, dict):
        if _is_recipe_type(data.get("@type")):
            return data
        if "@graph" in data:
            for item in data["@graph"]:
                if isinstance(item, dict) and _is_recipe_type(item.get("@type")):
                    return item
    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_in_json_ld(item)
            if result:
                return result
    return None


def has_recipe_in_description(description: str) -> bool:
    """
    Check if a video description appears to contain a recipe.

    Looks for:
    - "Ingredients" header
    - Multiple lines with quantities
    - "Method", "Instructions", or "Directions" header
    """
    if not description:
        return False

    desc_lower = description.lower()

    # Check for ingredients header
    has_ingredients = any(marker in desc_lower for marker in [
        "ingredients", "*ingredients*", "**ingredients**"
    ])

    # Check for method/instructions header
    has_method = any(marker in desc_lower for marker in [
        "method", "instructions", "directions",
        "*method*", "**method**",
        "*instructions*", "**instructions**",
    ])

    # Check for quantity patterns (numbers followed by units)
    quantity_pattern = r'\d+\s*(?:cup|tbsp|tsp|oz|lb|g|kg|ml|clove|bunch|head)'
    has_quantities = len(re.findall(quantity_pattern, desc_lower)) >= 2

    return has_ingredients and (has_method or has_quantities)


def scrape_recipe_from_url(url: str) -> Optional[Dict[str, Any]]:
    """Fetch a URL and extract recipe data from JSON-LD."""
    try:
        response = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; KitchenOS/1.0)"
        })
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  -> Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue
        recipe = _find_recipe_in_json_ld(data)
        if recipe:
            return parse_json_ld_recipe(recipe)
    return None


# Ollama configuration (same as extract_recipe.py)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"


def parse_recipe_from_description(
    description: str,
    title: str = "",
    channel: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Extract recipe from a video description using Ollama.

    Only called if has_recipe_in_description() returns True.

    Returns:
        Recipe dict if extraction succeeds, None on error
    """
    if not has_recipe_in_description(description):
        return None

    prompt = "{}\n\n{}".format(
        DESCRIPTION_EXTRACTION_PROMPT,
        build_description_prompt(title, channel, description)
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        recipe_json = result.get("response", "")
        return json.loads(recipe_json)
    except Exception as e:
        print(f"  -> Description parsing failed: {e}")
        return None


def extract_cooking_tips(transcript: str, recipe: Dict[str, Any]) -> List[str]:
    """Extract practical cooking tips from video transcript."""
    if not transcript:
        return []

    prompt = "{}\n\n{}".format(
        TIPS_EXTRACTION_PROMPT,
        build_tips_prompt(recipe, transcript)
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        tips_json = result.get("response", "[]")
        tips = json.loads(tips_json)

        if isinstance(tips, list):
            return [str(t) for t in tips if t][:5]
        return []
    except Exception as e:
        print(f"  -> Tips extraction failed: {e}")
        return []
