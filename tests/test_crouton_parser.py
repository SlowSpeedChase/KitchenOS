"""Tests for Crouton .crumb file parser"""

import pytest
from lib.crouton_parser import map_quantity_type, map_ingredient, map_steps, parse_crumb_file


class TestMapQuantityType:
    """Maps Crouton quantityType enum to KitchenOS unit strings"""

    def test_cup(self):
        assert map_quantity_type("CUP") == "cup"

    def test_tablespoon(self):
        assert map_quantity_type("TABLESPOON") == "tbsp"

    def test_teaspoon(self):
        assert map_quantity_type("TEASPOON") == "tsp"

    def test_grams(self):
        assert map_quantity_type("GRAMS") == "g"

    def test_ounce(self):
        assert map_quantity_type("OUNCE") == "oz"

    def test_pound(self):
        assert map_quantity_type("POUND") == "lb"

    def test_fluid_ounce(self):
        assert map_quantity_type("FLUID_OUNCE") == "fl oz"

    def test_mills(self):
        assert map_quantity_type("MILLS") == "ml"

    def test_kgs(self):
        assert map_quantity_type("KGS") == "kg"

    def test_can(self):
        assert map_quantity_type("CAN") == "can"

    def test_bunch(self):
        assert map_quantity_type("BUNCH") == "bunch"

    def test_packet(self):
        assert map_quantity_type("PACKET") == "packet"

    def test_pinch(self):
        assert map_quantity_type("PINCH") == "pinch"

    def test_item(self):
        assert map_quantity_type("ITEM") == "whole"

    def test_unknown_returns_whole(self):
        assert map_quantity_type("UNKNOWN_UNIT") == "whole"

    def test_none_returns_whole(self):
        assert map_quantity_type(None) == "whole"


class TestMapIngredient:
    """Converts Crouton ingredient objects to KitchenOS {amount, unit, item} dicts"""

    def test_standard_ingredient(self):
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "chicken breast"},
            "quantity": {"amount": 1, "quantityType": "POUND"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 1, "unit": "lb", "item": "chicken breast", "inferred": False}

    def test_item_quantity(self):
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "jalapeno"},
            "quantity": {"amount": 1, "quantityType": "ITEM"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 1, "unit": "whole", "item": "jalapeno", "inferred": False}

    def test_no_quantity(self):
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "to taste salt"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": "", "unit": "", "item": "to taste salt", "inferred": False}

    def test_fractional_amount(self):
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "butter"},
            "quantity": {"amount": 2.5, "quantityType": "TABLESPOON"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 2.5, "unit": "tbsp", "item": "butter", "inferred": False}

    def test_repeating_decimal_rounded(self):
        """1/3 stored as 0.333... should round to 0.33"""
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "tahini"},
            "quantity": {"amount": 0.3333333333333333, "quantityType": "CUP"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 0.33, "unit": "cup", "item": "tahini", "inferred": False}

    def test_two_thirds_rounded(self):
        """2/3 stored as 0.666... should round to 0.67"""
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "cream"},
            "quantity": {"amount": 0.6666666666666666, "quantityType": "CUP"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 0.67, "unit": "cup", "item": "cream", "inferred": False}

    def test_clean_float_unchanged(self):
        """Amounts like 1.5 should stay as 1.5, not become 1.50"""
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "salt"},
            "quantity": {"amount": 1.5, "quantityType": "TEASPOON"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 1.5, "unit": "tsp", "item": "salt", "inferred": False}

    def test_whole_number_stays_int(self):
        """Integer amounts like 2 should stay as int, not become 2.0"""
        crouton_ing = {
            "order": 0, "uuid": "abc",
            "ingredient": {"uuid": "def", "name": "garlic"},
            "quantity": {"amount": 2, "quantityType": "ITEM"},
        }
        result = map_ingredient(crouton_ing)
        assert result == {"amount": 2, "unit": "whole", "item": "garlic", "inferred": False}


