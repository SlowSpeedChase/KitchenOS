# Nutrition Macros Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize nutrition frontmatter keys to a consistent `nutrition_` prefix, fix silent data-loss bugs in the extraction pipeline, backfill 221 existing recipes with USDA + AI estimates, create `My Macros.md`, and verify the nutrition dashboard works end-to-end.

**Architecture:** Schema rename first (template → extractor → migration), then backfill as a standalone script that reads each recipe's ingredient table, runs USDA → AI lookup, and writes the four `nutrition_*` keys. Dashboard already works structurally once keys are correct.

**Tech Stack:** Python 3.11, existing `lib/nutrition_lookup.py` (USDA + AI), `lib/recipe_parser.py`, `lib/backup.py`, `migrate_recipes.py` pattern, pytest.

**Note:** The `/refresh-nutrition` API endpoint already exists (`api_server.py:512`). The design doc was wrong about it being missing — no endpoint work needed.

---

### Task 1: Update tests for new nutrition key names in recipe_template.py

**Files:**
- Modify: `tests/test_recipe_template.py:59-110`

**Context:** `generate_nutrition_section()` currently reads `calories`, `carbs`, `fat`. We're renaming them to `nutrition_calories`, `nutrition_carbs`, `nutrition_fat`. Update tests first so they fail against the old implementation, then fix the implementation in Task 2.

**Step 1: Update TestNutritionSection tests to use new key names**

In `tests/test_recipe_template.py`, find `class TestNutritionSection` and update the test data dicts:

```python
class TestNutritionSection:
    def test_generate_nutrition_section_with_data(self):
        recipe_data = {
            "nutrition_calories": 450,   # was "calories"
            "nutrition_protein": 25,
            "nutrition_carbs": 45,       # was "carbs"
            "nutrition_fat": 18,         # was "fat"
            "serving_size": "1 cup",
            "nutrition_source": "nutritionix",
        }
        result = generate_nutrition_section(recipe_data)

        assert "## Nutrition (per serving)" in result
        assert "| Calories | Protein | Carbs | Fat |" in result
        assert "| 450" in result
        assert "| 25g" in result
        assert "| 45g" in result
        assert "| 18g" in result
        assert "*Serving size: 1 cup" in result
        assert "Nutritionix" in result

    def test_generate_nutrition_section_without_data(self):
        recipe_data = {}
        result = generate_nutrition_section(recipe_data)
        assert result == ""

    def test_includes_nutrition_in_frontmatter(self):
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "nutrition_calories": 450,   # was "calories"
            "nutrition_protein": 25,
            "nutrition_carbs": 45,       # was "carbs"
            "nutrition_fat": 18,         # was "fat"
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(
            recipe_data,
            video_url="https://youtube.com/watch?v=abc123",
            video_title="Test Video",
            channel="Test Channel"
        )
        assert "nutrition_calories: 450" in result
        assert "nutrition_protein: 25" in result
        assert "nutrition_carbs: 45" in result
        assert "nutrition_fat: 18" in result
        assert "nutrition_source:" in result
        # Old keys must NOT appear
        assert "\ncalories:" not in result
        assert "\ncarbs:" not in result
        assert "\nfat:" not in result
```

**Step 2: Run tests — verify they fail**

```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/pytest tests/test_recipe_template.py::TestNutritionSection -v
```

Expected: FAIL — `generate_nutrition_section` still reads old keys so the section won't render, and frontmatter will still have old key names.

---

### Task 2: Rename nutrition keys in recipe_template.py

**Files:**
- Modify: `templates/recipe_template.py`

**Step 1: Update RECIPE_SCHEMA**

In `RECIPE_SCHEMA` dict (around line 14), rename three keys:

```python
# Replace these three lines:
"calories": int,
"nutrition_protein": int,
"carbs": int,
"fat": int,

# With:
"nutrition_calories": int,
"nutrition_protein": int,
"nutrition_carbs": int,
"nutrition_fat": int,
```

