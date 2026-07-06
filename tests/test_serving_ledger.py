"""Serving ledger: cooks produce servings; every serving is placed."""
import sqlite3

import pytest

from lib import inventory_db
from lib import serving_ledger as sl
from lib.serving_ledger import OverplacementError


def _mk_cook(**over):
    kw = dict(recipe="Chili", week="2026-W28", scale=1.5,
              servings_produced=6.0, date="2026-07-07", meal="dinner")
    kw.update(over)
    return sl.create_cook(**kw)


def test_create_cook_autoplaces_anchor_serving(tmp_db):
    cook = _mk_cook()
    assert cook["recipe"] == "Chili"
    assert cook["servings_produced"] == 6.0
    assert len(cook["placements"]) == 1
    p = cook["placements"][0]
    assert (p["destination"], p["date"], p["meal"], p["count"]) == \
        ("slot", "2026-07-07", "dinner", 1.0)
    assert cook["unassigned"] == 5.0


def test_create_cook_requires_servings_produced(tmp_db):
    with pytest.raises(ValueError):
        sl.create_cook(recipe="Chili", week="2026-W28", servings_produced=None)


def test_overplacement_rejected(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 5.0)
    with pytest.raises(OverplacementError):
        sl.add_placement(cook["id"], "trash", 0.5)


def test_placements_merge_on_same_target(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 1.0)
    sl.add_placement(cook["id"], "freezer", 2.0)
    rows = [p for p in sl.get_cook(cook["id"])["placements"]
            if p["destination"] == "freezer"]
    assert len(rows) == 1 and rows[0]["count"] == 3.0


