# Crouton Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import 123 Crouton `.crumb` recipes into KitchenOS Obsidian vault, preserving source links and enriching metadata via Ollama.

**Architecture:** Standalone `import_crouton.py` script that parses Crouton JSON, maps fields to KitchenOS schema, enriches with Ollama, and saves using existing `format_recipe_markdown()` and `format_recipemd()` templates. New `lib/crouton_parser.py` handles all Crouton-specific parsing logic.

**Tech Stack:** Python 3.11, Ollama (mistral:7b), existing KitchenOS template system (templates/recipe_template.py, templates/recipemd_template.py)

**Design doc:** `docs/plans/2026-02-17-crouton-import-design.md`

---

### Task 1: Crouton Unit Mapping

**Files:**
- Create: `tests/test_crouton_parser.py`
- Create: `lib/crouton_parser.py`

**Step 1: Write the failing test for unit mapping**

```python
"""Tests for Crouton .crumb file parser"""

import pytest
from lib.crouton_parser import map_quantity_type


class TestMapQuantityType:
    """Maps Crouton quantityType enum to KitchenOS unit strings"""

    def test_cup(self):
        assert map_quantity_type("CUP") == "cup"

    def test_tablespoon(self):
        assert map_quantity_type("TABLESPOON") == "tbsp"

    def test_teaspoon(self):
        assert map_quantity_type("TEASPOON") == "tsp"

    def test_grams(self):
        assert map_quantity_type("GRAMS") == "g"

    def test_ounce(self):
        assert map_quantity_type("OUNCE") == "oz"

    def test_pound(self):
        assert map_quantity_type("POUND") == "lb"

    def test_fluid_ounce(self):
        assert map_quantity_type("FLUID_OUNCE") == "fl oz"

    def test_mills(self):
        assert map_quantity_type("MILLS") == "ml"

    def test_kgs(self):
        assert map_quantity_type("KGS") == "kg"

    def test_can(self):
        assert map_quantity_type("CAN") == "can"

    def test_bunch(self):
        assert map_quantity_type("BUNCH") == "bunch"

    def test_packet(self):
        assert map_quantity_type("PACKET") == "packet"

    def test_pinch(self):
        assert map_quantity_type("PINCH") == "pinch"

    def test_item(self):
        assert map_quantity_type("ITEM") == "whole"

    def test_unknown_returns_whole(self):
        assert map_quantity_type("UNKNOWN_UNIT") == "whole"

    def test_none_returns_whole(self):
        assert map_quantity_type(None) == "whole"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapQuantityType -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.crouton_parser'`

**Step 3: Write minimal implementation**

```python
"""Parser for Crouton .crumb recipe files.

Crouton is an iOS recipe manager that exports to .crumb JSON files.
See docs/plans/2026-02-17-crouton-import-design.md for full schema reference.
"""

# Crouton quantityType enum → KitchenOS unit string
UNIT_MAP = {
    "CUP": "cup",
    "TABLESPOON": "tbsp",
    "TEASPOON": "tsp",
    "GRAMS": "g",
    "OUNCE": "oz",
    "POUND": "lb",
    "FLUID_OUNCE": "fl oz",
    "MILLS": "ml",
    "KGS": "kg",
    "CAN": "can",
    "BUNCH": "bunch",
    "PACKET": "packet",
    "PINCH": "pinch",
    "ITEM": "whole",
}


def map_quantity_type(quantity_type: str | None) -> str:
    """Map Crouton quantityType to KitchenOS unit string."""
    if not quantity_type:
        return "whole"
    return UNIT_MAP.get(quantity_type, "whole")
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapQuantityType -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tests/test_crouton_parser.py lib/crouton_parser.py
git commit -m "feat: add Crouton unit mapping"
```

---

### Task 2: Crouton Ingredient Parsing

**Files:**
- Modify: `tests/test_crouton_parser.py`
- Modify: `lib/crouton_parser.py`

