# Recipe Link Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add recipe link detection to check video descriptions for recipe URLs before AI extraction.

**Architecture:** Priority chain (Webpage → Description → AI extraction). New `recipe_sources.py` module handles link detection, webpage scraping, description parsing, and tips extraction. Integrates with existing `extract_recipe.py`.

**Tech Stack:** Python 3.9, BeautifulSoup4 (new), requests, Ollama/mistral:7b

---

## Task 1: Add BeautifulSoup Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add beautifulsoup4 to requirements**

Add to `requirements.txt`:
```
beautifulsoup4>=4.12.0
```

**Step 2: Install in worktree venv**

Run: `.venv/bin/pip install beautifulsoup4`
Expected: Successfully installed beautifulsoup4

**Step 3: Verify import works**

Run: `.venv/bin/python -c "from bs4 import BeautifulSoup; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add beautifulsoup4 dependency

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create recipe_sources.py with find_recipe_link()

**Files:**
- Create: `recipe_sources.py`
- Create: `tests/test_recipe_sources.py`

**Step 1: Create tests directory and test file**

Create `tests/__init__.py` (empty file).

Create `tests/test_recipe_sources.py`:
```python
"""Tests for recipe_sources module"""

import pytest
from recipe_sources import find_recipe_link


class TestFindRecipeLink:
    """Tests for find_recipe_link function"""

    def test_explicit_recipe_label(self):
        """Finds URL after 'Recipe:' label"""
        description = """Check out my channel!
Recipe: https://www.bingingwithbabish.com/recipes/pasta
Follow me on Instagram"""
        result = find_recipe_link(description)
        assert result == "https://www.bingingwithbabish.com/recipes/pasta"

    def test_full_recipe_label(self):
        """Finds URL after 'Full recipe:' label"""
        description = "Full recipe: https://example.com/recipe"
        result = find_recipe_link(description)
        assert result == "https://example.com/recipe"

    def test_nearby_keyword(self):
        """Finds URL on same line as 'recipe' keyword"""
        description = "Get the recipe here: https://seriouseats.com/pasta"
        result = find_recipe_link(description)
        assert result == "https://seriouseats.com/pasta"

    def test_known_domain(self):
        """Finds URL from known recipe domain without keyword"""
        description = """Links:
https://www.bonappetit.com/recipe/chicken
https://patreon.com/channel"""
        result = find_recipe_link(description)
        assert result == "https://www.bonappetit.com/recipe/chicken"

    def test_excludes_social_media(self):
        """Ignores social media URLs"""
        description = """Recipe links:
https://instagram.com/chef
https://twitter.com/chef"""
        result = find_recipe_link(description)
        assert result is None

    def test_excludes_affiliate_links(self):
        """Ignores Amazon affiliate URLs"""
        description = "Buy the pan: https://amzn.to/abc123"
        result = find_recipe_link(description)
        assert result is None

    def test_excludes_youtube(self):
        """Ignores YouTube URLs"""
        description = "Watch this: https://youtube.com/watch?v=abc"
        result = find_recipe_link(description)
        assert result is None

    def test_no_recipe_link(self):
        """Returns None when no recipe link found"""
        description = "Thanks for watching! Like and subscribe."
        result = find_recipe_link(description)
        assert result is None

    def test_first_match_wins(self):
        """Returns first matching URL"""
        description = """Recipe: https://first.com/recipe
Recipe: https://second.com/recipe"""
        result = find_recipe_link(description)
        assert result == "https://first.com/recipe"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'recipe_sources'"

**Step 3: Create recipe_sources.py with find_recipe_link**

Create `recipe_sources.py`:
```python
"""Recipe source extraction: webpage scraping, description parsing, tips extraction"""

import re
from typing import Optional


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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add recipe_sources.py tests/
git commit -m "feat: add find_recipe_link for detecting recipe URLs

Detects recipe links via explicit labels, nearby keywords,
or known recipe domains. Excludes social media and affiliates.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add scrape_recipe_from_url() with JSON-LD parsing

**Files:**
- Modify: `recipe_sources.py`
- Modify: `tests/test_recipe_sources.py`

**Step 1: Add tests for JSON-LD scraping**

Add to `tests/test_recipe_sources.py`:
```python
from recipe_sources import find_recipe_link, scrape_recipe_from_url, parse_json_ld_recipe