**Step 2: Update RECIPE_TEMPLATE frontmatter string**

Find the nutrition block in `RECIPE_TEMPLATE` (around line 193) and rename:

```
# Replace:
calories: {calories}
nutrition_protein: {nutrition_protein}
carbs: {carbs}
fat: {fat}

# With:
nutrition_calories: {nutrition_calories}
nutrition_protein: {nutrition_protein}
nutrition_carbs: {nutrition_carbs}
nutrition_fat: {nutrition_fat}
```

**Step 3: Update generate_nutrition_section()**

```python
def generate_nutrition_section(recipe_data: dict) -> str:
    calories = recipe_data.get("nutrition_calories")   # was "calories"
    if calories is None:
        return ""

    nutrition_protein = recipe_data.get("nutrition_protein", 0)
    carbs = recipe_data.get("nutrition_carbs", 0)      # was "carbs"
    fat = recipe_data.get("nutrition_fat", 0)          # was "fat"
    serving_size = recipe_data.get("serving_size", "1 serving")
    source = recipe_data.get("nutrition_source", "unknown")
    # (rest of function unchanged)
```

**Step 4: Update format_recipe_markdown() kwargs**

Find the `return RECIPE_TEMPLATE.format(...)` call (around line 384) and update four lines:

```python
# Replace:
calories=num_or_null(recipe_data.get('calories')),
nutrition_protein=num_or_null(recipe_data.get('nutrition_protein')),
carbs=num_or_null(recipe_data.get('carbs')),
fat=num_or_null(recipe_data.get('fat')),

# With:
nutrition_calories=num_or_null(recipe_data.get('nutrition_calories')),
nutrition_protein=num_or_null(recipe_data.get('nutrition_protein')),
nutrition_carbs=num_or_null(recipe_data.get('nutrition_carbs')),
nutrition_fat=num_or_null(recipe_data.get('nutrition_fat')),
```

**Step 5: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/test_recipe_template.py -v
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add templates/recipe_template.py tests/test_recipe_template.py
git commit -m "feat(schema): rename nutrition frontmatter keys to nutrition_* prefix

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Fix nutrition key writes in extract_recipe.py and api_server.py

**Files:**
- Modify: `extract_recipe.py:448-452`
- Modify: `api_server.py:255-259`

**Context:** Both files write `calories`, `protein_g`, `carbs_g`, `fat_g` — keys that the template never reads. This is why protein/carbs/fat have been silently null on every recipe since the feature was added.

**Step 1: Fix extract_recipe.py**

Find the nutrition write block (around line 447):

```python
# Replace these lines:
recipe_data["calories"] = nutrition_result.nutrition.calories
recipe_data["protein_g"] = nutrition_result.nutrition.protein
recipe_data["carbs_g"] = nutrition_result.nutrition.carbs
recipe_data["fat_g"] = nutrition_result.nutrition.fat

# With:
recipe_data["nutrition_calories"] = nutrition_result.nutrition.calories
recipe_data["nutrition_protein"] = nutrition_result.nutrition.protein
recipe_data["nutrition_carbs"] = nutrition_result.nutrition.carbs
recipe_data["nutrition_fat"] = nutrition_result.nutrition.fat
```

**Step 2: Fix api_server.py**

Find the nutrition write block in `/api/recipes/save` (around line 255):

```python
# Replace:
data['calories'] = nutrition_result.nutrition.calories
data['protein_g'] = nutrition_result.nutrition.protein
data['carbs_g'] = nutrition_result.nutrition.carbs
data['fat_g'] = nutrition_result.nutrition.fat

# With:
data['nutrition_calories'] = nutrition_result.nutrition.calories
data['nutrition_protein'] = nutrition_result.nutrition.protein
data['nutrition_carbs'] = nutrition_result.nutrition.carbs
data['nutrition_fat'] = nutrition_result.nutrition.fat
```

**Step 3: Run existing tests**

```bash
.venv/bin/pytest tests/test_api_server.py tests/test_nutrition_lookup.py -v
```

