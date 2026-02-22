# Meal Suggestions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Tap an empty meal slot to get an ingredient-aware recipe suggestion using a hybrid Ollama (local scoring) + Claude API (creative reasoning) pipeline.

**Architecture:** Extend `lib/recipe_index.py` to include parsed ingredients. Build `lib/meal_suggester.py` with ingredient overlap scoring, Ollama normalization, and Claude API reasoning. Add `/api/suggest-meal` endpoint. Update meal planner HTML with tap-to-suggest on empty cells.

**Tech Stack:** Python 3.11, Flask, Ollama (mistral:7b), Claude API (anthropic SDK), SortableJS

**Design Doc:** `docs/plans/2026-02-22-meal-suggestions-design.md`

---

### Task 1: Create pantry staples config

**Files:**
- Create: `config/pantry_staples.json`
- Test: `tests/test_meal_suggester.py` (create with first test)

**Step 1: Create the config file**

```json
[
    "salt", "pepper", "black pepper", "olive oil", "vegetable oil",
    "canola oil", "cooking spray", "butter", "garlic", "onion",
    "flour", "all-purpose flour", "sugar", "water", "ice"
]
```

**Step 2: Write the failing test**

Create `tests/test_meal_suggester.py`:

```python
"""Tests for meal suggestion engine."""

import json
from pathlib import Path


class TestPantryStaples:
    """Test pantry staples config loading."""

    def test_loads_pantry_staples(self):
        """Pantry staples config loads as a list of strings."""
        config_path = Path(__file__).parent.parent / "config" / "pantry_staples.json"
        with open(config_path) as f:
            staples = json.load(f)
        assert isinstance(staples, list)
        assert "salt" in staples
        assert "olive oil" in staples
        assert len(staples) >= 10
```