class TestParseJsonLdRecipe:
    """Tests for JSON-LD recipe parsing"""

    def test_parses_basic_recipe(self):
        """Parses standard Schema.org Recipe"""
        json_ld = {
            "@type": "Recipe",
            "name": "Pasta Aglio e Olio",
            "description": "A simple garlic pasta",
            "prepTime": "PT10M",
            "cookTime": "PT15M",
            "recipeYield": "4 servings",
            "recipeIngredient": [
                "1/2 lb linguine",
                "4 cloves garlic",
            ],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Boil pasta"},
                {"@type": "HowToStep", "text": "Saute garlic"},
            ],
            "recipeCuisine": "Italian",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["recipe_name"] == "Pasta Aglio e Olio"
        assert result["description"] == "A simple garlic pasta"
        assert result["prep_time"] == "10 minutes"
        assert result["cook_time"] == "15 minutes"
        assert result["cuisine"] == "Italian"
        assert len(result["ingredients"]) == 2
        assert len(result["instructions"]) == 2

    def test_handles_string_instructions(self):
        """Handles instructions as plain strings"""
        json_ld = {
            "@type": "Recipe",
            "name": "Simple Recipe",
            "recipeInstructions": [
                "Step one",
                "Step two",
            ],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["instructions"][0]["text"] == "Step one"
        assert result["instructions"][1]["step"] == 2

    def test_handles_single_instruction_string(self):
        """Handles single instruction as string"""
        json_ld = {
            "@type": "Recipe",
            "name": "Simple Recipe",
            "recipeInstructions": "Mix everything and bake.",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["instructions"][0]["text"] == "Mix everything and bake."

    def test_parses_iso_duration(self):
        """Parses ISO 8601 duration format"""
        json_ld = {
            "@type": "Recipe",
            "name": "Test",
            "prepTime": "PT1H30M",
            "cookTime": "PT45M",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["prep_time"] == "1 hour 30 minutes"
        assert result["cook_time"] == "45 minutes"

    def test_handles_missing_fields(self):
        """Returns None for missing optional fields"""
        json_ld = {
            "@type": "Recipe",
            "name": "Minimal Recipe",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["recipe_name"] == "Minimal Recipe"
        assert result["prep_time"] is None
        assert result["ingredients"] == []
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestParseJsonLdRecipe -v`
Expected: FAIL with "cannot import name 'parse_json_ld_recipe'"

**Step 3: Add parse_json_ld_recipe function**

Add to `recipe_sources.py`:
```python
import json
import re
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup


def parse_iso_duration(iso_duration: str) -> Optional[str]:
    """
    Parse ISO 8601 duration to human-readable string.

    Examples:
        PT10M -> "10 minutes"
        PT1H30M -> "1 hour 30 minutes"
        PT2H -> "2 hours"
    """
    if not iso_duration:
        return None

    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
    if not match:
        return iso_duration  # Return as-is if not ISO format

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


def parse_json_ld_recipe(json_ld: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a Schema.org Recipe JSON-LD object into our recipe format.
    """
    recipe = {
        "recipe_name": json_ld.get("name", "Untitled Recipe"),
        "description": json_ld.get("description"),
        "prep_time": parse_iso_duration(json_ld.get("prepTime")),
        "cook_time": parse_iso_duration(json_ld.get("cookTime")),
        "total_time": parse_iso_duration(json_ld.get("totalTime")),
        "servings": _parse_servings(json_ld.get("recipeYield")),
        "difficulty": None,  # Not in Schema.org
        "cuisine": json_ld.get("recipeCuisine"),
        "protein": None,  # Would need to infer from ingredients
        "dish_type": json_ld.get("recipeCategory"),
        "dietary": _parse_dietary(json_ld.get("suitableForDiet", [])),
        "equipment": [],  # Not commonly in JSON-LD
        "ingredients": _parse_ingredients(json_ld.get("recipeIngredient", [])),
        "instructions": _parse_instructions(json_ld.get("recipeInstructions", [])),
        "storage": None,
        "variations": [],
        "nutritional_info": _parse_nutrition(json_ld.get("nutrition")),
        "needs_review": False,  # Structured data is reliable
        "confidence_notes": "Extracted from structured JSON-LD data on recipe webpage.",
    }
    return recipe


def _parse_servings(yield_str) -> Optional[int]:
    """Parse recipeYield to integer servings"""
    if not yield_str:
        return None
    if isinstance(yield_str, int):
        return yield_str
    if isinstance(yield_str, list):
        yield_str = yield_str[0] if yield_str else ""
    match = re.search(r'(\d+)', str(yield_str))
    return int(match.group(1)) if match else None


def _parse_dietary(diets) -> List[str]:
    """Parse suitableForDiet to dietary tags"""
    if not diets:
        return []
    if isinstance(diets, str):
        diets = [diets]
    # Convert Schema.org diet URLs to simple labels
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
    """Parse recipeIngredient to our format"""
    if not ingredients:
        return []
    result = []
    for ing in ingredients:
        if isinstance(ing, str):
            result.append({
                "quantity": "",
                "item": ing,
                "inferred": False,
            })
        elif isinstance(ing, dict):
            result.append({
                "quantity": ing.get("amount", ""),
                "item": ing.get("name", str(ing)),
                "inferred": False,
            })
    return result


def _parse_instructions(instructions) -> List[Dict[str, Any]]:
    """Parse recipeInstructions to our format"""
    if not instructions:
        return []

    # Handle single string
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
    """Parse nutrition object to string summary"""
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestParseJsonLdRecipe -v`
Expected: All 5 tests PASS

**Step 5: Add tests for scrape_recipe_from_url**

Add to `tests/test_recipe_sources.py`:
```python
from unittest.mock import patch, Mock


class TestScrapeRecipeFromUrl:
    """Tests for scrape_recipe_from_url function"""

    def test_extracts_json_ld_recipe(self):
        """Extracts recipe from JSON-LD script tag"""
        html = '''
        <html>
        <head>
        <script type="application/ld+json">
        {"@type": "Recipe", "name": "Test Recipe", "recipeIngredient": ["1 cup flour"]}
        </script>
        </head>
        <body><h1>Test Recipe</h1></body>
        </html>
        '''
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/recipe")

            assert result is not None
            assert result["recipe_name"] == "Test Recipe"
            assert len(result["ingredients"]) == 1

    def test_handles_graph_json_ld(self):
        """Handles JSON-LD with @graph array"""
        html = '''
        <html>
        <script type="application/ld+json">
        {"@graph": [
            {"@type": "WebPage", "name": "Page"},
            {"@type": "Recipe", "name": "Graph Recipe"}
        ]}
        </script>
        </html>
        '''
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result["recipe_name"] == "Graph Recipe"

    def test_returns_none_on_timeout(self):
        """Returns None on request timeout"""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result is None

    def test_returns_none_on_404(self):
        """Returns None on HTTP error"""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
            mock_get.return_value = mock_response
            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result is None

    def test_returns_none_when_no_recipe_schema(self):
        """Returns None when page has no recipe JSON-LD"""
        html = '<html><body><h1>Not a recipe</h1></body></html>'
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/page")
            assert result is None
```

**Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestScrapeRecipeFromUrl -v`
Expected: FAIL with "cannot import name 'scrape_recipe_from_url'"

**Step 7: Add scrape_recipe_from_url function**

Add to `recipe_sources.py`:
```python
def scrape_recipe_from_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a URL and extract recipe data from JSON-LD.

    Returns:
        Recipe dict if found, None on error or if no recipe schema present
    """
    try:
        response = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; KitchenOS/1.0)"
        })
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  → Failed to fetch {url}: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Find all JSON-LD script tags
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        recipe = _find_recipe_in_json_ld(data)
        if recipe:
            return parse_json_ld_recipe(recipe)

    # No JSON-LD recipe found
    return None


def _find_recipe_in_json_ld(data) -> Optional[Dict[str, Any]]:
    """Find Recipe object in JSON-LD data (handles @graph arrays)"""
    if isinstance(data, dict):
        if data.get("@type") == "Recipe":
            return data
        # Check @graph array
        if "@graph" in data:
            for item in data["@graph"]:
                if isinstance(item, dict) and item.get("@type") == "Recipe":
                    return item
    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_in_json_ld(item)
            if result:
                return result
    return None
```

**Step 8: Run all scraping tests**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py -v`
Expected: All 19 tests PASS

**Step 9: Commit**

```bash
git add recipe_sources.py tests/test_recipe_sources.py
git commit -m "feat: add scrape_recipe_from_url with JSON-LD parsing

Fetches recipe webpages and extracts structured Schema.org Recipe data.
Handles @graph arrays, ISO 8601 durations, various instruction formats.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add parse_recipe_from_description()

**Files:**
- Modify: `recipe_sources.py`
- Modify: `tests/test_recipe_sources.py`
- Modify: `prompts/recipe_extraction.py`

**Step 1: Add test for description parsing**

Add to `tests/test_recipe_sources.py`:
```python
class TestParseRecipeFromDescription:
    """Tests for parse_recipe_from_description function"""

    def test_detects_recipe_in_description(self):
        """Returns True when description looks like a recipe"""
        description = """
*Ingredients*
1/2 cup flour
2 eggs

*Method*
Mix and bake.
"""
        from recipe_sources import has_recipe_in_description
        assert has_recipe_in_description(description) is True

    def test_rejects_non_recipe_description(self):
        """Returns False for descriptions without recipe"""
        description = "Thanks for watching! Subscribe for more."
        from recipe_sources import has_recipe_in_description
        assert has_recipe_in_description(description) is False
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestParseRecipeFromDescription -v`
Expected: FAIL with "cannot import name 'has_recipe_in_description'"

**Step 3: Add has_recipe_in_description function**

Add to `recipe_sources.py`:
```python
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestParseRecipeFromDescription -v`
Expected: 2 tests PASS

**Step 5: Add description extraction prompt**

Add to `prompts/recipe_extraction.py`:
```python
DESCRIPTION_EXTRACTION_PROMPT = """You are extracting a recipe from a YouTube video description.
The description contains a written recipe - parse it accurately.

Rules:
- Extract EXACTLY what is written (no inference needed)
- Parse quantities and ingredients precisely
- Number the instructions in order
- Set needs_review: false (this is explicit text)

Output valid JSON matching this schema:
{
  "recipe_name": "string",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
  "dietary": ["array of tags"],
  "equipment": ["array of items"],
  "ingredients": [
    {"quantity": "string", "item": "string", "inferred": false}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
  "variations": ["array of strings"],
  "needs_review": false,
  "confidence_notes": "Extracted from video description text."
}"""

DESCRIPTION_USER_TEMPLATE = """Extract the recipe from this video description.

VIDEO TITLE: {title}
CHANNEL: {channel}

DESCRIPTION:
{description}"""


def build_description_prompt(title: str, channel: str, description: str) -> str:
    """Build prompt for description recipe extraction"""
    return DESCRIPTION_USER_TEMPLATE.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        description=description or "",
    )
```

**Step 6: Add parse_recipe_from_description function**

Add to `recipe_sources.py`:
```python
from prompts.recipe_extraction import (
    DESCRIPTION_EXTRACTION_PROMPT,
    build_description_prompt,
)

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

    prompt = f"{DESCRIPTION_EXTRACTION_PROMPT}\n\n{build_description_prompt(title, channel, description)}"

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
        print(f"  → Description parsing failed: {e}")
        return None
```

**Step 7: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py -v`
Expected: All 21 tests PASS

**Step 8: Commit**

```bash
git add recipe_sources.py prompts/recipe_extraction.py tests/test_recipe_sources.py
git commit -m "feat: add parse_recipe_from_description

Detects recipes in video descriptions and extracts via Ollama.
Uses dedicated prompt for parsing written recipes.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add extract_cooking_tips()

**Files:**
- Modify: `recipe_sources.py`
- Modify: `prompts/recipe_extraction.py`
- Modify: `tests/test_recipe_sources.py`

**Step 1: Add tips extraction prompt**

Add to `prompts/recipe_extraction.py`:
```python
TIPS_EXTRACTION_PROMPT = """You are extracting cooking tips from a video transcript.
Given a recipe and the video transcript, find practical tips mentioned in the video
that are NOT already in the written recipe.

Focus on:
- Visual/sensory cues ("when you see it turning brown")
- Timing guidance ("this only takes 30 seconds")
- Technique details ("stir constantly")
- Warnings ("be careful not to burn")
- Substitutions mentioned

Exclude:
- Ingredients already listed
- Steps already in instructions
- Banter, jokes, personal stories
- Sponsorships, outros

Return a JSON array of 3-5 short tip strings. If no useful tips found, return [].

Example output:
["Watch for the garlic to turn golden, not brown - it burns quickly",
 "Reserve pasta water before draining - you'll need about 1/4 cup",
 "Let the pan cool slightly before adding the pasta to avoid splattering"]"""

TIPS_USER_TEMPLATE = """Extract cooking tips from this video that aren't in the recipe.

RECIPE:
{recipe_json}

TRANSCRIPT:
{transcript}"""


def build_tips_prompt(recipe: dict, transcript: str) -> str:
    """Build prompt for tips extraction"""
    import json
    return TIPS_USER_TEMPLATE.format(
        recipe_json=json.dumps(recipe, indent=2),
        transcript=transcript or "No transcript available",
    )
```

**Step 2: Add extract_cooking_tips function**

Add to `recipe_sources.py`:
```python
from prompts.recipe_extraction import (
    DESCRIPTION_EXTRACTION_PROMPT,
    build_description_prompt,
    TIPS_EXTRACTION_PROMPT,
    build_tips_prompt,
)


def extract_cooking_tips(transcript: str, recipe: Dict[str, Any]) -> List[str]:
    """
    Extract practical cooking tips from video transcript.

    Tips are things mentioned in the video but not in the written recipe:
    visual cues, timing, techniques, warnings, substitutions.

    Returns:
        List of tip strings (may be empty)
    """
    if not transcript:
        return []

    prompt = f"{TIPS_EXTRACTION_PROMPT}\n\n{build_tips_prompt(recipe, transcript)}"

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

        # Ensure we have a list of strings
        if isinstance(tips, list):
            return [str(t) for t in tips if t][:5]  # Max 5 tips
        return []
    except Exception as e:
        print(f"  → Tips extraction failed: {e}")
        return []
```

**Step 3: Add basic test for tips function**

Add to `tests/test_recipe_sources.py`:
```python
class TestExtractCookingTips:
    """Tests for extract_cooking_tips function"""

    def test_returns_empty_list_for_no_transcript(self):
        """Returns empty list when no transcript"""
        from recipe_sources import extract_cooking_tips
        result = extract_cooking_tips("", {"recipe_name": "Test"})
        assert result == []

    def test_returns_list_type(self):
        """Always returns a list"""
        from recipe_sources import extract_cooking_tips
        result = extract_cooking_tips("", {})
        assert isinstance(result, list)
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestExtractCookingTips -v`
Expected: 2 tests PASS

**Step 5: Commit**

```bash
git add recipe_sources.py prompts/recipe_extraction.py tests/test_recipe_sources.py
git commit -m "feat: add extract_cooking_tips

Extracts practical cooking tips from video transcripts that
aren't in the written recipe. Uses dedicated prompt.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Update template to render video_tips

**Files:**
- Modify: `templates/recipe_template.py`

**Step 1: Update RECIPE_TEMPLATE**

In `templates/recipe_template.py`, update the template to include video tips section.

Find and replace the `{notes_section}` line to add tips before it:
```python
RECIPE_TEMPLATE = '''---
title: "{title}"
source_url: "{source_url}"
source_channel: "{source_channel}"
date_added: {date_added}
video_title: "{video_title}"
recipe_source: "{recipe_source}"

prep_time: {prep_time}
cook_time: {cook_time}
total_time: {total_time}
servings: {servings}
difficulty: {difficulty}

cuisine: {cuisine}
protein: {protein}
dish_type: {dish_type}
dietary: {dietary}

equipment: {equipment}

tags:
{tags}

needs_review: {needs_review}
confidence_notes: "{confidence_notes}"
---

# {title}

> {description}

## Ingredients

{ingredients}

## Instructions

{instructions}

## Equipment

{equipment_list}
{video_tips_section}{notes_section}
---
*Extracted from [{video_title}]({source_url}) on {date_added}*
'''
```

**Step 2: Update format_recipe_markdown function**

Add video_tips formatting to `format_recipe_markdown()`:
```python
def format_recipe_markdown(recipe_data, video_url, video_title, channel):
    """Format recipe data into markdown string"""

    # ... (existing code for ingredients, instructions, etc.)

    # Format video tips section
    video_tips = recipe_data.get('video_tips', [])
    if video_tips:
        tips_lines = ["## Tips from the Video", ""]
        tips_lines.extend(f"- {tip}" for tip in video_tips)
        video_tips_section = "\n".join(tips_lines) + "\n\n"
    else:
        video_tips_section = ""

    # Get recipe source
    recipe_source = recipe_data.get('source', 'ai_extraction')

    return RECIPE_TEMPLATE.format(
        # ... existing fields ...
        recipe_source=recipe_source,
        video_tips_section=video_tips_section,
        # ... rest of fields ...
    )
```

**Step 3: Test template renders correctly**

Run: `.venv/bin/python -c "
from templates.recipe_template import format_recipe_markdown
recipe = {
    'recipe_name': 'Test',
    'description': 'A test recipe',
    'ingredients': [{'quantity': '1 cup', 'item': 'flour', 'inferred': False}],
    'instructions': [{'step': 1, 'text': 'Mix', 'time': None}],
    'equipment': ['bowl'],
    'video_tips': ['Tip 1', 'Tip 2'],
    'source': 'webpage',
}
print(format_recipe_markdown(recipe, 'http://test', 'Test Video', 'Channel'))
"`

Expected: Output includes `## Tips from the Video` section with tips

**Step 4: Commit**

```bash
git add templates/recipe_template.py
git commit -m "feat: add video_tips section to recipe template

Renders tips from video as bullet list after equipment.
Adds recipe_source field to frontmatter.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Integrate into extract_recipe.py

**Files:**
- Modify: `extract_recipe.py`

**Step 1: Add imports for new functions**

Add at top of `extract_recipe.py`:
```python
from recipe_sources import (
    find_recipe_link,
    scrape_recipe_from_url,
    parse_recipe_from_description,
    extract_cooking_tips,
)
```

**Step 2: Update main() function with priority chain**

Replace the extraction logic in `main()`:
```python
def main():
    parser = argparse.ArgumentParser(
        description="Extract recipes from YouTube cooking videos"
    )
    parser.add_argument(
        'url',
        type=str,
        help='YouTube video URL or ID'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print recipe without saving to Obsidian'
    )
    args = parser.parse_args()

    # Parse video ID
    video_id = youtube_parser(args.url)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"Fetching video data for: {video_id}")

    # Get video metadata
    metadata = get_video_metadata(video_id)
    if not metadata:
        print("Error: Could not fetch video metadata", file=sys.stderr)
        sys.exit(1)

    title = metadata['title']
    channel = metadata['channel']
    description = metadata['description']

    print(f"Title: {title}")
    print(f"Channel: {channel}")

    # Get transcript
    transcript_result = get_transcript(video_id)
    transcript = transcript_result['text']

    if not transcript:
        print(f"Warning: No transcript available ({transcript_result.get('error', 'unknown error')})")
    else:
        print(f"Transcript source: {transcript_result['source']}")
        print(f"Transcript length: {len(transcript)} characters")

    # === PRIORITY CHAIN ===
    recipe_data = None
    source = None
    recipe_link = None

    # 1. Check for recipe link in description
    print("\nChecking for recipe link...")
    recipe_link = find_recipe_link(description)

    if recipe_link:
        print(f"  → Found: {recipe_link}")
        print("  → Fetching recipe from webpage...")
        recipe_data = scrape_recipe_from_url(recipe_link)
        if recipe_data:
            source = "webpage"
            print("  ✓ Recipe extracted from webpage")
        else:
            print("  → Webpage scraping failed, trying description...")

    # 2. Try parsing recipe from description
    if not recipe_data:
        print("Checking description for inline recipe...")
        recipe_data = parse_recipe_from_description(description, title, channel)
        if recipe_data:
            source = "description"
            print("  ✓ Recipe extracted from description")
        else:
            print("  → No inline recipe found")

    # 3. Fall back to AI extraction from transcript
    if not recipe_data:
        print(f"\nExtracting recipe via Ollama ({OLLAMA_MODEL})...")
        recipe_data, error = extract_recipe_with_ollama(title, channel, description, transcript)
        if error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)
        source = "ai_extraction"

    # 4. Extract cooking tips if we got recipe from webpage or description
    if source in ("webpage", "description") and transcript:
        print("Extracting cooking tips from video...")
        tips = extract_cooking_tips(transcript, recipe_data)
        recipe_data['video_tips'] = tips
        if tips:
            print(f"  ✓ Found {len(tips)} tips")
        else:
            print("  → No additional tips found")

    # Add source metadata
    recipe_data['source'] = source
    recipe_data['source_url'] = recipe_link

    recipe_name = recipe_data.get('recipe_name', 'Unknown Recipe')
    print(f"\nExtracted: {recipe_name} (source: {source})")

    if args.dry_run:
        # Print markdown to stdout
        markdown = format_recipe_markdown(recipe_data, video_url, title, channel)
        print("\n" + "="*50)
        print("RECIPE MARKDOWN:")
        print("="*50)
        print(markdown)
    else:
        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel)
        print(f"\nSaved to: {filepath}")

    print("\nDone!")
