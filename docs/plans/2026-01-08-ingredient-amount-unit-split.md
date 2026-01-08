# Ingredient Amount/Unit Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split ingredient "Amount" column into separate "Amount" and "Unit" columns with parsing for informal measurements.

**Architecture:** New `lib/ingredient_parser.py` module handles all parsing. Updates to template, prompts, recipe_sources, and migration script consume this module.

**Tech Stack:** Python 3.9, pytest, regex parsing

---

## Task 1: Create Ingredient Parser - Unit Normalization

**Files:**
- Create: `lib/ingredient_parser.py`
- Create: `tests/test_ingredient_parser.py`

**Step 1: Write failing tests for unit normalization**

```python
# tests/test_ingredient_parser.py
"""Tests for ingredient parser module"""

import pytest
from lib.ingredient_parser import normalize_unit


class TestNormalizeUnit:
    """Tests for unit normalization"""

    def test_tablespoon_variants(self):
        """Normalizes tablespoon variants to tbsp"""
        assert normalize_unit("tablespoon") == "tbsp"
        assert normalize_unit("tablespoons") == "tbsp"
        assert normalize_unit("tbsp") == "tbsp"
        assert normalize_unit("tbs") == "tbsp"

    def test_teaspoon_variants(self):
        """Normalizes teaspoon variants to tsp"""
        assert normalize_unit("teaspoon") == "tsp"
        assert normalize_unit("teaspoons") == "tsp"
        assert normalize_unit("tsp") == "tsp"

    def test_weight_units(self):
        """Normalizes weight units"""
        assert normalize_unit("pound") == "lb"
        assert normalize_unit("pounds") == "lb"
        assert normalize_unit("lb") == "lb"
        assert normalize_unit("lbs") == "lb"
        assert normalize_unit("ounce") == "oz"
        assert normalize_unit("ounces") == "oz"
        assert normalize_unit("gram") == "g"
        assert normalize_unit("grams") == "g"

    def test_volume_units(self):
        """Normalizes volume units"""
        assert normalize_unit("cup") == "cup"
        assert normalize_unit("cups") == "cup"
        assert normalize_unit("milliliter") == "ml"
        assert normalize_unit("milliliters") == "ml"

    def test_count_units(self):
        """Normalizes count units"""
        assert normalize_unit("clove") == "clove"
        assert normalize_unit("cloves") == "clove"
        assert normalize_unit("head") == "head"
        assert normalize_unit("bunch") == "bunch"
        assert normalize_unit("sprig") == "sprig"

    def test_unknown_unit_passthrough(self):
        """Unknown units pass through unchanged"""
        assert normalize_unit("widget") == "widget"
        assert normalize_unit("") == ""

    def test_case_insensitive(self):
        """Handles mixed case"""
        assert normalize_unit("Tablespoon") == "tbsp"
        assert normalize_unit("CUP") == "cup"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'lib.ingredient_parser'"

**Step 3: Write minimal implementation**

```python
# lib/ingredient_parser.py
"""Ingredient string parser - splits amount, unit, and item"""

# Unit normalization map
UNIT_ABBREVIATIONS = {
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp", "tbs": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "cup": "cup", "cups": "cup",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml",
    "liter": "l", "liters": "l", "l": "l",
    "clove": "clove", "cloves": "clove",
    "head": "head", "heads": "head",
    "knob": "knob",
    "bunch": "bunch", "bunches": "bunch",
    "sprig": "sprig", "sprigs": "sprig",
    "slice": "slice", "slices": "slice",
    "piece": "piece", "pieces": "piece",
    "can": "can", "cans": "can",
}


def normalize_unit(unit: str) -> str:
    """Normalize a unit string to its standard abbreviation."""
    if not unit:
        return ""
    return UNIT_ABBREVIATIONS.get(unit.lower(), unit.lower())
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestNormalizeUnit -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add lib/ingredient_parser.py tests/test_ingredient_parser.py
git commit -m "$(cat <<'EOF'
feat: add ingredient parser with unit normalization

