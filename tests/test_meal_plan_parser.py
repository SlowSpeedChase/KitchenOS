"""Tests for meal plan parser."""

import pytest
from datetime import date
from lib.meal_plan_parser import parse_meal_plan, extract_meals_for_day, insert_recipe_into_meal_plan, MealEntry


class TestParseMealPlan:
    """Test parsing full meal plan files."""

    def test_extracts_week_dates(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert len(result) == 7
        assert result[0]['date'] == date(2026, 1, 19)
        assert result[0]['day'] == 'Monday'

    def test_extracts_recipe_links(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Rich Fudgy Chocolate Cake]]
### Lunch
[[Caesar Salad]]
### Dinner
[[Pasta Aglio E Olio]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] == MealEntry('Rich Fudgy Chocolate Cake', 1)
        assert result[0]['lunch'] == MealEntry('Caesar Salad', 1)
        assert result[0]['dinner'] == MealEntry('Pasta Aglio E Olio', 1)

    def test_handles_empty_meals(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] is None
        assert result[0]['lunch'] is None
        assert result[0]['dinner'] == MealEntry('Pasta', 1)

    def test_handles_multiple_recipes_uses_first(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Eggs]]
[[Toast]]
### Lunch

### Dinner

### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        # Use first recipe only for simplicity
        assert result[0]['breakfast'] == MealEntry('Eggs', 1)

    def test_extracts_servings_multiplier(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]] x2
### Lunch
[[Caesar Salad]]
### Dinner
[[Pasta]] x3
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] == MealEntry('Pancakes', 2)
        assert result[0]['lunch'] == MealEntry('Caesar Salad', 1)
        assert result[0]['dinner'] == MealEntry('Pasta', 3)


class TestExtractMealsForDay:
    """Test extracting meals from a day section."""

    def test_extracts_all_meals(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch
[[Salad]]
### Dinner
[[Steak]]
### Notes
Some notes here
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == MealEntry('Pancakes', 1)
        assert result['lunch'] == MealEntry('Salad', 1)
        assert result['dinner'] == MealEntry('Steak', 1)

    def test_extracts_multiplier(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]] x2
### Lunch
[[Salad]]
### Dinner
[[Steak]] x3
### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == MealEntry('Pancakes', 2)
        assert result['lunch'] == MealEntry('Salad', 1)
        assert result['dinner'] == MealEntry('Steak', 3)

    def test_returns_none_for_empty(self):
        section = """## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner

### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] is None
        assert result['lunch'] is None
        assert result['dinner'] is None


class TestInsertRecipeIntoMealPlan:
    """Test inserting recipe links into meal plan markdown."""

    def test_inserts_into_empty_slot(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Monday", "Dinner", "Pasta Aglio E Olio")
        assert "### Dinner\n[[Pasta Aglio E Olio]]" in result

    def test_appends_to_existing_recipe(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner
[[Existing Recipe]]
### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Monday", "Dinner", "New Recipe")
        assert "[[Existing Recipe]]" in result
        assert "[[New Recipe]]" in result

    def test_inserts_into_correct_day(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

## Tuesday (Feb 10)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "Tuesday", "Breakfast", "Pancakes")
        # Tuesday breakfast should have the recipe
        assert "## Tuesday" in result
        # Monday dinner should still be empty
        monday_section = result.split("## Tuesday")[0]
        assert "[[Pancakes]]" not in monday_section

    def test_case_insensitive_day_and_meal(self):
        content = """# Meal Plan - Week 07

## Monday (Feb 9)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        result = insert_recipe_into_meal_plan(content, "monday", "dinner", "Test Recipe")
        assert "[[Test Recipe]]" in result

    def test_raises_on_invalid_day(self):
        content = "# Meal Plan\n## Monday (Feb 9)\n### Breakfast\n\n### Lunch\n\n### Dinner\n\n### Notes\n"
        with pytest.raises(ValueError, match="Day .* not found"):
            insert_recipe_into_meal_plan(content, "Funday", "Dinner", "Test")

    def test_raises_on_invalid_meal(self):
        content = "# Meal Plan\n## Monday (Feb 9)\n### Breakfast\n\n### Lunch\n\n### Dinner\n\n### Notes\n"
        with pytest.raises(ValueError, match="Meal .* not found"):
            insert_recipe_into_meal_plan(content, "Monday", "Brunch", "Test")
