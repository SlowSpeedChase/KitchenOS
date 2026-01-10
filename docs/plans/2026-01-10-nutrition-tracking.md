# Nutrition Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add macro tracking to recipes and generate a dashboard showing daily nutrition totals vs personal targets.

**Architecture:** Nutrition data stored per-serving in recipe frontmatter. Lookup chain: Nutritionix API → USDA API → AI estimation. Dashboard generator reads meal plans, sums recipe nutrition, compares to targets in My Macros.md.

**Tech Stack:** Python 3.11, requests (API calls), existing Ollama integration for AI fallback

**Design Doc:** `docs/plans/2026-01-10-nutrition-tracking-design.md`

---

## Task 1: Nutrition Data Types

**Files:**
- Create: `lib/nutrition.py`
- Test: `tests/test_nutrition.py`

**Step 1: Write the failing test**

```python
# tests/test_nutrition.py
"""Tests for nutrition data types."""

from lib.nutrition import NutritionData


class TestNutritionData:
    def test_create_nutrition_data(self):
        data = NutritionData(calories=450, protein=25, carbs=45, fat=18)
        assert data.calories == 450
        assert data.protein == 25
        assert data.carbs == 45
        assert data.fat == 18

    def test_add_nutrition_data(self):
        a = NutritionData(calories=200, protein=10, carbs=20, fat=8)
        b = NutritionData(calories=300, protein=15, carbs=25, fat=10)
        result = a + b
        assert result.calories == 500
        assert result.protein == 25
        assert result.carbs == 45
        assert result.fat == 18

    def test_multiply_nutrition_data(self):
        data = NutritionData(calories=200, protein=10, carbs=20, fat=8)
        result = data * 2
        assert result.calories == 400
        assert result.protein == 20
        assert result.carbs == 40
        assert result.fat == 16

    def test_nutrition_data_to_dict(self):
        data = NutritionData(calories=450, protein=25, carbs=45, fat=18)
        result = data.to_dict()
        assert result == {"calories": 450, "protein": 25, "carbs": 45, "fat": 18}

    def test_nutrition_data_from_dict(self):
        d = {"calories": 450, "protein": 25, "carbs": 45, "fat": 18}
        data = NutritionData.from_dict(d)
        assert data.calories == 450
        assert data.protein == 25

    def test_empty_nutrition_data(self):
        data = NutritionData.empty()
        assert data.calories == 0
        assert data.protein == 0
        assert data.carbs == 0
        assert data.fat == 0
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition.py -v`
Expected: FAIL with "No module named 'lib.nutrition'"

**Step 3: Write minimal implementation**

```python
# lib/nutrition.py
"""Nutrition data types for macro tracking."""

from dataclasses import dataclass
from typing import Self


@dataclass
class NutritionData:
    """Nutrition values per serving."""
    calories: int
    protein: int
    carbs: int
    fat: int

    def __add__(self, other: Self) -> Self:
        return NutritionData(
            calories=self.calories + other.calories,
            protein=self.protein + other.protein,
            carbs=self.carbs + other.carbs,
            fat=self.fat + other.fat,
        )

    def __mul__(self, multiplier: int | float) -> Self:
        return NutritionData(
            calories=int(self.calories * multiplier),
            protein=int(self.protein * multiplier),
            carbs=int(self.carbs * multiplier),
            fat=int(self.fat * multiplier),
        )

    def to_dict(self) -> dict:
        return {
            "calories": self.calories,
            "protein": self.protein,
            "carbs": self.carbs,
            "fat": self.fat,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            calories=d.get("calories", 0),
            protein=d.get("protein", 0),
            carbs=d.get("carbs", 0),
            fat=d.get("fat", 0),
        )

    @classmethod
    def empty(cls) -> Self:
        return cls(calories=0, protein=0, carbs=0, fat=0)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add lib/nutrition.py tests/test_nutrition.py
git commit -m "feat(nutrition): add NutritionData dataclass with arithmetic ops"
```

---

## Task 2: Nutritionix API Client

**Files:**
- Create: `lib/nutrition_lookup.py`
- Test: `tests/test_nutrition_lookup.py`

**Step 1: Write the failing test**

