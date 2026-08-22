"""The kitchen block carried by Selene's morning briefing.

Every test here injects its data. The endpoint's job is to be cheap and
unable to hang: it parses the recipe library once and never regenerates the
LLM task sidecar, and these tests are what hold both properties in place.
"""
from datetime import date

import pytest

from lib import kitchen_briefing as kb


TODAY = date(2026, 8, 22)          # a Saturday


def _cook(recipe, cook_date, placements):
    """A ledger cook dict, trimmed to the keys `plate` reads."""
    return {"recipe": recipe, "date": cook_date, "placements": placements}


def _slot(date_iso, meal, count=1.0):
    return {"destination": "slot", "date": date_iso, "meal": meal, "count": count}


class TestPlate:
    def test_orders_by_meal_not_by_cook_id(self):
        cooks = [
            _cook("Chicken Tinga", "2026-08-22", [_slot("2026-08-22", "dinner")]),
            _cook("Steel-Cut Oats", "2026-08-22", [_slot("2026-08-22", "breakfast")]),
        ]
        assert [p["recipe"] for p in kb.plate(TODAY, cooks)] == [
            "Steel-Cut Oats", "Chicken Tinga"]

    def test_placement_from_an_earlier_cook_is_a_leftover(self):
        """The fridge item that otherwise becomes waste — the whole reason the
        plate line covers the day rather than just dinner."""
        cooks = [_cook("Chorizo Chili", "2026-08-20", [_slot("2026-08-22", "lunch")])]
        assert kb.plate(TODAY, cooks) == [
            {"meal": "lunch", "recipe": "Chorizo Chili", "leftover": True}]

    def test_same_day_cook_is_not_a_leftover(self):
        cooks = [_cook("Chicken Tinga", "2026-08-22", [_slot("2026-08-22", "dinner")])]
        assert kb.plate(TODAY, cooks)[0]["leftover"] is False

    def test_ignores_other_days(self):
        cooks = [_cook("Tomorrow Stew", "2026-08-23", [_slot("2026-08-23", "dinner")])]
        assert kb.plate(TODAY, cooks) == []

    def test_ignores_freezer_and_trash_placements(self):
        cooks = [_cook("Batch Chili", "2026-08-22", [
            {"destination": "freezer", "date": None, "meal": None, "count": 4.0},
            {"destination": "trash", "date": None, "meal": None, "count": 1.0},
        ])]
        assert kb.plate(TODAY, cooks) == []

    def test_ignores_zero_count_placements(self):
        cooks = [_cook("Ghost", "2026-08-22", [_slot("2026-08-22", "dinner", count=0)])]
        assert kb.plate(TODAY, cooks) == []

    def test_deduplicates_split_placements_of_one_cook(self):
        """Two half-servings into the same slot is one thing on the plate."""
        cooks = [_cook("Chicken Tinga", "2026-08-22", [
            _slot("2026-08-22", "dinner", count=0.5),
            _slot("2026-08-22", "dinner", count=0.5),
        ])]
        assert len(kb.plate(TODAY, cooks)) == 1

    def test_empty_when_nothing_is_placed(self):
        assert kb.plate(TODAY, []) == []
