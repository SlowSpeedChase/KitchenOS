"""Tests for shopping list generator."""

import pytest
from pathlib import Path
from unittest.mock import patch

from lib.shopping_list_generator import (
    generate_shopping_list,
    parse_week_string,
    extract_recipe_links,
    slugify,
    MEAL_PLANS_PATH,
)


def test_generate_shopping_list_returns_dict():
    """Generator returns structured result."""
    result = generate_shopping_list("2026-W04")
    assert isinstance(result, dict)
    # Either success with items or failure with error
    assert "success" in result
    if result["success"]:
        assert "items" in result
    else:
        assert "error" in result


def test_generate_shopping_list_invalid_format():
    """Invalid week format returns error."""
    result = generate_shopping_list("2026-04")
    assert result["success"] is False
    assert "Invalid week format" in result["error"]


def test_parse_week_string_valid():
    """Valid week string returns path."""
    # Only works if file exists - this is an integration test
    try:
        path = parse_week_string("2026-W04")
        assert path == MEAL_PLANS_PATH / "2026-W04.md"
    except ValueError:
        pytest.skip("No meal plan for 2026-W04")


def test_parse_week_string_invalid_format():
    """Invalid format raises ValueError."""
    with pytest.raises(ValueError, match="Invalid week format"):
        parse_week_string("2026-04")


def test_parse_week_string_missing_file():
    """Missing file raises ValueError."""
    with pytest.raises(ValueError, match="Meal plan not found"):
        parse_week_string("1999-W01")


def test_extract_recipe_links():
    """Extracts wiki links from content."""
    content = "# Meal\n## Monday\n[[pasta]]\n[[salad]]\n"

    with patch.object(Path, 'read_text', return_value=content):
        links = extract_recipe_links(Path("/fake/path.md"))

    assert links == ["pasta", "salad"]


def test_extract_recipe_links_empty():
    """Returns empty list when no links."""
    content = "# Meal\n## Monday\nNo recipes yet\n"

    with patch.object(Path, 'read_text', return_value=content):
        links = extract_recipe_links(Path("/fake/path.md"))

    assert links == []


def test_slugify():
    """Slugify converts text to lowercase slug."""
    assert slugify("Pasta Aglio e Olio") == "pasta-aglio-e-olio"
    assert slugify("Lu Rou Fan") == "lu-rou-fan"


def test_slugify_special_chars():
    """Slugify handles special characters."""
    assert slugify("Test!@#Recipe") == "test-recipe"
    assert slugify("--multiple---dashes--") == "multiple-dashes"


def test_generate_shopping_list_no_recipes():
    """Returns error when meal plan has no recipes."""
    with patch('lib.shopping_list_generator.parse_week_string') as mock_parse:
        mock_path = Path("/fake/plan.md")
        mock_parse.return_value = mock_path

        with patch.object(Path, 'read_text', return_value="# Empty Meal Plan\n"):
            result = generate_shopping_list("2026-W04")

    assert result["success"] is False
    assert "No recipes found" in result["error"]