```python
# tests/test_nutrition_lookup.py
"""Tests for nutrition lookup APIs."""

import json
from unittest.mock import patch, Mock

from lib.nutrition_lookup import lookup_nutritionix, NutritionLookupResult
from lib.nutrition import NutritionData


class TestLookupNutritionix:
    def test_parses_successful_response(self):
        mock_response = {
            "foods": [{
                "nf_calories": 364.42,
                "nf_protein": 10.33,
                "nf_total_carbohydrate": 76.31,
                "nf_total_fat": 0.98,
            }]
        }

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_nutritionix("1 cup flour")

        assert result is not None
        assert result.nutrition.calories == 364
        assert result.nutrition.protein == 10
        assert result.nutrition.carbs == 76
        assert result.nutrition.fat == 1
        assert result.source == "nutritionix"

    def test_returns_none_on_empty_foods(self):
        mock_response = {"foods": []}

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_nutritionix("unknown ingredient xyz")

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(status_code=401)
            result = lookup_nutritionix("1 cup flour")

        assert result is None

    def test_returns_none_on_missing_credentials(self):
        with patch("lib.nutrition_lookup.os.getenv", return_value=None):
            result = lookup_nutritionix("1 cup flour")

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestLookupNutritionix -v`
Expected: FAIL with "cannot import name 'lookup_nutritionix'"

**Step 3: Write minimal implementation**

```python
# lib/nutrition_lookup.py
"""Nutrition lookup from external APIs."""

import os
from dataclasses import dataclass
from typing import Optional

import requests

from lib.nutrition import NutritionData


NUTRITIONIX_URL = "https://trackapi.nutritionix.com/v2/natural/nutrients"


@dataclass
class NutritionLookupResult:
    """Result from a nutrition lookup."""
    nutrition: NutritionData
    source: str  # "nutritionix", "usda", "ai", "manual"


def lookup_nutritionix(ingredient: str) -> Optional[NutritionLookupResult]:
    """Look up nutrition data from Nutritionix API.

    Args:
        ingredient: Natural language ingredient (e.g., "2 cups flour")

    Returns:
        NutritionLookupResult or None if lookup fails
    """
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    api_key = os.getenv("NUTRITIONIX_API_KEY")

    if not app_id or not api_key:
        return None

    headers = {
        "x-app-id": app_id,
        "x-app-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            NUTRITIONIX_URL,
            headers=headers,
            json={"query": ingredient},
            timeout=10,
        )

        if response.status_code != 200:
            return None

        data = response.json()
        foods = data.get("foods", [])

        if not foods:
            return None

        food = foods[0]
        nutrition = NutritionData(
            calories=int(food.get("nf_calories", 0)),
            protein=int(food.get("nf_protein", 0)),
            carbs=int(food.get("nf_total_carbohydrate", 0)),
            fat=int(food.get("nf_total_fat", 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="nutritionix")

    except (requests.RequestException, KeyError, ValueError):
        return None
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestLookupNutritionix -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add lib/nutrition_lookup.py tests/test_nutrition_lookup.py
git commit -m "feat(nutrition): add Nutritionix API client"
```

---

## Task 3: USDA API Client

**Files:**
- Modify: `lib/nutrition_lookup.py`
- Modify: `tests/test_nutrition_lookup.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_nutrition_lookup.py

from lib.nutrition_lookup import lookup_usda


class TestLookupUsda:
    def test_parses_successful_response(self):
        mock_response = {
            "foods": [{
                "fdcId": 123456,
                "description": "Flour, wheat, all-purpose",
                "foodNutrients": [
                    {"nutrientId": 1008, "value": 364},  # calories
                    {"nutrientId": 1003, "value": 10},   # protein
                    {"nutrientId": 1005, "value": 76},   # carbs
                    {"nutrientId": 1004, "value": 1},    # fat
                ]
            }]
        }

        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_usda("flour")

        assert result is not None
        assert result.nutrition.calories == 364
        assert result.nutrition.protein == 10
        assert result.nutrition.carbs == 76
        assert result.nutrition.fat == 1
        assert result.source == "usda"

    def test_returns_none_on_empty_results(self):
        mock_response = {"foods": []}

        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: mock_response
            )
            result = lookup_usda("unknown ingredient xyz")

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=500)
            result = lookup_usda("flour")

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestLookupUsda -v`
Expected: FAIL with "cannot import name 'lookup_usda'"

**Step 3: Write minimal implementation**

