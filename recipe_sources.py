"""Recipe source extraction: webpage scraping, description parsing, tips extraction"""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# Config directory
CONFIG_DIR = Path(__file__).parent / "config"

from lib.ingredient_parser import parse_ingredient
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
    "pinterest.com",
    "pinterest.co.uk",
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


def _parse_ingredients(ingredients) -> List[Dict[str, Any]]:
    """Parse ingredients from recipeIngredient field to amount/unit/item format."""
    if not ingredients:
        return []
    result = []
    for ing in ingredients:
        if isinstance(ing, str):
            parsed = parse_ingredient(ing)
            result.append({
                "amount": parsed["amount"],
                "unit": parsed["unit"],
                "item": parsed["item"],
                "inferred": False,
            })
        elif isinstance(ing, dict):
            # Handle dict format from some sources
            if "amount" in ing:
                result.append({
                    "amount": str(ing.get("amount", "1")),
                    "unit": ing.get("unit", "whole"),
                    "item": ing.get("name", ing.get("item", "")),
                    "inferred": False,
                })
            else:
                # Legacy format with quantity field
                qty = ing.get("quantity", "")
                name = ing.get("name", "")
                parsed = parse_ingredient("{} {}".format(qty, name).strip())
                result.append({
                    "amount": parsed["amount"],
                    "unit": parsed["unit"],
                    "item": parsed["item"],
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


def _extract_image_url(image_field) -> Optional[str]:
    """Extract image URL from JSON-LD image field.

    Handles:
    - None → None
    - str → return directly
    - list → first string found, or first dict's 'url' key
    - dict → return .get("url")
    """
    if image_field is None:
        return None
    if isinstance(image_field, str):
        return image_field
    if isinstance(image_field, list):
        for item in image_field:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return item.get("url")
        return None
    if isinstance(image_field, dict):
        return image_field.get("url")
    return None


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
        "image_url": _extract_image_url(json_ld.get("image")),
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
    - "Ingredients" header (on its own line, not as a reference)
    - Multiple lines with quantities
    - "Method", "Instructions", or "Directions" header
    """
    if not description:
        return False

    desc_lower = description.lower()

    # Exclude patterns that reference ingredients elsewhere (pinned comment, video, etc.)
    reference_patterns = [
        r'ingredients.*(?:in|see|check|find).*(?:pinned|comment|video|link|below|description)',
        r'(?:pinned|comment).*ingredients',
        r'ingredients.*you\'ll need.*(?:pinned|comment)',
    ]
    for pattern in reference_patterns:
        if re.search(pattern, desc_lower):
            return False

    # Check for ingredients header - must be at start of a line (actual header)
    ingredients_header_pattern = r'^(?:\*{1,2})?ingredients(?:\*{1,2})?(?:\s*:)?$'
    has_ingredients = bool(re.search(
        ingredients_header_pattern,
        desc_lower,
        re.MULTILINE
    ))

    # Check for method/instructions header - must be at start of a line
    method_header_pattern = r'^(?:\*{1,2})?(?:method|instructions|directions)(?:\*{1,2})?(?:\s*:)?$'
    has_method = bool(re.search(
        method_header_pattern,
        desc_lower,
        re.MULTILINE
    ))

    # Check for quantity patterns (numbers followed by units)
    # Must have at least 3 to be a real ingredient list, not just nutrition info
    quantity_pattern = r'\d+\s*(?:cup|tbsp|tsp|oz|lb|g|kg|ml|clove|bunch|head)\b'
    has_quantities = len(re.findall(quantity_pattern, desc_lower)) >= 3

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


def load_creator_mapping() -> Dict[str, Optional[str]]:
    """
    Load channel → website mapping from config file.

    Returns:
        Dict mapping lowercase channel names to website domains.
        Value is None for channels known to have no recipe site.
        Returns empty dict if config file is missing.
    """
    config_path = CONFIG_DIR / "creator_websites.json"

    if not config_path.exists():
        print(f"  -> Warning: Creator mapping not found at {config_path}")
        return {}

    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
        # Filter out comments
        return {k: v for k, v in data.items() if not k.startswith('_')}
    except (json.JSONDecodeError, IOError) as e:
        print(f"  -> Warning: Could not load creator mapping: {e}")
        return {}


def search_for_recipe_url(
    channel: str,
    title: str,
    site: Optional[str] = None
) -> Optional[str]:
    """
    Search DuckDuckGo for a recipe URL.

    Args:
        channel: YouTube channel name
        title: Video title
        site: Optional domain to restrict search (e.g., "feelgoodfoodie.net")

    Returns:
        Recipe URL if found, None otherwise
    """
    # Clean up title (remove channel name if present, common suffixes)
    clean_title = title
    for suffix in [" | " + channel, " - " + channel, " by " + channel]:
        if clean_title.lower().endswith(suffix.lower()):
            clean_title = clean_title[:-len(suffix)]

    # Build query
    if site:
        query = f'"{clean_title}" recipe site:{site}'
    else:
        query = f'"{channel}" "{clean_title}" recipe'

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5)

            for result in results:
                url = result.get("href", "")

                # Skip excluded domains
                if _is_excluded_domain(url):
                    continue

                # Prefer URLs with /recipe/ in path
                if "/recipe/" in url.lower():
                    return url

                # Accept first non-excluded result
                return url

            return None

    except Exception as e:
        print(f"  -> DuckDuckGo search failed: {e}")
        return None


def search_creator_website(channel: str, title: str) -> Optional[str]:
    """
    Attempt to find recipe URL on creator's website.

    1. Load channel → website mapping
    2. If mapped to null → return None (creator has no site)
    3. If mapped to domain → search that domain
    4. If not mapped → search DuckDuckGo without site restriction

    Args:
        channel: YouTube channel name
        title: Video title

    Returns:
        Recipe URL if found, None otherwise
    """
    # Normalize channel name for lookup
    channel_key = channel.lower().strip()

    # Load mapping
    mapping = load_creator_mapping()

    # Check if channel is in mapping
    if channel_key in mapping:
        site = mapping[channel_key]

        # null means creator has no recipe site - don't search
        if site is None:
            print(f"  -> {channel} has no recipe website (skipping search)")
            return None

        print(f"  -> Searching {site} for \"{title}\"...")
    else:
        site = None
        print(f"  -> Searching web for \"{channel}\" \"{title}\"...")

    url = search_for_recipe_url(channel=channel, title=title, site=site)

    if url:
        print(f"  -> Found: {url}")
    else:
        print(f"  -> No recipe URL found")

    return url
