"""Tests for the Use-It-Up waste suggester."""

from datetime import date, timedelta

from lib.inventory import InventoryItem
from lib import use_it_up


TODAY = date(2026, 6, 24)
SOON = (TODAY + timedelta(days=1)).isoformat()   # within the 3-day threshold
LATER = (TODAY + timedelta(days=30)).isoformat()
EXPIRED = (TODAY - timedelta(days=1)).isoformat()       # within the grace window
LONG_EXPIRED = (TODAY - timedelta(days=21)).isoformat()  # assumed already used

RECIPES = [
    {"name": "Strawberry Spinach Salad",
     "ingredient_items": ["strawberries", "spinach", "olive oil", "feta"]},
    {"name": "Banana Bread",
     "ingredient_items": ["bananas", "flour", "butter", "sugar"]},
    {"name": "Plain Toast",
     "ingredient_items": ["bread", "butter"]},
]


def _item(name, expires, category="produce"):
    return InventoryItem(name=name, quantity=1, unit="ct",
                         category=category, expires=expires)


class TestAtRisk:
    def test_only_expiring_or_expired(self):
        items = [_item("Strawberries", SOON), _item("Carrots", LATER)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Strawberries"]

    def test_excludes_staples(self):
        # Butter is a staple — even expiring, it must not be flagged.
        items = [_item("Salted Butter", SOON, category="dairy"),
                 _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]

    def test_expired_sorts_before_soon(self):
        items = [_item("Spinach", SOON), _item("Strawberries", EXPIRED)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [s for s, _ in flagged] == ["expired", "soon"]

    def test_long_expired_dropped(self):
        # Expired weeks ago — assumed already used; not actionable noise.
        items = [_item("Old Berries", LONG_EXPIRED), _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]

    def test_milk_is_a_staple_not_flagged(self):
        items = [_item("Whole Milk", SOON, category="dairy"), _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]


class TestSuggest:
    def test_ranks_by_at_risk_items_used(self):
        items = [_item("Strawberries", SOON), _item("Spinach", SOON),
                 _item("Bananas", SOON)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        names = [s["recipe"] for s in result["suggestions"]]
        # Salad uses 2 at-risk items (strawberries + spinach); banana bread uses 1.
        assert names[0] == "Strawberry Spinach Salad"
        assert "Banana Bread" in names

    def test_staple_assumed_available(self):
        # Banana bread needs flour/butter/sugar (staples) + bananas (at-risk).
        # It should still surface — staples don't block the suggestion.
        items = [_item("Bananas", SOON)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        assert any(s["recipe"] == "Banana Bread" for s in result["suggestions"])

    def test_empty_when_nothing_at_risk(self):
        items = [_item("Carrots", LATER)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        assert result == {"at_risk": [], "suggestions": []}


class TestRender:
    def test_markdown_lists_at_risk_and_recipes(self):
        items = [_item("Strawberries", SOON)]
        md = use_it_up.render_markdown(use_it_up.suggest(items, RECIPES, today=TODAY))
        assert "# 🥗 Use It Up" in md
        assert "Strawberries" in md
        assert "[[Strawberry Spinach Salad]]" in md

    def test_markdown_all_clear(self):
        md = use_it_up.render_markdown({"at_risk": [], "suggestions": []})
        assert "good shape" in md
