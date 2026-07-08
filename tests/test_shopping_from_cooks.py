from pathlib import Path

import lib.shopping_list_generator as slg
from lib import serving_ledger as sl

RECIPE_MD = """---
title: Chili
servings: 4
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | dried beans |
| 1 | lb | ground beef |
"""


def _setup_vault(tmp_vault, monkeypatch):
    recipes = tmp_vault / "Recipes"
    plans = tmp_vault / "Meal Plans"
    recipes.mkdir(parents=True)
    plans.mkdir(parents=True)
    (recipes / "Chili.md").write_text(RECIPE_MD, encoding="utf-8")
    # Module constants are captured at import time — repoint them.
    monkeypatch.setattr(slg, "RECIPES_PATH", recipes)
    monkeypatch.setattr(slg, "MEAL_PLANS_PATH", plans)
    return recipes, plans


def test_ledger_week_scales_fractionally(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W28.md").write_text("# plan\n", encoding="utf-8")
    sl.create_cook(recipe="Chili", week="2026-W28", scale=1.5,
                   servings_produced=6.0, date="2026-07-07", meal="dinner")
    result = slg.generate_shopping_list("2026-W28")
    assert result["success"] is True
    assert result["source"] == "ledger"
    assert any("3 cup" in i and "dried beans" in i for i in result["items"])


def test_freezer_only_week_produces_empty_list(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W29.md").write_text("# plan\n", encoding="utf-8")
    cook = sl.create_cook(recipe="Chili", week="2026-W28", scale=1.0,
                          servings_produced=4.0,
                          date="2026-07-07", meal="dinner")
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    sl.move_servings(frozen["id"], 2.0, "slot", date="2026-07-14", meal="dinner")
    result = slg.generate_shopping_list("2026-W29")
    assert result["success"] is True
    assert result["source"] == "ledger"
    assert result["items"] == []


def test_emptied_ledger_week_has_no_phantom_links(tmp_db, tmp_vault, monkeypatch):
    """Deleting the last cook regenerates an empty skeleton, so the link-scan
    grocery fallback no longer sees the deleted recipe."""
    from lib import week_view
    _setup_vault(tmp_vault, monkeypatch)
    cook = sl.create_cook(recipe="Chili", week="2026-W28", scale=1.5,
                          servings_produced=6.0,
                          date="2026-07-07", meal="dinner")
    week_view.write_week_markdown("2026-W28")
    sl.delete_cook(cook["id"])
    week_view.write_week_markdown("2026-W28")
    result = slg.generate_shopping_list("2026-W28")
    # The stale card would have produced success=True with Chili's
    # ingredients; the empty skeleton has no links at all.
    assert result["success"] is False
    assert "No recipes found" in result["error"]
    assert not result.get("items")


def test_legacy_week_falls_back_to_link_scan(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W20.md").write_text(
        "## Monday (May 11)\n### Dinner\n[[Chili]] x2\n", encoding="utf-8")
    result = slg.generate_shopping_list("2026-W20")
    assert result["success"] is True
    assert result["source"] == "links"
    assert any("4 cup" in i for i in result["items"])
