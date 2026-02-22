# Tag Normalization & Import Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize all recipe tag fields (protein, dish_type, difficulty, dietary, meal_occasion) across existing recipes and add validation at import time so new recipes come in clean. Also improve seasonal matching coverage.

**Architecture:** Create a shared `lib/normalizer.py` module with controlled vocabularies and correction maps. The migration script uses it to clean existing recipes. `extract_recipe.py` and `import_crouton.py` call `normalize_recipe_data()` after AI extraction to validate before saving. Seasonal matching gets a keyword fallback before the Ollama call.

**Tech Stack:** Python 3.11, existing `migrate_cuisine.py` pattern, `lib/seasonality.py`

---

### Task 1: Create `lib/normalizer.py` with controlled vocabularies and normalize function

**Files:**
- Create: `lib/normalizer.py`
- Create: `tests/test_normalizer.py`

**Step 1: Write the failing tests**

Create `tests/test_normalizer.py`:

```python
"""Tests for recipe data normalization."""
from lib.normalizer import normalize_field, normalize_recipe_data, PROTEIN_MAP, DISH_TYPE_MAP


class TestNormalizeProtein:
    """Test protein field normalization."""

    def test_lowercase_passthrough(self):
        assert normalize_field("protein", "chicken") == "chicken"

    def test_case_normalization(self):
        assert normalize_field("protein", "Chicken") == "chicken"

    def test_cut_consolidation(self):
        assert normalize_field("protein", "Chicken breast") == "chicken"
        assert normalize_field("protein", "chicken thighs") == "chicken"
        assert normalize_field("protein", "Rotisserie chicken") == "chicken"

    def test_ground_beef_to_beef(self):
        assert normalize_field("protein", "ground beef") == "beef"

    def test_bean_variants(self):
        assert normalize_field("protein", "Black beans") == "beans"
        assert normalize_field("protein", "White beans") == "beans"
        assert normalize_field("protein", "Butter beans") == "beans"

    def test_dairy_variants(self):
        assert normalize_field("protein", "cheese") == "dairy"
        assert normalize_field("protein", "Greek yogurt") == "dairy"
        assert normalize_field("protein", "cottage cheese") == "dairy"
        assert normalize_field("protein", "Feta") == "dairy"

    def test_numeric_values_become_null(self):
        assert normalize_field("protein", "70g") is None
        assert normalize_field("protein", "42g") is None
        assert normalize_field("protein", "20G Protein") is None

    def test_descriptive_values_become_null(self):
        assert normalize_field("protein", "No specific protein listed") is None
        assert normalize_field("protein", "High Protein") is None

    def test_null_stays_null(self):
        assert normalize_field("protein", None) is None
        assert normalize_field("protein", "null") is None

    def test_string_null_becomes_none(self):
        assert normalize_field("protein", "null") is None


class TestNormalizeDishType:
    """Test dish_type field normalization."""

    def test_main_variants(self):
        assert normalize_field("dish_type", "Main") == "main"
        assert normalize_field("dish_type", "Main Course") == "main"
        assert normalize_field("dish_type", "main course") == "main"
        assert normalize_field("dish_type", "Main Dish") == "main"
        assert normalize_field("dish_type", "pasta dish") == "main"
        assert normalize_field("dish_type", "Bowl") == "main"

    def test_case_normalization(self):
        assert normalize_field("dish_type", "Dessert") == "dessert"
        assert normalize_field("dish_type", "Salad") == "salad"

    def test_merge_variants(self):
        assert normalize_field("dish_type", "Wrap") == "sandwich"
        assert normalize_field("dish_type", "Smoothie") == "drink"
        assert normalize_field("dish_type", "Dressing") == "sauce"


class TestNormalizeDifficulty:
    """Test difficulty field normalization."""

    def test_case_normalization(self):
        assert normalize_field("difficulty", "Medium") == "medium"
        assert normalize_field("difficulty", "Easy") == "easy"

    def test_verbose_stripped(self):
        assert normalize_field("difficulty", "Medium (due to need for planning)") == "medium"


class TestNormalizeDietary:
    """Test dietary array normalization."""

    def test_case_and_format(self):
        result = normalize_field("dietary", ["High Protein", "Gluten-free"])
        assert result == ["high-protein", "gluten-free"]

    def test_dedup(self):
        result = normalize_field("dietary", ["vegan", "Vegan"])
        assert result == ["vegan"]

    def test_removes_invalid(self):
        result = normalize_field("dietary", ["dairy", "vegan"])
        assert result == ["vegan"]

    def test_empty_array_passthrough(self):
        assert normalize_field("dietary", []) == []


class TestNormalizeMealOccasion:
    """Test meal_occasion array normalization."""

    def test_removes_leaked_values(self):
        result = normalize_field("meal_occasion", ["weeknight-dinner", "vegan", "dessert"])
        assert result == ["weeknight-dinner"]

    def test_valid_values_pass(self):
        result = normalize_field("meal_occasion", ["packed-lunch", "meal-prep"])
        assert result == ["packed-lunch", "meal-prep"]


class TestNormalizeRecipeData:
    """Test full recipe_data normalization."""

    def test_normalizes_all_fields(self):
        data = {
            "recipe_name": "Test",
            "protein": "Chicken breast",
            "dish_type": "Main Course",
            "difficulty": "Medium",
            "dietary": ["High Protein"],
            "meal_occasion": ["weeknight-dinner"],
            "cuisine": "Italian",
        }
        result = normalize_recipe_data(data)
        assert result["protein"] == "chicken"
        assert result["dish_type"] == "main"
        assert result["difficulty"] == "medium"
        assert result["dietary"] == ["high-protein"]

    def test_unknown_string_sets_needs_review(self):
        data = {
            "recipe_name": "Test",
            "protein": "unicorn meat",
            "dish_type": "main",
            "difficulty": "easy",
        }
        result = normalize_recipe_data(data)
        assert result["needs_review"] is True

    def test_known_values_no_review_flag(self):
        data = {
            "recipe_name": "Test",
            "protein": "chicken",
            "dish_type": "main",
            "difficulty": "easy",
        }
        result = normalize_recipe_data(data)
        # Should not force needs_review to True (leave existing value)
        assert result.get("needs_review") is not True
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_normalizer.py -v`
Expected: FAIL (module not found)