First part of amount/unit split feature.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Ingredient Parser - Informal Measurements

**Files:**
- Modify: `lib/ingredient_parser.py`
- Modify: `tests/test_ingredient_parser.py`

**Step 1: Write failing tests for informal measurement detection**

```python
# Add to tests/test_ingredient_parser.py
from lib.ingredient_parser import normalize_unit, is_informal_measurement, INFORMAL_UNITS


class TestInformalMeasurements:
    """Tests for informal measurement handling"""

    def test_pinch_variants(self):
        """Detects pinch-type measurements"""
        assert is_informal_measurement("a pinch") is True
        assert is_informal_measurement("a smidge") is True
        assert is_informal_measurement("a dash") is True
        assert is_informal_measurement("a sprinkle") is True

    def test_handful_variants(self):
        """Detects handful-type measurements"""
        assert is_informal_measurement("a handful") is True
        assert is_informal_measurement("a splash") is True

    def test_taste_variants(self):
        """Detects taste-type measurements"""
        assert is_informal_measurement("to taste") is True
        assert is_informal_measurement("as needed") is True

    def test_vague_quantities(self):
        """Detects vague quantities"""
        assert is_informal_measurement("some") is True
        assert is_informal_measurement("a few") is True
        assert is_informal_measurement("a couple") is True

    def test_case_insensitive(self):
        """Handles mixed case"""
        assert is_informal_measurement("A Pinch") is True
        assert is_informal_measurement("TO TASTE") is True

    def test_rejects_standard_units(self):
        """Rejects standard measurement units"""
        assert is_informal_measurement("cup") is False
        assert is_informal_measurement("tablespoon") is False
        assert is_informal_measurement("1/2 cup") is False

    def test_informal_units_list(self):
        """INFORMAL_UNITS contains expected entries"""
        assert "a pinch" in INFORMAL_UNITS
        assert "to taste" in INFORMAL_UNITS
        assert "a sprinkle" in INFORMAL_UNITS
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestInformalMeasurements -v`
Expected: FAIL with "cannot import name 'is_informal_measurement'"

**Step 3: Write implementation**

```python
# Add to lib/ingredient_parser.py after UNIT_ABBREVIATIONS

# Informal measurements (amount defaults to 1)
INFORMAL_UNITS = [
    "a pinch", "a smidge", "a dash", "a sprinkle", "a handful", "a splash",
    "to taste", "as needed",
    "some", "a few", "a couple",
]


def is_informal_measurement(text: str) -> bool:
    """Check if text is an informal measurement phrase."""
    if not text:
        return False
    text_lower = text.lower().strip()
    return text_lower in INFORMAL_UNITS
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestInformalMeasurements -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add lib/ingredient_parser.py tests/test_ingredient_parser.py
git commit -m "$(cat <<'EOF'
feat: add informal measurement detection

Handles 'a pinch', 'to taste', 'a sprinkle', etc.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Ingredient Parser - Number Parsing

**Files:**
- Modify: `lib/ingredient_parser.py`
- Modify: `tests/test_ingredient_parser.py`

**Step 1: Write failing tests for number parsing**

```python
# Add to tests/test_ingredient_parser.py
from lib.ingredient_parser import parse_amount


