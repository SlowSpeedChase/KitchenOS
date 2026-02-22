# Season Filter & Cuisine Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clean up inconsistent cuisine data across 156 recipes, populate seasonal ingredient data via Ollama, and add an "In Season" filter chip to the meal planner dashboard.

**Architecture:** A new standalone migration script (`migrate_cuisine.py`) handles both cuisine corrections and seasonal data population. The backend (`recipe_index.py`) is extended to expose `peak_months` in the API. The frontend (`meal_planner.html`) gets a special green "In Season" toggle chip that filters recipes by current month.

**Tech Stack:** Python 3.11, Ollama (mistral:7b), Flask API, vanilla JS (SortableJS dashboard)

---

### Task 1: Add `peak_months` to Recipe Index

**Files:**
- Modify: `lib/recipe_index.py:7` (FILTER_FIELDS tuple)
- Test: `tests/test_recipe_index.py`

**Step 1: Write the failing test**

Add to `tests/test_recipe_index.py` inside `TestGetRecipeIndex`:

```python
def test_extracts_peak_months(self):
    """Should extract peak_months from frontmatter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        (recipes_dir / "Summer Salad.md").write_text(
            '---\ntitle: "Summer Salad"\ncuisine: "American"\n'
            'peak_months: [5, 6, 7, 8]\nseasonal_ingredients: ["tomato", "cucumber"]\n---\n\n# Summer Salad'
        )
        result = get_recipe_index(recipes_dir)
        assert result[0]["peak_months"] == [5, 6, 7, 8]

def test_peak_months_defaults_to_none(self):
    """Missing peak_months becomes None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        (recipes_dir / "Old Recipe.md").write_text(
            '---\ntitle: "Old Recipe"\ncuisine: "Italian"\n---\n\n# Old Recipe'
        )
        result = get_recipe_index(recipes_dir)
        assert result[0]["peak_months"] is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py::TestGetRecipeIndex::test_extracts_peak_months tests/test_recipe_index.py::TestGetRecipeIndex::test_peak_months_defaults_to_none -v`
Expected: FAIL — `peak_months` not in returned dicts (KeyError)

**Step 3: Write minimal implementation**

Edit `lib/recipe_index.py:7` — change the FILTER_FIELDS tuple:

```python
FILTER_FIELDS = ("cuisine", "protein", "difficulty", "meal_occasion", "dish_type", "peak_months")
```

Also update the docstring on line 18 to include `peak_months`:

```python
            name, cuisine, protein, difficulty, meal_occasion, dish_type, peak_months
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_recipe_index.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add lib/recipe_index.py tests/test_recipe_index.py
git commit -m "feat: expose peak_months in recipe index API"
```

---

### Task 2: Add "In Season" Chip to Meal Planner Dashboard

**Files:**
- Modify: `templates/meal_planner.html:116-120` (add green chip CSS)
- Modify: `templates/meal_planner.html:960-968` (add peak_months to recipe card data)
- Modify: `templates/meal_planner.html:1002-1017` (update matchesActiveFilters)
- Modify: `templates/meal_planner.html:1019-1074` (update buildFilterChips)

No automated test — this is frontend HTML/JS in a single-file template. Manual verification.

**Step 1: Add CSS for green "In Season" chip**

After line 120 (`.chip.active` closing brace), add:

```css
.chip.season {
    border-color: var(--success);
    color: var(--success);
}

.chip.season.active {
    background: var(--success);
    color: #ffffff;
    border-color: var(--success);
}
```

**Step 2: Store peak_months on recipe cards**

In `renderRecipes()` around line 968, after `card.dataset.dishType = recipe.dish_type || '';`, add:

```javascript
card.dataset.peakMonths = JSON.stringify(recipe.peak_months || []);
```

**Step 3: Update matchesActiveFilters for season**

Replace the `matchesActiveFilters` function (lines 1002-1017) with:

