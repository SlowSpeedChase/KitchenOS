"""Tests for meal plan template generation."""

import pytest
from templates.meal_plan_template import generate_meal_plan_markdown


def test_includes_generate_button():
    """Template includes shopping list button."""
    result = generate_meal_plan_markdown(2026, 4)
    assert "```button" in result
    assert "Generate Shopping List" in result
    assert "kitchenos://generate-shopping-list?week=2026-W04" in result


class TestGenerateMealPlanMarkdown:
    """Test meal plan markdown generation."""

    def test_includes_snack_section(self):
        result = generate_meal_plan_markdown(2026, 4)

        # Check Monday has snack section
        assert '### Snack' in result

        # Verify order: Lunch before Snack before Dinner
        lunch_pos = result.find('### Lunch')
        snack_pos = result.find('### Snack')
        dinner_pos = result.find('### Dinner')

        assert lunch_pos < snack_pos < dinner_pos