**Step 1: Write the failing test for ingredient mapping**

Add to `tests/test_crouton_parser.py`:

```python
from lib.crouton_parser import map_ingredient


class TestMapIngredient:
    """Converts Crouton ingredient objects to KitchenOS {amount, unit, item} dicts"""

    def test_standard_ingredient(self):
        """Ingredient with amount and unit"""
        crouton_ing = {
            "order": 0,
            "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "chicken breast"},
            "quantity": {"amount": 1, "quantityType": "POUND"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 1, "unit": "lb", "item": "chicken breast", "inferred": False}

    def test_item_quantity(self):
        """Ingredient measured in items (whole)"""
        crouton_ing = {
            "order": 0,
            "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "jalapeno"},
            "quantity": {"amount": 1, "quantityType": "ITEM"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 1, "unit": "whole", "item": "jalapeno", "inferred": False}

    def test_no_quantity(self):
        """Ingredient with no quantity (e.g., 'to taste salt')"""
        crouton_ing = {
            "order": 0,
            "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "to taste salt"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": "", "unit": "", "item": "to taste salt", "inferred": False}

    def test_fractional_amount(self):
        """Amount is a float"""
        crouton_ing = {
            "order": 0,
            "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "butter"},
            "quantity": {"amount": 2.5, "quantityType": "TABLESPOON"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 2.5, "unit": "tbsp", "item": "butter", "inferred": False}
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapIngredient -v`
Expected: FAIL with `ImportError: cannot import name 'map_ingredient'`

**Step 3: Write minimal implementation**

Add to `lib/crouton_parser.py`:

```python
def map_ingredient(crouton_ing: dict) -> dict:
    """Convert a Crouton ingredient object to KitchenOS format.

    Crouton format: {ingredient: {name: str}, quantity?: {amount, quantityType}}
    KitchenOS format: {amount, unit, item, inferred}
    """
    name = crouton_ing.get("ingredient", {}).get("name", "")
    quantity = crouton_ing.get("quantity")

    if quantity:
        amount = quantity.get("amount", "")
        unit = map_quantity_type(quantity.get("quantityType"))
    else:
        amount = ""
        unit = ""

    return {
        "amount": amount,
        "unit": unit,
        "item": name,
        "inferred": False,
    }
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapIngredient -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tests/test_crouton_parser.py lib/crouton_parser.py
git commit -m "feat: add Crouton ingredient mapping"
```

---

### Task 3: Crouton Step Parsing

**Files:**
- Modify: `tests/test_crouton_parser.py`
- Modify: `lib/crouton_parser.py`

**Step 1: Write the failing test for step mapping**

Add to `tests/test_crouton_parser.py`:

```python
from lib.crouton_parser import map_steps


class TestMapSteps:
    """Converts Crouton step arrays to KitchenOS instruction dicts"""

    def test_simple_steps(self):
        """Steps without sections"""
        crouton_steps = [
            {"order": 0, "uuid": "a", "isSection": False, "step": "Preheat oven to 350F."},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Mix dry ingredients."},
        ]
        result = map_steps(crouton_steps)
        assert result == [
            {"step": 1, "text": "Preheat oven to 350F.", "time": None},
            {"step": 2, "text": "Mix dry ingredients.", "time": None},
        ]

    def test_steps_with_section_header(self):
        """Section headers become prefixed in the next steps' text"""
        crouton_steps = [
            {"order": 0, "uuid": "a", "isSection": True, "step": "For the Sauce"},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Heat oil in a pan."},
            {"order": 2, "uuid": "c", "isSection": False, "step": "Add garlic."},
        ]
        result = map_steps(crouton_steps)
        assert result == [
            {"step": 1, "text": "**For the Sauce** — Heat oil in a pan.", "time": None},
            {"step": 2, "text": "Add garlic.", "time": None},
        ]

    def test_sorts_by_order(self):
        """Steps should be sorted by order field"""
        crouton_steps = [
            {"order": 2, "uuid": "c", "isSection": False, "step": "Third."},
            {"order": 0, "uuid": "a", "isSection": False, "step": "First."},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Second."},
        ]
        result = map_steps(crouton_steps)
        assert result[0]["text"] == "First."
        assert result[1]["text"] == "Second."
        assert result[2]["text"] == "Third."

    def test_empty_steps(self):
        result = map_steps([])
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapSteps -v`
Expected: FAIL with `ImportError: cannot import name 'map_steps'`

