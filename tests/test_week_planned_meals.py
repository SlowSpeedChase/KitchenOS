"""Day viewing includes both planned preparation and every dated serving."""

from lib import inventory_db
from lib import serving_ledger as sl


def cook(recipe="Chili", **overrides):
    fields = dict(
        recipe=recipe,
        week="2026-W45",
        date="2026-11-06",
        meal="dinner",
        servings_produced=6,
    )
    fields.update(overrides)
    return sl.create_cook(**fields)


def test_week_board_exposes_one_anchor_with_its_placement_count(tmp_db, tmp_path):
    item = cook()
    sl.add_placement(item["id"], "slot", 0.5, date="2026-11-06", meal="dinner")
    board = sl.week_board("2026-W45", tmp_path)
    assert board.get("planned_meals") == [
        {
            "date": "2026-11-06",
            "meal": "dinner",
            "recipe": "Chili",
            "cook_id": item["id"],
            "bundle_id": None,
            "bundle_name": None,
            "anchor": True,
            "count": 1.5,
        }
    ]


def test_local_leftovers_include_every_dated_slot_but_not_freezer_or_trash(
    tmp_db, tmp_path
):
    item = cook()
    sl.add_placement(item["id"], "slot", 1.5, date="2026-11-07", meal="lunch")
    sl.add_placement(item["id"], "slot", 1, date="2026-11-07", meal="dinner")
    sl.add_placement(item["id"], "freezer", 1)
    sl.add_placement(item["id"], "trash", 1)
    rows = sl.week_board("2026-W45", tmp_path).get("planned_meals", [])
    assert [
        (r["date"], r["meal"], r["recipe"], r["anchor"], r["count"]) for r in rows
    ] == [
        ("2026-11-06", "dinner", "Chili", True, 1),
        ("2026-11-07", "lunch", "Chili", False, 1.5),
        ("2026-11-07", "dinner", "Chili", False, 1),
    ]


def test_foreign_week_leftover_is_present_without_original_cook_anchor(
    tmp_db, tmp_path
):
    item = cook()
    sl.add_placement(item["id"], "slot", 2, date="2026-11-13", meal="lunch")
    board = sl.week_board("2026-W46", tmp_path)
    assert board["cooks"] == []
    assert board.get("planned_meals") == [
        {
            "date": "2026-11-13",
            "meal": "lunch",
            "recipe": "Chili",
            "cook_id": item["id"],
            "bundle_id": None,
            "bundle_name": None,
            "anchor": False,
            "count": 2,
        }
    ]


def test_unscheduled_cook_has_no_anchor_but_can_have_dated_leftovers(tmp_db, tmp_path):
    item = cook(date=None, meal=None)
    assert sl.week_board("2026-W45", tmp_path).get("planned_meals") == []
    sl.add_placement(item["id"], "slot", 1, date="2026-11-07", meal="lunch")
    rows = sl.week_board("2026-W45", tmp_path)["planned_meals"]
    assert len(rows) == 1
    assert rows[0]["anchor"] is False
    assert (rows[0]["date"], rows[0]["meal"]) == ("2026-11-07", "lunch")


def test_anchor_without_servings_still_represents_planned_preparation(tmp_db, tmp_path):
    item = cook(initial_placement_count=0)
    rows = sl.week_board("2026-W45", tmp_path).get("planned_meals", [])
    assert len(rows) == 1
    assert rows[0]["cook_id"] == item["id"]
    assert rows[0]["anchor"] is True
    assert rows[0]["count"] == 0


def test_bundle_members_retain_distinct_recipe_identity_and_metadata(tmp_db, tmp_path):
    bundle = sl.create_bundle(
        "Rice Plate",
        [
            {
                "recipe": "Rice A",
                "scale": 1,
                "servings_produced": 4,
                "initial_placement_count": 1,
            },
            {
                "recipe": "Rice B",
                "scale": 0.5,
                "servings_produced": 2,
                "initial_placement_count": 0.5,
            },
        ],
        "2026-W45",
        date="2026-11-06",
        meal="dinner",
    )
    for item in bundle["cooks"]:
        sl.add_placement(item["id"], "slot", 0.5, date="2026-11-13", meal="lunch")
    rows = sl.week_board("2026-W46", tmp_path).get("planned_meals", [])
    assert [r["recipe"] for r in rows] == ["Rice A", "Rice B"]
    assert [r["cook_id"] for r in rows] == [c["id"] for c in bundle["cooks"]]
    assert all(
        r["bundle_id"] == bundle["bundle_id"] and r["bundle_name"] == "Rice Plate"
        for r in rows
    )
    assert all(r["anchor"] is False and r["count"] == 0.5 for r in rows)


def test_multiple_cooks_of_same_recipe_are_not_collapsed(tmp_db, tmp_path):
    first, second = cook(), cook()
    rows = sl.week_board("2026-W45", tmp_path).get("planned_meals", [])
    assert [r["cook_id"] for r in rows] == [first["id"], second["id"]]
    assert [r["recipe"] for r in rows] == ["Chili", "Chili"]


def test_projection_does_not_mutate_ledger_or_plan(tmp_db, tmp_path):
    item = cook()
    sl.add_placement(item["id"], "slot", 1, date="2026-11-13", meal="lunch")
    plan = tmp_path / "2026-W46.md"
    plan.write_text("Hand-authored legacy plan stays untouched.\n")

    def snapshot():
        conn = inventory_db.connect()
        try:
            return {
                table: [
                    tuple(row)
                    for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")
                ]
                for table in ("cooks", "placements")
            }
        finally:
            conn.close()

    before = snapshot()
    rows = sl.week_board("2026-W46", tmp_path).get("planned_meals", [])
    assert len(rows) == 1
    assert snapshot() == before
    assert plan.read_text() == "Hand-authored legacy plan stays untouched.\n"