```javascript
function matchesActiveFilters(recipe) {
    // Special: "In Season" toggle
    if (seasonFilterActive) {
        const months = recipe.peak_months || [];
        const currentMonth = new Date().getMonth() + 1;
        if (!months.includes(currentMonth)) return false;
    }

    for (const [field, values] of Object.entries(activeFilters)) {
        if (values.size === 0) continue;

        if (field === 'meal_occasion') {
            const recipeValues = recipe.meal_occasion || [];
            const hasMatch = recipeValues.some(v => values.has(v));
            if (!hasMatch) return false;
        } else {
            const recipeValue = recipe[field] || '';
            if (!values.has(recipeValue)) return false;
        }
    }
    return true;
}
```

**Step 4: Add seasonFilterActive state variable**

Near the top of the `<script>` section, find where `let activeFilters = {};` is declared and add after it:

```javascript
let seasonFilterActive = false;
```

**Step 5: Update buildFilterChips to add "In Season" chip first**

In `buildFilterChips()` (line 1019), after `chipsContainer.innerHTML = '';` and `activeFilters = {};`, add before the chipData loop:

```javascript
// "In Season" toggle chip — always first
seasonFilterActive = false;
const seasonChip = document.createElement('button');
seasonChip.className = 'chip season';
seasonChip.textContent = 'In Season';
seasonChip.addEventListener('click', function() {
    seasonFilterActive = !seasonFilterActive;
    seasonChip.classList.toggle('active', seasonFilterActive);
    renderRecipes();
});
chipsContainer.appendChild(seasonChip);
```

This goes right after `activeFilters = {};` (line 1022) and before the `const chipData = [];` line.

**Step 6: Manual verification**

1. Restart API server: `launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist && launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist`
2. Open: `http://localhost:5001/meal-planner`
3. Verify: Green "In Season" chip appears as first chip
4. Click it: Should turn green background, filter recipes
5. Click a cuisine chip too: Should AND combine (both filters apply)

**Step 7: Commit**

```bash
git add templates/meal_planner.html
git commit -m "feat: add In Season filter chip to meal planner dashboard"
```

---

### Task 3: Create Cuisine Migration Script — Core Logic

**Files:**
- Create: `migrate_cuisine.py`
- Test: `tests/test_migrate_cuisine.py`

**Step 1: Write the failing tests**

Create `tests/test_migrate_cuisine.py`:

```python
"""Tests for cuisine data cleanup migration."""
import tempfile
from pathlib import Path

from migrate_cuisine import (
    apply_cuisine_corrections,
    CUISINE_CORRECTIONS,
    RECIPE_OVERRIDES,
)


class TestApplyCuisineCorrections:
    """Test deterministic cuisine correction logic."""

    def test_recipe_override_takes_priority(self):
        """Per-recipe override wins over general corrections."""
        result = apply_cuisine_corrections("Seneyet Jaj O Batata", "Ethiopian")
        assert result == "Middle Eastern"

    def test_variant_consolidated(self):
        """Variant cuisine names get consolidated to base."""
        result = apply_cuisine_corrections("Any Recipe", "Korean-inspired")
        assert result == "Korean"

    def test_correct_cuisine_unchanged(self):
        """Already-correct cuisines pass through unchanged."""
        result = apply_cuisine_corrections("Any Recipe", "Italian")
        assert result == "Italian"

    def test_null_cuisine_filled_by_override(self):
        """Null cuisine gets filled if recipe is in RECIPE_OVERRIDES."""
        result = apply_cuisine_corrections("Pasta Aglio E Olio Inspired By Chef", None)
        assert result == "Italian"

    def test_null_cuisine_without_override_stays_null(self):
        """Null cuisine without override remains None."""
        result = apply_cuisine_corrections("Unknown Recipe", None)
        assert result is None

    def test_dietary_label_cleared(self):
        """Dietary labels (Vegan, Vegetarian) get cleared when not in overrides."""
        result = apply_cuisine_corrections("Unknown Vegan Recipe", "Vegan")
        assert result is None

    def test_corrupt_data_cleared(self):
        """Corrupt values like 'protein:' get cleared."""
        result = apply_cuisine_corrections("Some Recipe", "protein:")
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py -v`
Expected: FAIL — `migrate_cuisine` module not found