**Step 3: Write minimal implementation**

Add to `lib/crouton_parser.py`:

```python
def map_steps(crouton_steps: list) -> list:
    """Convert Crouton steps to KitchenOS instruction format.

    Handles isSection=True steps as bold section headers prepended to
    the following step's text.
    """
    if not crouton_steps:
        return []

    # Sort by order field
    sorted_steps = sorted(crouton_steps, key=lambda s: s.get("order", 0))

    instructions = []
    pending_section = None
    step_num = 1

    for s in sorted_steps:
        if s.get("isSection"):
            pending_section = s.get("step", "")
            continue

        text = s.get("step", "")
        if pending_section:
            text = f"**{pending_section}** — {text}"
            pending_section = None

        instructions.append({
            "step": step_num,
            "text": text,
            "time": None,
        })
        step_num += 1

    return instructions
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestMapSteps -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tests/test_crouton_parser.py lib/crouton_parser.py
git commit -m "feat: add Crouton step parsing with section headers"
```

---

### Task 4: Full Crumb File Parser

**Files:**
- Modify: `tests/test_crouton_parser.py`
- Modify: `lib/crouton_parser.py`

**Step 1: Write the failing test for parse_crumb_file**

Add to `tests/test_crouton_parser.py`:

```python
import json
from lib.crouton_parser import parse_crumb_file


class TestParseCrumbFile:
    """Parses a complete .crumb JSON file into KitchenOS recipe_data dict"""

    def _make_crumb(self, **overrides):
        """Helper to build a minimal .crumb dict"""
        base = {
            "name": "Test Recipe",
            "uuid": "abc-123",
            "serves": 4,
            "duration": 15,
            "cookingDuration": 30,
            "webLink": "https://example.com/recipe",
            "sourceName": "Test Kitchen",
            "notes": "Some notes here",
            "tags": [],
            "ingredients": [
                {
                    "order": 0,
                    "uuid": "i1",
                    "ingredient": {"uuid": "ig1", "name": "flour"},
                    "quantity": {"amount": 2, "quantityType": "CUP"},
                },
            ],
            "steps": [
                {"order": 0, "uuid": "s1", "isSection": False, "step": "Mix it."},
            ],
            "defaultScale": 1,
            "isPublicRecipe": False,
            "folderIDs": [],
            "images": [],
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert result["recipe_name"] == "Test Recipe"
        assert result["servings"] == 4
        assert result["source_url"] == "https://example.com/recipe"
        assert result["source_channel"] == "Test Kitchen"
        assert result["recipe_source"] == "crouton_import"
        assert result["needs_review"] is True

    def test_time_formatting(self):
        data = self._make_crumb(duration=15, cookingDuration=30)
        result = parse_crumb_file(data)
        assert result["prep_time"] == "15 minutes"
        assert result["cook_time"] == "30 minutes"

    def test_no_time(self):
        data = self._make_crumb(duration=0, cookingDuration=0)
        result = parse_crumb_file(data)
        assert result["prep_time"] is None
        assert result["cook_time"] is None

    def test_ingredients_mapped(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert len(result["ingredients"]) == 1
        assert result["ingredients"][0]["item"] == "flour"
        assert result["ingredients"][0]["unit"] == "cup"

    def test_steps_mapped(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert len(result["instructions"]) == 1
        assert result["instructions"][0]["text"] == "Mix it."

    def test_url_from_notes_fallback(self):
        """When webLink is empty, extract URL from notes"""
        data = self._make_crumb(
            webLink="",
            notes="Recipe: https://www.youtube.com/watch?v=abc123\nEnjoy!"
        )
        result = parse_crumb_file(data)
        assert result["source_url"] == "https://www.youtube.com/watch?v=abc123"

    def test_notes_preserved(self):
        data = self._make_crumb(notes="My personal notes here")
        result = parse_crumb_file(data)
        assert result["notes"] == "My personal notes here"

    def test_no_serves(self):
        data = self._make_crumb()
        del data["serves"]
        result = parse_crumb_file(data)
        assert result["servings"] is None

    def test_missing_optional_fields(self):
        """Handles .crumb files missing optional fields"""
        data = {
            "name": "Minimal Recipe",
            "uuid": "abc",
            "ingredients": [],
            "steps": [],
            "defaultScale": 1,
            "isPublicRecipe": False,
            "folderIDs": [],
            "images": [],
            "tags": [],
        }
        result = parse_crumb_file(data)
        assert result["recipe_name"] == "Minimal Recipe"
        assert result["source_url"] == ""
        assert result["source_channel"] == ""
        assert result["servings"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestParseCrumbFile -v`