**Step 3: Write `lib/normalizer.py`**

```python
"""Recipe data normalization — controlled vocabularies and correction maps.

Ensures consistent tag values across all recipe sources (AI extraction,
web scraping, Crouton import). Used by both migration and import pipeline.
"""

import re

# --- Controlled Vocabularies ---
# Each maps (lowercased lookup key) -> standard value.
# Entries not in the map are checked against VALID_VALUES for passthrough.

PROTEIN_MAP = {
    # Case normalization
    "chicken": "chicken",
    "beef": "beef",
    "pork": "pork",
    "lamb": "lamb",
    "turkey": "turkey",
    "fish": "fish",
    "seafood": "seafood",
    "tofu": "tofu",
    "tempeh": "tempeh",
    "eggs": "eggs",
    "beans": "beans",
    "lentils": "lentils",
    "chickpeas": "chickpeas",
    "dairy": "dairy",
    "protein powder": "protein powder",
    # Cut/variant consolidation
    "chicken breast": "chicken",
    "chicken breasts": "chicken",
    "chicken thighs": "chicken",
    "chicken thigh": "chicken",
    "chicken legs or thighs": "chicken",
    "rotisserie chicken": "chicken",
    "chicken mince": "chicken",
    "chicken and turkey bacon": "chicken",
    "chicken (from egg yolks)": "eggs",
    "chicken (protein powder used)": "protein powder",
    "ground beef": "beef",
    "ground turkey": "turkey",
    "turkey bacon": "turkey",
    "smoked sausage": "pork",
    "breakfast sausage": "pork",
    "breakfast sausage, bacon": "pork",
    "bacon": "pork",
    "veal": "beef",
    "salmon": "fish",
    "smoked salmon": "fish",
    "shrimp": "seafood",
    "egg whites": "eggs",
    "egg": "eggs",
    # Bean variants
    "black beans": "beans",
    "white beans": "beans",
    "butter beans": "beans",
    "white beans and lentils": "beans",
    # Dairy variants
    "cheese": "dairy",
    "feta": "dairy",
    "goat cheese": "dairy",
    "cottage cheese": "dairy",
    "greek yogurt": "dairy",
    "greek-style yogurt": "dairy",
    "good culture cottage cheese": "dairy",
    "dairy (cheese)": "dairy",
    # Null-outs (invalid as protein source)
    "none": None,
    "no specific protein listed": None,
    "high protein": None,
    "plant-based": None,
    "protein-rich pasta": None,
}

# Regex for numeric protein values like "70g", "42g", "20G Protein"
_NUMERIC_PROTEIN_RE = re.compile(r"^\d+[gG]", re.IGNORECASE)

VALID_PROTEINS = {
    "chicken", "beef", "pork", "lamb", "turkey", "fish", "seafood",
    "tofu", "tempeh", "eggs", "beans", "lentils", "chickpeas",
    "dairy", "protein powder",
}

DISH_TYPE_MAP = {
    # Standard values
    "main": "main",
    "side": "side",
    "dessert": "dessert",
    "breakfast": "breakfast",
    "snack": "snack",
    "salad": "salad",
    "soup": "soup",
    "sandwich": "sandwich",
    "appetizer": "appetizer",
    "drink": "drink",
    "sauce": "sauce",
    "bread": "bread",
    "dip": "dip",
    # Variant consolidation
    "main course": "main",
    "main dish": "main",
    "entrée": "main",
    "entree": "main",
    "pasta dish": "main",
    "bowl": "main",
    "side dish": "side",
    "wrap": "sandwich",
    "smoothie": "drink",
    "beverage": "drink",
    "dressing": "sauce",
    "condiment": "sauce",
    "starter": "appetizer",
}

VALID_DISH_TYPES = {
    "main", "side", "dessert", "breakfast", "snack", "salad", "soup",
    "sandwich", "appetizer", "drink", "sauce", "bread", "dip",
}

DIFFICULTY_MAP = {
    "easy": "easy",
    "medium": "medium",
    "hard": "hard",
}

# Regex to strip verbose difficulty descriptions like "Medium (due to ...)"
_DIFFICULTY_PAREN_RE = re.compile(r"\s*\(.*\)\s*$")

VALID_DIFFICULTIES = {"easy", "medium", "hard"}

DIETARY_MAP = {
    "vegan": "vegan",
    "vegetarian": "vegetarian",
    "gluten-free": "gluten-free",
    "gluten free": "gluten-free",
    "dairy-free": "dairy-free",
    "dairy free": "dairy-free",
    "low-carb": "low-carb",
    "low carb": "low-carb",
    "low-calorie": "low-calorie",
    "low calorie": "low-calorie",
    "high-protein": "high-protein",
    "high protein": "high-protein",
    "high-fiber": "high-fiber",
    "high fiber": "high-fiber",
    "keto": "keto",
    "paleo": "paleo",
    "nut-free": "nut-free",
    "nut free": "nut-free",
}

VALID_DIETARY = {
    "vegan", "vegetarian", "gluten-free", "dairy-free", "low-carb",
    "low-calorie", "high-protein", "high-fiber", "keto", "paleo", "nut-free",
}

VALID_MEAL_OCCASIONS = {
    "weeknight-dinner", "packed-lunch", "grab-and-go-breakfast",
    "afternoon-snack", "weekend-project", "date-night", "lazy-sunday",
    "crowd-pleaser", "meal-prep", "brunch", "post-workout", "family-meal",
}


def normalize_field(field: str, value):
    """Normalize a single recipe field value against its controlled vocabulary.

    Args:
        field: Field name (protein, dish_type, difficulty, dietary, meal_occasion)
        value: Current value (str, list, or None)

    Returns:
        Normalized value, or None for invalid string fields.
        For unknown values not in the map, returns a tuple ("unknown", original)
        so the caller can decide whether to flag needs_review.
    """
    if field == "protein":
        return _normalize_protein(value)
    elif field == "dish_type":
        return _normalize_dish_type(value)
    elif field == "difficulty":
        return _normalize_difficulty(value)
    elif field == "dietary":
        return _normalize_dietary(value)
    elif field == "meal_occasion":
        return _normalize_meal_occasion(value)
    return value


def _normalize_protein(value) -> str | None:
    if value is None or value == "null":
        return None

    low = str(value).strip().lower()

    # Numeric values like "70g" → null
    if _NUMERIC_PROTEIN_RE.match(low):
        return None

    # Check explicit map
    if low in PROTEIN_MAP:
        return PROTEIN_MAP[low]

    # Comma-separated → take first recognizable
    if "," in low:
        for part in low.split(","):
            part = part.strip()
            if part in PROTEIN_MAP:
                return PROTEIN_MAP[part]
        return None

    # Check if already a valid value (case-insensitive)
    if low in VALID_PROTEINS:
        return low

    # Contains a valid protein keyword? (e.g., "chicken (if serving with chicken)")
    for valid in VALID_PROTEINS:
        if valid in low:
            return valid

    # Unknown → return as-is but caller will flag needs_review
    return ("unknown", value)


def _normalize_dish_type(value) -> str | None:
    if value is None or value == "null":
        return None

    low = str(value).strip().lower()

    if low in DISH_TYPE_MAP:
        return DISH_TYPE_MAP[low]

    if low in VALID_DISH_TYPES:
        return low

    return ("unknown", value)


def _normalize_difficulty(value) -> str | None:
    if value is None or value == "null":
        return None

    low = str(value).strip().lower()
    # Strip parenthetical descriptions
    low = _DIFFICULTY_PAREN_RE.sub("", low).strip()

    if low in DIFFICULTY_MAP:
        return DIFFICULTY_MAP[low]

    return ("unknown", value)


def _normalize_dietary(value) -> list:
    if not value or not isinstance(value, list):
        return []

    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        low = item.strip().lower()
        mapped = DIETARY_MAP.get(low, low if low in VALID_DIETARY else None)
        if mapped and mapped not in seen:
            seen.add(mapped)
            result.append(mapped)

    return result


def _normalize_meal_occasion(value) -> list:
    if not value or not isinstance(value, list):
        return []

    return [v for v in value if isinstance(v, str) and v in VALID_MEAL_OCCASIONS]


def normalize_recipe_data(recipe_data: dict) -> dict:
    """Normalize all tag fields in a recipe_data dict.

    Modifies the dict in place and returns it. Sets needs_review=True
    if any field had an unknown value that couldn't be mapped.

    Args:
        recipe_data: Recipe data dict from AI extraction or import

    Returns:
        Same dict with normalized field values
    """
    had_unknown = False

    for field in ("protein", "dish_type", "difficulty"):
        val = recipe_data.get(field)
        normalized = normalize_field(field, val)
        if isinstance(normalized, tuple) and normalized[0] == "unknown":
            had_unknown = True
            recipe_data[field] = normalized[1]  # Keep original
        else:
            recipe_data[field] = normalized

    for field in ("dietary", "meal_occasion"):
        val = recipe_data.get(field)
        recipe_data[field] = normalize_field(field, val)

    if had_unknown:
        recipe_data["needs_review"] = True

    return recipe_data
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_normalizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/normalizer.py tests/test_normalizer.py
git commit -m "feat: add recipe data normalizer with controlled vocabularies"
```

