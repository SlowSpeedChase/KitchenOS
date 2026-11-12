from concurrent.futures import ThreadPoolExecutor
import pytest
from lib import serving_ledger as sl


def cook():
    return sl.create_cook(
        recipe="The Sexy Skillet Lasagna", week="2026-W39", servings_produced=8
    )


def args(**changes):
    return dict(
        dict(
            date="2026-09-22",
            meal="dinner",
            start="2026-09-22T19:00:00-05:00",
            timezone="America/Chicago",
            duration_minutes=90,
            servings_to_eat=1,
        ),
        **changes,
    )


def test_retry_and_concurrency_only_place_once():
    c = cook()
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: sl.schedule_cook(c["id"], **args()), range(2)))
    saved = sl.get_cook(c["id"])
    assert saved["date"] == "2026-09-22"
    assert sum(p["count"] for p in saved["placements"]) == 1
    assert (
        saved["unassigned"] == 7 and saved["cooked_at"] is None and saved["scale"] == 1
    )
    assert len(sl.schedules_for_week("2026-W39")) == 1


def test_capacity_rollback_and_fractional_first_placement():
    c = cook()
    with pytest.raises(sl.OverplacementError):
        sl.schedule_cook(c["id"], **args(servings_to_eat=9))
    assert sl.get_cook(c["id"])["date"] is None
    assert not sl.schedules_for_week("2026-W39")
    sl.schedule_cook(c["id"], **args(servings_to_eat=1.5))
    assert sl.get_cook(c["id"])["unassigned"] == 6.5


def test_existing_servings_and_leftovers_preserved_then_cleanup():
    c = cook()
    sl.schedule_cook(c["id"], **args(servings_to_eat=2))
    sl.add_placement(c["id"], "slot", 1, date="2026-09-25", meal="lunch")
    sl.schedule_cook(
        c["id"],
        **args(date="2026-09-23", start="2026-09-23T19:00:00-05:00", servings_to_eat=3),
    )
    assert {(p["date"], p["count"]) for p in sl.get_cook(c["id"])["placements"]} == {
        ("2026-09-23", 2),
        ("2026-09-25", 1),
    }
    sl.move_cook(c["id"], "2026-09-24", "dinner")
    assert not sl.schedules_for_week("2026-W39")
    sl.schedule_cook(c["id"], **args())
    sl.update_cook(c["id"], notes="unchanged anchor")
    assert sl.schedules_for_week("2026-W39")
    sl.update_cook(c["id"], meal="lunch")
    assert not sl.schedules_for_week("2026-W39")
    sl.schedule_cook(c["id"], **args())
    sl.delete_cook(c["id"])
    assert not sl.schedules_for_week("2026-W39")


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-09-29", "start": "2026-09-29T19:00:00-05:00"},
        {"start": "2026-09-22T19:00:00Z"},
        {"start": "2026-09-22T19:01:00-05:00"},
        {"start": "2026-09-23T19:00:00-05:00"},
        {"start": "2026-09-22T23:00:00-05:00"},
        {"timezone": "bad"},
        {"duration_minutes": True},
        {"servings_to_eat": float("nan")},
        {"servings_to_eat": 0},
        {"servings_to_eat": True},
    ],
)
def test_invalid_schedule_is_atomic(changes):
    c = cook()
    with pytest.raises(ValueError):
        sl.schedule_cook(c["id"], **args(**changes))
    assert sl.get_cook(c["id"])["date"] is None


def test_cooked_and_missing_rejected():
    with pytest.raises(ValueError):
        sl.schedule_cook(999, **args())
    c = cook()
    sl.update_cook(c["id"], cooked_at="2026-09-21")
    with pytest.raises(ValueError):
        sl.schedule_cook(c["id"], **args())


def test_api_schedule_and_read():
    from api_server import app

    c = cook()
    client = app.test_client()
    response = client.post(f"/api/cooks/{c['id']}/schedule", json=args())
    assert response.status_code == 200
    assert response.json["cook"]["date"] == "2026-09-22"
    assert (
        client.get("/api/planning-calendar/2026-W39").json["schedules"][0]["cook_id"]
        == c["id"]
    )


def test_selected_cook_does_not_block_its_own_opening():
    from lib import planning_calendar as pc
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    pc.save_snapshot(
        dict(
            version=1,
            selection_id="a" * 64,
            generated_at=now.isoformat(),
            timezone="America/Chicago",
            coverage_start="2026-09-19",
            coverage_end="2026-10-24",
            events=[],
        )
    )
    c = cook()
    sl.schedule_cook(c["id"], **args(duration_minutes=180))
    result = pc.read_week("2026-W39", duration_minutes=180, exclude_cook_id=c["id"])
    assert any(
        w["start"] == "2026-09-22T19:00:00-05:00"
        for w in result["days"]["2026-09-22"]["windows"]
    )


def test_unschedule_preserves_cook_and_retry_is_noop():
    c = cook()
    sl.schedule_cook(c["id"], **args())
    before = sl.get_cook(c["id"])
    assert sl.unschedule_cook(c["id"]) == before
    assert sl.unschedule_cook(c["id"]) == before
    assert sl.get_cook(c["id"]) == before
    assert sl.schedules_for_week("2026-W39") == []
    with pytest.raises(ValueError):
        sl.unschedule_cook(999)