Expected: FAIL with `ImportError: cannot import name 'parse_crumb_file'`

**Step 3: Write minimal implementation**

Add to `lib/crouton_parser.py`:

```python
import re


def extract_url_from_text(text: str) -> str:
    """Extract first URL from free text."""
    match = re.search(r'https?://\S+', text)
    return match.group(0) if match else ""


def format_duration(minutes: int | None) -> str | None:
    """Convert minutes integer to readable string."""
    if not minutes:
        return None
    if minutes == 60:
        return "1 hour"
    if minutes > 60:
        h = minutes // 60
        m = minutes % 60
        if m == 0:
            return f"{h} hours"
        return f"{h} hours {m} minutes"
    return f"{minutes} minutes"


def parse_crumb_file(crumb_data: dict) -> dict:
    """Parse a Crouton .crumb JSON dict into KitchenOS recipe_data format.

    Args:
        crumb_data: Parsed JSON from a .crumb file

    Returns:
        dict matching the recipe_data schema expected by format_recipe_markdown()
    """
    name = crumb_data.get("name", "Untitled Recipe")

    # Source URL: prefer webLink, fall back to URL in notes
    web_link = crumb_data.get("webLink", "")
    notes = crumb_data.get("notes", "")
    source_url = web_link or extract_url_from_text(notes)

    # Map ingredients
    ingredients = [
        map_ingredient(ing)
        for ing in sorted(
            crumb_data.get("ingredients", []),
            key=lambda i: i.get("order", 0),
        )
    ]

    # Map steps
    instructions = map_steps(crumb_data.get("steps", []))

    # Time
    duration = crumb_data.get("duration", 0)
    cooking_duration = crumb_data.get("cookingDuration", 0)

    return {
        "recipe_name": name,
        "source_url": source_url,
        "source_channel": crumb_data.get("sourceName", ""),
        "recipe_source": "crouton_import",
        "servings": crumb_data.get("serves"),
        "prep_time": format_duration(duration),
        "cook_time": format_duration(cooking_duration),
        "ingredients": ingredients,
        "instructions": instructions,
        "notes": notes,
        "needs_review": True,
        "confidence_notes": "Imported from Crouton app. Metadata enriched by AI.",
        # Fields to be filled by Ollama enrichment (or left null)
        "description": "",
        "cuisine": None,
        "protein": None,
        "difficulty": None,
        "dish_type": None,
        "meal_occasion": [],
        "dietary": [],
        "equipment": [],
    }
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_crouton_parser.py::TestParseCrumbFile -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tests/test_crouton_parser.py lib/crouton_parser.py
git commit -m "feat: add full .crumb file parser"
```

---