**Step 3: Write minimal implementation**

Create `migrate_cuisine.py`:

```python
#!/usr/bin/env python3
"""
KitchenOS - Cuisine Data Cleanup & Seasonal Population Migration

Fixes inconsistent cuisine values and populates seasonal ingredient data.

Usage:
    python migrate_cuisine.py [--dry-run] [--no-seasonal]
"""

import argparse
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table

OBSIDIAN_RECIPES_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS/Recipes"
)

# Variant consolidation — maps non-standard cuisine values to standard ones.
# None means "clear this value" (handled per-recipe in RECIPE_OVERRIDES or left null).
CUISINE_CORRECTIONS = {
    "Asian-inspired": "Asian",
    "Korean-inspired": "Korean",
    "Korean-American": "Korean",
    "Japanese-American fusion": "Japanese",
    "Chinese (Sichuan) or Asian": "Chinese",
    "Italian (inferred from Murcattt channel)": "Italian",
    "Vegan": None,
    "Vegetarian": None,
    "Not specified": None,
    "International": None,
    "Fusion": None,
    "protein:": None,
}

# Per-recipe overrides — applied first, wins over CUISINE_CORRECTIONS.
# Keys are recipe filenames (stem, no .md extension).
RECIPE_OVERRIDES = {
    # Misclassified
    "Seneyet Jaj O Batata": "Middle Eastern",
    "Macarona Bi Laban": "Middle Eastern",
    "Beef Steak Pepper Lunch Skillet": "Japanese",
    "Spicy Baked Black Bean Nachos": "Tex-Mex",
    "Queso Dip Recipe": "Tex-Mex",
    "Chili Cheese Tortillas": "Tex-Mex",
    "Cilantro Lime Chicken": "Mexican",
    "Ginger-Lime Marinade For Chicken": "Asian",
    # Dietary labels → actual cuisine
    "200G Lentils And 1 Sweet Potato": "Indian",
    "Cauliflower Steak With Butter Bean Puree And Chimichurri": "South American",
    "High-Protein Bean Lentil Dip (Crouton)": "Middle Eastern",
    # Null fills — misclassified or obviously inferable
    "Pasta Aglio E Olio Inspired By Chef": "Italian",
    "Hash Brown Casserole": "American",
    "Rich Fudgy Chocolate Cake": "American",
    "Large Batch Freezer Biscuits": "American",
    "Lime Cheesecake": "American",
    "Meal Prep Systems": "American",
    "19 Calorie Fudgy Brownies (Crouton)": "American",
    "5-Ingredient Cottage Cheese Cookie Dough": "American",
    "Blended Chocolate Salted Caramel Chia Pudding Mousse": "American",
    "Blueberry Donut Holes (Cottage Cheese Or Yogurt)": "American",
    "Charred Cabbage": "American",
    "Cherry Vanilla Breakfast Smoothie": "American",
    "Chewy Peanut Butter Cookies": "American",
    "Chocolate Chip Protein Cookies": "American",
    "Chocolate Cream Pie": "American",
    "Cosmic Brownie Protein Ice Cream": "American",
    "Cottage Cheese Chicken Caesar Wrap": "American",
    "Dairy-Free Dill Dressing": "American",
    "Deconstructed Strawberry Cheesecake 20G Protein": "American",
    "Double Dark Chocolate Granola": "American",
    "Dr. Rupy's No Bake Protein Bar": "American",
    "Goddess Salad": "American",
    "Healthy Blueberry Apple Oatmeal Cake": "American",
    "Healthy Delicious Recipe": "American",
    "High Protein Low Cal Chicken Sandwich": "American",
    "High Protein Sweet Potato, Beef, And Cottage Cheese Bowl": "American",
    "High-Protein Chocolate Chia Pudding Recipe": "American",
    "Matcha Smoothie": "American",
    "Nutella Protein Dessert": "American",
    "Oat Flour Pancakes": "American",
    "Oats With Chia Seeds & Yogurt Recipe": "American",
    "Peanut Butter Chocolate Coffee Smoothie": "American",
    "Protein Cabbage Wraps (Meatless)": "American",
    "Protein Cheesecake": "American",
    "Salted Honey Pistachio Cookies": "American",
    "Slutty Brownie Recipe": "American",
    "Strawberry Buttercream Frosting": "American",
    "Untitled-Recipe": "American",
    # Sriracha Lime → Asian-Inspired
    "Sriracha Lime Chicken Bowls": "Asian",
    # Breakfast Lentils → Indian
    "Breakfast Lentils Vegan Porridge": "Indian",
}


def apply_cuisine_corrections(recipe_name: str, current_cuisine) -> str | None:
    """Apply deterministic cuisine corrections for a recipe.

    Priority: RECIPE_OVERRIDES > CUISINE_CORRECTIONS > pass-through.

    Args:
        recipe_name: Recipe filename stem (no .md)
        current_cuisine: Current cuisine value (str or None)

    Returns:
        Corrected cuisine string, or None if should be null
    """
    # 1. Per-recipe override (highest priority)
    if recipe_name in RECIPE_OVERRIDES:
        return RECIPE_OVERRIDES[recipe_name]

    # 2. General correction map
    if current_cuisine in CUISINE_CORRECTIONS:
        return CUISINE_CORRECTIONS[current_cuisine]

    # 3. Pass through
    return current_cuisine
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add migrate_cuisine.py tests/test_migrate_cuisine.py
git commit -m "feat: add cuisine correction logic with deterministic map"
```