Expected: All PASS (these tests mock the nutrition calls, so they verify the surrounding logic still works).

**Step 4: Commit**

```bash
git add extract_recipe.py api_server.py
git commit -m "fix(nutrition): correct key names written by extraction pipeline

protein_g/carbs_g/fat_g were written but template read nutrition_protein/
carbs/fat — macros have been null on every new recipe since feature was added.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Write tests for nutrition key rename migration

**Files:**
- Modify: `tests/test_migrate.py`

**Context:** We need a `rename_nutrition_keys()` function in `migrate_recipes.py` that renames the three old frontmatter keys. Write tests first.

**Step 1: Add tests to test_migrate.py**

```python
from migrate_recipes import rename_nutrition_keys


class TestRenameNutritionKeys:
    def test_renames_calories_carbs_fat(self):
        content = "---\ntitle: Test\ncalories: 450\ncarbs: 45\nfat: 18\n---\n# Test\n"
        new_content, changes = rename_nutrition_keys(content)
        assert "nutrition_calories: 450" in new_content
        assert "nutrition_carbs: 45" in new_content
        assert "nutrition_fat: 18" in new_content
        assert "\ncalories:" not in new_content
        assert "\ncarbs:" not in new_content
        assert "\nfat:" not in new_content
        assert len(changes) == 3

    def test_preserves_nutrition_protein(self):
        content = "---\nnutrition_protein: 25\n---\n# Test\n"
        new_content, changes = rename_nutrition_keys(content)
        assert "nutrition_protein: 25" in new_content
        assert changes == []

    def test_does_not_rename_already_prefixed_keys(self):
        content = "---\nnutrition_calories: 450\nnutrition_carbs: 45\nnutrition_fat: 18\n---\n# Test\n"
        new_content, changes = rename_nutrition_keys(content)
        assert changes == []
        assert new_content == content

    def test_does_not_touch_body_text(self):
        content = "---\ncalories: 450\n---\n\n| Calories | Carbs | Fat |\nHigh in fat content.\n"
        new_content, changes = rename_nutrition_keys(content)
        # Frontmatter key renamed
        assert "nutrition_calories: 450" in new_content
        # Body table header preserved exactly
        assert "| Calories | Carbs | Fat |" in new_content
        assert "High in fat content." in new_content

    def test_handles_null_values(self):
        content = "---\ncalories: null\ncarbs: null\nfat: null\n---\n# Test\n"
        new_content, changes = rename_nutrition_keys(content)
        assert "nutrition_calories: null" in new_content
        assert "nutrition_carbs: null" in new_content
        assert "nutrition_fat: null" in new_content
        assert len(changes) == 3

    def test_returns_unchanged_content_when_no_frontmatter(self):
        content = "# Just a heading\nNo frontmatter here."
        new_content, changes = rename_nutrition_keys(content)
        assert new_content == content
        assert changes == []
```

**Step 2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/test_migrate.py::TestRenameNutritionKeys -v
```

Expected: FAIL — `rename_nutrition_keys` not yet defined.

---

### Task 5: Implement rename_nutrition_keys in migrate_recipes.py

**Files:**
- Modify: `migrate_recipes.py`

**Step 1: Add NUTRITION_KEY_RENAMES constant and rename function**

After the imports block (around line 28), add:

```python
NUTRITION_KEY_RENAMES = {
    'calories': 'nutrition_calories',
    'carbs': 'nutrition_carbs',
    'fat': 'nutrition_fat',
}


def rename_nutrition_keys(content: str) -> tuple[str, list[str]]:
    """Rename old nutrition frontmatter keys to nutrition_* prefix.

    Only operates on the frontmatter section; body text is untouched.
    Idempotent — already-prefixed keys are left alone.
    """
    changes = []
    parts = content.split('---', 2)
    if len(parts) < 3:
        return content, changes

    frontmatter = parts[1]
    new_frontmatter = frontmatter

    for old_key, new_key in NUTRITION_KEY_RENAMES.items():
        # Anchored to start-of-line so 'nutrition_calories:' is not matched by 'calories:'
        pattern = rf'(?m)^(\s*){re.escape(old_key)}:'
        if re.search(pattern, new_frontmatter):
            new_frontmatter = re.sub(pattern, rf'\g<1>{new_key}:', new_frontmatter)
            changes.append(f"Renamed '{old_key}' to '{new_key}'")

    if not changes:
        return content, changes

    return f"---{new_frontmatter}---{parts[2]}", changes
```

