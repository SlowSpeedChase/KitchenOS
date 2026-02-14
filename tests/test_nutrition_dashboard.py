"""Tests for nutrition dashboard generator."""

import tempfile
from datetime import date
from pathlib import Path

from lib.nutrition_dashboard import (
    get_recipe_nutrition,
    calculate_daily_nutrition,
    format_daily_summary_row,
    generate_dashboard,
)
from lib.nutrition import NutritionData
from lib.meal_plan_parser import MealEntry


def create_recipe_file(recipes_dir: Path, name: str, nutrition: dict) -> None:
    """Helper to create a recipe file with nutrition data."""
    content = f"""---
title: "{name}"
nutrition_calories: {nutrition.get('calories', 0)}
nutrition_protein: {nutrition.get('protein', 0)}
nutrition_carbs: {nutrition.get('carbs', 0)}
nutrition_fat: {nutrition.get('fat', 0)}
nutrition_source: "test"
---

# {name}
"""
    (recipes_dir / f"{name}.md").write_text(content)


def create_meal_plan(meal_plans_dir: Path, week: str, meals: dict) -> None:
    """Helper to create a meal plan file.

    Meal values can be plain strings ("Recipe") or "Recipe x2" for multiplier.
    """
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    dates = ['Jan 13', 'Jan 14', 'Jan 15', 'Jan 16', 'Jan 17', 'Jan 18', 'Jan 19']

    sections = []
    for i, (day, date_str) in enumerate(zip(days, dates)):
        day_meals = meals.get(day, {})
        section = f"## {day} ({date_str})\n\n"
        for meal_type in ['breakfast', 'lunch', 'dinner']:
            section += f"### {meal_type.capitalize()}\n\n"
            if meal_type in day_meals:
                value = day_meals[meal_type]
                # Support "Recipe x2" syntax in test helper
                if ' x' in value and value.split(' x')[-1].isdigit():
                    parts = value.rsplit(' x', 1)
                    section += f"[[{parts[0]}]] x{parts[1]}\n\n"
                else:
                    section += f"[[{value}]]\n\n"
        sections.append(section)

    content = f"""---
week: {week}
---

# Meal Plan {week}

{"".join(sections)}"""

    (meal_plans_dir / f"{week}.md").write_text(content)


def create_macros_file(vault_path: Path, targets: dict) -> None:
    """Helper to create My Macros.md file."""
    content = f"""---
calories: {targets.get('calories', 2000)}
protein: {targets.get('protein', 150)}
carbs: {targets.get('carbs', 200)}
fat: {targets.get('fat', 65)}
---

# My Daily Macros
"""
    (vault_path / "My Macros.md").write_text(content)


