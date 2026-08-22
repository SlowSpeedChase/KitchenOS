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


class _Item:
    """An inventory item, trimmed to what at_risk reads."""
    def __init__(self, name, expires):
        self.name = name
        self.expires = expires


class TestAtRisk:
    def test_expired_and_soon_only_most_urgent_first(self, monkeypatch):
        monkeypatch.setattr(kb, "_at_risk_items", lambda items, today: [
            ("expired", _Item("ground beef", "2026-08-21")),
            ("soon", _Item("cilantro", "2026-08-24")),
        ])
        result = kb.at_risk(["ignored"], TODAY)
        assert result == [
            {"item": "ground beef", "status": "expired", "expires": "2026-08-21"},
            {"item": "cilantro", "status": "soon", "expires": "2026-08-24"},
        ]

    def test_empty_on_a_clean_fridge(self, monkeypatch):
        monkeypatch.setattr(kb, "_at_risk_items", lambda items, today: [])
        assert kb.at_risk([], TODAY) == []


class TestAtRiskAgainstTheRealWindow:
    """No monkeypatch. The seam's tuple order is exactly what went wrong here,
    and a fake that encodes the wrong contract cannot catch a wrong contract.
    """

    def test_names_the_food_not_the_status(self):
        from lib.inventory import InventoryItem

        items = [
            InventoryItem(name="ground beef", quantity=1.0, expires="2026-08-21"),
            InventoryItem(name="cilantro", quantity=1.0, expires="2026-08-24"),
        ]
        result = kb.at_risk(items, TODAY)
        assert [r["item"] for r in result] == ["ground beef", "cilantro"]
        assert [r["status"] for r in result] == ["expired", "soon"]


class TestLook:
    """One item per reason, three maximum. The three signals are
    incommensurable and are never blended into a single score."""

    def test_one_of_each_reason_in_order(self, monkeypatch):
        monkeypatch.setattr(kb, "_never_cooked", lambda idx, limit: [
            {"display_name": "Lamb Ragu", "added": "2026-04-12"}])
        monkeypatch.setattr(kb, "_fully_covered", lambda idx, items, today: [
            {"display_name": "Shakshuka"}])
        monkeypatch.setattr(kb, "_in_season", lambda idx, today: [
            {"display_name": "Corn Chowder"}])
        assert kb.look([], [], TODAY) == [
            {"reason": "never-cooked", "recipe": "Lamb Ragu", "detail": "saved 12 Apr"},
            {"reason": "on-hand", "recipe": "Shakshuka", "detail": "all on hand"},
            {"reason": "seasonal", "recipe": "Corn Chowder", "detail": "peak now"},
        ]

    def test_a_barren_reason_is_simply_absent(self, monkeypatch):
        monkeypatch.setattr(kb, "_never_cooked", lambda idx, limit: [])
        monkeypatch.setattr(kb, "_fully_covered", lambda idx, items, today: [
            {"display_name": "Shakshuka"}])
        monkeypatch.setattr(kb, "_in_season", lambda idx, today: [])
        assert [r["reason"] for r in kb.look([], [], TODAY)] == ["on-hand"]

    def test_never_cooked_without_an_arrival_date_has_no_parenthetical(self, monkeypatch):
        monkeypatch.setattr(kb, "_never_cooked", lambda idx, limit: [
            {"display_name": "Mystery Stew", "added": None}])
        monkeypatch.setattr(kb, "_fully_covered", lambda idx, items, today: [])
        monkeypatch.setattr(kb, "_in_season", lambda idx, today: [])
        assert kb.look([], [], TODAY) == [
            {"reason": "never-cooked", "recipe": "Mystery Stew", "detail": None}]

    def test_the_same_recipe_never_appears_twice(self, monkeypatch):
        """Two reasons can pick the same recipe; the block must not repeat it."""
        monkeypatch.setattr(kb, "_never_cooked", lambda idx, limit: [
            {"display_name": "Shakshuka", "added": "2026-04-12"}])
        monkeypatch.setattr(kb, "_fully_covered", lambda idx, items, today: [
            {"display_name": "Shakshuka"}])
        monkeypatch.setattr(kb, "_in_season", lambda idx, today: [])
        assert [r["reason"] for r in kb.look([], [], TODAY)] == ["never-cooked"]