### Task 5: Ollama Enrichment Prompt

**Files:**
- Create: `prompts/crouton_enrichment.py`

**Step 1: Write the enrichment prompt module**

This task doesn't have a meaningful unit test (it's a prompt template). Write the module directly.

```python
"""Prompt for enriching Crouton imports with AI-inferred metadata.

Used by import_crouton.py to classify recipes that Crouton exports
without metadata like cuisine, difficulty, or dish type.
"""

import json

CROUTON_ENRICHMENT_PROMPT = """You are classifying a recipe that was imported from a recipe app.
The recipe already has ingredients and instructions. You need to infer the metadata.

Rules:
- Base your answers ONLY on the recipe name, ingredients, and instructions provided
- If a field cannot be determined, use null
- Be conservative — only classify what is clearly evident
- For meal_occasion, pick 1-3 that best fit from: weeknight-dinner, grab-and-go-breakfast, meal-prep, weekend-project, packed-lunch, afternoon-snack, date-night, post-workout, crowd-pleaser, lazy-sunday

Output valid JSON matching this schema:
{
  "description": "string (1-2 sentence summary of the dish)",
  "cuisine": "string or null (e.g., Italian, Mexican, Indian, American)",
  "protein": "string or null (main protein: chicken, beef, tofu, etc.)",
  "difficulty": "easy|medium|hard or null",
  "dish_type": "string or null (e.g., Main, Side, Dessert, Snack, Breakfast, Soup, Salad, Drink)",
  "meal_occasion": ["array of 1-3 strings"],
  "dietary": ["array of tags like vegetarian, vegan, gluten-free, dairy-free — empty if none"],
  "equipment": ["array of notable equipment like oven, blender, slow cooker — empty if basic"]
}"""


def build_enrichment_prompt(recipe_name: str, ingredients: list, instructions: list) -> str:
    """Build user prompt for Ollama enrichment.

    Args:
        recipe_name: Name of the recipe
        ingredients: List of {amount, unit, item} dicts
        instructions: List of {step, text} dicts

    Returns:
        Formatted prompt string
    """
    # Compact ingredient list
    ing_lines = []
    for ing in ingredients:
        amount = ing.get("amount", "")
        unit = ing.get("unit", "")
        item = ing.get("item", "")
        if amount and unit:
            ing_lines.append(f"- {amount} {unit} {item}")
        elif amount:
            ing_lines.append(f"- {amount} {item}")
        else:
            ing_lines.append(f"- {item}")

    # Compact instruction list
    step_lines = [
        f"{s.get('step', i+1)}. {s.get('text', '')}"
        for i, s in enumerate(instructions)
    ]

    return f"""Classify this recipe:

RECIPE: {recipe_name}

INGREDIENTS:
{chr(10).join(ing_lines)}

INSTRUCTIONS:
{chr(10).join(step_lines)}"""
```

**Step 2: Commit**

```bash
git add prompts/crouton_enrichment.py
git commit -m "feat: add Ollama enrichment prompt for Crouton imports"
```

---

### Task 6: Import Script — Core Logic

**Files:**
- Create: `import_crouton.py`

This is the main script. It ties together the parser, enrichment, and template system.

**Step 1: Write the import script**