```

**Step 3: Test the full pipeline**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`

Expected:
- Should find recipe link in description
- Should scrape from bingingwithbabish.com
- Should extract tips from transcript
- Should output markdown with "Tips from the Video" section

**Step 4: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: integrate recipe link detection into pipeline

Priority chain: webpage → description → AI extraction.
Extracts cooking tips when using webpage or description source.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

Add to "Key Functions" section:
```markdown
**recipe_sources.py:**
- `find_recipe_link()` - Detects recipe URLs in video descriptions
- `scrape_recipe_from_url()` - Fetches and parses JSON-LD from recipe websites
- `parse_recipe_from_description()` - Extracts inline recipes from descriptions
- `extract_cooking_tips()` - Pulls practical tips from transcripts
```

Update "Architecture" section:
```markdown
### Pipeline Flow

```
YouTube URL → extract_recipe.py
    ↓
main.py (fetch metadata + transcript)
    ↓
recipe_sources.py:
  1. find_recipe_link() → scrape_recipe_from_url()
  2. parse_recipe_from_description()
  3. extract_recipe_with_ollama() (fallback)
    ↓
extract_cooking_tips() (if webpage/description source)
    ↓
template → Obsidian
```
```

Update "Future Enhancements" to mark recipe link detection as complete.

**Step 2: Update README.md**