def test_slot_placement_requires_date_and_meal(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.add_placement(cook["id"], "slot", 1.0)          # no date/meal
    with pytest.raises(ValueError):
        sl.add_placement(cook["id"], "nowhere", 1.0)       # bad destination


def test_move_servings_freezer_to_slot_conserves_count(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 3.0)
    result = sl.move_servings(frozen["id"], 2.0, "slot",
                              date="2026-07-14", meal="lunch")
    assert result["to"]["count"] == 2.0
    c = sl.get_cook(cook["id"])
    total_placed = sum(p["count"] for p in c["placements"])
    assert total_placed == 6.0 - c["unassigned"]
    freezer = [p for p in c["placements"] if p["destination"] == "freezer"]
    assert freezer[0]["count"] == 1.0


def test_move_all_servings_deletes_source_row(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    sl.move_servings(frozen["id"], 2.0, "trash")
    dests = {p["destination"] for p in sl.get_cook(cook["id"])["placements"]}
    assert "freezer" not in dests and "trash" in dests


def test_shrinking_produced_below_placed_rejected(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 4.0)   # placed now 5.0
    with pytest.raises(OverplacementError):
        sl.update_cook(cook["id"], servings_produced=4.0)


def test_delete_cook_cascades(tmp_db):
    cook = _mk_cook()
    sl.delete_cook(cook["id"])
    assert sl.get_cook(cook["id"]) is None
    assert sl.freezer_contents() == []


def test_freezer_contents_joined_with_cook(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 2.0)
    fz = sl.freezer_contents()
    assert len(fz) == 1
    assert fz[0]["recipe"] == "Chili" and fz[0]["count"] == 2.0
    assert fz[0]["cook_week"] == "2026-W28"


def test_cooks_for_week_filters(tmp_db):
    _mk_cook()
    _mk_cook(week="2026-W29", date="2026-07-15")
    assert len(sl.cooks_for_week("2026-W28")) == 1


# --- Finding 1: TOCTOU race on capacity checks ---------------------------
# A bare SELECT doesn't start sqlite3's implicit transaction, so the
# check-then-write in add_placement/update_placement/update_cook/
# move_servings must open its transaction with BEGIN IMMEDIATE *before* the
# read, so the read happens under the write lock. We prove this
# deterministically: hold the write lock on a second connection via
# BEGIN IMMEDIATE, then show add_placement's own BEGIN IMMEDIATE contends
# for that same lock (blocks until busy_timeout, then raises
# OperationalError) rather than sailing through on a stale read.
def test_add_placement_write_lock_contends_with_concurrent_writer(tmp_db, monkeypatch):
    cook = _mk_cook()

    # A second, independent connection takes the write lock and holds it.
    blocker = inventory_db.connect()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("SELECT 1")

    # Shrink busy_timeout for connections opened from here on so the test
    # doesn't have to wait out the real 5000ms before observing the
    # contention.
    orig_connect = inventory_db.connect

    def fast_connect(*args, **kwargs):
        conn = orig_connect(*args, **kwargs)
        conn.execute("PRAGMA busy_timeout = 200")
        return conn

    monkeypatch.setattr(inventory_db, "connect", fast_connect)

    try:
        with pytest.raises(sqlite3.OperationalError):
            sl.add_placement(cook["id"], "freezer", 1.0)
    finally:
        blocker.rollback()
        blocker.close()


# --- Finding 2: update_cook validation gaps -------------------------------

def test_update_cook_rejects_invalid_meal(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.update_cook(cook["id"], meal="brunch")


def test_update_cook_allows_clearing_meal(tmp_db):
    cook = _mk_cook()
    updated = sl.update_cook(cook["id"], meal=None)
    assert updated["meal"] is None


def test_update_cook_no_fields_rejected(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.update_cook(cook["id"])


# --- Finding 3: coverage gaps ----------------------------------------------

def test_update_placement_changes_count_capacity_checked(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 4.0)  # placed: 1 + 4 = 5
    updated = sl.update_placement(frozen["id"], count=2.0)  # placed: 1 + 2 = 3
    assert updated["count"] == 2.0
    c = sl.get_cook(cook["id"])
    assert c["unassigned"] == 3.0
    with pytest.raises(OverplacementError):
        sl.update_placement(frozen["id"], count=6.0)  # 1 + 6 = 7 > 6


def test_update_placement_slot_to_freezer_nulls_date_and_meal(tmp_db):
    cook = _mk_cook()
    anchor = sl.get_cook(cook["id"])["placements"][0]
    assert anchor["destination"] == "slot"
    updated = sl.update_placement(anchor["id"], destination="freezer")
    assert updated["destination"] == "freezer"
    assert updated["date"] is None and updated["meal"] is None
    stored = sl.get_cook(cook["id"])["placements"][0]
    assert stored["destination"] == "freezer"
    assert stored["date"] is None and stored["meal"] is None


def test_delete_placement_removes_row(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    sl.delete_placement(frozen["id"])
    c = sl.get_cook(cook["id"])
    assert all(p["id"] != frozen["id"] for p in c["placements"])
    assert c["unassigned"] == 5.0


def test_placements_for_week_includes_cross_week_cook_excludes_non_slot(tmp_db):
    # Week 2026-W28 runs Mon 2026-07-06 .. Sun 2026-07-12.
    cook_a = _mk_cook()  # week 2026-W28, anchor slot 2026-07-07 dinner
    sl.add_placement(cook_a["id"], "freezer", 2.0)
    sl.add_placement(cook_a["id"], "trash", 1.0)

    # Anchored in a different week, but with a slot placement dated inside
    # 2026-W28 — placements_for_week goes by placement date, not cook week.
    cook_b = _mk_cook(recipe="Soup", week="2026-W29", date="2026-07-15")
    sl.add_placement(cook_b["id"], "slot", 1.0, date="2026-07-11", meal="lunch")

    rows = sl.placements_for_week("2026-W28")
    assert {r["destination"] for r in rows} == {"slot"}
    assert {r["recipe"] for r in rows} == {"Chili", "Soup"}
    dates = sorted(r["date"] for r in rows)
    assert dates == ["2026-07-07", "2026-07-11"]
    assert all("2026-07-06" <= d <= "2026-07-12" for d in dates)


# --- Task 2: recipe_macros, day_totals, week_board -------------------------

RECIPE_MD = """---
title: Chili
servings: 4
nutrition_calories: 500
nutrition_protein: 30
nutrition_carbs: 40
nutrition_fat: 20
nutrition_coverage: 0.95
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | lb | ground beef |
"""

LOW_COVERAGE_MD = RECIPE_MD.replace("title: Chili", "title: Mystery Soup") \
                           .replace("nutrition_coverage: 0.95",
                                    "nutrition_coverage: 0.4")


def _write_recipe(vault, name, content):
    recipes = vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / f"{name}.md").write_text(content, encoding="utf-8")
    return recipes


def test_day_totals_sum_placed_servings(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Chili", RECIPE_MD)
    cook = _mk_cook()                                  # anchor: 1 serving Jul 7 dinner
    sl.add_placement(cook["id"], "slot", 2.0, date="2026-07-07", meal="dinner")
    sl.add_placement(cook["id"], "slot", 1.0, date="2026-07-08", meal="lunch")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["calories"] == 1500    # 3 servings x 500
    assert totals["2026-07-07"]["incomplete"] is False
    assert totals["2026-07-08"]["protein"] == 30


def test_day_totals_flags_low_coverage(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Mystery Soup", LOW_COVERAGE_MD)
    sl.create_cook(recipe="Mystery Soup", week="2026-W28", scale=1.0,
                   servings_produced=4.0, date="2026-07-07", meal="dinner")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["incomplete"] is True


def test_day_totals_flags_missing_recipe(tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    sl.create_cook(recipe="Ghost Recipe", week="2026-W28", scale=1.0,
                   servings_produced=2.0, date="2026-07-07", meal="dinner")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["incomplete"] is True
    assert totals["2026-07-07"]["calories"] == 0


# --- M1: validate week/date formats BEFORE any insert ----------------------

def test_create_cook_rejects_bad_week_format(tmp_db):
    with pytest.raises(ValueError):
        _mk_cook(week="garbage")
    conn = inventory_db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM cooks").fetchone()["n"] == 0
    finally:
        conn.close()


def test_create_cook_rejects_bad_date(tmp_db):
    with pytest.raises(ValueError):
        _mk_cook(date="July 7th")
    conn = inventory_db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM cooks").fetchone()["n"] == 0
    finally:
        conn.close()


def test_add_placement_rejects_bad_date(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.add_placement(cook["id"], "slot", 1.0, date="notadate", meal="lunch")


def test_move_servings_rejects_bad_date(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    with pytest.raises(ValueError):
        sl.move_servings(frozen["id"], 1.0, "slot", date="notadate", meal="lunch")


# --- I4: garbage nutrition frontmatter must not raise ------------------------

def test_recipe_macros_garbage_frontmatter_returns_none(tmp_db, tmp_vault):
    garbage = RECIPE_MD.replace("nutrition_calories: 500",
                                'nutrition_calories: "lots"')
    recipes = _write_recipe(tmp_vault, "Garbage Stew", garbage)
    assert sl.recipe_macros("Garbage Stew", recipes) is None


def test_day_totals_garbage_frontmatter_marks_incomplete(tmp_db, tmp_vault):
    garbage = RECIPE_MD.replace("nutrition_calories: 500",
                                'nutrition_calories: "lots"')
    recipes = _write_recipe(tmp_vault, "Garbage Stew", garbage)
    sl.create_cook(recipe="Garbage Stew", week="2026-W28", scale=1.0,
                   servings_produced=4.0, date="2026-07-07", meal="dinner")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["incomplete"] is True


def test_week_board_shape(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Chili", RECIPE_MD)
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 2.0)
    board = sl.week_board("2026-W28", recipes)
    assert board["week"] == "2026-W28"
    assert len(board["cooks"]) == 1
    assert board["cooks"][0]["unassigned"] == 3.0
    assert len(board["freezer"]) == 1
    assert "2026-07-07" in board["day_totals"]
