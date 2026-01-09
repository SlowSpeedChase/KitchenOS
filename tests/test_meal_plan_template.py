"""Tests for meal plan template."""

from templates.meal_plan_template import generate_meal_plan_markdown


def test_includes_generate_button():
    """Template includes shopping list button."""
    result = generate_meal_plan_markdown(2026, 4)
    assert "```button" in result
    assert "Generate Shopping List" in result
    assert "kitchenos://generate-shopping-list?week=2026-W04" in result