**Step 2: Integrate rename into migrate_recipe_content()**

At the top of `migrate_recipe_content()`, before the ingredient table check, add:

```python
def migrate_recipe_content(content: str, filename: str = None) -> Tuple[str, List[str]]:
    changes = []
    new_content = content

    # Rename old nutrition keys to nutrition_* prefix
    new_content, rename_changes = rename_nutrition_keys(new_content)
    changes.extend(rename_changes)

    # (rest of function unchanged)
```

**Step 3: Add nutrition key detection to needs_content_migration()**

Add one more check at the end of `needs_content_migration()`:

```python
def needs_content_migration(content: str) -> bool:
    # ... existing checks ...

    # Check for old nutrition keys in frontmatter
    if '\ncalories:' in content or '\ncarbs:' in content or '\nfat:' in content:
        return True

    return False
```

**Step 4: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/test_migrate.py -v
```

Expected: All PASS.

**Step 5: Run full test suite**

```bash
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add migrate_recipes.py tests/test_migrate.py
git commit -m "feat(migrate): rename old nutrition keys to nutrition_* prefix

Adds rename_nutrition_keys() and integrates it into migrate_recipe_content()
so running migrate_recipes.py upgrades existing recipe files to the new schema.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Run migration on vault

**Step 1: Dry run**

```bash
.venv/bin/python migrate_recipes.py --dry-run 2>&1 | head -40
```

Expected output: List of ~267 files showing `Would rename 'calories' to 'nutrition_calories'` etc.

**Step 2: Run migration**

```bash
.venv/bin/python migrate_recipes.py
```

Expected: ~267 files updated, 0 errors.

**Step 3: Spot-check a file**

```bash
head -25 "/Users/chaseeasterling/KitchenOS/KitchenOS_Vault/Recipes/10-Minute Chili Garlic Noodles.md"
```

Expected: frontmatter shows `nutrition_calories:`, `nutrition_protein:`, `nutrition_carbs:`, `nutrition_fat:` — no bare `calories:`, `carbs:`, or `fat:`.

**Step 4: Commit (no code changes — vault files are not in the repo)**

No git commit needed for vault file changes.

---

### Task 7: Create My Macros.md in vault

**Step 1: Create the file**

Create `/Users/chaseeasterling/KitchenOS/KitchenOS_Vault/My Macros.md`:

```markdown
---
calories: 2000
protein: 150
carbs: 200
fat: 65
---
# My Macros

Daily macro targets used by the Nutrition Dashboard.

Edit the frontmatter values above to match your actual targets.
```

**Step 2: Verify load_macro_targets reads it correctly**

```bash
.venv/bin/python -c "
from lib.paths import vault_root
from lib.macro_targets import load_macro_targets
targets = load_macro_targets(vault_root())
print(targets)
"
```

Expected: `NutritionData(calories=2000, protein=150, carbs=200, fat=65)`

---

### Task 8: Write tests for backfill_nutrition.py

**Files:**
- Create: `tests/test_backfill_nutrition.py`

**Step 1: Create test file**