class TestParseAmount:
    """Tests for amount parsing"""

    def test_whole_numbers(self):
        """Parses whole numbers"""
        assert parse_amount("1") == "1"
        assert parse_amount("12") == "12"

    def test_fractions(self):
        """Parses fractions as decimals"""
        assert parse_amount("1/2") == "0.5"
        assert parse_amount("1/4") == "0.25"
        assert parse_amount("3/4") == "0.75"

    def test_mixed_fractions(self):
        """Parses mixed fractions"""
        assert parse_amount("1 1/2") == "1.5"
        assert parse_amount("2 1/4") == "2.25"

    def test_decimals_passthrough(self):
        """Decimal strings pass through"""
        assert parse_amount("0.5") == "0.5"
        assert parse_amount("1.25") == "1.25"

    def test_ranges(self):
        """Ranges preserved as strings"""
        assert parse_amount("3-4") == "3-4"
        assert parse_amount("2-3") == "2-3"

    def test_word_numbers(self):
        """Converts word numbers to digits"""
        assert parse_amount("one") == "1"
        assert parse_amount("two") == "2"
        assert parse_amount("three") == "3"
        assert parse_amount("One") == "1"

    def test_empty_returns_one(self):
        """Empty/None returns '1' as default"""
        assert parse_amount("") == "1"
        assert parse_amount(None) == "1"
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestParseAmount -v`
Expected: FAIL with "cannot import name 'parse_amount'"

**Step 3: Write implementation**

```python
# Add to lib/ingredient_parser.py
from fractions import Fraction
import re

# Word to number mapping
WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}


def parse_amount(amount_str: str) -> str:
    """
    Parse amount string to normalized form.

    - Fractions → decimals (1/2 → 0.5)
    - Mixed fractions → decimals (1 1/2 → 1.5)
    - Ranges preserved (3-4 → 3-4)
    - Word numbers → digits (one → 1)
    - Empty → "1"
    """
    if not amount_str:
        return "1"

    amount_str = amount_str.strip()

    # Check for word numbers
    if amount_str.lower() in WORD_NUMBERS:
        return WORD_NUMBERS[amount_str.lower()]

    # Check for ranges (preserve as-is)
    if re.match(r'^\d+-\d+$', amount_str):
        return amount_str

    # Check for decimals (preserve as-is)
    if re.match(r'^\d+\.\d+$', amount_str):
        return amount_str

    # Normalize spaces around slashes
    normalized = re.sub(r'(\d)\s*/\s*(\d)', r'\1/\2', amount_str)

    # Try mixed fraction: "1 1/2"
    mixed_match = re.match(r'^(\d+)\s+(\d+/\d+)$', normalized)
    if mixed_match:
        whole, frac = mixed_match.groups()
        total = float(whole) + float(Fraction(frac))
        return _format_decimal(total)

    # Try simple fraction: "1/2"
    frac_match = re.match(r'^(\d+/\d+)$', normalized)
    if frac_match:
        total = float(Fraction(frac_match.group(1)))
        return _format_decimal(total)

    # Try whole number
    whole_match = re.match(r'^(\d+)$', normalized)
    if whole_match:
        return whole_match.group(1)

    # Fallback: return "1"
    return "1"


