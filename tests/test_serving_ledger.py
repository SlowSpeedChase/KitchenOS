"""Serving ledger: cooks produce servings; every serving is placed."""
import pytest

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