---

### Task 2: Add keyword-based seasonal matching fallback

**Files:**
- Modify: `lib/seasonality.py` — add `keyword_match_seasonal()` function, update `match_ingredients_to_seasonal()` to use it first
- Modify: `prompts/seasonal_matching.py` — loosen prompt
- Create: `tests/test_seasonality_keyword.py`

**Step 1: Write the failing tests**

Create `tests/test_seasonality_keyword.py`:

```python
"""Tests for keyword-based seasonal ingredient matching."""
from lib.seasonality import keyword_match_seasonal


class TestKeywordMatchSeasonal:
    """Test simple keyword matching against seasonal config."""

    def test_exact_match(self):
        ingredients = [{"item": "corn"}]
        result = keyword_match_seasonal(ingredients)
        assert "corn" in result

    def test_substring_match(self):
        """'cherry tomatoes' should match 'tomato'."""
        ingredients = [{"item": "cherry tomatoes"}]
        result = keyword_match_seasonal(ingredients)
        assert "tomato" in result

    def test_compound_ingredient(self):
        """'ears fresh corn' should match 'corn'."""
        ingredients = [{"item": "ears fresh corn"}]
        result = keyword_match_seasonal(ingredients)
        assert "corn" in result

    def test_plural_match(self):
        """'peaches' should match 'peach'."""
        ingredients = [{"item": "large firm-but-ripe peaches"}]
        result = keyword_match_seasonal(ingredients)
        assert "peach" in result

    def test_skips_pantry_staples(self):
        """Should not match pantry items even if they contain produce words."""
        ingredients = [{"item": "olive oil"}, {"item": "flour"}, {"item": "salt"}]
        result = keyword_match_seasonal(ingredients)
        assert len(result) == 0

    def test_deduplicates(self):
        """Multiple ingredients matching same seasonal item → one entry."""
        ingredients = [{"item": "tomatoes"}, {"item": "cherry tomatoes"}]
        result = keyword_match_seasonal(ingredients)
        assert result.count("tomato") == 1

    def test_multi_word_seasonal(self):
        """'sweet potato' is a multi-word seasonal entry."""
        ingredients = [{"item": "sweet potatoes"}]
        result = keyword_match_seasonal(ingredients)
        assert "sweet potato" in result
        # Should NOT also match "potato" separately
        assert "potato" not in result

    def test_green_bean_match(self):
        """'fresh green beans' should match 'green bean'."""
        ingredients = [{"item": "fresh green beans"}]
        result = keyword_match_seasonal(ingredients)
        assert "green bean" in result

    def test_empty_ingredients(self):
        result = keyword_match_seasonal([])
        assert result == []

    def test_bell_pepper_match(self):
        """'red bell pepper' should match 'bell pepper'."""
        ingredients = [{"item": "red bell pepper"}]
        result = keyword_match_seasonal(ingredients)
        assert "bell pepper" in result
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_seasonality_keyword.py -v`
Expected: FAIL (function not found)

