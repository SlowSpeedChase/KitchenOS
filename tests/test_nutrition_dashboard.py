"""Tests for nutrition dashboard generator."""

import tempfile
from datetime import date
from pathlib import Path

from lib.nutrition_dashboard import (
    get_recipe_nutrition,
    calculate_daily_nutrition,
    format_daily_summary_row,
    generate_dashboard,
    compute_dashboard,
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
        for meal_type in ['breakfast', 'lunch', 'snack', 'dinner']:
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


def _dashboard_vault(tmp_dir, meals, recipe_nutrition=None):
    """A vault with targets, one 500-kcal recipe, and the given meal plan."""
    vault_path = Path(tmp_dir)
    recipes_dir = vault_path / "Recipes"
    meal_plans_dir = vault_path / "Meal Plans"
    recipes_dir.mkdir()
    meal_plans_dir.mkdir()
    create_macros_file(vault_path, {'calories': 2000, 'protein': 150,
                                    'carbs': 200, 'fat': 65})
    create_recipe_file(recipes_dir, "Test Recipe",
                       recipe_nutrition or {'calories': 500, 'protein': 25,
                                            'carbs': 50, 'fat': 20})
    create_meal_plan(meal_plans_dir, "2026-W03", meals)
    return vault_path


FULL_DAY = {'breakfast': 'Test Recipe', 'lunch': 'Test Recipe',
            'snack': 'Test Recipe', 'dinner': 'Test Recipe'}


class TestUnplannedWeeksAreNotStarvationWeeks:
    """An empty calendar is not a diet.

    The live 2026-W31 dashboard reported 715 kcal/day against a 2300 target
    because a single Sunday dinner was the entire week. Averaged over "days
    with any meal on them", one filled slot counts as a day's eating, so the
    less you plan the more alarming the number gets.
    """

    def test_reports_how_much_of_the_week_is_planned(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _dashboard_vault(tmp, {'Monday': {'dinner': 'Test Recipe'}})
            data = compute_dashboard("2026-W03", vault)
            assert data["days_planned"] == 1
            assert data["days_total"] == 7
            assert data["slots_planned"] == 1
            assert data["slots_total"] == 28

    def test_warns_that_averages_cover_only_planned_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _dashboard_vault(tmp, {'Monday': {'dinner': 'Test Recipe'}})
            data = compute_dashboard("2026-W03", vault)
            assert any("1 of 7" in w for w in data["warnings"]), data["warnings"]

    def test_a_fully_planned_week_needs_no_caveat(self):
        with tempfile.TemporaryDirectory() as tmp:
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                    'Friday', 'Saturday', 'Sunday']
            vault = _dashboard_vault(tmp, {d: dict(FULL_DAY) for d in days})
            data = compute_dashboard("2026-W03", vault)
            assert data["days_planned"] == 7
            assert data["slots_planned"] == 28
            assert not any("of 7 day" in w for w in data["warnings"]), data["warnings"]

    def test_each_day_reports_how_many_slots_it_filled(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _dashboard_vault(tmp, {
                'Monday': {'dinner': 'Test Recipe'},
                'Tuesday': dict(FULL_DAY),
            })
            days = {d["day"]: d for d in compute_dashboard("2026-W03", vault)["days"]}
            assert days["Monday"]["slots_filled"] == 1
            assert days["Tuesday"]["slots_filled"] == 4
            assert days["Wednesday"]["slots_filled"] == 0

    def test_averages_still_describe_the_planned_days(self):
        """The caveat is added; the arithmetic is not silently redefined."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = _dashboard_vault(tmp, {'Monday': {'dinner': 'Test Recipe'}})
            data = compute_dashboard("2026-W03", vault)
            assert data["averages"]["calories"] == 500


class TestNullCaloriesAreMissingNotZero:
    """A recipe with the key present and empty must not read as 0 kcal.

    `int(fm.get('nutrition_calories', 0) or 0)` turned a null into a zero, so a
    recipe with no macros silently *lowered* a day's total instead of being
    reported as missing data.
    """

    def test_null_calories_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipes_dir = Path(tmp)
            (recipes_dir / "Blank.md").write_text(
                '---\ntitle: "Blank"\nnutrition_calories: null\n'
                'nutrition_protein: null\n---\n\n# Blank\n', encoding="utf-8")
            assert get_recipe_nutrition("Blank", recipes_dir) is None

    def test_zero_calories_is_still_a_real_answer(self):
        """Zero is a value (black coffee); null is an absence. Don't conflate."""
        with tempfile.TemporaryDirectory() as tmp:
            recipes_dir = Path(tmp)
            create_recipe_file(recipes_dir, "Water", {'calories': 0, 'protein': 0,
                                                      'carbs': 0, 'fat': 0})
            assert get_recipe_nutrition("Water", recipes_dir) == NutritionData(
                calories=0, protein=0, carbs=0, fat=0)

    def test_a_null_recipe_is_reported_missing_not_counted_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _dashboard_vault(tmp, {'Monday': {'dinner': 'Ghost'}})
            (vault / "Recipes" / "Ghost.md").write_text(
                '---\ntitle: "Ghost"\nnutrition_calories: null\n---\n\n# Ghost\n',
                encoding="utf-8")
            data = compute_dashboard("2026-W03", vault)
            assert any("Ghost" in w for w in data["warnings"]), data["warnings"]