```python
#!/usr/bin/env python3
"""
Import recipes from Crouton iOS app (.crumb files) into KitchenOS Obsidian vault.

Usage:
    python import_crouton.py "/path/to/Crouton Recipes"
    python import_crouton.py --dry-run "/path/to/Crouton Recipes"
    python import_crouton.py --no-enrich "/path/to/Crouton Recipes"
"""

import argparse
import json
import sys
import re
import requests
from datetime import date
from pathlib import Path

from lib.crouton_parser import parse_crumb_file
from prompts.crouton_enrichment import CROUTON_ENRICHMENT_PROMPT, build_enrichment_prompt
from templates.recipe_template import format_recipe_markdown, generate_filename, generate_tools_callout
from templates.recipemd_template import format_recipemd, generate_recipemd_filename

# Configuration (matches extract_recipe.py)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
OBSIDIAN_RECIPES_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents"
    "/iCloud~md~obsidian/Documents/KitchenOS/Recipes"
)


def enrich_with_ollama(recipe_data: dict) -> dict:
    """Call Ollama to infer missing metadata fields.

    Args:
        recipe_data: Parsed recipe data from parse_crumb_file()

    Returns:
        Updated recipe_data with enriched fields (or unchanged on failure)
    """
    prompt = (
        f"{CROUTON_ENRICHMENT_PROMPT}\n\n"
        f"{build_enrichment_prompt(recipe_data['recipe_name'], recipe_data['ingredients'], recipe_data['instructions'])}"
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        response.raise_for_status()
        result = json.loads(response.json().get("response", "{}"))

        # Merge enriched fields into recipe_data
        for field in ("description", "cuisine", "protein", "difficulty", "dish_type"):
            val = result.get(field)
            if val and isinstance(val, str):
                recipe_data[field] = val

        # List fields
        for field in ("meal_occasion", "dietary", "equipment"):
            val = result.get(field)
            if val and isinstance(val, list):
                recipe_data[field] = val

        # Normalize meal_occasion to slugified strings
        occasion = recipe_data.get("meal_occasion", [])
        if isinstance(occasion, str):
            occasion = [occasion]
        recipe_data["meal_occasion"] = [
            o.strip().lower().replace(" ", "-")
            for o in occasion
            if o and isinstance(o, str)
        ][:3]

        return recipe_data

    except Exception as e:
        print(f"    Ollama enrichment failed: {e}", file=sys.stderr)
        return recipe_data


def check_duplicate(recipe_name: str) -> bool:
    """Check if a recipe with this name already exists in the vault."""
    filename = generate_filename(recipe_name)
    return (OBSIDIAN_RECIPES_PATH / filename).exists()


def save_imported_recipe(recipe_data: dict) -> Path:
    """Save a Crouton-imported recipe to the Obsidian vault.

    Handles duplicate naming and generates both main + Cooking Mode files.

    Returns:
        Path to the saved main recipe file.
    """
    recipe_name = recipe_data["recipe_name"]
    is_duplicate = check_duplicate(recipe_name)

    if is_duplicate:
        recipe_name_for_file = f"{recipe_name} (Crouton)"
    else:
        recipe_name_for_file = recipe_name

    # Generate markdown using existing template
    # We pass source_url as video_url and source_channel as channel
    source_url = recipe_data.get("source_url", "")
    source_channel = recipe_data.get("source_channel", "") or "Crouton"
    today = date.today().isoformat()

    # For the template, we use source_channel as "video_title" display
    # since these aren't YouTube videos
    video_title = f"Crouton — {source_channel}" if source_channel != "Crouton" else "Crouton"

    # Override recipe_name for filename generation (but keep original in data)
    file_recipe_data = dict(recipe_data)
    file_recipe_data["recipe_name"] = recipe_name_for_file

    markdown = format_recipe_markdown(
        file_recipe_data,
        video_url=source_url,
        video_title=video_title,
        channel=source_channel,
        date_added=today,
    )

    # Replace the footer line to say "Imported from Crouton" instead of "Extracted from"
    old_footer_pattern = f"*Extracted from [{re.escape(video_title)}]({re.escape(source_url)}) on {today}*"
    if source_url:
        new_footer = f"*Imported from Crouton — [source]({source_url}) on {today}*"
    else:
        new_footer = f"*Imported from Crouton on {today}*"
    # Use simple string replacement (escape regex chars in the pattern)
    markdown = re.sub(
        r'\*Extracted from \[.*?\]\(.*?\) on ' + re.escape(today) + r'\*',
        new_footer,
        markdown,
    )

    # Inject Crouton notes into My Notes section if present
    crouton_notes = recipe_data.get("notes", "")
    if crouton_notes:
        empty_notes = "## My Notes\n\n<!-- Your personal notes, ratings, and modifications go here -->"
        filled_notes = f"## My Notes\n\n*From Crouton:*\n{crouton_notes}"
        markdown = markdown.replace(empty_notes, filled_notes)

    # Write main recipe file
    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)
    filename = generate_filename(recipe_name_for_file)
    filepath = OBSIDIAN_RECIPES_PATH / filename
    filepath.write_text(markdown, encoding="utf-8")

    # Write Cooking Mode file
    recipemd_content = format_recipemd(
        file_recipe_data,
        video_url=source_url,
        video_title=video_title,
        channel=source_channel,
    )
    recipemd_dir = OBSIDIAN_RECIPES_PATH / "Cooking Mode"
    recipemd_dir.mkdir(parents=True, exist_ok=True)
    recipemd_filename = generate_recipemd_filename(recipe_name_for_file)
    recipemd_path = recipemd_dir / recipemd_filename
    recipemd_path.write_text(recipemd_content, encoding="utf-8")

    return filepath, is_duplicate


def main():
    parser = argparse.ArgumentParser(
        description="Import Crouton .crumb recipes into KitchenOS"
    )
    parser.add_argument(
        "crouton_dir",
        type=str,
        help="Path to folder containing .crumb files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without writing files",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip Ollama enrichment (faster, but metadata fields will be null)",
    )
    args = parser.parse_args()

    crouton_dir = Path(args.crouton_dir)
    if not crouton_dir.is_dir():
        print(f"Error: {crouton_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    crumb_files = sorted(crouton_dir.glob("*.crumb"))
    if not crumb_files:
        print(f"No .crumb files found in {crouton_dir}")
        sys.exit(0)

    total = len(crumb_files)
    imported = 0
    duplicates = 0
    failed = 0

    print(f"Found {total} .crumb files in {crouton_dir}")
    if args.dry_run:
        print("DRY RUN — no files will be written\n")
    if args.no_enrich:
        print("Skipping Ollama enrichment\n")

    for i, crumb_path in enumerate(crumb_files, 1):
        prefix = f"[{i:3d}/{total}]"

        try:
            with open(crumb_path, encoding="utf-8") as f:
                crumb_data = json.load(f)

            recipe_data = parse_crumb_file(crumb_data)
            recipe_name = recipe_data["recipe_name"]
            is_dup = check_duplicate(recipe_name)
            dup_label = " (duplicate)" if is_dup else ""

            if args.dry_run:
                suffix = f" → {recipe_name} (Crouton).md" if is_dup else ""
                print(f"{prefix} {recipe_name}{dup_label}{suffix}")
                if is_dup:
                    duplicates += 1
                imported += 1
                continue

            # Enrich with Ollama
            if not args.no_enrich:
                print(f"{prefix} {recipe_name}{dup_label} ... enriching", end="", flush=True)
                recipe_data = enrich_with_ollama(recipe_data)
                print(" ... ", end="", flush=True)
            else:
                print(f"{prefix} {recipe_name}{dup_label} ... ", end="", flush=True)

            # Save
            filepath, was_dup = save_imported_recipe(recipe_data)
            print(f"saved → {filepath.name}")

            imported += 1
            if was_dup:
                duplicates += 1

        except Exception as e:
            print(f"{prefix} {crumb_path.stem} ... FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {imported} imported ({duplicates} duplicates), {failed} failed")


if __name__ == "__main__":
    main()
```

