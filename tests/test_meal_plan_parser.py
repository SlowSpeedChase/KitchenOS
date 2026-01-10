"""Tests for meal plan parser."""

import pytest
from datetime import date
from lib.meal_plan_parser import parse_meal_plan, extract_meals_for_day


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

        assert result[0]['breakfast'] == 'Rich Fudgy Chocolate Cake'
        assert result[0]['lunch'] == 'Caesar Salad'
        assert result[0]['dinner'] == 'Pasta Aglio E Olio'

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
        assert result[0]['dinner'] == 'Pasta'

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
        assert result[0]['breakfast'] == 'Eggs'


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

        assert result['breakfast'] == 'Pancakes'
        assert result['lunch'] == 'Salad'
        assert result['dinner'] == 'Steak'

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
