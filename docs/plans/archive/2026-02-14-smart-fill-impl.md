# Smart Fill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Ollama-powered "Smart Fill" that fills empty meal plan slots with recipe picks optimized for variety, time, and meal_occasion matching.

**Architecture:** New `lib/smart_fill.py` module loads recipe catalog from frontmatter, builds an Ollama prompt with the catalog + current plan state + recent history, parses the JSON response, and writes wikilinks into empty slots via the existing `insert_recipe_into_meal_plan()`. Exposed via `--fill` CLI flag and `/fill-meal-plan` API endpoint.

**Tech Stack:** Python 3.11, Ollama (Mistral 7B), existing `lib/meal_plan_parser.py` and `lib/recipe_parser.py`

---

### Task 1: Time Normalizer Utility

**Files:**
- Create: `lib/time_utils.py`
- Test: `tests/test_time_utils.py`

**Step 1: Write the failing tests**

```python
"""Tests for time utility functions."""

import pytest
from lib.time_utils import parse_time_to_minutes


class TestParseTimeToMinutes:
    """Test normalizing time strings to minutes."""

    def test_minutes_only(self):
        assert parse_time_to_minutes("20 minutes") == 20

    def test_hours_and_minutes(self):
        assert parse_time_to_minutes("1 hour 30 minutes") == 90

    def test_hours_only(self):
        assert parse_time_to_minutes("2 hours") == 120

    def test_abbreviated(self):
        assert parse_time_to_minutes("20 min") == 20

    def test_with_estimated_prefix(self):
        assert parse_time_to_minutes("(estimated) 20 minutes") == 20

    def test_approximately_prefix(self):
        assert parse_time_to_minutes("Approximately 20 minutes") == 20

    def test_bare_number(self):
        assert parse_time_to_minutes("30") == 30

    def test_null_returns_none(self):
        assert parse_time_to_minutes(None) is None

    def test_empty_string_returns_none(self):
        assert parse_time_to_minutes("") is None

    def test_unparseable_returns_none(self):
        assert parse_time_to_minutes("a long time") is None

    def test_complex_estimated_string(self):
        assert parse_time_to_minutes("(estimated) 2 minutes 15 seconds (with checking every 30 seconds)") == 2
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_time_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.time_utils'`

**Step 3: Write minimal implementation**

```python
"""Time string parsing utilities."""

import re
from typing import Optional


def parse_time_to_minutes(time_str: Optional[str]) -> Optional[int]:
    """Parse a time string into total minutes.

    Handles formats like:
        "20 minutes", "1 hour 30 minutes", "(estimated) 20 min",
        "Approximately 45 minutes", "30"

    Args:
        time_str: Time string to parse, or None

    Returns:
        Total minutes as int, or None if unparseable
    """
    if not time_str:
        return None

    # Strip common prefixes
    cleaned = re.sub(r'^\(estimated\)\s*', '', time_str, flags=re.IGNORECASE)
    cleaned = re.sub(r'^approximately\s*', '', cleaned, flags=re.IGNORECASE)

    # Strip parenthetical suffixes like "(with checking every 30 seconds)"
    cleaned = re.sub(r'\s*\(.*\)\s*$', '', cleaned)

    total = 0
    found = False

    # Match hours
    hours_match = re.search(r'(\d+)\s*hours?', cleaned, re.IGNORECASE)
    if hours_match:
        total += int(hours_match.group(1)) * 60
        found = True

    # Match minutes
    min_match = re.search(r'(\d+)\s*min(?:utes?)?', cleaned, re.IGNORECASE)
    if min_match:
        total += int(min_match.group(1))
        found = True

    # Match bare number (assume minutes)
    if not found:
        bare_match = re.match(r'^\s*(\d+)\s*$', cleaned)
        if bare_match:
            total = int(bare_match.group(1))
            found = True

    return total if found else None
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_time_utils.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/time_utils.py tests/test_time_utils.py
git commit -m "feat: add time string parser for smart fill"
```

---

### Task 2: Recipe Catalog Loader

**Files:**
- Create: `lib/recipe_catalog.py`
- Test: `tests/test_recipe_catalog.py`

**Step 1: Write the failing tests**