def _format_decimal(value: float) -> str:
    """Format float to clean decimal string."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip('0').rstrip('.')
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestParseAmount -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add lib/ingredient_parser.py tests/test_ingredient_parser.py
git commit -m "$(cat <<'EOF'
feat: add amount parsing with fraction/word support

Converts fractions to decimals, handles word numbers.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Ingredient Parser - Main Parse Function

**Files:**
- Modify: `lib/ingredient_parser.py`
- Modify: `tests/test_ingredient_parser.py`

**Step 1: Write failing tests for main parse function**

```python
# Add to tests/test_ingredient_parser.py
from lib.ingredient_parser import parse_ingredient


class TestParseIngredient:
    """Tests for main ingredient parsing"""

    def test_standard_format(self):
        """Parses 'amount unit item' format"""
        result = parse_ingredient("2 cups flour")
        assert result == {"amount": "2", "unit": "cup", "item": "flour"}

    def test_fraction_amount(self):
        """Handles fractions"""
        result = parse_ingredient("1/2 cup sugar")
        assert result == {"amount": "0.5", "unit": "cup", "item": "sugar"}

    def test_informal_measurement(self):
        """Handles informal measurements"""
        result = parse_ingredient("a pinch salt")
        assert result == {"amount": "1", "unit": "a pinch", "item": "salt"}

        result = parse_ingredient("to taste pepper")
        assert result == {"amount": "1", "unit": "to taste", "item": "pepper"}

    def test_no_unit(self):
        """Uses 'whole' for unitless items"""
        result = parse_ingredient("2 eggs")
        assert result == {"amount": "2", "unit": "whole", "item": "eggs"}

        result = parse_ingredient("1/2 lemon")
        assert result == {"amount": "0.5", "unit": "whole", "item": "lemon"}

    def test_no_amount(self):
        """Defaults amount to 1 when missing"""
        result = parse_ingredient("Lavash bread")
        assert result == {"amount": "1", "unit": "whole", "item": "lavash bread"}

    def test_metric_units(self):
        """Handles metric units"""
        result = parse_ingredient("500 g chicken")
        assert result == {"amount": "500", "unit": "g", "item": "chicken"}

        result = parse_ingredient("250 ml milk")
        assert result == {"amount": "250", "unit": "ml", "item": "milk"}

    def test_count_units(self):
        """Handles count units"""
        result = parse_ingredient("3 cloves garlic")
        assert result == {"amount": "3", "unit": "clove", "item": "garlic"}

        result = parse_ingredient("1 head lettuce")
        assert result == {"amount": "1", "unit": "head", "item": "lettuce"}

    def test_knob_measurement(self):
        """Handles knob measurement"""
        result = parse_ingredient("1 knob fresh ginger")
        assert result == {"amount": "1", "unit": "knob", "item": "fresh ginger"}

    def test_inch_notation(self):
        """Handles inch notation"""
        result = parse_ingredient('1" knob ginger')
        assert result == {"amount": "1", "unit": "knob", "item": "ginger"}

    def test_comma_format(self):
        """Handles 'item, amount unit' format from some sources"""
        result = parse_ingredient("Chicken Breasts, 500 g")
        assert result == {"amount": "500", "unit": "g", "item": "chicken breasts"}

    def test_range_amounts(self):
        """Preserves ranges"""
        result = parse_ingredient("3-4 cloves garlic")
        assert result == {"amount": "3-4", "unit": "clove", "item": "garlic"}

    def test_complex_item_descriptions(self):
        """Handles complex item descriptions"""
        result = parse_ingredient("1/2 cup flat leaf parsley, finely chopped")
        assert result["amount"] == "0.5"
        assert result["unit"] == "cup"
        assert "parsley" in result["item"].lower()

    def test_salt_and_pepper_to_taste(self):
        """Handles 'salt and pepper to taste'"""
        result = parse_ingredient("Salt and pepper to taste")
        assert result == {"amount": "1", "unit": "to taste", "item": "salt and pepper"}
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestParseIngredient -v`
Expected: FAIL with "cannot import name 'parse_ingredient'"

**Step 3: Write implementation**

```python
# Add to lib/ingredient_parser.py
from typing import Dict

# Units that are definitely units (not item descriptors)
KNOWN_UNITS = set(UNIT_ABBREVIATIONS.keys()) | {
    "knob", "pinch", "dash", "splash",
}


def parse_ingredient(text: str) -> Dict[str, str]:
    """
    Parse an ingredient string into amount, unit, and item.

    Returns:
        {"amount": str, "unit": str, "item": str}
    """
    if not text:
        return {"amount": "1", "unit": "whole", "item": ""}

    text = text.strip()

    # Handle comma format: "Chicken Breasts, 500 g"
    if ", " in text:
        parts = text.rsplit(", ", 1)
        if len(parts) == 2:
            potential_item, potential_qty = parts
            # Check if second part looks like quantity
            if re.match(r'^[\d/\s]+\s*\w*$', potential_qty) or _starts_with_informal(potential_qty):
                # Recursively parse the quantity part, then combine
                qty_parsed = _parse_quantity_unit(potential_qty)
                return {
                    "amount": qty_parsed["amount"],
                    "unit": qty_parsed["unit"],
                    "item": potential_item.lower().strip(),
                }

    # Check for informal measurement at start
    text_lower = text.lower()
    for informal in INFORMAL_UNITS:
        if text_lower.startswith(informal):
            remainder = text[len(informal):].strip()
            return {
                "amount": "1",
                "unit": informal,
                "item": remainder.lower() if remainder else "",
            }

    # Check for "X to taste" at end
    if text_lower.endswith(" to taste"):
        item = text[:-9].strip()
        return {"amount": "1", "unit": "to taste", "item": item.lower()}

    # Parse standard format: "amount unit item" or "amount item"
    return _parse_standard_format(text)


def _starts_with_informal(text: str) -> bool:
    """Check if text starts with an informal measurement."""
    text_lower = text.lower().strip()
    return any(text_lower.startswith(inf) for inf in INFORMAL_UNITS)


def _parse_quantity_unit(text: str) -> Dict[str, str]:
    """Parse just the quantity/unit part (no item)."""
    text = text.strip()

    # Handle informal
    for informal in INFORMAL_UNITS:
        if text.lower() == informal:
            return {"amount": "1", "unit": informal}

    # Try to extract number and unit
    # Pattern: number(s) followed by optional unit
    match = re.match(r'^([\d/.\s-]+)\s*(.*)$', text)
    if match:
        amount_part, unit_part = match.groups()
        amount = parse_amount(amount_part.strip())
        unit = normalize_unit(unit_part.strip()) if unit_part.strip() else "whole"
        return {"amount": amount, "unit": unit}

    return {"amount": "1", "unit": "whole"}


def _parse_standard_format(text: str) -> Dict[str, str]:
    """Parse 'amount unit item' or 'amount item' format."""
    # Handle inch notation: 1" knob → 1 knob
    text = re.sub(r'(\d+)\s*["\'\u201c\u201d]', r'\1 ', text)

    # Try to match: number + optional unit + item
    # Pattern handles: "2 cups flour", "1/2 cup sugar", "3-4 cloves garlic"
    pattern = r'^([\d/.\s-]+)?\s*(.*)$'
    match = re.match(pattern, text.strip())

    if not match:
        return {"amount": "1", "unit": "whole", "item": text.lower()}

    amount_part, remainder = match.groups()
    amount_part = (amount_part or "").strip()
    remainder = (remainder or "").strip()

    # Parse the amount
    if amount_part:
        amount = parse_amount(amount_part)
    else:
        amount = "1"

    # Now try to extract unit from remainder
    if not remainder:
        return {"amount": amount, "unit": "whole", "item": ""}

    # Check if first word is a known unit
    words = remainder.split(None, 1)
    first_word = words[0].lower() if words else ""

    # Check against known units
    if first_word in KNOWN_UNITS or first_word in UNIT_ABBREVIATIONS:
        unit = normalize_unit(first_word)
        item = words[1] if len(words) > 1 else ""
        return {"amount": amount, "unit": unit, "item": item.lower().strip()}

    # No unit found - use "whole"
    return {"amount": amount, "unit": "whole", "item": remainder.lower()}
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py::TestParseIngredient -v`
Expected: PASS (all 13 tests)

**Step 5: Run all parser tests**

Run: `.venv/bin/python -m pytest tests/test_ingredient_parser.py -v`
Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add lib/ingredient_parser.py tests/test_ingredient_parser.py
git commit -m "$(cat <<'EOF'
feat: add main ingredient parsing function

Handles all formats: standard, comma-separated, informal, unitless.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Update Recipe Template

**Files:**
- Modify: `templates/recipe_template.py:148-156`
- Modify: `tests/test_migrate.py` (add template test)

**Step 1: Write failing test for 3-column table output**

```python
# Add to tests/test_migrate.py or create new test file
import pytest
from templates.recipe_template import format_recipe_markdown


class TestIngredientTableFormat:
    """Tests for 3-column ingredient table"""

    def test_three_column_header(self):
        """Output has Amount | Unit | Ingredient header"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"amount": "2", "unit": "cup", "item": "flour"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "| Amount | Unit | Ingredient |" in result

    def test_three_column_rows(self):
        """Ingredient rows have 3 columns"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"amount": "0.5", "unit": "cup", "item": "sugar"},
                {"amount": "1", "unit": "a pinch", "item": "salt"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        assert "| 0.5 | cup | sugar |" in result
        assert "| 1 | a pinch | salt |" in result

    def test_backwards_compat_old_format(self):
        """Handles old 'quantity' format gracefully"""
        recipe = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [
                {"quantity": "2 cups", "item": "flour"},
            ],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe, "http://test.com", "Test", "Channel")
        # Should parse and output in new format
        assert "| Amount | Unit | Ingredient |" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::TestIngredientTableFormat -v`
Expected: FAIL

**Step 3: Update recipe_template.py**

```python
# Modify templates/recipe_template.py

# Update imports at top
from lib.ingredient_parser import parse_ingredient

# Replace the ingredient formatting section (around line 148-156)
# In format_recipe_markdown function:

    # Format ingredients as 3-column table
    ingredients_lines = ["| Amount | Unit | Ingredient |", "|--------|------|------------|"]
    for ing in recipe_data.get('ingredients', []):
        # Handle new format (amount, unit, item)
        if 'amount' in ing and 'unit' in ing:
            amount = ing.get('amount', '1')
            unit = ing.get('unit', 'whole')
            item = ing.get('item', '')
        # Handle old format (quantity, item) - parse it
        elif 'quantity' in ing:
            quantity = ing.get('quantity', '')
            item_raw = ing.get('item', '')
            # Combine and re-parse
            combined = f"{quantity} {item_raw}".strip()
            parsed = parse_ingredient(combined)
            amount = parsed['amount']
            unit = parsed['unit']
            item = parsed['item']
        else:
            amount = '1'
            unit = 'whole'
            item = str(ing)

        if ing.get('inferred'):
            item = f"{item} *(inferred)*"
        ingredients_lines.append(f"| {amount} | {unit} | {item} |")
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::TestIngredientTableFormat -v`
Expected: PASS

**Step 5: Commit**

```bash
git add templates/recipe_template.py tests/test_migrate.py
git commit -m "$(cat <<'EOF'
feat: update recipe template to 3-column ingredient table

Amount | Unit | Ingredient format with backwards compatibility.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update AI Extraction Prompts

**Files:**
- Modify: `prompts/recipe_extraction.py:26-27, 84-85`

**Step 1: Update the JSON schema in prompts**

Update both `SYSTEM_PROMPT` and `DESCRIPTION_EXTRACTION_PROMPT`:

```python
# In SYSTEM_PROMPT, change ingredients schema from:
#   "ingredients": [
#     {"quantity": "string", "item": "string", "inferred": boolean}
#   ],
# To:
  "ingredients": [
    {"amount": "number or string", "unit": "string", "item": "string", "inferred": boolean}
  ],

# Add note about units:
# Standard units: tbsp, tsp, cup, oz, lb, g, kg, ml, l, clove, head, bunch, sprig, slice, piece, can
# Informal units: a pinch, a smidge, a dash, a sprinkle, a handful, a splash, to taste, as needed, some, a few, a couple
# Default unit: "whole" (for items like eggs, lemons)
```

**Step 2: No test needed - this is prompt text**

The AI output will be validated by the existing parsing functions.

**Step 3: Apply the changes**

```python
# prompts/recipe_extraction.py - update SYSTEM_PROMPT ingredients section

SYSTEM_PROMPT = """You are a recipe extraction assistant. Given a YouTube video transcript
and description about cooking, extract a structured recipe.