```python
"""Tests for backfill_nutrition.py"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from lib.nutrition import NutritionData
from lib.nutrition_lookup import NutritionLookupResult


def make_recipe_file(path: Path, name: str, nutrition_calories=None, servings=2, ingredients=None):
    """Helper — writes a minimal recipe file."""
    cal_val = nutrition_calories if nutrition_calories is not None else "null"
    ing_table = ""
    if ingredients:
        rows = "\n".join(f"| {i['amount']} | {i['unit']} | {i['item']} |" for i in ingredients)
        ing_table = f"## Ingredients\n\n| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}\n"

    content = f"""---
title: "{name}"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: {cal_val}
nutrition_protein: null
nutrition_carbs: null
nutrition_fat: null
nutrition_source: null
servings: {servings}
serving_size: null
---

# {name}

{ing_table}## Instructions

1. Cook it.
"""
    (path / f"{name}.md").write_text(content)


class TestBackfillNutrition:
    def test_skips_recipes_with_existing_nutrition(self, tmp_path):
        from backfill_nutrition import collect_recipes_needing_backfill
        make_recipe_file(tmp_path, "Already Done", nutrition_calories=450)
        make_recipe_file(tmp_path, "Needs Work", nutrition_calories=None)
        recipes = collect_recipes_needing_backfill(tmp_path)
        names = [r.stem for r in recipes]
        assert "Needs Work" in names
        assert "Already Done" not in names

    def test_writes_correct_keys_after_lookup(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Test Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "flour"},
        ])
        recipe_path = tmp_path / "Test Recipe.md"

        mock_result = NutritionLookupResult(
            NutritionData(calories=300, protein=8, carbs=60, fat=1),
            source="usda"
        )
        with patch("backfill_nutrition.lookup_usda_ai", return_value=mock_result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 150" in content   # 300 / 2 servings
        assert "nutrition_protein: 4" in content
        assert "nutrition_carbs: 30" in content
        assert "nutrition_fat: 0" in content
        assert "nutrition_source: usda" in content

    def test_defaults_null_servings_to_one(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "No Servings", servings="null", ingredients=[
            {"amount": "2", "unit": "cups", "item": "rice"},
        ])
        recipe_path = tmp_path / "No Servings.md"

        mock_result = NutritionLookupResult(
            NutritionData(calories=400, protein=8, carbs=80, fat=1),
            source="ai"
        )
        with patch("backfill_nutrition.lookup_usda_ai", return_value=mock_result):
            backfill_recipe(recipe_path, dry_run=False)

        content = recipe_path.read_text()
        # servings=1 so no division: 400/1 = 400
        assert "nutrition_calories: 400" in content

    def test_dry_run_does_not_write_file(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Dry Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "oats"},
        ])
        recipe_path = tmp_path / "Dry Recipe.md"
        original = recipe_path.read_text()

        mock_result = NutritionLookupResult(
            NutritionData(calories=300, protein=10, carbs=50, fat=5),
            source="usda"
        )
        with patch("backfill_nutrition.lookup_usda_ai", return_value=mock_result):
            backfill_recipe(recipe_path, dry_run=True)

        assert recipe_path.read_text() == original

    def test_skips_recipe_with_no_ingredients(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Empty Recipe", ingredients=None)
        recipe_path = tmp_path / "Empty Recipe.md"

        with patch("backfill_nutrition.lookup_usda_ai") as mock_lookup:
            backfill_recipe(recipe_path, dry_run=False)
            mock_lookup.assert_not_called()
```

