"""Tests for backfill_nutrition.py"""
from pathlib import Path
from unittest.mock import patch

from lib.nutrition import NutritionData
from lib.nutrition_engine import RecipeNutritionResult


def make_result(cal, pro, carb, fat, source="usda", servings_used=2,
                needs_review=False, confidence=0.8):
    """Build an engine-style result for mocking calculate_recipe_nutrition."""
    nd = NutritionData(cal, pro, carb, fat)
    return RecipeNutritionResult(
        per_serving=nd, total=nd, source=source, servings_used=servings_used,
        servings_inferred=False, needs_review=needs_review,
        confidence=confidence, line_items=[],
    )


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

        result = make_result(150, 4, 30, 0, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 150" in content
        assert "nutrition_protein: 4" in content
        assert "nutrition_carbs: 30" in content
        assert "nutrition_fat: 0" in content
        assert 'nutrition_source: "usda"' in content
        assert "nutrition_confidence: 0.8" in content

    def test_propagates_needs_review(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Review Me", ingredients=[
            {"amount": "1", "unit": "whole", "item": "mystery"},
        ])
        recipe_path = tmp_path / "Review Me.md"

        result = make_result(100, 1, 2, 3, needs_review=True)
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)

        assert "needs_review: true" in recipe_path.read_text()

    def test_defaults_null_servings_to_one(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "No Servings", servings="null", ingredients=[
            {"amount": "2", "unit": "cups", "item": "rice"},
        ])
        recipe_path = tmp_path / "No Servings.md"

        result = make_result(400, 8, 80, 1, "off", servings_used=1)
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)

        assert "nutrition_calories: 400" in recipe_path.read_text()

    def test_dry_run_does_not_write_file(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Dry Recipe", ingredients=[
            {"amount": "1", "unit": "cup", "item": "oats"},
        ])
        recipe_path = tmp_path / "Dry Recipe.md"
        original = recipe_path.read_text()

        result = make_result(300, 10, 50, 5, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=True)

        assert recipe_path.read_text() == original

    def test_skips_recipe_with_no_ingredients(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Empty Recipe", ingredients=None)
        recipe_path = tmp_path / "Empty Recipe.md"

        with patch("backfill_nutrition.calculate_recipe_nutrition") as mock_lookup:
            result = backfill_recipe(recipe_path, dry_run=False)
            mock_lookup.assert_not_called()
        assert result is False

    def test_overwrites_existing_numeric_values(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Force Recipe", nutrition_calories=450, ingredients=[
            {"amount": "1", "unit": "cup", "item": "butter"},
        ])
        recipe_path = tmp_path / "Force Recipe.md"

        result = make_result(900, 1, 0, 100, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 900" in content
        assert "nutrition_fat: 100" in content

    def test_rewrite_is_idempotent_no_duplicate_keys(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        content = '''---
title: "Already Backfilled"
source_url: "https://youtube.com/watch?v=abc"
nutrition_calories: 300
nutrition_protein: 10
nutrition_carbs: 40
nutrition_fat: 8
nutrition_source: "usda"
servings: 2
serving_size: "1 serving"
---

# Already Backfilled

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | cup | oats |

## Instructions

1. Cook it.
'''
        recipe_path = tmp_path / "Already Backfilled.md"
        recipe_path.write_text(content)

        result = make_result(250, 9, 35, 6, "usda")
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=result):
            backfill_recipe(recipe_path, dry_run=False)
            # Run a second time — must not introduce duplicate keys.
            backfill_recipe(recipe_path, dry_run=False)

        out = recipe_path.read_text()
        assert out.count('"1 serving"') == 1
        assert out.count("nutrition_calories:") == 1
        assert out.count("nutrition_confidence:") == 1
        assert "nutrition_calories: 250" in out

    def test_fix_duplicates_collapses_repeated_keys(self, tmp_path):
        from backfill_nutrition import fix_duplicates_in_file

        # Mirrors the real corruption: nutrition_calories appears twice.
        content = '''---
title: "Dupe Salad"
source_url: "https://feelgoodfoodie.net/x"
nutrition_calories: 144
nutrition_protein: 3
nutrition_carbs: 15
nutrition_fat: 11
nutrition_source: "ai"
servings: 8
nutrition_calories: 144
nutrition_carbs: 15
nutrition_fat: 11
---

# Dupe Salad

## Instructions

1. Toss.
'''
        recipe_path = tmp_path / "Dupe Salad.md"
        recipe_path.write_text(content)

        changed = fix_duplicates_in_file(recipe_path)
        out = recipe_path.read_text()
        assert changed is True
        assert out.count("nutrition_calories:") == 1
        assert out.count("nutrition_carbs:") == 1
        assert out.count("nutrition_fat:") == 1
        # Value preserved.
        assert "nutrition_calories: 144" in out

    def test_collect_skips_unreadable_files(self, tmp_path):
        from backfill_nutrition import collect_recipes_needing_backfill

        make_recipe_file(tmp_path, "Good Recipe", nutrition_calories=None)
        bad_file = tmp_path / "Bad Recipe.md"
        bad_file.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")

        recipes = collect_recipes_needing_backfill(tmp_path)
        names = [r.stem for r in recipes]
        assert "Good Recipe" in names
        assert "Bad Recipe" not in names