```python
"""Tests for recipe catalog loader."""

import pytest
from pathlib import Path
from lib.recipe_catalog import load_recipe_catalog, format_catalog_for_prompt


class TestLoadRecipeCatalog:
    """Test loading recipe metadata from files."""

    def test_loads_frontmatter_fields(self, tmp_path):
        recipe = tmp_path / "Pasta.md"
        recipe.write_text('''---
title: "Pasta Aglio E Olio"
cuisine: "Italian"
protein: "None"
dish_type: "Main"
meal_occasion: ["weeknight-dinner"]
difficulty: "easy"
prep_time: "5 minutes"
cook_time: "15 minutes"
---

# Pasta Aglio E Olio
''')
        catalog = load_recipe_catalog(tmp_path)

        assert len(catalog) == 1
        assert catalog[0]['title'] == 'Pasta Aglio E Olio'
        assert catalog[0]['cuisine'] == 'Italian'
        assert catalog[0]['meal_occasion'] == ['weeknight-dinner']
        assert catalog[0]['total_minutes'] == 20

    def test_skips_non_recipe_files(self, tmp_path):
        # File without source_url-like frontmatter is still loaded
        recipe = tmp_path / "Notes.md"
        recipe.write_text("# Just notes\nNo frontmatter here.")
        catalog = load_recipe_catalog(tmp_path)
        assert len(catalog) == 0

    def test_handles_null_times(self, tmp_path):
        recipe = tmp_path / "Quick Snack.md"
        recipe.write_text('''---
title: "Quick Snack"
cuisine: "American"
protein: null
dish_type: "Snack"
meal_occasion: ["afternoon-snack"]
difficulty: null
prep_time: null
cook_time: null
---

# Quick Snack
''')
        catalog = load_recipe_catalog(tmp_path)

        assert len(catalog) == 1
        assert catalog[0]['total_minutes'] is None

    def test_skips_hidden_files(self, tmp_path):
        hidden = tmp_path / ".hidden.md"
        hidden.write_text('---\ntitle: "Hidden"\n---\n')
        catalog = load_recipe_catalog(tmp_path)
        assert len(catalog) == 0

    def test_skips_subdirectories(self, tmp_path):
        subdir = tmp_path / "Cooking Mode"
        subdir.mkdir()
        sub_file = subdir / "Recipe.md"
        sub_file.write_text('---\ntitle: "Sub"\ncuisine: "Test"\n---\n')
        catalog = load_recipe_catalog(tmp_path)
        assert len(catalog) == 0

    def test_falls_back_dish_type_for_empty_occasion(self, tmp_path):
        recipe = tmp_path / "Pancakes.md"
        recipe.write_text('''---
title: "Pancakes"
cuisine: "American"
protein: null
dish_type: "Breakfast"
meal_occasion: []
difficulty: "easy"
prep_time: "10 minutes"
cook_time: "15 minutes"
---

# Pancakes
''')
        catalog = load_recipe_catalog(tmp_path)
        assert catalog[0]['meal_occasion'] == []
        assert catalog[0]['dish_type'] == 'Breakfast'


class TestFormatCatalogForPrompt:
    """Test formatting catalog into compact prompt text."""

    def test_formats_single_recipe(self):
        catalog = [{
            'title': 'Pasta Aglio E Olio',
            'cuisine': 'Italian',
            'protein': 'None',
            'dish_type': 'Main',
            'meal_occasion': ['weeknight-dinner'],
            'difficulty': 'easy',
            'total_minutes': 20,
        }]
        result = format_catalog_for_prompt(catalog)

        assert "1. Pasta Aglio E Olio" in result
        assert "italian" in result.lower()
        assert "20min" in result

    def test_formats_null_time(self):
        catalog = [{
            'title': 'Mystery Dish',
            'cuisine': None,
            'protein': None,
            'dish_type': 'Main',
            'meal_occasion': [],
            'difficulty': None,
            'total_minutes': None,
        }]
        result = format_catalog_for_prompt(catalog)

        assert "?min" in result

    def test_numbers_recipes_sequentially(self):
        catalog = [
            {'title': 'A', 'cuisine': 'X', 'protein': 'Y', 'dish_type': 'Z', 'meal_occasion': [], 'difficulty': None, 'total_minutes': 10},
            {'title': 'B', 'cuisine': 'X', 'protein': 'Y', 'dish_type': 'Z', 'meal_occasion': [], 'difficulty': None, 'total_minutes': 20},
        ]
        result = format_catalog_for_prompt(catalog)

        assert result.startswith("1. A")
        assert "\n2. B" in result
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.recipe_catalog'`

