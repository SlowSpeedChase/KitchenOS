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


def _task(text, day, can_do_ahead=False, done=False):
    return {"id": "abc123", "text": text, "recipe": "Chicken Tinga",
            "day": day, "can_do_ahead": can_do_ahead, "done": done}


def _cached(*tasks):
    return {"tasks": list(tasks)}


PLATE = [{"meal": "dinner", "recipe": "Chicken Tinga", "leftover": False}]
VERDICT = {"cook_id": 7, "recipe": "Lamb Ragu", "when": "Thursday"}


class TestNextAction:
    def test_todays_prep_wins(self):
        cached = _cached(_task("brown the chorizo", "Saturday"),
                         _task("chop onions", "Sunday", can_do_ahead=True))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result == {"kind": "prep", "text": "brown the chorizo", "detail": None}

    def test_done_tasks_are_skipped(self):
        cached = _cached(_task("brown the chorizo", "Saturday", done=True))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_do_ahead_is_second(self):
        cached = _cached(_task("chop onions", "Monday", can_do_ahead=True))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result == {"kind": "ahead", "text": "chop onions",
                          "detail": "do-ahead for Monday"}

    def test_other_day_without_the_flag_is_not_offered(self):
        cached = _cached(_task("simmer", "Monday", can_do_ahead=False))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_stale_sidecar_skips_prep_entirely(self):
        """A stale sidecar must fall through, never regenerate."""
        cached = _cached(_task("brown the chorizo", "Saturday"))
        result = kb.next_action(TODAY, "2026-W34", cached, False, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_missing_sidecar_falls_through(self):
        result = kb.next_action(TODAY, "2026-W34", None, False, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_verdict_is_third(self):
        result = kb.next_action(TODAY, "2026-W34", None, False, PLATE, VERDICT)
        assert result == {"kind": "verdict",
                          "text": "how did Lamb Ragu go?", "detail": "Thursday"}

    def test_empty_plate_falls_to_plan_the_week(self):
        result = kb.next_action(TODAY, "2026-W34", None, False, [], None)
        assert result == {"kind": "plan-week", "text": "plan the week",
                          "detail": "2026-W34"}

    def test_plan_week_does_not_fire_when_the_plate_is_full(self):
        assert kb.next_action(TODAY, "2026-W34", None, False, PLATE, None) is None

    def test_verdict_outranks_plan_week_even_on_an_empty_plate(self):
        result = kb.next_action(TODAY, "2026-W34", None, False, [], VERDICT)
        assert result["kind"] == "verdict"