**Step 2: Test with --dry-run**

Run: `.venv/bin/python import_crouton.py --dry-run "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026"`

Expected: Lists all 123 recipes with duplicate markers, no files written.

**Step 3: Commit**

```bash
git add import_crouton.py
git commit -m "feat: add Crouton import script with --dry-run and --no-enrich"
```

---

### Task 7: Test Dry Run and Fix Issues

**Files:**
- Modify: `import_crouton.py` (if needed)
- Modify: `lib/crouton_parser.py` (if needed)

**Step 1: Run dry-run against real data**

Run: `.venv/bin/python import_crouton.py --dry-run "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026"`

Expected: All 123 recipes listed without errors. Fix any parsing issues that surface.

**Step 2: Run --no-enrich import of first 3 recipes to verify output**

Manually test by temporarily limiting the loop or by creating a test folder with 3 .crumb files:

Run:
```bash
mkdir -p /tmp/crouton-test
cp "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026/Butter Chicken.crumb" /tmp/crouton-test/
cp "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026/BEEF BIRRIA.crumb" /tmp/crouton-test/
cp "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026/Baked Mac and Cheese.crumb" /tmp/crouton-test/
.venv/bin/python import_crouton.py --no-enrich /tmp/crouton-test
```

Expected: 3 recipe files created in Obsidian vault. Verify:
- YAML frontmatter is valid
- Ingredients table looks correct
- Source URLs preserved in frontmatter
- Cooking Mode files created
- Footer says "Imported from Crouton"
- My Notes section has Crouton notes where present

