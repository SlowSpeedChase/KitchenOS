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

    def test_deduplicates_two_distinct_cooks_of_the_same_recipe(self):
        """Cooking the same recipe twice and placing both into one slot is
        still one line — intentional (the output carries no count), and
        previously unpinned by any test."""
        cooks = [
            _cook("Chicken Tinga", "2026-08-22", [_slot("2026-08-22", "dinner")]),
            _cook("Chicken Tinga", "2026-08-22", [_slot("2026-08-22", "dinner")]),
        ]
        assert kb.plate(TODAY, cooks) == [
            {"meal": "dinner", "recipe": "Chicken Tinga", "leftover": False}]

    def test_empty_when_nothing_is_placed(self):
        assert kb.plate(TODAY, []) == []


class TestLoadCooksAcrossWeeks:
    """`_load_cooks` folds in cooks from other ISO weeks whose leftovers land
    in the requested week — same pattern `week_view.render_week_markdown`
    uses (`cooks_for_week` + `placements_for_week`) so a Sunday cook's Monday
    leftover doesn't vanish when the ISO week rolls over."""

    def test_a_leftover_from_a_prior_iso_week_reaches_the_plate(self, monkeypatch):
        from lib import serving_ledger

        # 2026-08-16 is a Sunday (ISO week 33); its leftover lands on
        # 2026-08-22, a Saturday in ISO week 34 — TODAY's week.
        foreign_cook = {
            "id": 99, "recipe": "Chorizo Chili", "date": "2026-08-16",
            "week": "2026-W33", "placements": [_slot("2026-08-22", "lunch")],
        }
        monkeypatch.setattr(serving_ledger, "cooks_for_week", lambda week: [])
        monkeypatch.setattr(
            serving_ledger, "placements_for_week",
            lambda week: [{"cook_id": 99, "date": "2026-08-22"}])
        monkeypatch.setattr(
            serving_ledger, "get_cook",
            lambda cid: foreign_cook if cid == 99 else None)

        cooks = kb._load_cooks("2026-W34")
        assert kb.plate(TODAY, cooks) == [
            {"meal": "lunch", "recipe": "Chorizo Chili", "leftover": True}]

    def test_does_not_duplicate_a_cook_already_in_this_week(self, monkeypatch):
        """A cook already returned by `cooks_for_week` must not be re-fetched
        or duplicated just because one of its own placements also matched
        `placements_for_week`."""
        from lib import serving_ledger

        own_cook = {
            "id": 1, "recipe": "Chicken Tinga", "date": "2026-08-22",
            "week": "2026-W34", "placements": [_slot("2026-08-22", "dinner")],
        }
        calls = []
        monkeypatch.setattr(serving_ledger, "cooks_for_week", lambda week: [own_cook])
        monkeypatch.setattr(
            serving_ledger, "placements_for_week",
            lambda week: [{"cook_id": 1, "date": "2026-08-22"}])
        monkeypatch.setattr(
            serving_ledger, "get_cook", lambda cid: calls.append(cid) or None)

        cooks = kb._load_cooks("2026-W34")
        assert calls == []
        assert [c["id"] for c in cooks] == [1]


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
        """TODAY is Saturday; Sunday is the only day still ahead of it this
        week. A Monday do-ahead task (the week's own, already-past Monday)
        must NOT win this — see test_a_past_day_do_ahead_task_is_not_offered."""
        cached = _cached(_task("chop onions", "Sunday", can_do_ahead=True))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result == {"kind": "ahead", "text": "chop onions",
                          "detail": "do-ahead for Sunday"}

    def test_other_day_without_the_flag_is_not_offered(self):
        cached = _cached(_task("simmer", "Sunday", can_do_ahead=False))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_a_past_day_do_ahead_task_is_not_offered(self):
        """TODAY is Saturday. A Monday do-ahead task is behind today, not
        ahead of it — the plan is one Monday-Sunday week, not a rolling
        calendar, so there is no "next Monday" to pull it toward."""
        cached = _cached(_task("chop onions", "Monday", can_do_ahead=True))
        result = kb.next_action(TODAY, "2026-W34", cached, True, PLATE, VERDICT)
        assert result["kind"] == "verdict"

    def test_nearest_future_do_ahead_day_wins(self):
        """Wednesday today, with do-ahead tasks on both Thursday and
        Saturday: the nearer day (Thursday) must be offered, not whichever
        sidecar entry happens to come first."""
        wednesday = date(2026, 8, 19)
        cached = _cached(
            _task("bake the crust", "Saturday", can_do_ahead=True),
            _task("marinate the chicken", "Thursday", can_do_ahead=True),
        )
        result = kb.next_action(wednesday, "2026-W34", cached, True, PLATE, VERDICT)
        assert result == {"kind": "ahead", "text": "marinate the chicken",
                          "detail": "do-ahead for Thursday"}

    def test_rung_two_falls_through_when_the_only_ahead_candidate_is_done(self):
        """`done`-filtering is tested on rung 1 (prep) but was never tested on
        rung 2 (ahead) — the only guard that would have caught a filter that
        stopped comparing against `done` on this rung."""
        cached = _cached(
            _task("chop onions", "Sunday", can_do_ahead=True, done=True))
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