```python
# Add to lib/nutrition_lookup.py

USDA_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# USDA nutrient IDs
NUTRIENT_CALORIES = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_CARBS = 1005
NUTRIENT_FAT = 1004


def lookup_usda(ingredient: str) -> Optional[NutritionLookupResult]:
    """Look up nutrition data from USDA FoodData Central.

    Args:
        ingredient: Ingredient name to search

    Returns:
        NutritionLookupResult or None if lookup fails
    """
    # Extract just the food name (remove quantities)
    # Simple approach: take last word or phrase after numbers
    words = ingredient.split()
    food_name = " ".join(w for w in words if not w.replace(".", "").replace("/", "").isdigit())

    params = {
        "query": food_name,
        "pageSize": 1,
        "dataType": ["Foundation", "SR Legacy"],
    }

    try:
        response = requests.get(USDA_URL, params=params, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        foods = data.get("foods", [])

        if not foods:
            return None

        food = foods[0]
        nutrients = {n["nutrientId"]: n.get("value", 0) for n in food.get("foodNutrients", [])}

        nutrition = NutritionData(
            calories=int(nutrients.get(NUTRIENT_CALORIES, 0)),
            protein=int(nutrients.get(NUTRIENT_PROTEIN, 0)),
            carbs=int(nutrients.get(NUTRIENT_CARBS, 0)),
            fat=int(nutrients.get(NUTRIENT_FAT, 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="usda")

    except (requests.RequestException, KeyError, ValueError):
        return None
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestLookupUsda -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add lib/nutrition_lookup.py tests/test_nutrition_lookup.py
git commit -m "feat(nutrition): add USDA FoodData Central API client"
```

---

## Task 4: AI Estimation Fallback

**Files:**
- Modify: `lib/nutrition_lookup.py`
- Modify: `tests/test_nutrition_lookup.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_nutrition_lookup.py

from lib.nutrition_lookup import estimate_with_ai


class TestEstimateWithAi:
    def test_parses_ollama_response(self):
        mock_ollama_response = {
            "response": '{"calories": 200, "protein": 5, "carbs": 40, "fat": 2}'
        }

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_ollama_response
            )
            result = estimate_with_ai(["1 cup flour", "2 eggs"])

        assert result is not None
        assert result.nutrition.calories == 200
        assert result.source == "ai"

    def test_returns_none_on_invalid_json(self):
        mock_ollama_response = {
            "response": "I cannot determine the nutrition."
        }

        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_ollama_response
            )
            result = estimate_with_ai(["mystery ingredient"])

        assert result is None

    def test_returns_none_on_api_error(self):
        with patch("lib.nutrition_lookup.requests.post") as mock_post:
            mock_post.side_effect = requests.RequestException("Connection failed")
            result = estimate_with_ai(["1 cup flour"])

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestEstimateWithAi -v`
Expected: FAIL with "cannot import name 'estimate_with_ai'"

**Step 3: Write minimal implementation**

```python
# Add to lib/nutrition_lookup.py

import json

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

NUTRITION_PROMPT = """Estimate the total nutrition for these ingredients combined.
Return ONLY a JSON object with these exact keys: calories, protein, carbs, fat.
Values should be integers representing the total for all ingredients.

Ingredients:
{ingredients}

JSON response:"""


def estimate_with_ai(ingredients: list[str]) -> Optional[NutritionLookupResult]:
    """Estimate nutrition using Ollama AI.

    Args:
        ingredients: List of ingredient strings

    Returns:
        NutritionLookupResult or None if estimation fails
    """
    prompt = NUTRITION_PROMPT.format(ingredients="\n".join(f"- {i}" for i in ingredients))

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )

        if response.status_code != 200:
            return None

        data = response.json()
        response_text = data.get("response", "")

        # Extract JSON from response
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1

        if json_start == -1 or json_end == 0:
            return None

        nutrition_json = json.loads(response_text[json_start:json_end])

        nutrition = NutritionData(
            calories=int(nutrition_json.get("calories", 0)),
            protein=int(nutrition_json.get("protein", 0)),
            carbs=int(nutrition_json.get("carbs", 0)),
            fat=int(nutrition_json.get("fat", 0)),
        )

        return NutritionLookupResult(nutrition=nutrition, source="ai")

    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError):
        return None
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestEstimateWithAi -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add lib/nutrition_lookup.py tests/test_nutrition_lookup.py
git commit -m "feat(nutrition): add AI estimation fallback via Ollama"
```

---

## Task 5: Recipe Nutrition Calculator

