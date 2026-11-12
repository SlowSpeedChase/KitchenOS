"""Static contract pins for the planner's shopping-list confirmation UI."""

from pathlib import Path


def test_planner_uses_purchase_items_and_line_displays():
    html = (Path(__file__).resolve().parents[1] / "templates" / "meal_planner.html").read_text()

    assert "pendingShoppingPreview.purchase_items" in html
    assert "line.needed_display" in html
    assert "line.to_buy_display" in html
    assert "inventory_matches: matches" in html
    assert "item: line.matched_inventory.item" in html