**Step 3: Write minimal implementation**

```python
"""Load recipe catalog metadata for smart fill."""

from pathlib import Path
from typing import Optional

from lib.recipe_parser import parse_recipe_file
from lib.time_utils import parse_time_to_minutes


def load_recipe_catalog(recipes_dir: Path) -> list[dict]:
    """Load frontmatter metadata from all recipe files.

    Args:
        recipes_dir: Path to recipes directory

    Returns:
        List of dicts with keys: title, cuisine, protein, dish_type,
        meal_occasion, difficulty, total_minutes
    """
    catalog = []

    if not recipes_dir.exists():
        return catalog

    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith('.'):
            continue

        try:
            content = md_file.read_text(encoding='utf-8')
            parsed = parse_recipe_file(content)
            fm = parsed['frontmatter']

            # Skip files without a title (not a recipe)
            if 'title' not in fm:
                continue

            # Calculate total time
            prep = parse_time_to_minutes(fm.get('prep_time'))
            cook = parse_time_to_minutes(fm.get('cook_time'))
            total = parse_time_to_minutes(fm.get('total_time'))

            if total is not None:
                total_minutes = total
            elif prep is not None and cook is not None:
                total_minutes = prep + cook
            elif cook is not None:
                total_minutes = cook
            elif prep is not None:
                total_minutes = prep
            else:
                total_minutes = None

            catalog.append({
                'title': fm.get('title', md_file.stem),
                'cuisine': fm.get('cuisine'),
                'protein': fm.get('protein'),
                'dish_type': fm.get('dish_type'),
                'meal_occasion': fm.get('meal_occasion', []) or [],
                'difficulty': fm.get('difficulty'),
                'total_minutes': total_minutes,
            })
        except Exception:
            continue

    return catalog


def format_catalog_for_prompt(catalog: list[dict]) -> str:
    """Format recipe catalog as compact numbered list for Ollama prompt.

    Args:
        catalog: List of recipe metadata dicts

    Returns:
        Formatted string with one recipe per line
    """
    lines = []
    for i, r in enumerate(catalog, 1):
        time_str = f"{r['total_minutes']}min" if r['total_minutes'] is not None else "?min"
        cuisine = r['cuisine'] or '?'
        protein = r['protein'] or '?'
        dish_type = r['dish_type'] or '?'
        difficulty = r['difficulty'] or '?'
        occasions = ', '.join(r['meal_occasion']) if r['meal_occasion'] else 'none'

        lines.append(f"{i}. {r['title']} | {cuisine} | {protein} | {dish_type} | {time_str} | {difficulty} | occasions: {occasions}")

    return '\n'.join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_catalog.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/recipe_catalog.py tests/test_recipe_catalog.py
git commit -m "feat: add recipe catalog loader for smart fill"
```

---

### Task 3: Smart Fill Prompt & Ollama Integration

**Files:**
- Create: `prompts/smart_fill.py`
- Create: `lib/smart_fill.py`
- Test: `tests/test_smart_fill.py`

**Step 1: Write the failing tests**