Rules:
- Extract ONLY what is shown/said in the video
- When inferring (timing, quantities, temperatures), mark with "(estimated)"
- If a field cannot be determined, use null
- Set needs_review: true if significant inference was required
- List confidence_notes explaining what was inferred vs explicit
- For ingredients: use standard unit abbreviations (tbsp, tsp, cup, oz, lb, g, ml)
- For informal amounts (a pinch, to taste), set amount to 1 and use the phrase as unit
- For unitless items (eggs, lemons), use "whole" as unit

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
    {"amount": "number or string", "unit": "string", "item": "string", "inferred": boolean}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
  "variations": ["array of strings"],
  "nutritional_info": "string or null",
  "needs_review": boolean,
  "confidence_notes": "string"
}"""

# Also update DESCRIPTION_EXTRACTION_PROMPT similarly
```

**Step 4: Commit**

```bash
git add prompts/recipe_extraction.py
git commit -m "$(cat <<'EOF'
feat: update AI prompts for amount/unit split

New ingredient schema: amount, unit, item (was: quantity, item).

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update Recipe Sources

**Files:**
- Modify: `recipe_sources.py:170-227`

**Step 1: Write test for updated ingredient parsing**

```python
# Add to tests/test_recipe_sources.py

class TestIngredientParsing:
    """Tests for ingredient parsing from JSON-LD"""

    def test_parses_to_new_format(self):
        """Outputs amount/unit/item format"""
        from recipe_sources import _parse_ingredients
        ingredients = ["500 g chicken", "2 cups flour"]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert result[0]["item"] == "chicken"

        assert result[1]["amount"] == "2"
        assert result[1]["unit"] == "cup"

    def test_handles_comma_format(self):
        """Handles 'Item, amount unit' format"""
        from recipe_sources import _parse_ingredients
        ingredients = ["Chicken Breasts, 500 g"]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert "chicken" in result[0]["item"].lower()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestIngredientParsing -v`
Expected: FAIL

**Step 3: Update recipe_sources.py**

```python
# recipe_sources.py - update _parse_ingredients function

from lib.ingredient_parser import parse_ingredient

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
                # Legacy format
                parsed = parse_ingredient(f"{ing.get('quantity', '')} {ing.get('name', '')}".strip())
                result.append({
                    "amount": parsed["amount"],
                    "unit": parsed["unit"],
                    "item": parsed["item"],
                    "inferred": False,
                })
    return result

# Remove the old _split_ingredient_string function (no longer needed)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py::TestIngredientParsing -v`
Expected: PASS

**Step 5: Run all recipe_sources tests**

Run: `.venv/bin/python -m pytest tests/test_recipe_sources.py -v`
Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add recipe_sources.py tests/test_recipe_sources.py
git commit -m "$(cat <<'EOF'
refactor: update recipe_sources to use ingredient_parser

Webpage scraper now outputs amount/unit/item format.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update Migration Script

**Files:**
- Modify: `migrate_recipes.py`
- Modify: `lib/recipe_parser.py` (add ingredient table parsing)

**Step 1: Write test for ingredient table migration**

```python
# Add to tests/test_migrate.py

class TestIngredientMigration:
    """Tests for migrating ingredient tables"""

    def test_parses_old_2column_table(self):
        """Parses old 2-column ingredient table"""
        from lib.recipe_parser import parse_ingredient_table

        table = """| Amount | Ingredient |