**Step 3: Add `keyword_match_seasonal()` to `lib/seasonality.py`**

Add this function before `match_ingredients_to_seasonal()`:

```python
# Pantry staples to skip during keyword matching
_PANTRY_KEYWORDS = {
    "oil", "flour", "sugar", "salt", "pepper", "butter", "cream",
    "milk", "water", "broth", "stock", "vinegar", "soy sauce",
    "pasta", "rice", "noodle", "bread", "tortilla", "wrap",
    "spice", "seasoning", "powder", "extract", "vanilla",
    "honey", "syrup", "sauce", "ketchup", "mustard", "mayo",
    "nuts", "seeds", "chocolate", "cocoa", "coffee", "tea",
}


def _is_pantry_item(ingredient_text: str) -> bool:
    """Check if ingredient is a pantry staple (skip seasonal matching)."""
    low = ingredient_text.lower()
    return any(kw in low for kw in _PANTRY_KEYWORDS)


def keyword_match_seasonal(ingredients: list[dict]) -> list[str]:
    """Match recipe ingredients to seasonal produce using simple keyword matching.

    Checks if any seasonal produce name appears as a word/substring in ingredient items.
    Multi-word seasonal names (e.g., "sweet potato", "green bean") are checked first
    to prevent partial matches (e.g., "sweet potato" should not also match "potato").

    Args:
        ingredients: List of ingredient dicts with 'item' key

    Returns:
        Deduplicated list of matched seasonal ingredient names
    """
    if not ingredients:
        return []

    config = load_seasonal_config()
    seasonal_names = list(config["ingredients"].keys())

    # Sort by length descending so multi-word names match first
    seasonal_names.sort(key=len, reverse=True)

    matched = []
    matched_set = set()

    for ing in ingredients:
        item = ing.get("item", "")
        if not item or _is_pantry_item(item):
            continue

        item_low = item.lower()
        # Track which portions of the item text have been "claimed"
        # to prevent "sweet potato" also matching "potato"
        claimed = set()

        for seasonal_name in seasonal_names:
            if seasonal_name in matched_set:
                # Already matched this seasonal item from another ingredient
                continue

            # Check: does the seasonal name (or its plural) appear in the item?
            if _keyword_in_text(seasonal_name, item_low, claimed):
                matched_set.add(seasonal_name)
                matched.append(seasonal_name)
                # Mark the matched portion as claimed
                claimed.add(seasonal_name)

    return matched


def _keyword_in_text(seasonal_name: str, text: str, claimed: set) -> bool:
    """Check if a seasonal ingredient name matches within ingredient text.

    Handles plurals by also checking name + 's'/'es'.
    """
    # Skip if a longer name already claimed this portion
    for c in claimed:
        if seasonal_name in c:
            return False

    # Direct substring
    if seasonal_name in text:
        return True

    # Plural forms
    if seasonal_name + "s" in text:
        return True
    if seasonal_name + "es" in text:
        return True

    return False
```