```python
"""Tests for smart fill logic."""

import pytest
import json
from lib.smart_fill import (
    find_empty_slots,
    parse_fill_response,
    build_plan_state_for_prompt,
)


class TestFindEmptySlots:
    """Test identifying empty slots in a parsed meal plan."""

    def test_all_empty(self):
        days = [
            {'day': 'Monday', 'breakfast': None, 'lunch': None, 'dinner': None},
            {'day': 'Tuesday', 'breakfast': None, 'lunch': None, 'dinner': None},
        ]
        empty = find_empty_slots(days)

        assert ('Monday', 'breakfast') in empty
        assert ('Monday', 'lunch') in empty
        assert ('Monday', 'dinner') in empty
        assert ('Tuesday', 'breakfast') in empty
        assert len(empty) == 6

    def test_partially_filled(self):
        from lib.meal_plan_parser import MealEntry
        days = [
            {'day': 'Monday', 'breakfast': MealEntry('Pancakes', 1), 'lunch': None, 'dinner': MealEntry('Pasta', 1)},
        ]
        empty = find_empty_slots(days)

        assert empty == [('Monday', 'lunch')]

    def test_all_filled(self):
        from lib.meal_plan_parser import MealEntry
        days = [
            {'day': 'Monday', 'breakfast': MealEntry('A', 1), 'lunch': MealEntry('B', 1), 'dinner': MealEntry('C', 1)},
        ]
        empty = find_empty_slots(days)
        assert empty == []


class TestParseFillResponse:
    """Test parsing Ollama JSON response into slot assignments."""

    def test_parses_valid_response(self):
        catalog = [
            {'title': 'Pancakes'},
            {'title': 'Salad'},
            {'title': 'Steak'},
        ]
        response = json.dumps({
            "monday": {"breakfast": 1, "dinner": 3},
            "tuesday": {"lunch": 2},
        })
        result = parse_fill_response(response, catalog)

        assert result[('Monday', 'breakfast')] == 'Pancakes'
        assert result[('Monday', 'dinner')] == 'Steak'
        assert result[('Tuesday', 'lunch')] == 'Salad'

    def test_skips_invalid_recipe_number(self):
        catalog = [{'title': 'Pancakes'}]
        response = json.dumps({
            "monday": {"breakfast": 1, "dinner": 99},
        })
        result = parse_fill_response(response, catalog)

        assert ('Monday', 'breakfast') in result
        assert ('Monday', 'dinner') not in result

    def test_skips_zero_index(self):
        catalog = [{'title': 'Pancakes'}]
        response = json.dumps({"monday": {"breakfast": 0}})
        result = parse_fill_response(response, catalog)
        assert len(result) == 0

    def test_handles_malformed_json(self):
        catalog = [{'title': 'Pancakes'}]
        result = parse_fill_response("not json", catalog)
        assert result == {}


class TestBuildPlanStateForPrompt:
    """Test formatting current plan state for the prompt."""

    def test_shows_filled_and_empty(self):
        from lib.meal_plan_parser import MealEntry
        days = [
            {'day': 'Monday', 'breakfast': MealEntry('Pancakes', 1), 'lunch': None, 'dinner': None},
        ]
        result = build_plan_state_for_prompt(days)

        assert 'Monday' in result
        assert 'Pancakes' in result
        assert 'EMPTY' in result
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smart_fill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.smart_fill'`

**Step 3: Write the prompt template**

```python
"""Prompt templates for smart fill meal planning."""

SMART_FILL_SYSTEM = """You are a meal planning assistant. Given a recipe catalog and a partially-filled weekly meal plan, pick recipes for the empty slots.

Rules:
- Only fill slots marked EMPTY — do not change filled slots
- Weekday dinners (Monday-Friday): prefer recipes ≤30 minutes total time
- Weekend (Saturday-Sunday): any time is fine
- Don't repeat the same protein on consecutive days
- Don't repeat the same cuisine within 3 days
- Match meal_occasion when available: breakfast-tagged recipes for breakfast slots, etc.
- If meal_occasion is empty, use dish_type as a hint (e.g., "Breakfast" dish_type → breakfast slot)
- Prefer recipes NOT in the recent history list
- If constraints conflict, prioritize: occasion match > variety > time

Return ONLY valid JSON mapping days to meals to recipe numbers:
{"monday": {"breakfast": 5, "lunch": 12}, "tuesday": {"dinner": 3}}

Use recipe numbers from the catalog (1-indexed). Only include slots you are filling."""


SMART_FILL_USER = """RECIPE CATALOG:
{catalog}

CURRENT PLAN:
{plan_state}

RECENT HISTORY (avoid if possible):
{recent_history}

Fill all EMPTY slots. Return JSON only."""


def build_smart_fill_prompt(catalog_text: str, plan_state: str, recent_history: str) -> str:
    """Build the full user prompt for smart fill."""
    return SMART_FILL_USER.format(
        catalog=catalog_text,
        plan_state=plan_state,
        recent_history=recent_history or "None",
    )
```

**Step 4: Write the smart fill module**