|--------|------------|
| 500 g | Chicken Breasts |
| a sprinkle | Salt |
|  | Lavash bread |"""

        result = parse_ingredient_table(table)

        assert len(result) == 3
        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert result[0]["item"] == "chicken breasts"

    def test_converts_to_3column_format(self):
        """Migration rewrites table to 3 columns"""
        from migrate_recipes import migrate_ingredient_table

        old_table = """| Amount | Ingredient |
|--------|------------|
| 500 g | Chicken |"""

        new_table = migrate_ingredient_table(old_table)

        assert "| Amount | Unit | Ingredient |" in new_table
        assert "| 500 | g | chicken |" in new_table
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::TestIngredientMigration -v`
Expected: FAIL

**Step 3: Add ingredient table parsing to lib/recipe_parser.py**

```python
# Add to lib/recipe_parser.py
import re
from lib.ingredient_parser import parse_ingredient


def parse_ingredient_table(table_text: str) -> list:
    """
    Parse a markdown ingredient table into structured data.

    Handles both old 2-column (Amount | Ingredient) and
    new 3-column (Amount | Unit | Ingredient) formats.
    """
    lines = table_text.strip().split('\n')
    ingredients = []

    for line in lines:
        # Skip header and separator lines
        if not line.startswith('|') or '---' in line:
            continue
        if 'Amount' in line and 'Ingredient' in line:
            continue

        # Parse table row
        cells = [c.strip() for c in line.split('|')[1:-1]]  # Remove empty first/last

        if len(cells) == 2:
            # Old format: Amount | Ingredient
            amount_cell, ingredient_cell = cells
            combined = f"{amount_cell} {ingredient_cell}".strip()
            parsed = parse_ingredient(combined)
            ingredients.append(parsed)
        elif len(cells) == 3:
            # New format: Amount | Unit | Ingredient
            ingredients.append({
                "amount": cells[0] or "1",
                "unit": cells[1] or "whole",
                "item": cells[2].lower(),
            })

    return ingredients
```

**Step 4: Add migration function to migrate_recipes.py**

```python
# Add to migrate_recipes.py
from lib.recipe_parser import parse_ingredient_table


def migrate_ingredient_table(table_text: str) -> str:
    """Convert 2-column ingredient table to 3-column format."""
    ingredients = parse_ingredient_table(table_text)

    lines = ["| Amount | Unit | Ingredient |", "|--------|------|------------|"]
    for ing in ingredients:
        lines.append(f"| {ing['amount']} | {ing['unit']} | {ing['item']} |")

    return '\n'.join(lines)


def migrate_recipe_content(content: str) -> str:
    """Migrate recipe markdown content to new format."""
    # Find and replace ingredient table
    table_pattern = r'## Ingredients\n\n(\|[^\n]+\n\|[-|\s]+\n(?:\|[^\n]+\n)*)'

    def replace_table(match):
        old_table = match.group(1)
        # Check if already 3-column
        if '| Amount | Unit | Ingredient |' in old_table:
            return match.group(0)
        new_table = migrate_ingredient_table(old_table)
        return f"## Ingredients\n\n{new_table}\n"

    return re.sub(table_pattern, replace_table, content)
```

**Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate.py::TestIngredientMigration -v`
Expected: PASS

**Step 6: Update migrate_recipe_file to include ingredient migration**

```python
# Update migrate_recipe_file in migrate_recipes.py to call migrate_recipe_content
```

**Step 7: Commit**

```bash
git add migrate_recipes.py lib/recipe_parser.py tests/test_migrate.py
git commit -m "$(cat <<'EOF'
feat: add ingredient table migration

Converts 2-column tables to 3-column amount/unit/item format.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: End-to-End Test

**Files:**
- None (testing only)

**Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Test migration dry-run on real recipes**

Run: `.venv/bin/python migrate_recipes.py --dry-run`
Expected: Shows what would change, no errors

**Step 3: Run actual migration**

Run: `.venv/bin/python migrate_recipes.py`
Expected: Migrates recipes, creates backups

**Step 4: Verify migrated recipe**

Run: `cat "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes/butter-chicken-snack-wrap.md" | head -60`
Expected: Shows 3-column ingredient table

**Step 5: Test new extraction**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`
Expected: Shows 3-column ingredient table in output

**Step 6: Commit any fixes**

If any issues found, fix and commit.

---

## Task 10: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update JSON schema in CLAUDE.md**

Update the "Recipe JSON Schema" section:

```json
"ingredients": [{"amount": "number/string", "unit": "string", "item": "string", "inferred": boolean}]
```

**Step 2: Add note about ingredient parser**

Add to "Key Functions" section:

```
**lib/ingredient_parser.py:**
- `parse_ingredient()` - Splits ingredient string into amount, unit, item
- `normalize_unit()` - Standardizes unit abbreviations
- `is_informal_measurement()` - Detects "a pinch", "to taste", etc.
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: update CLAUDE.md for ingredient amount/unit split

New ingredient schema and parser documentation.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

Plan complete and saved to `docs/plans/2026-01-08-ingredient-amount-unit-split.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?