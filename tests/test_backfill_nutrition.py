"""Tests for backfill_nutrition.py"""
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

        # calculate_recipe_nutrition already returns per-serving values internally,
        # so the mock result IS the final per-serving value (no further division).
        mock_result = NutritionLookupResult(
            NutritionData(calories=150, protein=4, carbs=30, fat=0),
            source="usda"
        )
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=mock_result):
            updated = backfill_recipe(recipe_path, dry_run=False)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 150" in content
        assert "nutrition_protein: 4" in content
        assert "nutrition_carbs: 30" in content
        assert "nutrition_fat: 0" in content
        assert 'nutrition_source: "usda"' in content

    def test_defaults_null_servings_to_one(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "No Servings", servings="null", ingredients=[
            {"amount": "2", "unit": "cups", "item": "rice"},
        ])
        recipe_path = tmp_path / "No Servings.md"

        # Mock returns per-serving value (calculate_recipe_nutrition already divided by 1)
        mock_result = NutritionLookupResult(
            NutritionData(calories=400, protein=8, carbs=80, fat=1),
            source="ai"
        )
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=mock_result):
            backfill_recipe(recipe_path, dry_run=False)

        content = recipe_path.read_text()
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
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=mock_result):
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

    def test_force_overwrites_existing_numeric_values(self, tmp_path):
        from backfill_nutrition import backfill_recipe

        make_recipe_file(tmp_path, "Force Recipe", nutrition_calories=450, ingredients=[
            {"amount": "1", "unit": "cup", "item": "butter"},
        ])
        recipe_path = tmp_path / "Force Recipe.md"

        mock_result = NutritionLookupResult(
            NutritionData(calories=900, protein=1, carbs=0, fat=100),
            source="nutritionix"
        )
        with patch("backfill_nutrition.calculate_recipe_nutrition", return_value=mock_result):
            updated = backfill_recipe(recipe_path, dry_run=False, force=True)

        assert updated is True
        content = recipe_path.read_text()
        assert "nutrition_calories: 900" in content
        assert "nutrition_fat: 100" in content

    def test_collect_skips_unreadable_files(self, tmp_path):
        from backfill_nutrition import collect_recipes_needing_backfill

        make_recipe_file(tmp_path, "Good Recipe", nutrition_calories=None)
        # Create a file that will cause parse_recipe_file to raise
        bad_file = tmp_path / "Bad Recipe.md"
        bad_file.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")

        # Should not raise; should return only the good recipe
        recipes = collect_recipes_needing_backfill(tmp_path)
        names = [r.stem for r in recipes]
        assert "Good Recipe" in names
        assert "Bad Recipe" not in names