```python
"""Smart fill logic for meal plans."""

import json
import re
from pathlib import Path
from typing import Optional

import requests

from lib.meal_plan_parser import parse_meal_plan, insert_recipe_into_meal_plan, MealEntry
from lib.recipe_catalog import load_recipe_catalog, format_catalog_for_prompt
from prompts.smart_fill import SMART_FILL_SYSTEM, build_smart_fill_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

MEAL_TYPES = ['breakfast', 'lunch', 'dinner']


def find_empty_slots(days: list[dict]) -> list[tuple[str, str]]:
    """Find all empty meal slots in a parsed meal plan.

    Args:
        days: Parsed meal plan from parse_meal_plan()

    Returns:
        List of (day_name, meal_type) tuples for empty slots
    """
    empty = []
    for day in days:
        for meal in MEAL_TYPES:
            if day.get(meal) is None:
                empty.append((day['day'], meal))
    return empty


def build_plan_state_for_prompt(days: list[dict]) -> str:
    """Format current meal plan state for the prompt.

    Args:
        days: Parsed meal plan from parse_meal_plan()

    Returns:
        Human-readable plan state string
    """
    lines = []
    for day in days:
        day_lines = [f"{day['day']}:"]
        for meal in MEAL_TYPES:
            entry = day.get(meal)
            if entry is not None:
                day_lines.append(f"  {meal}: {entry.name}")
            else:
                day_lines.append(f"  {meal}: EMPTY")
        lines.append('\n'.join(day_lines))
    return '\n'.join(lines)


def get_recent_recipes(meal_plans_dir: Path, current_week: str, lookback: int = 2) -> list[str]:
    """Load recipe names from recent meal plans.

    Args:
        meal_plans_dir: Path to meal plans directory
        current_week: Current week string (e.g., "2026-W07")
        lookback: Number of previous weeks to check

    Returns:
        List of recipe names used recently
    """
    recent = []

    # Parse current week to get year and week number
    match = re.match(r'^(\d{4})-W(\d{2})$', current_week)
    if not match:
        return recent

    year = int(match.group(1))
    week = int(match.group(2))

    for i in range(1, lookback + 1):
        prev_week = week - i
        prev_year = year
        if prev_week < 1:
            prev_year -= 1
            prev_week += 52

        filename = f"{prev_year}-W{prev_week:02d}.md"
        filepath = meal_plans_dir / filename

        if not filepath.exists():
            continue

        content = filepath.read_text(encoding='utf-8')
        days = parse_meal_plan(content, prev_year, prev_week)

        for day in days:
            for meal in MEAL_TYPES:
                entry = day.get(meal)
                if entry is not None:
                    recent.append(entry.name)

    return recent


def parse_fill_response(response_text: str, catalog: list[dict]) -> dict:
    """Parse Ollama JSON response into slot assignments.

    Args:
        response_text: Raw JSON string from Ollama
        catalog: Recipe catalog (for mapping numbers to names)

    Returns:
        Dict mapping (day, meal) tuples to recipe title strings
    """
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return {}

    # Handle wrapped response like {"meal_plan": {...}}
    if isinstance(data, dict) and len(data) == 1:
        key = list(data.keys())[0]
        if key not in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
            data = data[key]

    assignments = {}
    for day_name, meals in data.items():
        if not isinstance(meals, dict):
            continue
        day_title = day_name.strip().title()
        for meal_type, recipe_num in meals.items():
            if not isinstance(recipe_num, int) or recipe_num < 1 or recipe_num > len(catalog):
                continue
            meal_title = meal_type.strip().lower()
            if meal_title in MEAL_TYPES:
                assignments[(day_title, meal_title)] = catalog[recipe_num - 1]['title']

    return assignments


def fill_meal_plan(
    plan_content: str,
    year: int,
    week: int,
    recipes_dir: Path,
    meal_plans_dir: Path,
) -> tuple[str, list[str]]:
    """Fill empty slots in a meal plan using Ollama.

    Args:
        plan_content: Current meal plan markdown content
        year: ISO year
        week: ISO week number
        recipes_dir: Path to recipes directory
        meal_plans_dir: Path to meal plans directory

    Returns:
        Tuple of (updated_content, list_of_fills) where fills are
        human-readable strings like "Monday dinner: Pasta Aglio E Olio"

    Raises:
        ConnectionError: If Ollama is not running
        RuntimeError: If Ollama returns unusable response
    """
    # Parse current plan
    days = parse_meal_plan(plan_content, year, week)
    empty = find_empty_slots(days)

    if not empty:
        return plan_content, []

    # Load catalog
    catalog = load_recipe_catalog(recipes_dir)
    if not catalog:
        raise RuntimeError("No recipes found in catalog")

    catalog_text = format_catalog_for_prompt(catalog)
    plan_state = build_plan_state_for_prompt(days)

    # Get recent history
    week_str = f"{year}-W{week:02d}"
    recent = get_recent_recipes(meal_plans_dir, week_str)
    recent_text = ', '.join(recent) if recent else "None"

    # Build prompt
    prompt = f"{SMART_FILL_SYSTEM}\n\n{build_smart_fill_prompt(catalog_text, plan_state, recent_text)}"

    # Call Ollama
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
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Cannot connect to Ollama. Is it running? Try: ollama serve")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out (120s)")

    result = response.json()
    raw = result.get("response", "")

    # Parse response
    assignments = parse_fill_response(raw, catalog)

    if not assignments:
        raise RuntimeError(f"Ollama returned no valid assignments. Raw response: {raw[:200]}")

    # Apply assignments to content
    updated = plan_content
    fills = []

    for (day, meal), recipe_name in assignments.items():
        # Only fill slots that were empty
        if (day, meal) not in empty:
            continue
        try:
            updated = insert_recipe_into_meal_plan(updated, day, meal.title(), recipe_name)
            fills.append(f"{day} {meal}: {recipe_name}")
        except ValueError:
            continue

    return updated, fills
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smart_fill.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add prompts/smart_fill.py lib/smart_fill.py tests/test_smart_fill.py
git commit -m "feat: add smart fill prompt and core logic"
```