**Step 2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/test_backfill_nutrition.py -v
```

Expected: FAIL — `backfill_nutrition` module does not exist yet.

---

### Task 9: Implement backfill_nutrition.py

**Files:**
- Create: `backfill_nutrition.py`

**Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Backfill nutrition data for existing recipes using USDA + AI estimation.

Processes all recipes with nutrition_calories: null. For each recipe:
  1. Parse the ingredient table from the recipe body.
  2. Look up nutrition per ingredient via USDA FoodData Central (free).
  3. Fall back to Ollama AI estimate for any ingredients USDA can't find.
  4. Write nutrition_calories/protein/carbs/fat back to the recipe file.

Usage:
    .venv/bin/python backfill_nutrition.py [--dry-run] [--limit N] [--force]
"""

import argparse
import re
import sys
import os
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import paths
from lib.backup import create_backup
from lib.nutrition import NutritionData
from lib.nutrition_lookup import lookup_usda, estimate_with_ai, NutritionLookupResult
from lib.recipe_parser import parse_recipe_file, parse_ingredient_table


def lookup_usda_ai(ingredients: list[dict], servings: int) -> Optional[NutritionLookupResult]:
    """Look up nutrition using USDA per-ingredient, AI for fallback.

    Args:
        ingredients: List of dicts with 'amount', 'unit', 'item' keys.
        servings: Number of servings to divide total by.

    Returns:
        Per-serving NutritionLookupResult, or None if all lookups fail.
    """
    total = NutritionData.empty()
    any_usda = False
    failed_strs = []

    for ing in ingredients:
        result = lookup_usda(ing.get("item", ""))
        if result:
            total = total + result.nutrition
            any_usda = True
        else:
            failed_strs.append(
                f"{ing.get('amount', '1')} {ing.get('unit', '')} {ing.get('item', '')}".strip()
            )

    if failed_strs:
        ai_result = estimate_with_ai(failed_strs)
        if ai_result:
            total = total + ai_result.nutrition
            source = "usda+ai" if any_usda else "ai"
        elif not any_usda:
            return None
        else:
            source = "usda"
    else:
        source = "usda"

    servings = max(servings, 1)
    per_serving = total * (1.0 / servings)
    return NutritionLookupResult(nutrition=per_serving, source=source)


def extract_ingredients(body: str) -> list[dict]:
    """Extract structured ingredients from recipe body markdown."""
    match = re.search(r'## Ingredients\n\n((?:\|[^\n]+\n)+)', body)
    if not match:
        return []
    return parse_ingredient_table(match.group(1))


def write_nutrition_to_file(filepath: Path, nutrition: NutritionData, source: str) -> None:
    """Write nutrition values back into a recipe file's frontmatter."""
    content = filepath.read_text(encoding='utf-8')

    replacements = {
        'nutrition_calories': str(nutrition.calories),
        'nutrition_protein': str(nutrition.protein),
        'nutrition_carbs': str(nutrition.carbs),
        'nutrition_fat': str(nutrition.fat),
        'nutrition_source': f'"{source}"',
        'serving_size': '"1 serving"',
    }

    # Split off frontmatter for targeted replacement
    parts = content.split('---', 2)
    if len(parts) < 3:
        return

    frontmatter = parts[1]
    for key, value in replacements.items():
        # Only replace null values (don't overwrite existing data unless --force)
        pattern = rf'(?m)^(\s*{re.escape(key)}:\s*)null'
        frontmatter = re.sub(pattern, rf'\g<1>{value}', frontmatter)

    filepath.write_text(f"---{frontmatter}---{parts[2]}", encoding='utf-8')


def backfill_recipe(filepath: Path, dry_run: bool = False) -> bool:
    """Backfill nutrition for a single recipe file.

    Returns True if nutrition was calculated (or would be in dry_run), False if skipped.
    """
    content = filepath.read_text(encoding='utf-8')
    parsed = parse_recipe_file(content)
    frontmatter = parsed['frontmatter']
    body = parsed['body']

    ingredients = extract_ingredients(body)
    if not ingredients:
        return False

    try:
        servings = int(frontmatter.get('servings') or 1)
    except (ValueError, TypeError):
        servings = 1

    result = lookup_usda_ai(ingredients, servings)
    if result is None:
        return False

    if not dry_run:
        create_backup(filepath)
        write_nutrition_to_file(filepath, result.nutrition, result.source)

    return True


def collect_recipes_needing_backfill(recipes_dir: Path, force: bool = False) -> list[Path]:
    """Return recipe files with null nutrition_calories."""
    files = []
    for md_file in sorted(recipes_dir.glob("*.md")):
        if md_file.name.startswith('.'):
            continue
        content = md_file.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        fm = parsed['frontmatter']
        if 'source_url' not in fm:
            continue
        if force or fm.get('nutrition_calories') is None:
            files.append(md_file)
    return files


def main():
    parser = argparse.ArgumentParser(
        description="Backfill nutrition data for recipes using USDA + AI"
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing files')
    parser.add_argument('--limit', type=int, help='Process at most N recipes')
    parser.add_argument('--force', action='store_true', help='Re-process even recipes with existing data')
    args = parser.parse_args()

    recipes_dir = paths.recipes_dir()
    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    print(f"Scanning: {recipes_dir}")
    candidates = collect_recipes_needing_backfill(recipes_dir, force=args.force)

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Recipes to process: {len(candidates)}\n")

    updated = skipped = failed = 0

    for filepath in candidates:
        print(f"  {filepath.name}...", end=" ", flush=True)
        try:
            result = backfill_recipe(filepath, dry_run=args.dry_run)
            if result:
                print("ok")
                updated += 1
            else:
                print("skipped (no ingredients)")
                skipped += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done:")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")


if __name__ == "__main__":
    main()
```