**Step 3: Verify one duplicate is handled correctly**

The "19 Calorie Fudgy Brownies.crumb" should already exist in the vault. Copy it to the test folder and verify it creates "(Crouton)" suffixed file.

**Step 4: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix: address issues found during Crouton import testing"
```

---

### Task 8: Full Import Run

**Files:**
- No code changes — this is the real import run

**Step 1: Verify Ollama is running**

Run: `curl http://localhost:11434/api/tags`
Expected: JSON response listing available models including `mistral:7b`

**Step 2: Run full import with enrichment**

Run: `.venv/bin/python import_crouton.py "/Users/chaseeasterling/Documents/Crouton Recipes - Feb 17, 2026"`

Expected: All 123 recipes imported with Ollama enrichment. ~5-6 minutes total. Watch for failures in output.

**Step 3: Verify results in Obsidian vault**

- Open Obsidian, check that new recipes appear
- Spot-check 3-4 recipes for correct formatting
- Verify duplicates have "(Crouton)" suffix
- Check that Dataview queries pick up new recipes

**Step 4: Commit if any final fixes needed**

---

### Task 9: Run All Tests and Update Docs

**Files:**
- Modify: `CLAUDE.md` (add import_crouton.py docs)

**Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS (including new tests)

**Step 2: Update CLAUDE.md**

Add to the "Running Commands" section:

```markdown
### Import from Crouton

\```bash
# Import all .crumb files from a Crouton export folder
.venv/bin/python import_crouton.py "/path/to/Crouton Recipes"

# Preview without importing
.venv/bin/python import_crouton.py --dry-run "/path/to/Crouton Recipes"

# Import without Ollama enrichment (faster, metadata will be null)
.venv/bin/python import_crouton.py --no-enrich "/path/to/Crouton Recipes"
\```
```

Add to the "Core Components" table:

```
| `import_crouton.py` | Imports Crouton .crumb files into Obsidian vault |
| `lib/crouton_parser.py` | Parses Crouton .crumb JSON format |
| `prompts/crouton_enrichment.py` | AI prompt for classifying imported recipes |
```

Add to the "Key Functions" section:

```markdown
**lib/crouton_parser.py:**
- `parse_crumb_file()` - Parses .crumb JSON dict into KitchenOS recipe_data format
- `map_quantity_type()` - Maps Crouton quantityType enum to unit string
- `map_ingredient()` - Converts Crouton ingredient object to {amount, unit, item}
- `map_steps()` - Converts Crouton steps with section header support
```

**Step 3: Commit**

```bash
git add CLAUDE.md tests/test_crouton_parser.py lib/crouton_parser.py prompts/crouton_enrichment.py import_crouton.py
git commit -m "docs: add Crouton import to CLAUDE.md"
```