**Step 3: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py::TestPantryStaples::test_loads_pantry_staples -v`
Expected: PASS

**Step 4: Commit**

```bash
git add config/pantry_staples.json tests/test_meal_suggester.py
git commit -m "feat: add pantry staples config for meal suggestions"
```

---

### Task 2: Extend recipe index with ingredients

**Files:**
- Modify: `lib/recipe_index.py`
- Test: `tests/test_recipe_index.py`

The recipe index currently returns metadata without ingredients. We need an option to include parsed ingredient items so the meal suggester can score overlap.

**Step 1: Write the failing test**

Add to `tests/test_recipe_index.py`:

```python
class TestGetRecipeIndexWithIngredients:
    """Test ingredient extraction in recipe index."""

    def test_includes_ingredient_items_when_requested(self):
        """Should extract ingredient item names from recipe body."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Chicken Shawarma.md").write_text(
                '---\ntitle: "Chicken Shawarma"\ncuisine: "Middle Eastern"\nprotein: "chicken"\n---\n\n'
                '# Chicken Shawarma\n\n'
                '## Ingredients\n\n'
                '| Amount | Unit | Ingredient |\n'
                '|--------|------|------------|\n'
                '| 2 | lb | chicken thighs |\n'
                '| 1 | cup | greek yogurt |\n'
                '| 3 | cloves | garlic |\n'
                '| 1 | tsp | cumin |\n'
            )
            result = get_recipe_index(recipes_dir, include_ingredients=True)
            assert len(result) == 1
            items = result[0]["ingredient_items"]
            assert "chicken thighs" in items
            assert "greek yogurt" in items
            assert "garlic" in items
            assert "cumin" in items

    def test_ingredient_items_empty_when_no_table(self):
        """Recipes without ingredient tables get empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Simple.md").write_text(
                '---\ntitle: "Simple"\n---\n\n# Simple\n\nJust text.'
            )
            result = get_recipe_index(recipes_dir, include_ingredients=True)
            assert result[0]["ingredient_items"] == []

    def test_no_ingredients_by_default(self):
        """Default call should NOT include ingredient_items (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text(
                '---\ntitle: "Recipe"\ncuisine: "Italian"\n---\n\n# Recipe'
            )
            result = get_recipe_index(recipes_dir)
            assert "ingredient_items" not in result[0]
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py::TestGetRecipeIndexWithIngredients -v`
Expected: FAIL — `get_recipe_index() got an unexpected keyword argument 'include_ingredients'`

**Step 3: Implement**

Modify `lib/recipe_index.py`:

```python
"""Recipe index — scan recipe files and extract frontmatter metadata."""

from pathlib import Path

from lib.recipe_parser import parse_recipe_file, parse_recipe_body

FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type", "peak_months")


def get_recipe_index(recipes_dir: Path, include_ingredients: bool = False) -> list[dict]:
    """Scan all recipe .md files and return metadata for filtering.

    Args:
        recipes_dir: Path to the Recipes folder in Obsidian vault
        include_ingredients: If True, include 'ingredient_items' list of item strings

    Returns:
        List of dicts sorted by name, each with keys:
            name, cuisine, protein, difficulty, meal_occasion, dish_type, peak_months, image
            (plus ingredient_items if include_ingredients=True)
    """
    recipes = []

    for filepath in recipes_dir.iterdir():
        if not filepath.is_file() or filepath.suffix != ".md":
            continue

        name = filepath.stem
        entry = {"name": name}

        try:
            content = filepath.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            for field in FILTER_FIELDS:
                entry[field] = fm.get(field)

            if include_ingredients:
                body_data = parse_recipe_body(parsed["body"])
                entry["ingredient_items"] = [
                    ing["item"] for ing in body_data.get("ingredients", [])
                    if ing.get("item")
                ]
        except Exception:
            for field in FILTER_FIELDS:
                entry.setdefault(field, None)
            if include_ingredients:
                entry["ingredient_items"] = []

        # Check for matching image file
        images_dir = recipes_dir / "Images"
        image_file = images_dir / f"{name}.jpg"
        entry["image"] = f"{name}.jpg" if image_file.exists() else None

        recipes.append(entry)

    recipes.sort(key=lambda r: r["name"])
    return recipes
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v`
Expected: ALL PASS (including existing tests — backward compatible)

**Step 5: Commit**

```bash
git add lib/recipe_index.py tests/test_recipe_index.py
git commit -m "feat: add include_ingredients option to recipe index"
```

---

### Task 3: Build ingredient overlap scoring

**Files:**
- Create: `lib/meal_suggester.py`
- Test: `tests/test_meal_suggester.py` (append)

This is the core scoring logic. No AI calls — pure Python string matching.

**Step 1: Write the failing tests**

Append to `tests/test_meal_suggester.py`:

```python
from lib.meal_suggester import normalize_ingredient, score_overlap, rank_candidates


class TestNormalizeIngredient:
    """Test ingredient normalization for matching."""

    def test_lowercase(self):
        assert normalize_ingredient("Chicken Thighs") == "chicken thighs"

    def test_strips_preparation(self):
        assert normalize_ingredient("diced tomatoes") == "tomatoes"
        assert normalize_ingredient("minced garlic") == "garlic"
        assert normalize_ingredient("finely chopped onion") == "onion"

    def test_strips_adjectives(self):
        assert normalize_ingredient("fresh basil") == "basil"
        assert normalize_ingredient("large eggs") == "eggs"
        assert normalize_ingredient("boneless skinless chicken thighs") == "chicken thighs"

    def test_passthrough_simple(self):
        assert normalize_ingredient("rice") == "rice"
        assert normalize_ingredient("soy sauce") == "soy sauce"


class TestScoreOverlap:
    """Test ingredient overlap scoring."""

    def test_full_overlap(self):
        """Recipe using only planned ingredients scores 1.0."""
        recipe_items = ["chicken", "rice"]
        planned_items = {"chicken", "rice", "broccoli"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 1.0
        assert shared == {"chicken", "rice"}

    def test_no_overlap(self):
        """Recipe sharing nothing scores 0.0."""
        recipe_items = ["salmon", "asparagus"]
        planned_items = {"chicken", "rice"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.0
        assert shared == set()

    def test_partial_overlap(self):
        """Score proportional to shared ingredients."""
        recipe_items = ["chicken", "rice", "soy sauce", "ginger"]
        planned_items = {"chicken", "rice"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.5
        assert shared == {"chicken", "rice"}

    def test_pantry_staples_excluded(self):
        """Pantry staples don't count toward total."""
        recipe_items = ["chicken", "salt", "pepper", "olive oil"]
        planned_items = {"chicken"}
        pantry = {"salt", "pepper", "olive oil"}
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 1.0  # chicken is the only non-pantry item
        assert shared == {"chicken"}

    def test_all_pantry_returns_zero(self):
        """Recipe with only pantry items scores 0.0 (nothing meaningful to match)."""
        recipe_items = ["salt", "pepper", "water"]
        planned_items = {"chicken"}
        pantry = {"salt", "pepper", "water"}
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.0


