"""Tests for clean_ingredients.py — the ingredient-table migration."""
from clean_ingredients import clean_recipe, render_table

RECIPE = """---
title: "Messy"
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| ½ | cup | flour |
| 1 | whole | ¾ cup greek yogurt |
| 1 | whole | salt to taste |
| °f oil |  |  |
| 1 | whole | maple syrup |

## Instructions

1. Mix.
"""


def test_preview_does_not_write(tmp_path):
    p = tmp_path / "Messy.md"
    p.write_text(RECIPE)
    original = p.read_text()
    cleaned, changed = clean_recipe(p, apply=False)
    assert changed
    assert p.read_text() == original  # untouched


def test_apply_rewrites_table_with_decimals(tmp_path):
    p = tmp_path / "Messy.md"
    p.write_text(RECIPE)
    clean_recipe(p, apply=True)
    out = p.read_text()

    # Decimals, not fractions
    assert "| 0.5 | cup | flour |" in out
    # Amount recovered from the item
    assert "| 0.75 | cup | greek yogurt |" in out
    # Garnish kept but as a negligible (to taste) unit
    assert "salt to taste" in out
    # Non-ingredient row dropped entirely
    assert "°f oil" not in out
    # Flagged-but-kept item still present
    assert "maple syrup" in out
    # Instructions section preserved
    assert "## Instructions" in out
    # Backup created
    assert (tmp_path / ".history").exists()


def test_render_table_excludes_dropped(tmp_path):
    from lib.ingredient_cleaner import clean_ingredients
    rows = clean_ingredients([
        {"amount": "1", "unit": "cup", "item": "rice"},
        {"amount": "°f oil", "unit": "", "item": ""},
    ])
    table = render_table(rows)
    assert "rice" in table
    assert "°f oil" not in table
    assert table.startswith("| Amount | Unit | Ingredient |")
