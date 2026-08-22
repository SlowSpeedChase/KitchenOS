"""Tests for the Cook-Now coverage suggester."""

import re
import pytest
from datetime import date, timedelta
from pathlib import Path

from lib.inventory import InventoryItem
from lib import cook_now

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "cook_now.html"


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

    def test_per_group_limit_keeps_every_group_reachable(self):
        """A low-tier group must not be squeezed out by a higher-tier one.

        Desserts carry a 0.35 tier weight, so with a single global cap they sit
        below every main and a chip-sized payload never contains one — the
        real-pantry case: best dessert ranked 264th. per_group caps within the
        group, and the list stays one ranking (mains first, desserts after).
        """
        recipes = [
            {"name": f"Main {i}", "dish_type": "main",
             "ingredient_items": ["rice"]} for i in range(3)
        ] + [
            {"name": f"Sweet {i}", "dish_type": "dessert",
             "ingredient_items": ["rice"]} for i in range(3)
        ]
        items = [_item("Rice")]
        flat = cook_now.generate(items, recipes, today=TODAY, limit=2)
        assert {r["group"] for r in flat["recipes"]} == {"Mains"}, (
            "global cap: the tier weight alone decides, desserts never appear")

        grouped = cook_now.generate(items, recipes, today=TODAY, limit=2,
                                    per_group=True)
        got = grouped["recipes"]
        assert [r["group"] for r in got] == ["Mains", "Mains", "Desserts", "Desserts"]
        assert [r["score"] for r in got] == sorted(
            (r["score"] for r in got), reverse=True), "still one ranking"

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

    def test_non_string_dish_type_falls_back_to_mains(self):
        """The hand-rolled frontmatter parser can hand back a list

        (`dish_type: [dessert]`) or an int (`dish_type: 2`) for malformed YAML
        in any one of 239 recipe files. Before this guard, `.strip()` on a
        non-string raised AttributeError inside `generate()` and 500'd the
        whole /api/cook-now page over a single bad file.
        """
        assert cook_now.group_for(["dessert"]) == "Mains"
        assert cook_now.group_for(2) == "Mains"
        assert cook_now.group_for(None) == "Mains"


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


class TestTemplateGroupsMatchTaxonomy:
    """Nothing else ties the page's chip list to the Python taxonomy.

    Renaming a group in DISH_TYPE_GROUPS would leave every other test passing
    while silently making those recipes' chips unreachable in the UI — they'd
    be counted in `hidden` with no chip able to reveal them.
    """

    def test_template_groups_array_matches_python_taxonomy(self):
        html = TEMPLATE_PATH.read_text(encoding="utf-8")
        match = re.search(r"const GROUPS = \[(.*?)\];", html)
        assert match, "templates/cook_now.html must define `const GROUPS = [...]`"
        names = re.findall(r'"([^"]+)"', match.group(1))
        assert names == list(cook_now.DISH_TYPE_GROUPS)

    def test_desserts_is_a_real_group(self):
        """Guards DEFAULT_ON's `!== "Desserts"` filter from becoming a no-op."""
        assert "Desserts" in cook_now.DISH_TYPE_GROUPS


class TestAllStaplesDemotion:
    """A recipe made entirely of staples must sink, not squat.

    Plain Rice (rice + salt + olive oil, all pantry staples) is perpetually
    at 100% coverage because staples never age out — before this factor it
    outranked every partially-covered real dinner, forever.
    """

    def test_all_staples_flag_reported(self):
        result = cook_now.generate([_item("Rice")], RECIPES, today=TODAY)
        rice = next(r for r in result["recipes"] if r["recipe"] == "Plain Rice")
        chicken = next(r for r in result["recipes"] if r["recipe"] == "Chicken Dinner")
        assert rice["all_staples"] is True
        assert chicken["all_staples"] is False

    def test_every_entry_carries_the_flag(self):
        result = cook_now.generate([_item("Chicken")], RECIPES, today=TODAY)
        assert result["recipes"], "fixture produced no entries"
        assert all(isinstance(r["all_staples"], bool) for r in result["recipes"])

    def test_sinks_below_a_partially_covered_real_main(self):
        # Only chicken on hand: Chicken Dinner is 2/3 covered (rice is a
        # staple, broccoli missing) — a real dinner you're one item short of.
        # Plain Rice is 100% covered but every bit of it is the staple
        # assumption. The near-miss dinner must outrank the squatter.
        items = [_item("Chicken")]
        result = cook_now.generate(items, RECIPES, today=TODAY)
        names = [r["recipe"] for r in result["recipes"]]
        assert names.index("Chicken Dinner") < names.index("Plain Rice")

    def test_one_real_ingredient_escapes_demotion(self):
        # Same coverage (100%), same default tier/nutrition/speed/yield —
        # the only differing factor is the demotion, so the score ratio IS
        # the weight. Pins that a single real ingredient escapes entirely.
        recipes = RECIPES + [
            {"name": "Garlic Butter Chicken",
             "ingredient_items": ["chicken", "butter", "salt"]},
        ]
        items = [_item("Chicken"), _item("Rice")]
        result = cook_now.generate(items, recipes, today=TODAY)
        gbc = next(r for r in result["recipes"]
                   if r["recipe"] == "Garlic Butter Chicken")
        rice = next(r for r in result["recipes"] if r["recipe"] == "Plain Rice")
        assert gbc["all_staples"] is False
        assert rice["all_staples"] is True
        assert gbc["score"] > rice["score"]
        assert rice["score"] == pytest.approx(
            gbc["score"] * cook_now._ALL_STAPLES_WEIGHT, abs=1e-3)

    def test_demoted_harder_than_banked(self):
        # A banked demotion expires (the freezer empties); all-staples never
        # does. Pinned so future tuning keeps that ordering argument.
        assert cook_now._ALL_STAPLES_WEIGHT < cook_now._BANKED_WEIGHT