class TestGetRecipeNutrition:
    def test_loads_nutrition_from_recipe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            create_recipe_file(recipes_dir, "Test Recipe", {
                'calories': 500,
                'protein': 30,
                'carbs': 50,
                'fat': 20
            })

            nutrition = get_recipe_nutrition("Test Recipe", recipes_dir)

            assert nutrition is not None
            assert nutrition.calories == 500
            assert nutrition.protein == 30

    def test_returns_none_for_missing_recipe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            nutrition = get_recipe_nutrition("Missing Recipe", recipes_dir)
            assert nutrition is None

    def test_returns_none_for_recipe_without_nutrition(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            (recipes_dir / "No Nutrition.md").write_text("""---
title: "No Nutrition"
---

# No Nutrition
""")

            nutrition = get_recipe_nutrition("No Nutrition", recipes_dir)
            assert nutrition is None


class TestCalculateDailyNutrition:
    def test_sums_all_meals(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            create_recipe_file(recipes_dir, "Breakfast", {
                'calories': 300, 'protein': 10, 'carbs': 40, 'fat': 10
            })
            create_recipe_file(recipes_dir, "Lunch", {
                'calories': 500, 'protein': 30, 'carbs': 50, 'fat': 15
            })
            create_recipe_file(recipes_dir, "Dinner", {
                'calories': 700, 'protein': 40, 'carbs': 60, 'fat': 25
            })

            day_data = {
                'breakfast': 'Breakfast',
                'lunch': 'Lunch',
                'dinner': 'Dinner'
            }

            total, missing = calculate_daily_nutrition(day_data, recipes_dir)

            assert total.calories == 1500
            assert total.protein == 80
            assert len(missing) == 0

    def test_multiplies_nutrition_by_servings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            create_recipe_file(recipes_dir, "Breakfast", {
                'calories': 300, 'protein': 10, 'carbs': 40, 'fat': 10
            })
            create_recipe_file(recipes_dir, "Dinner", {
                'calories': 500, 'protein': 30, 'carbs': 50, 'fat': 15
            })

            day_data = {
                'breakfast': MealEntry('Breakfast', 2),
                'lunch': None,
                'dinner': MealEntry('Dinner', 1)
            }

            total, missing = calculate_daily_nutrition(day_data, recipes_dir)

            # Breakfast 300*2 + Dinner 500*1 = 1100
            assert total.calories == 1100
            assert total.protein == 50  # 10*2 + 30*1
            assert len(missing) == 0

    def test_tracks_missing_recipes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            recipes_dir = Path(tmp_dir)
            create_recipe_file(recipes_dir, "Breakfast", {
                'calories': 300, 'protein': 10, 'carbs': 40, 'fat': 10
            })

            day_data = {
                'breakfast': 'Breakfast',
                'lunch': 'Missing Lunch',
                'dinner': None
            }

            total, missing = calculate_daily_nutrition(day_data, recipes_dir)

            assert total.calories == 300
            assert 'Missing Lunch' in missing


class TestFormatDailySummaryRow:
    def test_formats_row_with_data(self):
        actual = NutritionData(calories=1850, protein=140, carbs=180, fat=60)
        targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)

        row = format_daily_summary_row("Monday", actual, targets, has_meals=True)

        assert "Monday" in row
        assert "1850 / 2000" in row
        assert "140 / 150g" in row

    def test_formats_row_without_meals(self):
        targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)
        row = format_daily_summary_row("Monday", None, targets, has_meals=False)

        assert "Monday" in row
        assert "—" in row


class TestGenerateDashboard:
    def test_generates_complete_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            recipes_dir = vault_path / "Recipes"
            meal_plans_dir = vault_path / "Meal Plans"
            recipes_dir.mkdir()
            meal_plans_dir.mkdir()

            # Create macro targets
            create_macros_file(vault_path, {
                'calories': 2000,
                'protein': 150,
                'carbs': 200,
                'fat': 65
            })

            # Create recipe
            create_recipe_file(recipes_dir, "Test Recipe", {
                'calories': 500,
                'protein': 25,
                'carbs': 50,
                'fat': 20
            })

            # Create meal plan
            create_meal_plan(meal_plans_dir, "2026-W03", {
                'Monday': {'breakfast': 'Test Recipe', 'lunch': 'Test Recipe', 'dinner': 'Test Recipe'}
            })

            markdown, warnings = generate_dashboard("2026-W03", vault_path)

            assert "# Nutrition Dashboard" in markdown
            assert "2026-W03" in markdown
            assert "Monday" in markdown
            assert "1500 / 2000" in markdown  # 3 meals * 500 cal

    def test_dashboard_with_servings_multiplier(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            recipes_dir = vault_path / "Recipes"
            meal_plans_dir = vault_path / "Meal Plans"
            recipes_dir.mkdir()
            meal_plans_dir.mkdir()

            create_macros_file(vault_path, {
                'calories': 2000, 'protein': 150, 'carbs': 200, 'fat': 65
            })

            create_recipe_file(recipes_dir, "Test Recipe", {
                'calories': 500, 'protein': 25, 'carbs': 50, 'fat': 20
            })

            # Use x2 multiplier for dinner
            create_meal_plan(meal_plans_dir, "2026-W03", {
                'Monday': {'breakfast': 'Test Recipe', 'dinner': 'Test Recipe x2'}
            })

            markdown, warnings = generate_dashboard("2026-W03", vault_path)

            # breakfast 500 + dinner 500*2 = 1500
            assert "1500 / 2000" in markdown

    def test_handles_missing_macros_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_path = Path(tmp_dir)
            meal_plans_dir = vault_path / "Meal Plans"
            recipes_dir = vault_path / "Recipes"
            meal_plans_dir.mkdir()
            recipes_dir.mkdir()

            create_meal_plan(meal_plans_dir, "2026-W03", {})

            markdown, warnings = generate_dashboard("2026-W03", vault_path)

            assert any("My Macros.md not found" in w for w in warnings)