---

### Task 4: Add Frontmatter Update Logic to Migration Script

**Files:**
- Modify: `migrate_cuisine.py` (add `update_frontmatter_field` function)
- Test: `tests/test_migrate_cuisine.py` (add file-level tests)

**Step 1: Write the failing tests**

Add to `tests/test_migrate_cuisine.py`:

```python
from migrate_cuisine import update_frontmatter_field


class TestUpdateFrontmatterField:
    """Test updating a single frontmatter field in recipe content."""

    def test_updates_string_value(self):
        """Replaces existing cuisine string value."""
        content = '---\ntitle: "Test"\ncuisine: "Ethiopian"\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Middle Eastern")
        assert 'cuisine: "Middle Eastern"' in result
        assert "Ethiopian" not in result

    def test_updates_null_to_string(self):
        """Replaces null with string value."""
        content = '---\ntitle: "Test"\ncuisine: null\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Italian")
        assert 'cuisine: "Italian"' in result

    def test_preserves_other_fields(self):
        """Other frontmatter fields are unchanged."""
        content = '---\ntitle: "Test"\ncuisine: "Ethiopian"\nprotein: "chicken"\n---\n\n# Test'
        result = update_frontmatter_field(content, "cuisine", "Middle Eastern")
        assert 'protein: "chicken"' in result
        assert 'title: "Test"' in result

    def test_preserves_body(self):
        """Body content after frontmatter is unchanged."""
        content = '---\ntitle: "Test"\ncuisine: null\n---\n\n# Test\n\nSome body content.'
        result = update_frontmatter_field(content, "cuisine", "American")
        assert "# Test\n\nSome body content." in result

    def test_updates_list_field(self):
        """Can update a list field like seasonal_ingredients."""
        content = '---\ntitle: "Test"\nseasonal_ingredients: []\n---\n\n# Test'
        result = update_frontmatter_field(content, "seasonal_ingredients", ["tomato", "basil"])
        assert 'seasonal_ingredients: ["tomato", "basil"]' in result

    def test_updates_int_list_field(self):
        """Can update an int list field like peak_months."""
        content = '---\ntitle: "Test"\npeak_months: []\n---\n\n# Test'
        result = update_frontmatter_field(content, "peak_months", [4, 5, 6])
        assert "peak_months: [4, 5, 6]" in result
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py::TestUpdateFrontmatterField -v`
Expected: FAIL — `update_frontmatter_field` not found

**Step 3: Write minimal implementation**

Add to `migrate_cuisine.py`:

```python
def update_frontmatter_field(content: str, field: str, value) -> str:
    """Update a single frontmatter field in recipe markdown content.

    Args:
        content: Full markdown file content with YAML frontmatter
        field: Frontmatter field name to update
        value: New value (str, list, int, or None)

    Returns:
        Updated content with the field changed
    """
    # Format value for YAML
    if value is None:
        yaml_value = "null"
    elif isinstance(value, list):
        if not value:
            yaml_value = "[]"
        elif isinstance(value[0], str):
            yaml_value = "[" + ", ".join(f'"{v}"' for v in value) + "]"
        else:
            yaml_value = "[" + ", ".join(str(v) for v in value) + "]"
    elif isinstance(value, str):
        yaml_value = f'"{value}"'
    else:
        yaml_value = str(value)

    # Replace the field line in frontmatter
    pattern = rf'^({field}:\s*).*$'
    replacement = rf'\g<1>{yaml_value}'
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add migrate_cuisine.py tests/test_migrate_cuisine.py
git commit -m "feat: add frontmatter field update helper for cuisine migration"
```

---

### Task 5: Add CLI and Full Migration Runner

**Files:**
- Modify: `migrate_cuisine.py` (add `run_cuisine_migration`, `run_seasonal_migration`, `main`)
- Test: `tests/test_migrate_cuisine.py` (add integration tests)

**Step 1: Write the failing tests**

Add to `tests/test_migrate_cuisine.py`:

```python
from unittest.mock import patch
from migrate_cuisine import run_cuisine_migration


class TestRunCuisineMigration:
    """Test full cuisine migration on recipe files."""

    def test_fixes_misclassified_cuisine(self):
        """Overwrites wrong cuisine for known recipes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            recipe.write_text(
                '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'cuisine: "Middle Eastern"' in new_content
            assert len(results["updated"]) == 1

    def test_consolidates_variant(self):
        """Consolidates Korean-inspired to Korean."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Some Korean Dish.md"
            recipe.write_text(
                '---\ntitle: "Some Korean Dish"\ncuisine: "Korean-inspired"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            new_content = recipe.read_text()
            assert 'cuisine: "Korean"' in new_content

    def test_skips_correct_cuisine(self):
        """Recipes with correct cuisines are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Good Recipe.md"
            recipe.write_text(
                '---\ntitle: "Good Recipe"\ncuisine: "Italian"\n---\n\n# Test'
            )
            results = run_cuisine_migration(recipes_dir, dry_run=False)
            assert len(results["skipped"]) == 1

    def test_dry_run_no_changes(self):
        """Dry run reports changes but doesn't modify files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            original = '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            recipe.write_text(original)
            results = run_cuisine_migration(recipes_dir, dry_run=True)
            assert recipe.read_text() == original
            assert len(results["updated"]) == 1

    def test_creates_backup_before_modifying(self):
        """Should create backup in .history before writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            recipe = recipes_dir / "Seneyet Jaj O Batata.md"
            recipe.write_text(
                '---\ntitle: "Seneyet Jaj O Batata"\ncuisine: "Ethiopian"\n---\n\n# Test'
            )
            run_cuisine_migration(recipes_dir, dry_run=False)
            history_dir = recipes_dir / ".history"
            assert history_dir.exists()
            assert len(list(history_dir.glob("*.md"))) == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py::TestRunCuisineMigration -v`
Expected: FAIL — `run_cuisine_migration` not found

**Step 3: Write implementation**

Add to `migrate_cuisine.py`:

```python
from lib.seasonality import match_ingredients_to_seasonal, get_peak_months


def run_cuisine_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Run cuisine correction migration on all recipe files.

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
            recipe_name = md_file.stem
            current_cuisine = fm.get("cuisine")

            corrected = apply_cuisine_corrections(recipe_name, current_cuisine)

            if corrected == current_cuisine:
                results["skipped"].append((md_file.name, "cuisine already correct"))
                continue

            old_display = current_cuisine or "null"
            new_display = corrected or "null"
            change_desc = f'{old_display} → {new_display}'

            if dry_run:
                results["updated"].append((md_file.name, change_desc))
            else:
                create_backup(md_file)
                new_content = update_frontmatter_field(content, "cuisine", corrected)
                md_file.write_text(new_content, encoding="utf-8")
                results["updated"].append((md_file.name, change_desc))

        except Exception as e:
            results["errors"].append((md_file.name, str(e)))

    return results


def run_seasonal_migration(recipes_dir: Path, dry_run: bool = False) -> dict:
    """Populate seasonal_ingredients and peak_months for recipes with empty data.

    Requires Ollama running with mistral:7b.

    Args:
        recipes_dir: Path to Recipes folder
        dry_run: If True, report what would change without modifying files

    Returns:
        dict with 'updated', 'skipped', 'errors' lists
    """
    results = {"updated": [], "skipped": [], "errors": []}

    if not recipes_dir.exists():
        print(f"Recipes directory not found: {recipes_dir}")
        return results

    md_files = sorted(recipes_dir.glob("*.md"))
    total = len([f for f in md_files if not f.name.startswith(".")])
    count = 0

    for md_file in md_files:
        if md_file.name.startswith("."):
            continue

        count += 1

        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = parse_recipe_file(content)
            fm = parsed["frontmatter"]

            existing_seasonal = fm.get("seasonal_ingredients", [])
            if existing_seasonal:
                results["skipped"].append((md_file.name, "already has seasonal data"))
                continue

            # Parse ingredients from body
            ing_match = re.search(
                r"## Ingredients\n\n((?:\|[^\n]+\n)+)", parsed["body"]
            )
            if not ing_match:
                results["skipped"].append((md_file.name, "no ingredient table"))
                continue

            ingredients = parse_ingredient_table(ing_match.group(1))
            if not ingredients:
                results["skipped"].append((md_file.name, "empty ingredient table"))
                continue

            print(f"  [{count}/{total}] {md_file.stem}...", end=" ", flush=True)

            if dry_run:
                results["updated"].append((md_file.name, "would populate seasonal data"))
                print("(dry run)")
                continue

            seasonal = match_ingredients_to_seasonal(ingredients)
            months = get_peak_months(seasonal)

            if not seasonal:
                results["skipped"].append((md_file.name, "no seasonal matches"))
                print("no matches")
                continue

            new_content = update_frontmatter_field(content, "seasonal_ingredients", seasonal)
            new_content = update_frontmatter_field(new_content, "peak_months", months)
            md_file.write_text(new_content, encoding="utf-8")

            results["updated"].append(
                (md_file.name, f"matched: {seasonal}, months: {months}")
            )
            print(f"matched {len(seasonal)} items")

        except Exception as e:
            results["errors"].append((md_file.name, str(e)))
            print(f"error: {e}")

    return results


def print_results(results: dict, label: str, dry_run: bool):
    """Print migration results summary."""
    prefix = "Would update" if dry_run else "Updated"

    print(f"\n--- {label} ---")

    if results["updated"]:
        print(f"{prefix}: {len(results['updated'])} file(s)")
        for name, detail in results["updated"]:
            print(f"  {name}: {detail}")

    if results["skipped"]:
        print(f"Skipped: {len(results['skipped'])} file(s)")

    if results["errors"]:
        print(f"Errors: {len(results['errors'])} file(s)")
        for name, error in results["errors"]:
            print(f"  {name}: {error}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up cuisine data and populate seasonal ingredients"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without modifying files"
    )
    parser.add_argument(
        "--no-seasonal", action="store_true", help="Skip seasonal data population (Ollama)"
    )
    parser.add_argument(
        "--path", type=str, help="Path to recipes directory (default: Obsidian vault)"
    )
    args = parser.parse_args()

    recipes_dir = Path(args.path) if args.path else OBSIDIAN_RECIPES_PATH

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    # Phase 1: Cuisine cleanup
    print(f"Scanning: {recipes_dir}")
    print("\nPhase 1: Cuisine corrections...")
    cuisine_results = run_cuisine_migration(recipes_dir, dry_run=args.dry_run)
    print_results(cuisine_results, "Cuisine Cleanup", args.dry_run)

    # Phase 2: Seasonal data population
    if not args.no_seasonal:
        print("\nPhase 2: Seasonal data population (Ollama)...")
        seasonal_results = run_seasonal_migration(recipes_dir, dry_run=args.dry_run)
        print_results(seasonal_results, "Seasonal Data", args.dry_run)
    else:
        print("\nPhase 2: Skipped (--no-seasonal)")

    print("\nDone!")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify all pass**

Run: `.venv/bin/python -m pytest tests/test_migrate_cuisine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add migrate_cuisine.py tests/test_migrate_cuisine.py
git commit -m "feat: add cuisine migration runner with CLI, seasonal population, and backup support"
```

---

### Task 6: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add migrate_cuisine.py to Running Commands section**

After the "Migrate Recipes to New Schema" section, add:

```markdown
### Clean Up Cuisine Data & Populate Seasonal

