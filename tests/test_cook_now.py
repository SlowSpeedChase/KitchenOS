"""Tests for the Cook-Now coverage suggester."""

from datetime import date, timedelta

from lib.inventory import InventoryItem
from lib import cook_now


TODAY = date(2026, 6, 24)
SOON = (TODAY + timedelta(days=1)).isoformat()   # within the 3-day threshold
LATER = (TODAY + timedelta(days=30)).isoformat()

RECIPES = [
    {"name": "Chicken Dinner",
     "ingredient_items": ["boneless skinless chicken breasts", "rice", "broccoli"]},
    {"name": "Strawberry Spinach Salad",
     "ingredient_items": ["strawberries", "spinach", "olive oil", "feta"]},
    {"name": "Plain Rice",
     "ingredient_items": ["rice", "salt", "olive oil"]},
]


def _item(name, expires=LATER, category="produce"):
    return InventoryItem(name=name, quantity=1, unit="ct",
                         category=category, expires=expires)


class TestGenerate:
    def test_ranks_by_coverage(self):
        # Have chicken + rice + broccoli → Chicken Dinner is fully covered.
        items = [_item("Chicken"), _item("Rice"), _item("Broccoli")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        names = [r["recipe"] for r in result["recipes"]]
        assert names[0] == "Chicken Dinner"
        top = result["recipes"][0]
        assert top["have"] == 3 and top["total"] == 3
        assert top["coverage"] == 1.0 and top["missing"] == []

    def test_limit_respected(self):
        items = [_item("Rice")]
        result = cook_now.generate(items, RECIPES, today=TODAY, limit=2)
        assert len(result["recipes"]) <= 2

    def test_staples_count_as_on_hand_never_missing(self):
        # Plain Rice = rice (have) + salt + olive oil (both staples). With rice
        # on hand it is fully covered and nothing is listed missing.
        items = [_item("Rice")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        rice = next(r for r in result["recipes"] if r["recipe"] == "Plain Rice")
        assert rice["coverage"] == 1.0
        assert rice["missing"] == []

    def test_fuzzy_match(self):
        # Inventory "Chicken" satisfies "boneless skinless chicken breasts".
        items = [_item("Chicken")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        chicken = next(r for r in result["recipes"] if r["recipe"] == "Chicken Dinner")
        assert "boneless skinless chicken breasts" not in chicken["missing"]

    def test_missing_lists_nonstaple_unmatched(self):
        # Have only chicken. Rice is a pantry staple (assumed on hand), so only
        # broccoli — non-staple and unmatched — is listed missing.
        items = [_item("Chicken")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        chicken = next(r for r in result["recipes"] if r["recipe"] == "Chicken Dinner")
        assert chicken["missing"] == ["broccoli"]
        assert chicken["have"] == 2 and chicken["total"] == 3

    def test_at_risk_flag(self):
        # Spinach expiring soon and used by the salad → flagged.
        items = [_item("Spinach", expires=SOON), _item("Strawberries")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        salad = next(r for r in result["recipes"] if r["recipe"] == "Strawberry Spinach Salad")
        assert salad["at_risk"] is True
        chicken = next(r for r in result["recipes"] if r["recipe"] == "Chicken Dinner")
        assert chicken["at_risk"] is False


class TestRender:
    def test_markdown_structure(self):
        items = [_item("Rice")]
        md = cook_now.render_markdown(cook_now.generate(items, RECIPES, today=TODAY))
        assert "type: cook-now" in md
        assert "# 🍳 Cook Now" in md
        assert "Generated" in md
        assert "| Recipe | Have | Missing |" in md
        assert "[[Plain Rice]]" in md

    def test_no_missing_shows_dash(self):
        items = [_item("Chicken"), _item("Rice"), _item("Broccoli")]
        md = cook_now.render_markdown(cook_now.generate(items, RECIPES, today=TODAY))
        # Fully-covered Chicken Dinner row ends with the em-dash placeholder.
        assert "| [[Chicken Dinner]] | 100% (3/3) | — |" in md

    def test_at_risk_marker_and_legend(self):
        items = [_item("Spinach", expires=SOON), _item("Strawberries")]
        md = cook_now.render_markdown(cook_now.generate(items, RECIPES, today=TODAY))
        assert "[[Strawberry Spinach Salad]] ⏳" in md
        assert "⏳ = uses an item expiring soon." in md

    def test_empty_library_fallback(self):
        md = cook_now.render_markdown({"recipes": []})
        assert "No recipes with ingredients" in md


class TestChipGroups:
    def test_every_vocabulary_value_has_a_group(self):
        """A dish type with no chip would be unreachable in the UI."""
        from lib.normalizer import VALID_DISH_TYPES
        grouped = {dt for dts in cook_now.DISH_TYPE_GROUPS.values() for dt in dts}
        assert grouped == VALID_DISH_TYPES

    def test_no_dish_type_is_in_two_groups(self):
        seen, dupes = set(), []
        for dts in cook_now.DISH_TYPE_GROUPS.values():
            for dt in dts:
                if dt in seen:
                    dupes.append(dt)
                seen.add(dt)
        assert dupes == []

    def test_known_mappings(self):
        assert cook_now.group_for("dessert") == "Desserts"
        assert cook_now.group_for("main") == "Mains"
        assert cook_now.group_for("dip") == "Snacks"
        assert cook_now.group_for("bread") == "Sides"

    def test_unknown_and_missing_fall_back_to_mains(self):
        """A data gap must never hide a cookable recipe."""
        assert cook_now.group_for(None) == "Mains"
        assert cook_now.group_for("") == "Mains"
        assert cook_now.group_for("Tostada") == "Mains"

    def test_case_and_whitespace_insensitive(self):
        assert cook_now.group_for("  Dessert ") == "Desserts"


class TestGenerateCarriesGroup:
    def test_each_recipe_has_dish_type_and_group(self):
        items = [_item("Rice")]
        recipes = [{"name": "Plain Rice", "dish_type": "side",
                    "ingredient_items": ["rice", "salt", "olive oil"]}]
        result = cook_now.generate(items, recipes, today=TODAY)
        top = result["recipes"][0]
        assert top["dish_type"] == "side"
        assert top["group"] == "Sides"

    def test_note_rendering_is_unaffected_by_the_new_keys(self):
        """Cook Now.md must be byte-identical — the note is not part of this feature."""
        items = [_item("Rice")]
        recipes = [{"name": "Plain Rice", "dish_type": "side",
                    "ingredient_items": ["rice", "salt", "olive oil"]}]
        md = cook_now.render_markdown(cook_now.generate(items, recipes, today=TODAY))
        assert "Sides" not in md
        assert "dish_type" not in md