**Step 4: Update `match_ingredients_to_seasonal()` to try keyword matching first**

In `lib/seasonality.py`, modify `match_ingredients_to_seasonal()`:

```python
def match_ingredients_to_seasonal(ingredients: list[dict]) -> list[str]:
    """Match recipe ingredients to seasonal produce.

    Uses keyword matching first (fast, no API call), then falls back to
    Ollama fuzzy matching for recipes with no keyword matches.
    """
    if not ingredients:
        return []

    # Try keyword matching first (fast)
    keyword_matches = keyword_match_seasonal(ingredients)
    if keyword_matches:
        return keyword_matches

    # Fall back to Ollama for edge cases
    # ... (existing Ollama code stays here)
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_seasonality_keyword.py -v`
Expected: All PASS

**Step 6: Loosen the Ollama seasonal matching prompt**

In `prompts/seasonal_matching.py`, update the prompt to be less strict:

```python
SEASONAL_MATCHING_PROMPT = """Given these recipe ingredients:
{ingredient_items}

And these seasonal produce items:
{seasonal_names}

Return ONLY the matches as a JSON array of objects:
[{{"ingredient": "butternut squash", "matches": "butternut squash"}}]

Rules:
- Match fresh produce ingredients to their closest seasonal item
- Match variants generously: "baby spinach" -> "spinach", "cherry tomato" -> "tomato", "sweet corn" -> "corn", "fresh peaches" -> "peach"
- Skip obvious pantry staples (oil, flour, sugar, salt, spices, sauces, grains, pasta, rice, dried herbs)
- If an ingredient contains a produce name, match it (e.g., "ears fresh corn" -> "corn")
- If no match exists for an ingredient, omit it entirely
- Return an empty array [] if no ingredients match"""
```