class TestMapSteps:
    def test_simple_steps(self):
        crouton_steps = [
            {"order": 0, "uuid": "a", "isSection": False, "step": "Preheat oven to 350F."},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Mix dry ingredients."},
        ]
        result = map_steps(crouton_steps)
        assert result == [
            {"step": 1, "text": "Preheat oven to 350F.", "time": None},
            {"step": 2, "text": "Mix dry ingredients.", "time": None},
        ]

    def test_steps_with_section_header(self):
        crouton_steps = [
            {"order": 0, "uuid": "a", "isSection": True, "step": "For the Sauce"},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Heat oil in a pan."},
            {"order": 2, "uuid": "c", "isSection": False, "step": "Add garlic."},
        ]
        result = map_steps(crouton_steps)
        assert result == [
            {"step": 1, "text": "**For the Sauce** \u2014 Heat oil in a pan.", "time": None},
            {"step": 2, "text": "Add garlic.", "time": None},
        ]

    def test_sorts_by_order(self):
        crouton_steps = [
            {"order": 2, "uuid": "c", "isSection": False, "step": "Third."},
            {"order": 0, "uuid": "a", "isSection": False, "step": "First."},
            {"order": 1, "uuid": "b", "isSection": False, "step": "Second."},
        ]
        result = map_steps(crouton_steps)
        assert result[0]["text"] == "First."
        assert result[1]["text"] == "Second."
        assert result[2]["text"] == "Third."

    def test_empty_steps(self):
        result = map_steps([])
        assert result == []


class TestParseCrumbFile:
    def _make_crumb(self, **overrides):
        base = {
            "name": "Test Recipe", "uuid": "abc-123", "serves": 4,
            "duration": 15, "cookingDuration": 30,
            "webLink": "https://example.com/recipe",
            "sourceName": "Test Kitchen", "notes": "Some notes here",
            "tags": [],
            "ingredients": [{"order": 0, "uuid": "i1",
                "ingredient": {"uuid": "ig1", "name": "flour"},
                "quantity": {"amount": 2, "quantityType": "CUP"}}],
            "steps": [{"order": 0, "uuid": "s1", "isSection": False, "step": "Mix it."}],
            "defaultScale": 1, "isPublicRecipe": False, "folderIDs": [], "images": [],
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert result["recipe_name"] == "Test Recipe"
        assert result["servings"] == 4
        assert result["source_url"] == "https://example.com/recipe"
        assert result["source_channel"] == "Test Kitchen"
        assert result["source"] == "crouton_import"
        assert result["needs_review"] is True

    def test_time_formatting(self):
        data = self._make_crumb(duration=15, cookingDuration=30)
        result = parse_crumb_file(data)
        assert result["prep_time"] == "15 minutes"
        assert result["cook_time"] == "30 minutes"

    def test_no_time(self):
        data = self._make_crumb(duration=0, cookingDuration=0)
        result = parse_crumb_file(data)
        assert result["prep_time"] is None
        assert result["cook_time"] is None

    def test_ingredients_mapped(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert len(result["ingredients"]) == 1
        assert result["ingredients"][0]["item"] == "flour"
        assert result["ingredients"][0]["unit"] == "cup"

    def test_steps_mapped(self):
        data = self._make_crumb()
        result = parse_crumb_file(data)
        assert len(result["instructions"]) == 1
        assert result["instructions"][0]["text"] == "Mix it."

    def test_url_from_notes_fallback(self):
        data = self._make_crumb(webLink="", notes="Recipe: https://www.youtube.com/watch?v=abc123\nEnjoy!")
        result = parse_crumb_file(data)
        assert result["source_url"] == "https://www.youtube.com/watch?v=abc123"

    def test_notes_preserved(self):
        data = self._make_crumb(notes="My personal notes here")
        result = parse_crumb_file(data)
        assert result["notes"] == "My personal notes here"

    def test_no_serves(self):
        data = self._make_crumb()
        del data["serves"]
        result = parse_crumb_file(data)
        assert result["servings"] is None

    def test_missing_optional_fields(self):
        data = {"name": "Minimal Recipe", "uuid": "abc", "ingredients": [], "steps": [],
                "defaultScale": 1, "isPublicRecipe": False, "folderIDs": [], "images": [], "tags": []}
        result = parse_crumb_file(data)
        assert result["recipe_name"] == "Minimal Recipe"
        assert result["source_url"] == ""
        assert result["source_channel"] == ""
        assert result["servings"] is None