**Step 2: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/test_backfill_nutrition.py -v
```

Expected: All PASS.

**Step 3: Run full test suite**

```bash
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All PASS.

**Step 4: Commit**

```bash
git add backfill_nutrition.py tests/test_backfill_nutrition.py
git commit -m "feat: add backfill_nutrition.py to populate nutrition data on existing recipes

Uses USDA FoodData Central per ingredient with Ollama AI fallback.
Skips recipes with existing data; --force to re-process.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Run backfill and verify dashboard

**Step 1: Test run with a small batch**

```bash
.venv/bin/python backfill_nutrition.py --limit 5 --dry-run
```

Expected: Lists 5 recipes with "ok" or "skipped (no ingredients)".

**Step 2: Run on 5 recipes for real**

```bash
.venv/bin/python backfill_nutrition.py --limit 5
```

**Step 3: Spot-check a recipe file**

```bash
grep "nutrition_" "/Users/chaseeasterling/KitchenOS/KitchenOS_Vault/Recipes/10-Minute Chili Garlic Noodles.md"
```

Expected: All four `nutrition_*` keys have non-null values and `nutrition_source` is set.

**Step 4: Run full backfill**

```bash
.venv/bin/python backfill_nutrition.py
```

This will take several minutes (221 recipes × USDA lookups + Ollama fallbacks). Let it run.

**Step 5: Verify dashboard generation**

```bash
# Find the current week
.venv/bin/python -c "from datetime import date; y, w, _ = date.today().isocalendar(); print(f'{y}-W{w:02d}')"

# Generate dashboard for that week (replace YYYY-Wnn)
.venv/bin/python generate_nutrition_dashboard.py --week 2026-W22 --dry-run
```

Expected: Dashboard markdown output with no errors and actual numbers in the table (assuming the current week's meal plan references backfilled recipes).

**Step 6: Update CLAUDE.md future enhancements**

In `CLAUDE.md`, add to the Future Enhancements table:

```markdown
| Serving size correction | Medium | Workflow to correct `servings: null` on existing recipes; affects per-serving accuracy of backfilled nutrition |
```

**Step 7: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: add serving size correction to future enhancements

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Summary of Files Changed

| File | Change |
|------|--------|
| `templates/recipe_template.py` | Rename 3 nutrition keys to `nutrition_*` prefix |
| `extract_recipe.py` | Fix key names written after nutrition lookup |
| `api_server.py` | Same fix in `/api/recipes/save` route |
| `migrate_recipes.py` | Add `rename_nutrition_keys()`, integrate into migration |
| `backfill_nutrition.py` | New script — USDA + AI backfill |
| `CLAUDE.md` | Add serving size correction to future enhancements |
| Vault: `My Macros.md` | New file with daily macro targets (placeholder values) |
| `tests/test_recipe_template.py` | Update to new key names |
| `tests/test_migrate.py` | Add `TestRenameNutritionKeys` |
| `tests/test_backfill_nutrition.py` | New — tests for backfill script |