class TestRankCandidates:
    """Test ranking recipes by overlap with planned meals."""

    def test_ranks_by_score_descending(self):
        """Highest overlap first."""
        candidates = [
            {"name": "A", "ingredient_items": ["salmon", "lemon"]},
            {"name": "B", "ingredient_items": ["chicken", "rice", "soy sauce"]},
            {"name": "C", "ingredient_items": ["chicken", "yogurt"]},
        ]
        planned_items = {"chicken", "yogurt", "rice"}
        pantry = set()
        ranked = rank_candidates(candidates, planned_items, pantry, limit=10)
        assert ranked[0]["name"] == "C"  # 2/2 = 1.0
        assert ranked[1]["name"] == "B"  # 2/3 = 0.67
        assert ranked[2]["name"] == "A"  # 0/2 = 0.0

    def test_excludes_already_planned(self):
        """Recipes already in the meal plan are not suggested."""
        candidates = [
            {"name": "Chicken Shawarma", "ingredient_items": ["chicken", "yogurt"]},
            {"name": "Chicken Gyros", "ingredient_items": ["chicken", "yogurt", "pita"]},
        ]
        planned_items = {"chicken", "yogurt"}
        pantry = set()
        planned_names = {"Chicken Shawarma"}
        ranked = rank_candidates(candidates, planned_items, pantry, limit=10, exclude_names=planned_names)
        assert len(ranked) == 1
        assert ranked[0]["name"] == "Chicken Gyros"

    def test_respects_limit(self):
        """Only returns top N candidates."""
        candidates = [
            {"name": f"Recipe {i}", "ingredient_items": ["chicken"]}
            for i in range(20)
        ]
        planned_items = {"chicken"}
        pantry = set()
        ranked = rank_candidates(candidates, planned_items, pantry, limit=5)
        assert len(ranked) == 5
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py::TestNormalizeIngredient -v`
Expected: FAIL — `cannot import name 'normalize_ingredient' from 'lib.meal_suggester'`

**Step 3: Implement**

Create `lib/meal_suggester.py`:

```python
"""Meal suggestion engine — ingredient overlap scoring with AI reasoning."""

import json
import os
import re
from pathlib import Path
from typing import Optional

import requests

PANTRY_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pantry_staples.json"

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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add lib/meal_suggester.py tests/test_meal_suggester.py
git commit -m "feat: add ingredient overlap scoring for meal suggestions"
```

---

### Task 4: Add Ollama ingredient normalization

**Files:**
- Modify: `lib/meal_suggester.py`
- Test: `tests/test_meal_suggester.py` (append)
- Create: `prompts/meal_suggestion.py`

The `normalize_ingredient()` from Task 3 handles simple cases. This task adds Ollama-powered normalization for edge cases (batch run, cached).

**Step 1: Create prompt file**

Create `prompts/meal_suggestion.py`:

```python
"""Prompt templates for meal suggestion engine."""

NORMALIZE_PROMPT = """Normalize these ingredient names to base grocery items.
Remove preparation words (diced, minced, sliced), sizes (large, small),
and descriptors (fresh, frozen, boneless, skinless).
Group equivalent cuts of the same protein (e.g. chicken breast, chicken thigh → chicken).

Input ingredients:
{ingredients}

Respond with ONLY a JSON array of normalized names, same order as input.
Example: ["chicken", "tomato", "greek yogurt"]"""


SUGGEST_PROMPT = """You are a meal planning assistant. The user is planning meals for the week and wants to minimize grocery shopping by reusing ingredients and leftovers across meals.

## Already planned this week:
{planned_meals}

## Candidate recipes (ranked by ingredient overlap with planned meals):
{candidates}

Pick the best candidate for {day} {meal} considering:
1. Can leftovers from an earlier meal be directly reused? (e.g., roast chicken → chicken soup)
2. Which candidate adds the fewest NEW ingredients to the shopping list?
3. Does it make sense for the position in the week? (batch cook early, use leftovers later)

If no candidate is a strong fit, suggest a simple new recipe idea that builds on this week's ingredients.

Respond with ONLY this JSON (no markdown, no explanation):
{{"name": "Recipe Name", "reason": "one sentence explaining ingredient reuse", "is_new_idea": false, "new_ingredients_needed": ["item1", "item2"]}}"""