---

### Task 4: CLI Integration (`--fill` flag)

**Files:**
- Modify: `generate_meal_plan.py`

**Step 1: Add `--fill` argument and fill logic**

Add to the argparse section (after existing `--force` argument):

```python
parser.add_argument('--fill', type=str, nargs='?', const='auto',
                    help='Fill empty slots with AI picks. Optionally specify week (e.g., 2026-W07)')
```

Add new function and call it from `main()`:

```python
def fill_plan(week_str: str, dry_run: bool = False):
    """Fill empty slots in an existing meal plan."""
    from lib.smart_fill import fill_meal_plan

    try:
        year, week = parse_week_string(week_str)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    filepath = MEAL_PLANS_PATH / f"{year}-W{week:02d}.md"

    # Create plan if it doesn't exist
    if not filepath.exists():
        ensure_meal_plans_folder()
        content = generate_meal_plan_markdown(year, week)
        if not dry_run:
            filepath.write_text(content, encoding='utf-8')
            print(f"Created new plan: {filepath.name}")
    else:
        content = filepath.read_text(encoding='utf-8')

    print(f"Smart Fill: {year}-W{week:02d}")
    print("Loading recipe catalog...")

    recipes_dir = OBSIDIAN_VAULT / "Recipes"

    try:
        updated, fills = fill_meal_plan(content, year, week, recipes_dir, MEAL_PLANS_PATH)
    except (ConnectionError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not fills:
        print("No slots were filled.")
        return

    print(f"\nFilled {len(fills)} slot(s):")
    for fill in fills:
        print(f"  - {fill}")

    if dry_run:
        print("\nDry run — no changes written.")
    else:
        filepath.write_text(updated, encoding='utf-8')
        print(f"\nSaved: {filepath}")
```

In `main()`, add before the existing week generation logic:

```python
    if args.fill:
        week_str = args.fill if args.fill != 'auto' else f"{year}-W{week:02d}"
        fill_plan(week_str, dry_run=args.dry_run)
        return
```

**Step 2: Test manually**

Run: `.venv/bin/python generate_meal_plan.py --fill 2026-W04 --dry-run`
Expected: Prints catalog loading message and either fills or shows Ollama connection error

**Step 3: Commit**

```bash
git add generate_meal_plan.py
git commit -m "feat: add --fill flag for smart fill meal plans"
```

---

### Task 5: API Endpoint

**Files:**
- Modify: `api_server.py`

**Step 1: Add `/fill-meal-plan` endpoint**

Add after the existing `/add-to-meal-plan` POST route:

```python
@app.route('/fill-meal-plan', methods=['GET'])
def fill_meal_plan_endpoint():
    """Fill empty meal plan slots with AI-picked recipes."""
    from lib.smart_fill import fill_meal_plan

    week = request.args.get('week')
    if not week:
        return error_page("Error: week parameter required (e.g., 2026-W07)"), 400

    # Parse week
    try:
        parts = week.split('-W')
        year = int(parts[0])
        week_num = int(parts[1])
    except (ValueError, IndexError):
        return error_page(f"Error: Invalid week format: {week}"), 400

    # Find or create meal plan file
    MEAL_PLANS_PATH.mkdir(parents=True, exist_ok=True)
    plan_file = MEAL_PLANS_PATH / f"{week}.md"

    if not plan_file.exists():
        content = generate_meal_plan_markdown(year, week_num)
        plan_file.write_text(content, encoding='utf-8')
    else:
        content = plan_file.read_text(encoding='utf-8')

    try:
        updated, fills = fill_meal_plan(
            content, year, week_num,
            OBSIDIAN_RECIPES_PATH, MEAL_PLANS_PATH,
        )
    except ConnectionError:
        return error_page("Error: Cannot connect to Ollama. Is it running?"), 503
    except RuntimeError as e:
        return error_page(f"Error: {str(e)}"), 500

    if not fills:
        return error_page("No empty slots to fill."), 200

    # Write updated plan
    plan_file.write_text(updated, encoding='utf-8')

    # Success page
    from urllib.parse import quote
    encoded_file = quote(f"Meal Plans/{week}", safe='')
    fills_html = ''.join(f'<li>{f}</li>' for f in fills)

    return f'''<!DOCTYPE html>
<html><head><title>KitchenOS</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: system-ui; padding: 2rem; max-width: 600px; margin: 0 auto;">
<div style="background: #efe; border: 1px solid #0a0; padding: 1rem; border-radius: 8px;">
<strong style="color: #0a0;">Smart Fill Complete</strong><br>
Filled {len(fills)} slot(s):
<ul>{fills_html}</ul>
</div>
<p><a href="obsidian://open?vault=KitchenOS&file={encoded_file}">View Meal Plan</a></p>
</body></html>'''
```

**Step 2: Commit**

```bash
git add api_server.py
git commit -m "feat: add /fill-meal-plan API endpoint"
```

---

### Task 6: Smart Fill Button in Meal Plan Template

**Files:**
- Modify: `templates/meal_plan_template.py:31-53`

**Step 1: Add Smart Fill button**

In `generate_meal_plan_markdown()`, add the Smart Fill button after the Generate Shopping List button:

```python
    lines = [
        f"# Meal Plan - Week {week:02d} ({format_date_short(start_date)} - {format_date_short(end_date)}, {year})",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week_id}",
        "```",
        "",
        "```button",
        "name Smart Fill",
        "type link",
        f"url http://100.111.6.10:5001/fill-meal-plan?week={week_id}",
        "```",
        "",
    ]
```

**Step 2: Update test**

In `tests/test_meal_plan_template.py`, add a test:

```python
def test_includes_smart_fill_button(self):
    result = generate_meal_plan_markdown(2026, 3)
    assert "Smart Fill" in result
    assert "fill-meal-plan?week=2026-W03" in result
```

**Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_template.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add templates/meal_plan_template.py tests/test_meal_plan_template.py
git commit -m "feat: add Smart Fill button to meal plan template"
```

---

### Task 7: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update docs**

Add to the **Endpoints** table in CLAUDE.md:

```
| `/fill-meal-plan?week=<week>` | GET | AI-fill empty meal plan slots |
```

Add to the **Key Functions** section under a new heading:

```
**lib/smart_fill.py:**
- `fill_meal_plan()` - Fills empty meal plan slots using Ollama
- `find_empty_slots()` - Identifies empty slots in parsed meal plan
- `parse_fill_response()` - Parses Ollama JSON into slot assignments

**lib/recipe_catalog.py:**
- `load_recipe_catalog()` - Loads frontmatter metadata from all recipe files
- `format_catalog_for_prompt()` - Formats catalog as compact numbered list

**lib/time_utils.py:**
- `parse_time_to_minutes()` - Normalizes time strings to integer minutes
```

Add to **Running Commands** section:

```
### Smart Fill Meal Plan

```bash
# Fill empty slots in existing meal plan
.venv/bin/python generate_meal_plan.py --fill 2026-W07

# Preview without modifying
.venv/bin/python generate_meal_plan.py --fill 2026-W07 --dry-run
```
```

Add to **Core Components** table:

```
| `lib/smart_fill.py` | AI-powered meal plan slot filling |
| `lib/recipe_catalog.py` | Recipe metadata catalog loader |
| `lib/time_utils.py` | Time string parsing utilities |
| `prompts/smart_fill.py` | Smart fill prompt templates |
```

Update design doc status from "Approved" to "Completed".

**Step 2: Commit**

```bash
git add CLAUDE.md docs/plans/2026-02-14-smart-fill-design.md
git commit -m "docs: add smart fill documentation"
```