**Step 7: Commit**

```bash
git add lib/seasonality.py prompts/seasonal_matching.py tests/test_seasonality_keyword.py
git commit -m "feat: add keyword-based seasonal matching fallback"
```

---

### Task 3: Extend `migrate_cuisine.py` to normalize all tag fields

**Files:**
- Modify: `migrate_cuisine.py` — import normalizer, add phases for each field
- Modify: `tests/test_migrate_cuisine.py` — add tests for new phases

**Step 1: Write the failing tests**

Add to `tests/test_migrate_cuisine.py`:

```python
class TestRunTagMigration:
    """Test tag normalization migration across fields."""

    def test_normalizes_protein(self):
        """Should normalize protein from 'Chicken' to 'chicken'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\nprotein: "Chicken breast"\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'protein: "chicken"' in new_content
            assert len(results["updated"]) == 1

    def test_normalizes_dish_type(self):
        """Should normalize 'Main Course' to 'main'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\ndish_type: "Main Course"\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'dish_type: "main"' in new_content

    def test_normalizes_difficulty(self):
        """Should normalize 'Medium' to 'medium'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\ndifficulty: "Medium"\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'difficulty: "medium"' in new_content

    def test_normalizes_dietary_array(self):
        """Should normalize dietary array values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\ndietary: ["High Protein", "Gluten-free"]\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'dietary: ["high-protein", "gluten-free"]' in new_content

    def test_removes_leaked_meal_occasion(self):
        """Should remove non-occasion values from meal_occasion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\nmeal_occasion: ["weeknight-dinner", "vegan"]\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'meal_occasion: ["weeknight-dinner"]' in new_content

    def test_skips_already_correct(self):
        """Should skip recipes where all fields are already normalized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            recipe.write_text(
                '---\ntitle: "Test"\nprotein: "chicken"\ndish_type: "main"\n'
                'difficulty: "easy"\ndietary: ["vegan"]\nmeal_occasion: ["weeknight-dinner"]\n---\n\n# Test'
            )
            results = run_tag_migration(recipes_dir, dry_run=False)
            assert len(results["skipped"]) == 1

    def test_dry_run_no_changes(self):
        """Dry run should report but not modify files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Test Recipe.md"
            original = '---\ntitle: "Test"\nprotein: "Chicken"\n---\n\n# Test'
            recipe.write_text(original)
            results = run_tag_migration(recipes_dir, dry_run=True)
            assert recipe.read_text() == original
            assert len(results["updated"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py::TestRunTagMigration -v`
Expected: FAIL (function not found)

**Step 3: Add `run_tag_migration()` to `migrate_cuisine.py`**

Add this function and update `main()`:

```python
from lib.normalizer import normalize_field

# Fields to normalize (string fields and array fields handled differently)
TAG_STRING_FIELDS = ("protein", "dish_type", "difficulty")
TAG_ARRAY_FIELDS = ("dietary", "meal_occasion")


def run_tag_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Run tag normalization migration on all recipe files.

    Normalizes protein, dish_type, difficulty, dietary, and meal_occasion
    fields using controlled vocabularies from lib/normalizer.py.

    Args:
        recipes_dir: Path to Recipes folder
        dry_run: If True, report changes without modifying files

    Returns:
        dict with 'updated', 'skipped', 'errors' lists
    """
    results = {"updated": [], "skipped": [], "errors": []}

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith("."):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]
            changes = []

            new_content = content

            # Normalize string fields
            for field in TAG_STRING_FIELDS:
                current = fm.get(field)
                normalized = normalize_field(field, current)
                # Handle unknown values (tuple)
                if isinstance(normalized, tuple):
                    normalized = normalized[1]  # Keep original
                if normalized != current:
                    changes.append(f"{field}: {current} → {normalized}")
                    new_content = update_frontmatter_field(new_content, field, normalized)

            # Normalize array fields
            for field in TAG_ARRAY_FIELDS:
                current = fm.get(field, [])
                if not isinstance(current, list):
                    current = []
                normalized = normalize_field(field, current)
                if normalized != current:
                    changes.append(f"{field}: {current} → {normalized}")
                    new_content = update_frontmatter_field(new_content, field, normalized)

            if not changes:
                results["skipped"].append((md_file.name, "all tags already correct"))
                continue

            change_desc = "; ".join(changes)

            if dry_run:
                results["updated"].append((md_file.name, change_desc))
            else:
                create_backup(md_file)
                md_file.write_text(new_content, encoding="utf-8")
                results["updated"].append((md_file.name, change_desc))

        except Exception as e:
            results["errors"].append((md_file.name, str(e)))

    return results
```

Update `main()` to add a Phase 1.5 for tag normalization (between cuisine and seasonal):

```python
def main():
    # ... existing argparse setup ...
    # Add new flag:
    parser.add_argument(
        "--no-tags", action="store_true", help="Skip tag normalization"
    )

    # ... Phase 1: Cuisine corrections (existing) ...

    # Phase 1.5: Tag normalization
    if not args.no_tags:
        print("\nPhase 2: Tag normalization...")
        tag_results = run_tag_migration(recipes_dir, dry_run=args.dry_run)
        print_results(tag_results, "Tag Normalization", args.dry_run)
    else:
        print("\nPhase 2: Skipped (--no-tags)")

    # Phase 3: Seasonal (renumbered from Phase 2)
    if not args.no_seasonal:
        print("\nPhase 3: Seasonal data population (Ollama)...")
        # ... existing seasonal code ...
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add migrate_cuisine.py tests/test_migrate_cuisine.py
git commit -m "feat: extend migration to normalize all tag fields"
```

---

### Task 4: Wire normalizer into `extract_recipe.py`

**Files:**
- Modify: `extract_recipe.py:393-413` — replace ad-hoc normalization with `normalize_recipe_data()`

**Step 1: Update `extract_recipe.py`**

Add import at top:

```python
from lib.normalizer import normalize_recipe_data
```

Replace the existing ad-hoc normalization block (lines ~400-413) with:

```python
        # Normalize string fields that AI sometimes returns as lists
        for field in ('cuisine', 'protein', 'dish_type', 'difficulty'):
            val = recipe_data.get(field)
            if isinstance(val, list):
                recipe_data[field] = val[0] if val else None

        # Normalize meal_occasion to list of slugified strings (max 3)
        occasion = recipe_data.get('meal_occasion', [])
        if isinstance(occasion, str):
            occasion = [occasion]
        recipe_data['meal_occasion'] = [
            o.strip().lower().replace(' ', '-')
            for o in occasion if o and isinstance(o, str)
        ][:3]

        # Normalize all tag fields against controlled vocabularies
        normalize_recipe_data(recipe_data)
```

The existing list-coercion stays (it handles AI returning a list when string is expected), but the controlled vocabulary normalization runs after.

**Step 2: Verify no regressions**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/test_ics_generator.py --ignore=tests/test_sync_calendar.py --ignore=tests/test_creator_search.py`
Expected: All PASS

**Step 3: Commit**

```bash
git add extract_recipe.py
git commit -m "feat: wire normalizer into recipe extraction pipeline"
```

---

### Task 5: Wire normalizer into `import_crouton.py`

**Files:**
- Modify: `import_crouton.py:56-77` — add `normalize_recipe_data()` call after enrichment

**Step 1: Update `import_crouton.py`**

Add import at top:

```python
from lib.normalizer import normalize_recipe_data
```

In `enrich_with_ollama()`, add normalization after the meal_occasion slugification (line ~77, before `return recipe_data`):

```python
        # Normalize all tag fields against controlled vocabularies
        normalize_recipe_data(recipe_data)

        return recipe_data