```bash
# Preview cuisine corrections and seasonal population
.venv/bin/python migrate_cuisine.py --dry-run

# Apply all fixes
.venv/bin/python migrate_cuisine.py

# Cuisine fixes only (skip Ollama seasonal matching)
.venv/bin/python migrate_cuisine.py --no-seasonal
```
```

**Step 2: Add migrate_cuisine.py to Architecture > Core Components table**

Add row:

```
| `migrate_cuisine.py` | Cuisine data cleanup & seasonal data population |
```

**Step 3: Add migrate_cuisine.py to Key Functions section**

Add:

```markdown
**migrate_cuisine.py:**
- `apply_cuisine_corrections()` - Deterministic cuisine fix from correction map + per-recipe overrides
- `update_frontmatter_field()` - Updates single YAML frontmatter field in recipe content
- `run_cuisine_migration()` - Batch cuisine cleanup across all recipe files
- `run_seasonal_migration()` - Batch seasonal data population via Ollama
```

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add migrate_cuisine.py to CLAUDE.md"
```

---

### Task 7: Run Migration (Dry Run + Apply)

**Files:**
- No code changes — execution only

**Step 1: Verify Ollama is running**

Run: `curl http://localhost:11434/api/tags`
Expected: JSON response listing models including `mistral:7b`

**Step 2: Dry run**

Run: `.venv/bin/python migrate_cuisine.py --dry-run`
Expected: Report showing ~50+ cuisine corrections and ~150+ seasonal population candidates

**Step 3: Apply cuisine fixes only first**

Run: `.venv/bin/python migrate_cuisine.py --no-seasonal`
Expected: ~50+ files updated with corrected cuisines, backups created in `.history`

**Step 4: Verify cuisine fixes**

Run: `.venv/bin/python -c "from lib.recipe_index import get_recipe_index; from pathlib import Path; recipes = get_recipe_index(Path('/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes')); cuisines = set(r['cuisine'] for r in recipes if r['cuisine']); print(sorted(cuisines)); print(f'{len(cuisines)} unique cuisines'); nulls = [r['name'] for r in recipes if not r['cuisine']]; print(f'{len(nulls)} null cuisines: {nulls}')"`
Expected: ~20 clean cuisines, 0 or very few nulls

**Step 5: Apply seasonal data population**

Run: `.venv/bin/python migrate_cuisine.py`
Expected: Ollama processes each recipe (~3-5 min total), populates seasonal_ingredients and peak_months

**Step 6: Verify dashboard**

1. Restart API server to clear cache
2. Open `http://localhost:5001/meal-planner`
3. Verify: More cuisine chips visible, "In Season" chip works

---

### Task 8: Run Full Test Suite

**Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS — no regressions from recipe_index change or new migration

**Step 2: Commit any fixes if needed**

If tests fail, fix and commit.

---

### Task 9: Final Commit — Design Doc Update

**Files:**
- Modify: `docs/plans/2026-02-21-season-filter-cuisine-cleanup-design.md`

**Step 1: Mark design as implemented**

Change `**Status:** Approved` to `**Status:** Implemented`

**Step 2: Commit**

```bash
git add docs/plans/2026-02-21-season-filter-cuisine-cleanup-design.md
git commit -m "docs: mark season filter design as implemented"
```
