"""Tests for shopping list template."""

from templates.shopping_list_template import generate_shopping_list_markdown, generate_filename


def test_generates_markdown_with_header():
    """Template includes week in header."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["2 lbs chicken", "1 cup rice"]
    )
    assert "# Shopping List - Week 04" in result
    assert "[[2026-W04|Meal Plan]]" in result


def test_generates_checklist_items():
    """Template creates checkbox items."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["chicken", "rice"]
    )
    assert "- [ ] chicken" in result
    assert "- [ ] rice" in result


def test_includes_send_button():
    """Template includes button with correct week."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["item"]
    )
    assert "```button" in result
    assert "Send to Reminders" in result
    assert "kitchenos://send-to-reminders?week=2026-W04" in result


def test_generate_filename():
    """Filename uses week identifier."""
    assert generate_filename("2026-W04") == "2026-W04.md"


def test_empty_items_list():
    """Template handles empty items list."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=[]
    )
    assert "# Shopping List - Week 04" in result
    assert "## Items" in result
    # Should still have button
    assert "```button" in result


def test_items_section_header():
    """Template includes Items section header."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["test item"]
    )
    assert "## Items" in result


def test_template_includes_add_ingredients_button():
    """Shopping list template includes QuickAdd button."""
    from templates.shopping_list_template import generate_shopping_list_markdown

    result = generate_shopping_list_markdown('2026-W04', ['item1', 'item2'])

    assert '```button' in result
    assert 'Add Ingredients' in result
    assert 'QuickAdd: Add Ingredients to Shopping List' in result