SUGGEST_EMPTY_WEEK_PROMPT = """You are a meal planning assistant. The user is starting a fresh week with no meals planned yet.

## Available recipes in their library:
{recipe_summaries}

Suggest the best recipe to start the week for {day} {meal}. Choose a recipe that:
1. Uses versatile ingredients that can be reused in other meals later in the week
2. Works well for batch cooking or produces useful leftovers

Respond with ONLY this JSON (no markdown, no explanation):
{{"name": "Recipe Name", "reason": "one sentence explaining why this is a good starting point", "is_new_idea": false, "new_ingredients_needed": []}}"""
```

**Step 2: Write the failing test for Ollama normalization**

Append to `tests/test_meal_suggester.py`:

```python
from unittest.mock import patch, MagicMock


class TestOllamaNormalize:
    """Test Ollama-based ingredient normalization."""

    @patch("lib.meal_suggester.requests.post")
    def test_normalizes_via_ollama(self, mock_post):
        """Ollama returns normalized ingredient names."""
        from lib.meal_suggester import normalize_ingredients_ollama

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": '["chicken", "tomato", "greek yogurt"]'
        }
        mock_post.return_value = mock_response

        result = normalize_ingredients_ollama(
            ["boneless skinless chicken thighs", "fresh diced tomatoes", "low-fat Greek yogurt"]
        )
        assert result == ["chicken", "tomato", "greek yogurt"]

    @patch("lib.meal_suggester.requests.post")
    def test_falls_back_on_ollama_error(self, mock_post):
        """On Ollama failure, falls back to simple normalization."""
        from lib.meal_suggester import normalize_ingredients_ollama

        mock_post.side_effect = requests.exceptions.ConnectionError("Ollama down")

        result = normalize_ingredients_ollama(["fresh diced tomatoes", "large eggs"])
        assert result == ["tomatoes", "eggs"]
```

**Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py::TestOllamaNormalize -v`
Expected: FAIL — `cannot import name 'normalize_ingredients_ollama'`

**Step 4: Implement**

Add to `lib/meal_suggester.py`:

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"


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

        # Parse JSON array from response
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(items):
            return [str(n).lower().strip() for n in parsed]

        return [normalize_ingredient(item) for item in items]

    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return [normalize_ingredient(item) for item in items]
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add lib/meal_suggester.py prompts/meal_suggestion.py tests/test_meal_suggester.py
git commit -m "feat: add Ollama ingredient normalization with fallback"
```

---

### Task 5: Add Claude API suggestion call

**Files:**
- Modify: `lib/meal_suggester.py`
- Test: `tests/test_meal_suggester.py` (append)

**Step 1: Install anthropic package**

Run: `.venv/bin/pip install anthropic`

Add `anthropic>=0.40.0` to `requirements.txt`.

**Step 2: Write the failing tests**

Append to `tests/test_meal_suggester.py`:

```python
class TestClaudeSuggest:
    """Test Claude API suggestion call."""

    @patch("lib.meal_suggester.anthropic_client")
    def test_returns_suggestion_from_claude(self, mock_client):
        """Claude returns a recipe suggestion with reason."""
        from lib.meal_suggester import suggest_with_claude

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"name": "Chicken Fried Rice", "reason": "Uses leftover chicken from Monday", "is_new_idea": false, "new_ingredients_needed": ["rice", "soy sauce", "eggs"]}')]
        mock_client.messages.create.return_value = mock_message

        result = suggest_with_claude(
            planned_meals=[
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ],
            candidates=[
                {"name": "Chicken Fried Rice", "score": 0.4,
                 "shared_ingredients": ["chicken"],
                 "ingredient_items": ["chicken", "rice", "soy sauce", "eggs"]},
            ],
            day="Tuesday",
            meal="dinner",
        )
        assert result["name"] == "Chicken Fried Rice"
        assert "chicken" in result["reason"].lower() or "leftover" in result["reason"].lower()
        assert result["is_new_idea"] is False

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_returns_none_when_no_api_key(self):
        """Returns None if no Anthropic API key configured."""
        from lib.meal_suggester import suggest_with_claude

        result = suggest_with_claude(
            planned_meals=[{"day": "Monday", "meal": "dinner", "name": "X", "ingredients": ["a"]}],
            candidates=[{"name": "Y", "score": 0.3, "shared_ingredients": ["a"], "ingredient_items": ["a", "b"]}],
            day="Tuesday",
            meal="dinner",
        )
        assert result is None