class TestBuild:
    def test_parses_the_recipe_library_exactly_once(self, monkeypatch):
        """cook_now and use_it_up each re-read every recipe file when called
        bare. Building four parts of one block that way is the full-vault scan
        that made the old canvas homepage unusable on a phone.

        Patches the real parser (``lib.recipe_index.get_recipe_index``), not
        the ``_load_recipe_index`` seam: a bare ``cook_now.generate()`` (which
        ``_fully_covered`` calls) bypasses that seam entirely and calls the
        real parser directly when no ``recipe_index`` is handed to it, so
        counting seam calls alone would not have caught a second parse.
        ``kb._load_recipe_index`` is left unpatched so the real call path runs.
        """
        from lib import recipe_index as recipe_index_mod

        calls = []
        monkeypatch.setattr(recipe_index_mod, "get_recipe_index",
                            lambda *a, **kw: calls.append(1) or [])
        monkeypatch.setattr(kb, "_load_inventory", lambda: [])
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: (None, False))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)
        result = kb.build(TODAY)
        assert calls == [1]
        assert result["degraded"] == []

    def test_a_failing_component_degrades_and_names_itself(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("inventory is cold")
        monkeypatch.setattr(kb, "_load_recipe_index", lambda: [])
        monkeypatch.setattr(kb, "_load_inventory", boom)
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: (None, False))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)

        result = kb.build(TODAY)
        assert result["at_risk"] == []
        assert "inventory" in result["degraded"]
        assert result["week"] == "2026-W34"

    def test_stale_sidecar_is_named_in_degraded(self, monkeypatch):
        monkeypatch.setattr(kb, "_load_recipe_index", lambda: [])
        monkeypatch.setattr(kb, "_load_inventory", lambda: [])
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: ({"tasks": []}, False))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)
        assert "tasks-sidecar-stale" in kb.build(TODAY)["degraded"]

    def test_fresh_sidecar_is_not_named(self, monkeypatch):
        monkeypatch.setattr(kb, "_load_recipe_index", lambda: [])
        monkeypatch.setattr(kb, "_load_inventory", lambda: [])
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: ({"tasks": []}, True))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)
        assert "tasks-sidecar-stale" not in kb.build(TODAY)["degraded"]

    def test_plate_renders_the_short_title_override(self, monkeypatch):
        """The ledger stores the note basename; surfaces show display_name."""
        monkeypatch.setattr(kb, "_load_recipe_index", lambda: [
            {"name": "Chicken Tinga With Charred Onion",
             "display_name": "Chicken Tinga"}])
        monkeypatch.setattr(kb, "_load_inventory", lambda: [])
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [
            _cook("Chicken Tinga With Charred Onion", "2026-08-22",
                  [_slot("2026-08-22", "dinner")])])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: (None, False))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)
        result = kb.build(TODAY)
        assert result["plate"][0]["recipe"] == "Chicken Tinga"
        assert result["degraded"] == []

    def test_payload_carries_every_documented_key(self, monkeypatch):
        monkeypatch.setattr(kb, "_load_recipe_index", lambda: [])
        monkeypatch.setattr(kb, "_load_inventory", lambda: [])
        monkeypatch.setattr(kb, "_load_cooks", lambda week: [])
        monkeypatch.setattr(kb, "_load_sidecar", lambda week: (None, False))
        monkeypatch.setattr(kb, "_load_verdict", lambda today: None)
        result = kb.build(TODAY)
        assert set(result) == {"date", "week", "plate", "next",
                               "at_risk", "look", "degraded"}
        assert result["date"] == "2026-08-22"
        assert result["degraded"] == []
