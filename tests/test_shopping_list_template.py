"""Tests for shopping list template."""

from templates.shopping_list_template import generate_shopping_list_markdown, generate_filename


def test_generates_markdown_with_header():
    """Template includes week in header."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["2 lbs chicken", "1 cup rice"]
    )
    assert "# Shopping List - Jan 19 - Jan 25, 2026" in result
    assert "[[2026-W04|Meal Plan]]" in result


def test_header_is_the_date_range_not_a_week_number():
    """The title *is* the date range — "Week 04" identifies nothing to a human."""
    result = generate_shopping_list_markdown(week="2026-W04", items=["item"])
    assert "# Shopping List - Jan 19 - Jan 25, 2026" in result
    assert "Week 04" not in result


def test_header_falls_back_to_the_id_when_it_is_malformed():
    result = generate_shopping_list_markdown(week="not-a-week", items=["item"])
    assert "# Shopping List - not-a-week" in result


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
    assert "# Shopping List - Jan 19 - Jan 25, 2026" in result
    assert "## Need to purchase" in result
    # Should still have button
    assert "```button" in result


def test_inventory_matches_render_separately_without_purchase_checkboxes():
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["1 cup flour"],
        inventory_matches=[
            "0.33 cup shelled pistachios → Pistachios (1 ct) — verify amount and form"
        ],
    )

    assert "## Need to purchase" in result
    assert "- [ ] 1 cup flour" in result
    assert "## Inventory matches — verify" in result
    assert "- 0.33 cup shelled pistachios → Pistachios (1 ct)" in result
    assert "- [ ] 0.33 cup shelled pistachios" not in result


def test_template_records_generated_item_provenance_without_extra_checkboxes():
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["1 cup flour", "foil"],
        generated_items=["1 cup flour"],
    )

    assert "kitchenos-generated-items-v2:" in result
    assert result.count("- [ ] ") == 2


def test_items_section_header():
    """Template names the purchase section explicitly."""
    result = generate_shopping_list_markdown(
        week="2026-W04",
        items=["test item"]
    )
    assert "## Need to purchase" in result


def test_template_includes_add_ingredients_button():
    """Shopping list template includes QuickAdd button."""
    from templates.shopping_list_template import generate_shopping_list_markdown

    result = generate_shopping_list_markdown('2026-W04', ['item1', 'item2'])

    assert '```button' in result
    assert 'Add Ingredients' in result
    assert 'QuickAdd: Add Ingredients to Shopping List' in result
