"""Tests for shopping list generator."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from lib.shopping_list_generator import (
    generate_shopping_list,
    parse_week_string,
    extract_recipe_links,
    slugify,
    find_recipe_file,
    extract_ingredient_table,
    load_recipe_ingredients,
    parse_shopping_list_file,
    MEAL_PLANS_PATH,
    RECIPES_PATH,
    SHOPPING_LISTS_PATH,
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


# Tests for find_recipe_file

def test_find_recipe_file_exact_match():
    """Finds recipe by exact name."""
    with patch.object(Path, 'exists', return_value=True):
        result = find_recipe_file("Pasta Carbonara")
        assert result == RECIPES_PATH / "Pasta Carbonara.md"


def test_find_recipe_file_returns_none_when_not_found():
    """Returns None when recipe not found."""
    with patch.object(Path, 'exists', return_value=False):
        with patch.object(Path, 'glob', return_value=[]):
            result = find_recipe_file("Nonexistent Recipe")
            assert result is None


def test_find_recipe_file_slugified_match():
    """Finds recipe via slugified name matching."""
    mock_file = MagicMock(spec=Path)
    mock_file.stem = "pasta-aglio-e-olio"

    with patch.object(Path, 'exists', return_value=False):
        with patch.object(Path, 'glob', return_value=[mock_file]):
            result = find_recipe_file("Pasta Aglio e Olio")
            assert result == mock_file


# Tests for extract_ingredient_table

def test_extract_ingredient_table_finds_section():
    """Extracts ingredient table from body."""
    body = "## Description\n\nSome text\n\n## Ingredients\n\n| Amount | Unit | Item |\n|--------|------|------|\n| 1 | cup | rice |\n\n## Instructions"
    result = extract_ingredient_table(body)
    assert "| 1 | cup | rice |" in result


def test_extract_ingredient_table_empty_when_no_section():
    """Returns empty string when no ingredients section."""
    body = "## Description\nSome text\n## Instructions\n"
    result = extract_ingredient_table(body)
    assert result == ""


def test_extract_ingredient_table_handles_end_of_file():
    """Extracts ingredients when section is at end of file."""
    body = "## Description\n\nSome text\n\n## Ingredients\n\n| Amount | Unit | Item |\n| 2 | tbsp | oil |"
    result = extract_ingredient_table(body)
    assert "| 2 | tbsp | oil |" in result


def test_extract_ingredient_table_case_insensitive():
    """Section heading matching is case insensitive."""
    body = "## description\n\n## ingredients\n\n| 1 | cup | flour |"
    result = extract_ingredient_table(body)
    assert "| 1 | cup | flour |" in result


# Tests for load_recipe_ingredients

def test_load_recipe_ingredients_not_found():
    """Returns empty list and warning when recipe not found."""
    with patch('lib.shopping_list_generator.find_recipe_file', return_value=None):
        ingredients, warning = load_recipe_ingredients("Missing Recipe")
        assert ingredients == []
        assert "Recipe not found" in warning


def test_load_recipe_ingredients_no_table():
    """Returns empty list when recipe has no ingredients table."""
    mock_file = MagicMock(spec=Path)
    mock_file.read_text.return_value = "---\ntitle: Test\n---\n## Description\nNo ingredients here"

    with patch('lib.shopping_list_generator.find_recipe_file', return_value=mock_file):
        with patch('lib.shopping_list_generator.parse_recipe_file', return_value={'body': '## Description\nNo ingredients'}):
            ingredients, warning = load_recipe_ingredients("Test Recipe")
            assert ingredients == []
            assert "No ingredients table" in warning


def test_load_recipe_ingredients_success():
    """Successfully loads ingredients from recipe."""
    mock_file = MagicMock(spec=Path)
    mock_file.read_text.return_value = "content"

    body_with_table = "## Ingredients\n\n| Amount | Unit | Item |\n|--------|------|------|\n| 1 | cup | rice |"
    parsed_ingredients = [{"amount": "1", "unit": "cup", "item": "rice"}]

    with patch('lib.shopping_list_generator.find_recipe_file', return_value=mock_file):
        with patch('lib.shopping_list_generator.parse_recipe_file', return_value={'body': body_with_table}):
            with patch('lib.shopping_list_generator.parse_ingredient_table', return_value=parsed_ingredients):
                ingredients, warning = load_recipe_ingredients("Test Recipe")
                assert ingredients == parsed_ingredients
                assert warning is None


# Tests for parse_shopping_list_file

def test_parse_shopping_list_extracts_unchecked():
    """Parser extracts only unchecked items."""
    content = """# Shopping List
- [ ] chicken
- [x] rice
- [ ] onions
"""

    with patch.object(Path, 'exists', return_value=True):
        with patch.object(Path, 'read_text', return_value=content):
            result = parse_shopping_list_file("2026-W04")

    assert result['success'] is True
    assert result['items'] == ['chicken', 'onions']
    assert result['skipped'] == 1


def test_parse_shopping_list_not_found():
    """Returns error when shopping list file not found."""
    with patch.object(Path, 'exists', return_value=False):
        result = parse_shopping_list_file("1999-W01")

    assert result['success'] is False
    assert "Shopping list not found" in result['error']


def test_parse_shopping_list_case_insensitive_check():
    """Handles uppercase X in checked items."""
    content = """# Shopping List
- [ ] item1
- [X] item2
- [x] item3
"""

    with patch.object(Path, 'exists', return_value=True):
        with patch.object(Path, 'read_text', return_value=content):
            result = parse_shopping_list_file("2026-W04")

    assert result['success'] is True
    assert result['items'] == ['item1']
    assert result['skipped'] == 2


def test_parse_shopping_list_empty_items_skipped():
    """Empty checkbox items are not included."""
    content = """# Shopping List
- [ ]
- [ ] chicken
- [ ]
"""

    with patch.object(Path, 'exists', return_value=True):
        with patch.object(Path, 'read_text', return_value=content):
            result = parse_shopping_list_file("2026-W04")

    assert result['success'] is True
    assert result['items'] == ['chicken']