**Files:**
- Modify: `lib/nutrition_lookup.py`
- Modify: `tests/test_nutrition_lookup.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_nutrition_lookup.py

from lib.nutrition_lookup import calculate_recipe_nutrition


class TestCalculateRecipeNutrition:
    def test_sums_ingredients_and_divides_by_servings(self):
        ingredients = [
            {"amount": "2", "unit": "cups", "item": "flour"},
            {"amount": "3", "unit": "whole", "item": "eggs"},
        ]

        # Mock both lookups to return known values
        with patch("lib.nutrition_lookup.lookup_nutritionix") as mock_nx:
            mock_nx.side_effect = [
                NutritionLookupResult(NutritionData(400, 10, 80, 2), "nutritionix"),
                NutritionLookupResult(NutritionData(210, 18, 3, 15), "nutritionix"),
            ]
            result = calculate_recipe_nutrition(ingredients, servings=2)

        # Total: 610 cal, 28 protein, 83 carbs, 17 fat
        # Per serving (÷2): 305, 14, 41.5→41, 8.5→8
        assert result.nutrition.calories == 305
        assert result.nutrition.protein == 14
        assert result.nutrition.carbs == 41
        assert result.nutrition.fat == 8
        assert result.source == "nutritionix"

    def test_falls_back_to_usda(self):
        ingredients = [{"amount": "1", "unit": "cup", "item": "flour"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda") as mock_usda:
                mock_usda.return_value = NutritionLookupResult(
                    NutritionData(364, 10, 76, 1), "usda"
                )
                result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result.source == "usda"

    def test_falls_back_to_ai(self):
        ingredients = [{"amount": "1", "unit": "cup", "item": "mystery"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda", return_value=None):
                with patch("lib.nutrition_lookup.estimate_with_ai") as mock_ai:
                    mock_ai.return_value = NutritionLookupResult(
                        NutritionData(100, 5, 20, 2), "ai"
                    )
                    result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result.source == "ai"

    def test_returns_none_when_all_fail(self):
        ingredients = [{"amount": "1", "unit": "cup", "item": "unknown"}]

        with patch("lib.nutrition_lookup.lookup_nutritionix", return_value=None):
            with patch("lib.nutrition_lookup.lookup_usda", return_value=None):
                with patch("lib.nutrition_lookup.estimate_with_ai", return_value=None):
                    result = calculate_recipe_nutrition(ingredients, servings=1)

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestCalculateRecipeNutrition -v`
Expected: FAIL with "cannot import name 'calculate_recipe_nutrition'"

**Step 3: Write minimal implementation**

```python
# Add to lib/nutrition_lookup.py

def calculate_recipe_nutrition(
    ingredients: list[dict],
    servings: int
) -> Optional[NutritionLookupResult]:
    """Calculate total nutrition for a recipe.

    Tries Nutritionix first, then USDA, then AI estimation.

    Args:
        ingredients: List of ingredient dicts with amount, unit, item
        servings: Number of servings in recipe

    Returns:
        NutritionLookupResult with per-serving values, or None if all fail
    """
    total = NutritionData.empty()
    source = "nutritionix"
    failed_ingredients = []

    for ing in ingredients:
        ingredient_str = f"{ing.get('amount', '1')} {ing.get('unit', '')} {ing.get('item', '')}".strip()

        # Try Nutritionix first
        result = lookup_nutritionix(ingredient_str)

        # Fall back to USDA
        if result is None:
            result = lookup_usda(ing.get("item", ""))
            if result:
                source = "usda" if source == "nutritionix" else source

        if result:
            total = total + result.nutrition
        else:
            failed_ingredients.append(ingredient_str)

    # If any ingredients failed, try AI for the whole list
    if failed_ingredients:
        ai_result = estimate_with_ai(failed_ingredients)
        if ai_result:
            total = total + ai_result.nutrition
            source = "ai"
        elif not any(lookup_nutritionix(f"{i.get('amount', '1')} {i.get('unit', '')} {i.get('item', '')}".strip()) or lookup_usda(i.get("item", "")) for i in ingredients):
            # All ingredients failed
            return None

    # Divide by servings for per-serving values
    if servings > 0:
        per_serving = total * (1 / servings)
    else:
        per_serving = total

    return NutritionLookupResult(nutrition=per_serving, source=source)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition_lookup.py::TestCalculateRecipeNutrition -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add lib/nutrition_lookup.py tests/test_nutrition_lookup.py
git commit -m "feat(nutrition): add recipe nutrition calculator with fallback chain"
```

---

## Task 6: Update Recipe Template

**Files:**
- Modify: `templates/recipe_template.py`
- Modify: `tests/test_recipe_template.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_recipe_template.py

class TestNutritionSection:
    def test_includes_nutrition_in_frontmatter(self):
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "calories": 450,
            "protein": 25,
            "carbs": 45,
            "fat": 18,
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "calories: 450" in result
        assert "protein: 25" in result
        assert "carbs: 45" in result
        assert "fat: 18" in result
        assert 'serving_size: "1 cup"' in result
        assert 'nutrition_source: "nutritionix"' in result

    def test_includes_nutrition_table_in_body(self):
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "calories": 450,
            "protein": 25,
            "carbs": 45,
            "fat": 18,
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "## Nutrition (per serving)" in result
        assert "| Calories | Protein | Carbs | Fat |" in result
        assert "| 450      | 25g     | 45g   | 18g |" in result
        assert "*Serving size: 1 cup" in result

    def test_omits_nutrition_section_when_no_data(self):
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "## Nutrition (per serving)" not in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py::TestNutritionSection -v`
Expected: FAIL (assertions fail)