```

Also add normalization in `main()` for the `--no-enrich` path (when Ollama is skipped, data still needs normalizing). After the `if not args.no_enrich:` / `else:` block (around line ~236), add:

```python
            # Normalize tags even when not enriching
            if args.no_enrich:
                normalize_recipe_data(recipe_data)
```

**Step 2: Verify no regressions**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/test_ics_generator.py --ignore=tests/test_sync_calendar.py --ignore=tests/test_creator_search.py`
Expected: All PASS

**Step 3: Commit**

```bash
git add import_crouton.py
git commit -m "feat: wire normalizer into Crouton import pipeline"
```

---

### Task 6: Run tag migration on real vault (dry run first, then apply)

**Files:**
- No code changes — running existing scripts

**Step 1: Dry run to preview changes**

Run: `.venv/bin/python migrate_cuisine.py --dry-run --no-seasonal`

Review output — should show corrections for protein, dish_type, difficulty, dietary, and meal_occasion across all recipe files.

**Step 2: Apply migration**

Run: `.venv/bin/python migrate_cuisine.py --no-seasonal`

**Step 3: Verify unique values after migration**

Run a quick check:

```bash
grep -h "^protein:" "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes/"*.md | sort | uniq -c | sort -rn
grep -h "^dish_type:" "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes/"*.md | sort | uniq -c | sort -rn
grep -h "^difficulty:" "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes/"*.md | sort | uniq -c | sort -rn
```

Expected: Only standardized values from the controlled vocabularies.

**Step 4: Commit migration results (if any recipe files are tracked)**

No commit needed — recipe files are in the Obsidian vault, not in the git repo.

---

### Task 7: Re-run seasonal matching with improved keyword fallback

**Files:**
- No code changes — running existing scripts

**Step 1: Reset seasonal data to force re-matching**

The current `run_seasonal_migration()` skips recipes that already have seasonal data. To re-run with the keyword fallback, we need to temporarily bypass the skip.

Option: Add `--force-seasonal` flag to `migrate_cuisine.py` that clears existing seasonal data before re-matching.

Add to `migrate_cuisine.py`:

```python
parser.add_argument(
    "--force-seasonal", action="store_true",
    help="Clear existing seasonal data and re-match all recipes"
)
```

And in `run_seasonal_migration()`, when `force` is True, don't skip recipes with existing data.

**Step 2: Run seasonal re-matching**

Run: `.venv/bin/python migrate_cuisine.py --no-tags --force-seasonal --dry-run`

Check how many recipes now get matches.

**Step 3: Apply**

Run: `.venv/bin/python migrate_cuisine.py --no-tags --force-seasonal`

**Step 4: Commit code changes**

```bash
git add migrate_cuisine.py
git commit -m "feat: add --force-seasonal flag for re-matching"
```

---

### Task 8: Update CLAUDE.md and run full test suite

**Files:**
- Modify: `CLAUDE.md` — update Key Functions, Core Components

**Step 1: Update CLAUDE.md**

Add to Core Components table:
```
| `lib/normalizer.py` | Controlled vocabularies and tag normalization |
```

Add to Key Functions section:
```
**lib/normalizer.py:**
- `normalize_field()` - Normalizes a single recipe field against its controlled vocabulary
- `normalize_recipe_data()` - Normalizes all tag fields in a recipe_data dict
```

Update `migrate_cuisine.py` Key Functions to include:
```
- `run_tag_migration()` - Batch tag normalization across all recipe files
```

Update Running Commands section to document new flags:
```
# Tag normalization only (skip cuisine and seasonal)
.venv/bin/python migrate_cuisine.py --no-seasonal

# Force re-match seasonal data
.venv/bin/python migrate_cuisine.py --no-tags --force-seasonal
```

**Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/test_ics_generator.py --ignore=tests/test_sync_calendar.py --ignore=tests/test_creator_search.py`
Expected: All PASS

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with normalizer and tag migration"
```

---

### Task 9: Update design doc status

**Files:**
- Modify: `docs/plans/2026-02-21-tag-normalization-design.md`

**Step 1: Update status**

Change `**Status:** Approved` to `**Status:** Implemented`

**Step 2: Commit**

```bash
git add docs/plans/2026-02-21-tag-normalization-design.md
git commit -m "docs: mark tag normalization design as implemented"
```