class TestClaudeSuggestEmptyWeek:
    """Test Claude suggestion when no meals planned yet."""

    @patch("lib.meal_suggester.anthropic_client")
    def test_suggests_starting_recipe(self, mock_client):
        """When week is empty, suggests a good starting recipe."""
        from lib.meal_suggester import suggest_for_empty_week

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"name": "Chicken Shawarma", "reason": "Versatile chicken and yogurt base for multiple meals", "is_new_idea": false, "new_ingredients_needed": []}')]
        mock_client.messages.create.return_value = mock_message

        result = suggest_for_empty_week(
            recipe_summaries=[
                {"name": "Chicken Shawarma", "cuisine": "Middle Eastern", "protein": "chicken"},
                {"name": "Pasta Aglio", "cuisine": "Italian", "protein": "none"},
            ],
            day="Monday",
            meal="dinner",
        )
        assert result["name"] == "Chicken Shawarma"
        assert result["is_new_idea"] is False
```

**Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py::TestClaudeSuggest -v`
Expected: FAIL — `cannot import name 'suggest_with_claude'`

**Step 4: Implement**

Add to `lib/meal_suggester.py` (at the top, after existing imports):

```python
try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:
    anthropic_client = None
```

Add functions at the bottom:

```python
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 200


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

    # Format planned meals
    planned_text = "\n".join(
        f"- {m['day']} {m['meal']}: **{m['name']}** (ingredients: {', '.join(m['ingredients'])})"
        for m in planned_meals
    )

    # Format candidates
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
        # Extract JSON from response
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
        for r in recipe_summaries[:50]  # Limit to avoid huge prompts
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
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add lib/meal_suggester.py prompts/meal_suggestion.py tests/test_meal_suggester.py requirements.txt
git commit -m "feat: add Claude API suggestion with empty-week support"
```

---

### Task 6: Build the top-level suggest_meal() orchestrator

**Files:**
- Modify: `lib/meal_suggester.py`
- Test: `tests/test_meal_suggester.py` (append)

This is the main function that the API endpoint will call. It ties together scoring, tier decisions, and Claude/Ollama calls.

**Step 1: Write the failing tests**

Append to `tests/test_meal_suggester.py`:

```python
import tempfile


class TestSuggestMeal:
    """Test the top-level suggest_meal orchestrator."""

    def _make_recipes_dir(self, tmpdir, recipes):
        """Helper: write recipe files to a temp dir and return Path."""
        recipes_dir = Path(tmpdir)
        for name, ingredients in recipes.items():
            rows = "".join(
                f"| 1 | whole | {item} |\n" for item in ingredients
            )
            content = (
                f'---\ntitle: "{name}"\ncuisine: "test"\nprotein: "test"\n---\n\n'
                f"# {name}\n\n## Ingredients\n\n"
                f"| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}"
            )
            (recipes_dir / f"{name}.md").write_text(content)
        return recipes_dir

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_high_overlap_skips_claude(self):
        """When top candidate has >= 0.5 overlap, returns it without Claude."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Chicken Gyros": ["chicken", "yogurt", "pita", "cucumber"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir,
                planned_meals=planned,
                day="Tuesday",
                meal="dinner",
                skip_index=0,
            )
            assert result is not None
            assert result["name"] == "Chicken Gyros"
            assert result["score"] >= 0.5

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_excludes_planned_recipes(self):
        """Already-planned recipes are not suggested."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Chicken Shawarma": ["chicken", "yogurt", "cumin"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir,
                planned_meals=planned,
                day="Tuesday",
                meal="dinner",
                skip_index=0,
            )
            # Should not suggest Chicken Shawarma since it's already planned
            assert result is None or result["name"] != "Chicken Shawarma"

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_skip_index_cycles_candidates(self):
        """skip_index=1 returns second candidate."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "A": ["chicken", "yogurt"],
                "B": ["chicken", "rice"],
                "C": ["salmon", "rice"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Shawarma",
                 "ingredients": ["chicken", "yogurt"]},
            ]
            first = suggest_meal(recipes_dir=recipes_dir, planned_meals=planned,
                                 day="Tue", meal="dinner", skip_index=0)
            second = suggest_meal(recipes_dir=recipes_dir, planned_meals=planned,
                                  day="Tue", meal="dinner", skip_index=1)
            assert first is not None
            assert second is not None
            assert first["name"] != second["name"]
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py::TestSuggestMeal -v`
Expected: FAIL — `cannot import name 'suggest_meal'`

**Step 3: Implement**

Add to `lib/meal_suggester.py`:

```python
OVERLAP_THRESHOLD = 0.5


def suggest_meal(
    recipes_dir: Path,
    planned_meals: list[dict],
    day: str,
    meal: str,
    skip_index: int = 0,
) -> Optional[dict]:
    """Top-level orchestrator: suggest a meal for an empty slot.

    Pipeline:
    1. If no meals planned → ask Claude for a starting recipe (or return None)
    2. Collect planned ingredient names
    3. Load recipe library with ingredients
    4. Score and rank candidates
    5. If top candidate score >= threshold → return it directly
    6. Else → ask Claude to pick from candidates
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

    # Empty week — ask Claude or return None
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
        # High overlap — use directly
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

    # Low overlap — try Claude
    claude_result = suggest_with_claude(planned_meals, ranked[skip_index:], day, meal)
    if claude_result:
        # Check if Claude picked an existing recipe
        match = next((r for r in ranked if r["name"] == claude_result["name"]), None)
        if match:
            claude_result["score"] = match["score"]
            claude_result["shared_ingredients"] = match["shared_ingredients"]
        else:
            claude_result["score"] = 0.0
            claude_result["shared_ingredients"] = []
        return claude_result

    # Claude unavailable — fall back to top scored candidate
    top["reason"] = f"Shares {', '.join(top['shared_ingredients'][:3])}" if top["shared_ingredients"] else "Best available match"
    top["is_new_idea"] = False
    top["new_ingredients_needed"] = []
    return top
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_suggester.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add lib/meal_suggester.py tests/test_meal_suggester.py
git commit -m "feat: add suggest_meal orchestrator with tier decisions"
```

---

### Task 7: Add /api/suggest-meal endpoint