**Step 3: Write minimal implementation**

Update `templates/recipe_template.py`:

1. Add to `RECIPE_SCHEMA`:
```python
RECIPE_SCHEMA = {
    # ... existing fields ...
    "serving_size": str,
    "calories": int,
    "protein": int,
    "carbs": int,
    "fat": int,
    "nutrition_source": str,
}
```

2. Update `RECIPE_TEMPLATE` frontmatter section (after servings):
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
serving_size: {serving_size}
difficulty: {difficulty}

calories: {calories}
protein: {protein}
carbs: {carbs}
fat: {fat}
nutrition_source: {nutrition_source}

cuisine: {cuisine}
...
'''
```

3. Add nutrition section generation in `format_recipe_markdown()`:
```python
def generate_nutrition_section(recipe_data: dict) -> str:
    """Generate nutrition section if data available."""
    calories = recipe_data.get("calories")
    if calories is None:
        return ""

    protein = recipe_data.get("protein", 0)
    carbs = recipe_data.get("carbs", 0)
    fat = recipe_data.get("fat", 0)
    serving_size = recipe_data.get("serving_size", "1 serving")
    source = recipe_data.get("nutrition_source", "unknown")

    return f"""## Nutrition (per serving)

| Calories | Protein | Carbs | Fat |
|----------|---------|-------|-----|
| {calories}      | {protein}g     | {carbs}g   | {fat}g |

*Serving size: {serving_size} • Source: {source.title()}*

"""
```

4. Insert nutrition section in template formatting (after ingredients, before instructions).

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_template.py::TestNutritionSection -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add templates/recipe_template.py tests/test_recipe_template.py
git commit -m "feat(nutrition): add nutrition fields to recipe template"
```

---

## Task 7: Integrate Nutrition into Extraction Pipeline

**Files:**
- Modify: `extract_recipe.py`
- Test: Manual integration test

**Step 1: Read current extract_recipe.py**

Understand where to hook in nutrition calculation.

**Step 2: Add nutrition lookup call**

After recipe extraction succeeds, before saving:

```python
# In extract_recipe.py, after recipe_data is ready

from lib.nutrition_lookup import calculate_recipe_nutrition

# Calculate nutrition from ingredients
ingredients = recipe_data.get("ingredients", [])
servings = recipe_data.get("servings", 1) or 1

nutrition_result = calculate_recipe_nutrition(ingredients, servings)

if nutrition_result:
    recipe_data["calories"] = nutrition_result.nutrition.calories
    recipe_data["protein"] = nutrition_result.nutrition.protein
    recipe_data["carbs"] = nutrition_result.nutrition.carbs
    recipe_data["fat"] = nutrition_result.nutrition.fat
    recipe_data["nutrition_source"] = nutrition_result.source
    recipe_data["serving_size"] = recipe_data.get("serving_size", "1 serving")
```

**Step 3: Test manually**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`

Verify nutrition fields appear in output.

**Step 4: Commit**

```bash
git add extract_recipe.py
git commit -m "feat(nutrition): integrate nutrition lookup into extraction pipeline"
```

---

## Task 8: Macro Targets Parser

**Files:**
- Create: `lib/macro_targets.py`
- Test: `tests/test_macro_targets.py`

**Step 1: Write the failing test**

```python
# tests/test_macro_targets.py
"""Tests for macro targets parsing."""

from lib.macro_targets import parse_macro_targets, MacroTargets


class TestParseMacroTargets:
    def test_parses_frontmatter(self):
        content = """---
calories: 2000
protein: 150
carbs: 200
fat: 65
---

# My Daily Macros
"""
        targets = parse_macro_targets(content)

        assert targets.calories == 2000
        assert targets.protein == 150
        assert targets.carbs == 200
        assert targets.fat == 65

    def test_returns_defaults_on_missing_fields(self):
        content = """---
calories: 1800
---

# My Daily Macros
"""
        targets = parse_macro_targets(content)

        assert targets.calories == 1800
        assert targets.protein == 0
        assert targets.carbs == 0
        assert targets.fat == 0

    def test_returns_defaults_on_invalid_yaml(self):
        content = "# No frontmatter"
        targets = parse_macro_targets(content)

        assert targets.calories == 0
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_macro_targets.py -v`
Expected: FAIL with "No module named 'lib.macro_targets'"

**Step 3: Write minimal implementation**

```python
# lib/macro_targets.py
"""Parse macro targets from My Macros.md file."""

import re
from dataclasses import dataclass


@dataclass
class MacroTargets:
    """Daily macro targets."""
    calories: int
    protein: int
    carbs: int
    fat: int


def parse_macro_targets(content: str) -> MacroTargets:
    """Parse macro targets from markdown frontmatter.

    Args:
        content: Markdown file content

    Returns:
        MacroTargets with parsed values (0 for missing)
    """
    # Extract frontmatter
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return MacroTargets(calories=0, protein=0, carbs=0, fat=0)

    frontmatter = match.group(1)

    def extract_int(key: str) -> int:
        pattern = rf"^{key}:\s*(\d+)"
        m = re.search(pattern, frontmatter, re.MULTILINE)
        return int(m.group(1)) if m else 0

    return MacroTargets(
        calories=extract_int("calories"),
        protein=extract_int("protein"),
        carbs=extract_int("carbs"),
        fat=extract_int("fat"),
    )
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_macro_targets.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add lib/macro_targets.py tests/test_macro_targets.py
git commit -m "feat(nutrition): add macro targets parser"
```

---

## Task 9: Dashboard Generator

**Files:**
- Create: `generate_nutrition_dashboard.py`
- Test: `tests/test_nutrition_dashboard.py`

**Step 1: Write the failing test**

```python
# tests/test_nutrition_dashboard.py
"""Tests for nutrition dashboard generation."""

from unittest.mock import patch, mock_open
from generate_nutrition_dashboard import generate_dashboard, DailyNutrition
from lib.nutrition import NutritionData
from lib.macro_targets import MacroTargets


class TestGenerateDashboard:
    def test_generates_daily_summary_table(self):
        daily_data = {
            "Monday": DailyNutrition(
                nutrition=NutritionData(1850, 140, 180, 60),
                recipes=["Oatmeal", "Chicken Salad", "Pasta"]
            ),
            "Tuesday": DailyNutrition(
                nutrition=NutritionData(2100, 160, 210, 70),
                recipes=["Toast", "Soup", "Steak"]
            ),
        }
        targets = MacroTargets(calories=2000, protein=150, carbs=200, fat=65)

        result = generate_dashboard(
            week="2026-W03",
            daily_data=daily_data,
            targets=targets,
        )

        assert "# Nutrition Dashboard" in result
        assert "2026-W03" in result
        assert "| Monday" in result
        assert "1850 / 2000" in result
        assert "| Tuesday" in result
        assert "2100 / 2000" in result

    def test_shows_dash_for_empty_days(self):
        daily_data = {}
        targets = MacroTargets(calories=2000, protein=150, carbs=200, fat=65)

        result = generate_dashboard(
            week="2026-W03",
            daily_data=daily_data,
            targets=targets,
        )

        assert "| Monday    | —" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_nutrition_dashboard.py -v`
Expected: FAIL with "No module named 'generate_nutrition_dashboard'"

**Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Generate nutrition dashboard from meal plans."""

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from lib.nutrition import NutritionData
from lib.macro_targets import MacroTargets, parse_macro_targets
from lib.meal_plan_parser import parse_meal_plan
from lib.recipe_parser import parse_recipe_file


OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class DailyNutrition:
    """Nutrition data for a single day."""
    nutrition: NutritionData
    recipes: list[str]


def load_macro_targets() -> MacroTargets:
    """Load macro targets from My Macros.md."""
    macros_file = OBSIDIAN_VAULT / "My Macros.md"
    if not macros_file.exists():
        return MacroTargets(calories=0, protein=0, carbs=0, fat=0)

    content = macros_file.read_text()
    return parse_macro_targets(content)


def get_recipe_nutrition(recipe_name: str) -> NutritionData | None:
    """Get nutrition from a recipe file."""
    recipe_file = OBSIDIAN_VAULT / "Recipes" / f"{recipe_name}.md"
    if not recipe_file.exists():
        return None

    content = recipe_file.read_text()
    parsed = parse_recipe_file(content)
    frontmatter = parsed.get("frontmatter", {})

    calories = frontmatter.get("calories")
    if calories is None:
        return None

    return NutritionData(
        calories=int(calories),
        protein=int(frontmatter.get("protein", 0)),
        carbs=int(frontmatter.get("carbs", 0)),
        fat=int(frontmatter.get("fat", 0)),
    )


def calculate_daily_nutrition(meal_plan: dict) -> dict[str, DailyNutrition]:
    """Calculate nutrition totals for each day in meal plan."""
    daily_data = {}

    for day in DAYS:
        day_meals = meal_plan.get(day, {})
        total = NutritionData.empty()
        recipes = []

        for meal in ["Breakfast", "Lunch", "Dinner"]:
            meal_recipes = day_meals.get(meal, [])
            for recipe_name in meal_recipes:
                # Strip wiki-link syntax [[Recipe Name]]
                clean_name = recipe_name.strip("[]").split("|")[0]
                nutrition = get_recipe_nutrition(clean_name)
                if nutrition:
                    total = total + nutrition
                    recipes.append(clean_name)

        if recipes:
            daily_data[day] = DailyNutrition(nutrition=total, recipes=recipes)

    return daily_data


def format_value(actual: int, target: int, unit: str = "") -> str:
    """Format actual / target display."""
    if actual == 0 and target == 0:
        return "—"
    return f"{actual} / {target}{unit}"


def generate_dashboard(
    week: str,
    daily_data: dict[str, DailyNutrition],
    targets: MacroTargets,
) -> str:
    """Generate dashboard markdown content."""
    now = datetime.now().isoformat(timespec="seconds")

    lines = [
        "---",
        f"week: {week}",
        f"generated: {now}",
        "---",
        "",
        "# Nutrition Dashboard",
        "",
        f"**Week:** [[{week}]]",
        "**Targets:** [[My Macros]]",
        "",
        "## Daily Summary",
        "",
        "| Day       | Calories     | Protein    | Carbs      | Fat       |",
        "|-----------|--------------|------------|------------|-----------|",
    ]

    for day in DAYS:
        data = daily_data.get(day)
        if data:
            n = data.nutrition
            cal = format_value(n.calories, targets.calories)
            pro = format_value(n.protein, targets.protein, "g")
            carb = format_value(n.carbs, targets.carbs, "g")
            fat = format_value(n.fat, targets.fat, "g")
        else:
            cal = pro = carb = fat = "—"

        lines.append(f"| {day:<9} | {cal:<12} | {pro:<10} | {carb:<10} | {fat:<9} |")

    # Calculate averages
    if daily_data:
        days_with_data = len(daily_data)
        total = NutritionData.empty()
        for data in daily_data.values():
            total = total + data.nutrition
        avg = total * (1 / days_with_data)

        lines.extend([
            "",
            "## Week Averages",
            "",
            "| Macro    | Average | Target | Difference |",
            "|----------|---------|--------|------------|",
            f"| Calories | {avg.calories}    | {targets.calories}   | {avg.calories - targets.calories:+d}        |",
            f"| Protein  | {avg.protein}g    | {targets.protein}g   | {avg.protein - targets.protein:+d}g        |",
            f"| Carbs    | {avg.carbs}g    | {targets.carbs}g   | {avg.carbs - targets.carbs:+d}g        |",
            f"| Fat      | {avg.fat}g     | {targets.fat}g    | {avg.fat - targets.fat:+d}g         |",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by KitchenOS • [Refresh](http://localhost:5001/refresh-nutrition?week={week})*",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate nutrition dashboard")
    parser.add_argument("--week", help="Week to generate (e.g., 2026-W03)")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    args = parser.parse_args()

    # Determine week
    if args.week:
        week = args.week
    else:
        today = date.today()
        week = today.strftime("%G-W%V")

    # Load meal plan
    meal_plan_file = OBSIDIAN_VAULT / "Meal Plans" / f"{week}.md"
    if not meal_plan_file.exists():
        print(f"No meal plan found for {week}")
        return

    meal_plan_content = meal_plan_file.read_text()
    meal_plan = parse_meal_plan(meal_plan_content)

    # Calculate nutrition
    daily_data = calculate_daily_nutrition(meal_plan)

    # Load targets
    targets = load_macro_targets()

    # Generate dashboard
    dashboard = generate_dashboard(week, daily_data, targets)

    if args.dry_run:
        print(dashboard)
    else:
        output_file = OBSIDIAN_VAULT / "Nutrition Dashboard.md"
        output_file.write_text(dashboard)
        print(f"Dashboard written to {output_file}")


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_nutrition_dashboard.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add generate_nutrition_dashboard.py tests/test_nutrition_dashboard.py
git commit -m "feat(nutrition): add dashboard generator"
```

---

## Task 10: API Endpoint for Dashboard Refresh

**Files:**
- Modify: `api_server.py`
- Test: `tests/test_api_endpoints.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_api_endpoints.py

class TestRefreshNutritionEndpoint:
    def test_refresh_nutrition_returns_success(self, client):
        with patch("api_server.generate_nutrition_dashboard") as mock_gen:
            mock_gen.return_value = None
            response = client.get("/refresh-nutrition?week=2026-W03")

        assert response.status_code == 200
        assert b"Dashboard refreshed" in response.data

    def test_refresh_nutrition_uses_current_week_if_not_specified(self, client):
        with patch("api_server.generate_nutrition_dashboard") as mock_gen:
            mock_gen.return_value = None
            response = client.get("/refresh-nutrition")

        assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::TestRefreshNutritionEndpoint -v`
Expected: FAIL (endpoint doesn't exist)

**Step 3: Write minimal implementation**

Add to `api_server.py`:

```python
from datetime import date
from generate_nutrition_dashboard import main as generate_nutrition_dashboard

@app.route("/refresh-nutrition")
def refresh_nutrition():
    """Refresh the nutrition dashboard."""
    week = request.args.get("week")
    if not week:
        today = date.today()
        week = today.strftime("%G-W%V")

    try:
        # Import and run dashboard generator
        import sys
        sys.argv = ["generate_nutrition_dashboard.py", "--week", week]
        generate_nutrition_dashboard()
        return jsonify({"status": "success", "message": f"Dashboard refreshed for {week}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::TestRefreshNutritionEndpoint -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_endpoints.py
git commit -m "feat(nutrition): add /refresh-nutrition API endpoint"
```

---

## Task 11: Create My Macros Template

**Files:**
- Create: Template file in vault (manual or via script)

**Step 1: Create My Macros.md in Obsidian vault**

```markdown
---
calories: 2000
protein: 150
carbs: 200
fat: 65
---

# My Daily Macros

| Macro    | Target |
|----------|--------|
| Calories | 2000   |
| Protein  | 150g   |
| Carbs    | 200g   |
| Fat      | 65g    |

## Notes

<!-- Track why you set these targets, adjustments over time, etc. -->
```

**Step 2: Save file**

Save to: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/My Macros.md`

**Step 3: Commit documentation**

No code changes needed, but update CLAUDE.md.

---

## Task 12: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add to CLAUDE.md**

Add to "Running Commands" section:

```markdown
### Generate Nutrition Dashboard

```bash
# Generate for current week
.venv/bin/python generate_nutrition_dashboard.py

# Generate for specific week
.venv/bin/python generate_nutrition_dashboard.py --week 2026-W03

# Preview without saving
.venv/bin/python generate_nutrition_dashboard.py --dry-run
```
```

Add to "API Endpoints" table:

```markdown
| `/refresh-nutrition` | GET | Regenerate nutrition dashboard |
```

Add to "Core Components" table:

```markdown
| `lib/nutrition.py` | Nutrition data types |
| `lib/nutrition_lookup.py` | API clients for Nutritionix, USDA, AI fallback |
| `lib/macro_targets.py` | Parser for My Macros.md |
| `generate_nutrition_dashboard.py` | Dashboard generator |
```

Add to ".env" section:

```markdown
  - `NUTRITIONIX_APP_ID` - Nutritionix API (optional)
  - `NUTRITIONIX_API_KEY` - Nutritionix API (optional)
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add nutrition tracking documentation"
```

---

## Task 13: Final Integration Test

**Step 1: Create test recipe with nutrition**

Run extraction on a video to verify nutrition is calculated:

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```

Verify output includes:
- `calories:` in frontmatter
- `## Nutrition (per serving)` section

**Step 2: Test dashboard generation**

```bash
.venv/bin/python generate_nutrition_dashboard.py --dry-run
```

**Step 3: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(nutrition): complete nutrition tracking implementation"
```

---

## Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | NutritionData dataclass | 6 |
| 2 | Nutritionix API client | 4 |
| 3 | USDA API client | 3 |
| 4 | AI estimation fallback | 3 |
| 5 | Recipe nutrition calculator | 4 |
| 6 | Recipe template updates | 3 |
| 7 | Extraction pipeline integration | Manual |
| 8 | Macro targets parser | 3 |
| 9 | Dashboard generator | 2 |
| 10 | API endpoint | 2 |
| 11 | My Macros template | Manual |
| 12 | Documentation | Manual |
| 13 | Integration test | Manual |

**Total new tests:** ~30