def test_borrowed_schedule_and_unschedule_do_not_commit():
    from lib import inventory_db as db

    c = cook()
    with pytest.raises(RuntimeError):
        with db.write_transaction() as conn:
            assert (
                sl.schedule_cook(c["id"], **args(), conn=conn)["cook"]["date"]
                == "2026-09-22"
            )
            assert sl.unschedule_cook(c["id"], conn=conn)["date"] == "2026-09-22"
            raise RuntimeError()
    assert sl.get_cook(c["id"])["date"] is None
    assert sl.schedules_for_week("2026-W39") == []


def test_api_delete_schedule_preserves_cook():
    from api_server import app

    c = cook()
    sl.schedule_cook(c["id"], **args())
    before = sl.get_cook(c["id"])
    client = app.test_client()
    response = client.delete(f"/api/cooks/{c['id']}/schedule")
    assert response.status_code == 200
    assert sl.get_cook(c["id"]) == before
    assert sl.schedules_for_week("2026-W39") == []
    assert client.delete(f"/api/cooks/{c['id']}/schedule").status_code == 200
    assert client.delete("/api/cooks/999/schedule").status_code == 404


def test_expected_placement_is_checked_inside_transaction_before_first_serving():
    from lib import inventory_db as db

    c = cook()
    sl.schedule_cook(c["id"], **args(servings_to_eat=2))
    with db.write_transaction() as conn:
        # Another writer cleared the anchor since the native client's exact GET.
        conn.execute("UPDATE cooks SET date=NULL, meal=NULL WHERE id=?", (c["id"],))
        conn.execute("DELETE FROM cook_schedule WHERE cook_id=?", (c["id"],))
        before = list(
            conn.execute("SELECT * FROM placements WHERE cook_id=?", (c["id"],))
        )
        for servings in [None, 1.5]:
            with pytest.raises(ValueError, match="placement changed"):
                sl.schedule_cook(
                    c["id"],
                    **args(servings_to_eat=servings),
                    expected_unplaced=False,
                    conn=conn,
                )
        assert (
            list(conn.execute("SELECT * FROM placements WHERE cook_id=?", (c["id"],)))
            == before
        )
        assert (
            conn.execute("SELECT date FROM cooks WHERE id=?", (c["id"],)).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM cook_schedule WHERE cook_id=?", (c["id"],)
            ).fetchone()[0]
            == 0
        )


def test_precondition_rejects_new_anchor_and_preserves_unspecified_existing_servings():
    c = cook()
    sl.schedule_cook(c["id"], **args(servings_to_eat=2))
    before = sl.get_cook(c["id"])
    with pytest.raises(ValueError, match="placement changed"):
        sl.schedule_cook(c["id"], **args(), expected_unplaced=True)
    assert sl.get_cook(c["id"]) == before
    saved = sl.schedule_cook(
        c["id"], **args(servings_to_eat=None), expected_unplaced=False
    )
    assert saved["cook"] == before
    assert sum(p["count"] for p in saved["cook"]["placements"]) == 2


def test_native_schedule_api_accepts_optional_precondition_and_refuses_stale_placement():
    from api_server import app

    c = cook()
    client = app.test_client()
    first = client.post(
        f"/api/cooks/{c['id']}/schedule",
        json=dict(args(servings_to_eat=1.5), expected_unplaced=True),
    )
    assert first.status_code == 200
    moved = client.post(
        f"/api/cooks/{c['id']}/schedule",
        json=dict(args(servings_to_eat=None), expected_unplaced=False),
    )
    assert moved.status_code == 200
    assert sum(p["count"] for p in moved.json["cook"]["placements"]) == 1.5
    sl.update_cook(c["id"], date=None, meal=None)
    before = sl.get_cook(c["id"])
    response = client.post(
        f"/api/cooks/{c['id']}/schedule",
        json=dict(args(servings_to_eat=None), expected_unplaced=False),
    )
    assert response.status_code == 400
    assert "placement changed" in response.json["error"]
    assert sl.get_cook(c["id"]) == before
    assert sl.schedules_for_week("2026-W39") == []


@pytest.mark.parametrize("expected", [0, 1, "false", [], {}])
def test_schedule_rejects_nonboolean_precondition(expected):
    c = cook()
    with pytest.raises(ValueError, match="boolean"):
        sl.schedule_cook(c["id"], **args(), expected_unplaced=expected)
    assert sl.get_cook(c["id"])["date"] is None


def test_unspecified_servings_cannot_create_first_placement_or_bypass_legacy_validation():
    c = cook()
    for extra in [{}, {"expected_unplaced": True}, {"expected_unplaced": False}]:
        with pytest.raises(ValueError):
            sl.schedule_cook(c["id"], **args(servings_to_eat=None), **extra)
    assert sl.get_cook(c["id"])["placements"] == []
    assert sl.schedules_for_week("2026-W39") == []