**Files:**
- Modify: `api_server.py`
- Test: `tests/test_api_endpoints.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_suggest_meal_requires_fields(client):
    """Suggest endpoint requires week, day, meal fields."""
    response = client.post('/api/suggest-meal', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_suggest_meal_invalid_week(client):
    """Invalid week format returns 400."""
    response = client.post('/api/suggest-meal', json={
        "week": "invalid", "day": "Monday", "meal": "dinner"
    })
    assert response.status_code == 400
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_suggest_meal_requires_fields -v`
Expected: FAIL — 404 (endpoint doesn't exist)

**Step 3: Implement**

Find the location in `api_server.py` where other `/api/` routes are defined (near `api_meal_plan_get` and `api_meal_plan_put`). Add the new endpoint:

```python
@app.route('/api/suggest-meal', methods=['POST'])
def api_suggest_meal():
    """Suggest a recipe for an empty meal slot based on ingredient overlap."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Request body required"}), 400

    week = data.get("week")
    day = data.get("day")
    meal = data.get("meal")
    skip_index = data.get("skip_index", 0)

    if not week or not day or not meal:
        return jsonify({"error": "Required fields: week, day, meal"}), 400

    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400

    # Load current meal plan to get planned meals with ingredients
    plan_file = MEAL_PLANS_PATH / f"{week}.md"
    planned_meals = []

    if plan_file.exists():
        from lib.meal_plan_parser import parse_meal_plan
        from lib.recipe_parser import parse_recipe_file, parse_recipe_body

        content = plan_file.read_text(encoding="utf-8")
        parsed = parse_meal_plan(content)

        for day_data in parsed:
            for meal_type in ("breakfast", "lunch", "dinner"):
                entry = day_data.get(meal_type)
                if entry is not None and entry.name:
                    # Load ingredient items for this recipe
                    recipe_file = OBSIDIAN_RECIPES_PATH / f"{entry.name}.md"
                    ingredients = []
                    if recipe_file.exists():
                        try:
                            rc = recipe_file.read_text(encoding="utf-8")
                            rp = parse_recipe_file(rc)
                            body_data = parse_recipe_body(rp["body"])
                            ingredients = [
                                ing["item"] for ing in body_data.get("ingredients", [])
                                if ing.get("item")
                            ]
                        except Exception:
                            pass

                    planned_meals.append({
                        "day": day_data["day"],
                        "meal": meal_type,
                        "name": entry.name,
                        "ingredients": ingredients,
                    })

    from lib.meal_suggester import suggest_meal

    result = suggest_meal(
        recipes_dir=OBSIDIAN_RECIPES_PATH,
        planned_meals=planned_meals,
        day=day,
        meal=meal,
        skip_index=skip_index,
    )

    if result is None:
        return jsonify({"suggestion": None, "message": "No suggestions available"})

    return jsonify({"suggestion": result})
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_endpoints.py
git commit -m "feat: add /api/suggest-meal endpoint"
```

---

### Task 8: Add tap-to-suggest UI to meal planner

**Files:**
- Modify: `templates/meal_planner.html`

This task adds all frontend changes: empty cell tap handler, spinner, retry button, new-idea styling, and toast messages.

**Step 1: Add CSS for suggestion states**

Add these styles inside the `<style>` block in `templates/meal_planner.html`, after the existing `.grid-card` styles:

```css
/* --- Suggestion States --- */
.grid-cell.suggesting {
    border-color: var(--accent);
    border-style: solid;
    animation: pulse-border 1.5s ease-in-out infinite;
}

@keyframes pulse-border {
    0%, 100% { border-color: var(--accent); }
    50% { border-color: var(--border); }
}

.grid-cell.suggesting .empty-label {
    display: flex;
}

.grid-cell.suggesting .empty-label::before {
    content: '';
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 8px;
}

.grid-card .retry-btn {
    position: absolute;
    top: 4px;
    left: 4px;
    width: 22px;
    height: 22px;
    border: none;
    background: var(--accent);
    color: #ffffff;
    border-radius: 50%;
    font-size: 13px;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.7;
    transition: opacity 0.15s ease;
}

.grid-card .retry-btn:hover,
.grid-card .retry-btn:active {
    opacity: 1;
}

.grid-card.has-image .retry-btn {
    z-index: 1;
    background: rgba(0, 113, 227, 0.7);
}

.grid-card.new-idea {
    border-style: dashed;
    border-color: var(--accent);
}

.grid-card.new-idea .grid-card-name {
    font-style: italic;
}
```

**Step 2: Add empty cell click handler**

In the `<script>` block, add a new state variable at the top (near `let saveTimeout`):

```javascript
let suggestionSkipIndex = {};  // { "Tuesday-dinner": 0 } — tracks retries per cell
```

Add this function:

```javascript
async function suggestMeal(cell) {
    const day = cell.dataset.day;
    const meal = cell.dataset.meal;
    const cellKey = `${day}-${meal}`;

    // Already has a recipe or already suggesting
    if (cell.querySelector('.grid-card') || cell.classList.contains('suggesting')) return;

    // Show spinner
    cell.classList.add('suggesting');
    const emptyLabel = cell.querySelector('.empty-label');
    if (emptyLabel) emptyLabel.textContent = 'Suggesting...';

    const skipIndex = suggestionSkipIndex[cellKey] || 0;

    try {
        const response = await fetch('/api/suggest-meal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                week: currentWeek,
                day: day,
                meal: meal,
                skip_index: skipIndex,
            }),
        });

        const data = await response.json();

        cell.classList.remove('suggesting');

        if (!data.suggestion) {
            if (emptyLabel) emptyLabel.textContent = 'Drop recipe';
            showToast('No suggestions available', 'error');
            return;
        }

        const suggestion = data.suggestion;
        const card = createSuggestedCard(suggestion, cell);
        cell.appendChild(card);
        updateCellState(cell);
        debounceSave();

        // Show reason toast
        if (suggestion.reason) {
            showToast(suggestion.reason, 'success');
        }

        // Increment skip index for retry
        suggestionSkipIndex[cellKey] = skipIndex + 1;

    } catch (err) {
        console.error('Suggestion failed:', err);
        cell.classList.remove('suggesting');
        if (emptyLabel) emptyLabel.textContent = 'Drop recipe';
        showToast('Suggestion failed', 'error');
    }
}

function createSuggestedCard(suggestion, cell) {
    const card = createGridCard(suggestion.name, 1);

    // Mark new ideas
    if (suggestion.is_new_idea) {
        card.classList.add('new-idea');
    }

    // Add retry button
    const retryBtn = document.createElement('button');
    retryBtn.className = 'retry-btn';
    retryBtn.innerHTML = '&#x21bb;';  // ↻
    retryBtn.setAttribute('aria-label', 'Try another suggestion');
    retryBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        e.preventDefault();
        const parentCell = card.parentElement;
        card.remove();
        updateCellState(parentCell);
        suggestMeal(parentCell);
    });
    card.appendChild(retryBtn);

    return card;
}
```

**Step 3: Wire up empty cell clicks**

Modify the `buildGrid()` function. After creating each cell, add a click listener. Find this line in `buildGrid()`:

```javascript
cell.innerHTML = `<div class="meal-label">${MEAL_LABELS[meal]}</div><div class="empty-label">Drop recipe</div>`;
```

Add after appending the cell to the grid:

```javascript
cell.addEventListener('click', function(e) {
    // Only trigger on the empty area, not on cards
    if (e.target === cell || e.target.classList.contains('empty-label') || e.target.classList.contains('meal-label')) {
        suggestMeal(cell);
    }
});
```

**Step 4: Reset skip index on week navigation**

In the `navigateWeek()` function, add after `currentWeek = offsetWeek(...)`:

```javascript
suggestionSkipIndex = {};
```

**Step 5: Manual test**

Open `http://localhost:5001/meal-planner` in a browser:
1. Add one recipe to Monday dinner by dragging
2. Tap an empty cell (e.g., Tuesday dinner)
3. Verify spinner appears, then suggestion fills in
4. Tap the ↻ button to get another suggestion
5. Verify toast shows the reason

Run: `curl -X POST http://localhost:5001/api/suggest-meal -H "Content-Type: application/json" -d '{"week": "2026-W09", "day": "Tuesday", "meal": "dinner"}'`
Expected: JSON with `suggestion` key

**Step 6: Commit**

```bash
git add templates/meal_planner.html
git commit -m "feat: add tap-to-suggest UI for meal planner empty cells"
```

---

### Task 9: Add ANTHROPIC_API_KEY to .env and install dependency

**Files:**
- Modify: `.env` (add key placeholder)
- Modify: `requirements.txt` (add anthropic)

**Step 1: Add to requirements.txt**

Add this line: `anthropic>=0.40.0`

**Step 2: Install**

Run: `.venv/bin/pip install anthropic`

**Step 3: Add key to .env**

Add `ANTHROPIC_API_KEY=` line. The user will need to fill in their actual key.

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add anthropic SDK dependency for meal suggestions"
```

Note: Do NOT commit .env file.

---

### Task 10: Update documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Add to the **Endpoints** table:

```
| `/api/suggest-meal` | POST | Suggest recipe for empty meal slot |
```

Add to **Key Functions** under a new section or extend `api_server.py`:

```
**lib/meal_suggester.py:**
- `suggest_meal()` - Top-level orchestrator: scores ingredients, tiers to Claude
- `score_overlap()` - Scores ingredient overlap between recipe and planned meals
- `rank_candidates()` - Ranks all recipes by overlap score
- `normalize_ingredient()` - Normalizes ingredient name for matching
- `normalize_ingredients_ollama()` - Batch normalize via Ollama with fallback
- `suggest_with_claude()` - Asks Claude API to pick best candidate
- `suggest_for_empty_week()` - Asks Claude for starting recipe
```

Add to **Core Components** table:

```
| `lib/meal_suggester.py` | Ingredient overlap scoring + Claude/Ollama suggestion |
| `prompts/meal_suggestion.py` | Prompt templates for ingredient normalization and meal selection |
| `config/pantry_staples.json` | Pantry staples excluded from overlap scoring |
```

Add to **Environment** section:

```
- `ANTHROPIC_API_KEY` - Claude API for meal suggestions
```

Add to **Dependencies**:

```
anthropic                     # Claude API for meal suggestions
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add meal suggestion feature to CLAUDE.md"
```

---

### Task 11: End-to-end integration test

**Files:**
- No new files — manual testing

**Step 1: Ensure Ollama is running**

Run: `curl http://localhost:11434/api/tags`
Expected: 200 OK with model list

**Step 2: Ensure API server is running**

Run: `curl http://localhost:5001/health`
Expected: 200 OK

If not running: `launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist`

**Step 3: Test suggest endpoint with no planned meals**

```bash
curl -X POST http://localhost:5001/api/suggest-meal \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W09", "day": "Monday", "meal": "dinner"}'
```

Expected: JSON with a suggestion (from Claude if key is set, or None if not)

**Step 4: Test suggest endpoint with planned meals**

First, add a recipe to a meal plan, then:

```bash
curl -X POST http://localhost:5001/api/suggest-meal \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W09", "day": "Tuesday", "meal": "dinner"}'
```

Expected: JSON with a suggestion that shares ingredients with Monday's recipe

**Step 5: Test retry (skip_index)**

```bash
curl -X POST http://localhost:5001/api/suggest-meal \
  -H "Content-Type: application/json" \
  -d '{"week": "2026-W09", "day": "Tuesday", "meal": "dinner", "skip_index": 1}'
```

Expected: Different recipe than skip_index=0

**Step 6: Test in browser**

Open `http://localhost:5001/meal-planner` and test the full flow:
1. Drag a recipe to Monday dinner
2. Tap Tuesday dinner empty cell
3. Verify spinner → suggestion → toast
4. Tap ↻ for another suggestion
5. Navigate to different week, verify skip index resets

**Step 7: Final commit**

If all tests pass, run the full test suite:

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: ALL PASS
