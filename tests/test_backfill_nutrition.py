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
        assert 'nutrition_source: "usda"' in content

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
        assert "nutrition_calories: 400" in content   # 400 / 1 = 400

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
            result = backfill_recipe(recipe_path, dry_run=False)
            mock_lookup.assert_not_called()
        assert result is False
