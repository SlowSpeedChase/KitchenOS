"""Tests for lib/ingredient_cleaner.py — Phase A ingredient cleaning."""

from lib.ingredient_cleaner import clean_ingredient


def _clean(amount="1", unit="whole", item="", inferred=False):
    return clean_ingredient({"amount": amount, "unit": unit, "item": item, "inferred": inferred})


class TestDecimalAmounts:
    def test_fraction_to_decimal(self):
        r = _clean("1/2", "cup", "flour")
        assert r.amount == "0.5"
        assert not r.dropped

    def test_unicode_fraction_in_amount(self):
        assert _clean("¾", "cup", "flour").amount == "0.75"

    def test_unicode_fraction_in_item(self):
        r = _clean("1", "whole", "¾ cup flour")
        assert r.amount == "0.75"
        assert r.unit == "cup"
        assert r.item == "flour"

    def test_range_to_midpoint(self):
        assert _clean("3-4", "clove", "garlic").amount == "3.5"

    def test_clean_passthrough(self):
        r = _clean("2", "cup", "rice")
        assert (r.amount, r.unit, r.item) == ("2", "cup", "rice")
        assert not r.dropped and not r.needs_review


class TestA2AmountRecovery:
    def test_amount_embedded_in_item(self):
        r = _clean("1", "whole", "0.75 cup greek yogurt")
        assert r.amount == "0.75"
        assert r.unit == "cup"
        assert "greek yogurt" in r.item

    def test_estimated_paren_prefix(self):
        r = _clean("1", "whole", "(estimated) 1/2 cup parmesan")
        assert r.amount == "0.5"
        assert r.unit == "cup"
        assert "parmesan" in r.item

    def test_parenthetical_size_with_can(self):
        r = _clean("", "", "(14-ounce) can full fat coconut milk")
        assert r.amount == "14"
        assert r.unit == "oz"
        assert "coconut milk" in r.item

    def test_split_range_tail_recovered(self):
        # amount="1", item="to 1 1/4 cup water" → "1 to 1.25 cup" → 1.125 cup water
        r = _clean("1", "whole", "to 1 1/4 cup water")
        assert r.amount == "1.12"
        assert r.unit == "cup"
        assert r.item == "water"

    def test_split_range_tablespoons(self):
        r = _clean("3", "whole", "to 4 tablespoons ice water, plus more as needed")
        assert r.amount == "3.5"
        assert r.unit == "tbsp"
        assert "ice water" in r.item

    def test_validator_repair_amount_with_unit(self):
        r = _clean("30 grams", "none", "sugar")
        assert r.amount == "30"
        assert r.unit == "g"
        assert "sugar" in r.item


class TestA3UnitValidation:
    def test_liquid_with_count_unit_flagged(self):
        r = _clean("1", "whole", "maple syrup")
        assert r.needs_review
        assert "count unit" in r.note
        assert not r.dropped

    def test_unrecognized_unit_flagged(self):
        r = _clean("1", "blorp", "flour")
        assert r.needs_review
        assert "unrecognized unit" in r.note

    def test_junk_amount_flagged(self):
        r = _clean("Tomato Sauce", "whole", "tomato sauce")
        assert r.amount == "1"
        assert r.needs_review


class TestA4Drop:
    def test_temperature_leak_dropped(self):
        assert _clean("°f oil", "", "").dropped

    def test_instruction_leak_dropped(self):
        assert _clean("1", "whole", "preheat oven to 350").dropped

    def test_unit_only_item_dropped(self):
        assert _clean("1", "cup", "cup").dropped

    def test_empty_item_dropped(self):
        assert _clean("1", "whole", "").dropped


class TestRoundTrip:
    def test_to_ingredient_shape(self):
        d = _clean("1/2", "cup", "flour").to_ingredient()
        assert d == {"amount": "0.5", "unit": "cup", "item": "flour", "inferred": False}