Add section about recipe sources:
```markdown
## Recipe Sources

KitchenOS extracts recipes using a priority chain:

1. **Webpage** - If description contains a recipe link, scrapes JSON-LD structured data
2. **Description** - If description has inline recipe (ingredients + method), parses it
3. **Transcript** - Falls back to AI extraction from video transcript

When using webpage or description sources, KitchenOS also extracts practical cooking tips from the video that aren't in the written recipe.
```

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update documentation for recipe link detection

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: End-to-end verification

**Step 1: Run full test with Babish video**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`

Verify output shows:
- `Found: https://www.bingingwithbabish.com/recipes/...`
- `Recipe extracted from webpage`
- `Found N tips`
- Markdown includes `recipe_source: "webpage"`
- Markdown includes `## Tips from the Video`

**Step 2: Test fallback to description**

Find a video with inline recipe but no link, or create test:
```bash
.venv/bin/python -c "
from recipe_sources import has_recipe_in_description, parse_recipe_from_description
desc = '''
*Ingredients*
1 cup flour
2 eggs

*Method*
Mix and bake at 350F.
'''
print('Has recipe:', has_recipe_in_description(desc))
"
```

**Step 3: Test fallback to AI extraction**

Run with a video that has no recipe link or inline recipe to verify existing behavior still works.

**Step 4: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues from e2e testing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Add BeautifulSoup dependency |
| 2 | Create `find_recipe_link()` |
| 3 | Add `scrape_recipe_from_url()` with JSON-LD |
| 4 | Add `parse_recipe_from_description()` |
| 5 | Add `extract_cooking_tips()` |
| 6 | Update template for video_tips |
| 7 | Integrate into extract_recipe.py |
| 8 | Update documentation |
| 9 | End-to-end verification |

Each task builds on the previous, with tests written before implementation (TDD).
