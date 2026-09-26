"""Timed cooking uses the ledger's transaction and serving accounting."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from api_server import app
from lib import inventory_db, serving_ledger as sl


def create_unscheduled_cook(servings=8):
    return sl.create_cook("Chili", "2026-W39", servings_produced=servings)


def valid_args(**overrides):
    args = dict(date="2026-09-22", meal="dinner",
                start="2026-09-22T18:00:00-05:00", timezone="America/Chicago",
                duration_minutes=60, servings_to_eat=1)
    args.update(overrides)
    return args


def test_retry_only_places_first_serving_once(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    sl.schedule_cook(cook["id"], **valid_args(servings_to_eat=1))
    sl.schedule_cook(cook["id"], **valid_args(servings_to_eat=1))
    saved = sl.get_cook(cook["id"])
    assert sum(p["count"] for p in saved["placements"]) == 1
    assert saved["unassigned"] == 7


def test_generic_move_removes_stale_timed_schedule(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    sl.schedule_cook(cook["id"], **valid_args())
    sl.move_cook(cook["id"], "2026-09-23", "dinner")
    assert sl.schedules_for_week("2026-W39") == []


def test_invalid_offset_date_or_duration_rolls_back(tmp_db):
    cook = create_unscheduled_cook(servings=8)
    with pytest.raises(ValueError):
        sl.schedule_cook(cook["id"], **valid_args(
            start="2026-09-23T19:00:00-05:00"))
    assert sl.get_cook(cook["id"])["date"] is None


@pytest.mark.parametrize("overrides", [
    {"date": "2026-09-99"}, {"date": "20260922"}, {"date": None},
    {"start": "2026-09-22T18:00:00"}, {"start": None},
    {"start": "2026-09-22T18:00:00-06:00"},
    {"start": "2026-09-22T18:01:00-05:00"},
    {"start": "2026-09-22T18:00:01-05:00"},
    {"start": "2026-09-22T18:00:00.000001-05:00"},
    {"start": "2026-09-22T23:15:00-05:00"},
    {"timezone": "Central Time"}, {"timezone": None},
    {"timezone": "/usr/share/zoneinfo/America/Chicago"},
    {"duration_minutes": 0}, {"duration_minutes": 14},
    {"duration_minutes": 16}, {"duration_minutes": 375},
    {"duration_minutes": 60.5}, {"duration_minutes": "60"},
    {"duration_minutes": True}, {"duration_minutes": None},
    {"meal": "supper"}, {"meal": None},
    {"servings_to_eat": 0}, {"servings_to_eat": -1},
    {"servings_to_eat": float("inf")}, {"servings_to_eat": float("nan")},
    {"servings_to_eat": None}, {"servings_to_eat": True},
])
def test_bad_schedule_input_leaves_cook_unmodified(tmp_db, overrides):
    cook = create_unscheduled_cook()
    with pytest.raises(ValueError):
        sl.schedule_cook(cook["id"], **valid_args(**overrides))
    assert sl.get_cook(cook["id"]) == cook
    assert sl.schedules_for_week("2026-W39") == []


@pytest.mark.parametrize("start,duration,want", [
    ("2026-09-22T18:15-05:00", 15, "2026-09-22T18:15:00-05:00"),
    ("2026-09-22T18:00:00-05:00", 360, "2026-09-22T18:00:00-05:00"),
    ("2026-09-22T23:45:00-05:00", 15, "2026-09-22T23:45:00-05:00"),
])
def test_validate_normalizes_start_and_allows_midnight_boundary(start, duration, want):
    from lib.cook_schedule import validate
    assert validate("2026-09-22", start, "America/Chicago", duration) == want


@pytest.mark.parametrize("start", [
    "2026-11-01T01:15:00-05:00", "2026-11-01T01:15:00-06:00",
])
def test_validate_accepts_both_real_dst_fold_offsets(start):
    from lib.cook_schedule import validate
    assert validate("2026-11-01", start, "America/Chicago", 60) == start


@pytest.mark.parametrize("offset", ["-05:00", "-06:00"])
def test_validate_rejects_nonexistent_dst_wall_time(offset):
    from lib.cook_schedule import validate
    with pytest.raises(ValueError):
        validate("2026-03-08", f"2026-03-08T02:15:00{offset}",
                 "America/Chicago", 60)


def test_retry_on_fully_placed_cook_is_idempotent(tmp_db):
    cook = create_unscheduled_cook(servings=1)
    sl.schedule_cook(cook["id"], **valid_args())
    sl.schedule_cook(cook["id"], **valid_args())
    assert sl.get_cook(cook["id"])["unassigned"] == 0


def test_fractional_first_placement_and_timing_persist(tmp_db):
    cook = create_unscheduled_cook()
    saved = sl.schedule_cook(cook["id"], **valid_args(servings_to_eat=1.5))
    assert (saved["date"], saved["meal"], saved["unassigned"]) == (
        "2026-09-22", "dinner", 6.5)
    assert saved["placements"][0]["count"] == 1.5
    schedules = sl.schedules_for_week("2026-W39")
    assert len(schedules) == 1
    schedule = schedules[0]
    assert (schedule["cook_id"], schedule["recipe"], schedule["week"],
            schedule["date"], schedule["meal"], schedule["scale"],
            schedule["servings_produced"], schedule["cooked_at"]) == (
                cook["id"], "Chili", "2026-W39", "2026-09-22", "dinner", 1, 8, None)
    assert (schedule["start"], schedule["timezone"], schedule["duration_minutes"]) == (
        "2026-09-22T18:00:00-05:00", "America/Chicago", 60)
    assert sl.schedules_for_week("2026-W40") == []


def test_schedule_existing_anchor_moves_only_home_servings(tmp_db):
    cook = sl.create_cook("Chili", "2026-W39", servings_produced=8,
                          date="2026-09-21", meal="lunch", initial_placement_count=2)
    sl.add_placement(cook["id"], "slot", 1, date="2026-09-24", meal="lunch")
    sl.add_placement(cook["id"], "freezer", 3)
    saved = sl.schedule_cook(cook["id"], **valid_args(servings_to_eat=4))
    assert {(p["destination"], p["date"], p["meal"], p["count"])
            for p in saved["placements"]} == {
                ("slot", "2026-09-22", "dinner", 2),
                ("slot", "2026-09-24", "lunch", 1),
                ("freezer", None, None, 3)}
    assert saved["unassigned"] == 2


def test_timed_reschedule_upserts_without_adding_servings(tmp_db):
    cook = create_unscheduled_cook()
    sl.schedule_cook(cook["id"], **valid_args())
    saved = sl.schedule_cook(cook["id"], **valid_args(
        date="2026-09-23", start="2026-09-23T19:00:00-05:00",
        meal="lunch", duration_minutes=90, servings_to_eat=3))
    assert len(saved["placements"]) == 1
    assert (saved["placements"][0]["date"], saved["placements"][0]["meal"],
            saved["placements"][0]["count"]) == ("2026-09-23", "lunch", 1)
    assert saved["unassigned"] == 7
    schedules = sl.schedules_for_week("2026-W39")
    assert len(schedules) == 1
    assert (schedules[0]["start"], schedules[0]["duration_minutes"]) == (
        "2026-09-23T19:00:00-05:00", 90)


def test_capacity_failure_leaves_anchor_placements_and_timing_unchanged(tmp_db):
    cook = create_unscheduled_cook()
    sl.add_placement(cook["id"], "freezer", 7.5)
    before = sl.get_cook(cook["id"])
    with pytest.raises(sl.OverplacementError):
        sl.schedule_cook(cook["id"], **valid_args())
    assert sl.get_cook(cook["id"]) == before
    assert sl.schedules_for_week("2026-W39") == []


def test_schedule_rejects_date_outside_cook_week(tmp_db):
    cook = create_unscheduled_cook()
    with pytest.raises(ValueError, match="week"):
        sl.schedule_cook(cook["id"], **valid_args(
            date="2026-09-28", start="2026-09-28T18:00:00-05:00"))
    assert sl.get_cook(cook["id"]) == cook


def test_schedule_rejects_cooked_recipe(tmp_db):
    cook = create_unscheduled_cook()
    sl.update_cook(cook["id"], cooked_at="2026-09-21T12:00:00")
    before = sl.get_cook(cook["id"])
    with pytest.raises(ValueError, match="cooked"):
        sl.schedule_cook(cook["id"], **valid_args())
    assert sl.get_cook(cook["id"]) == before


def test_schedule_rejects_even_single_member_bundle(tmp_db):
    bundle = sl.create_bundle("Plate", [dict(recipe="Chili", scale=1,
                            servings_produced=8)], "2026-W39")
    cook = bundle["cooks"][0]
    with pytest.raises(ValueError, match="bundle"):
        sl.schedule_cook(cook["id"], **valid_args())
    assert sl.get_cook(cook["id"]) == cook


def test_missing_cook_rejected(tmp_db):
    with pytest.raises(ValueError, match="not found"):
        sl.schedule_cook(999, **valid_args())


@pytest.mark.parametrize("fields", [{"date": "2026-09-23"},
                                   {"meal": "lunch"}, {"date": None}])
def test_generic_patch_removes_stale_timing(tmp_db, fields):
    cook = create_unscheduled_cook()
    sl.schedule_cook(cook["id"], **valid_args())
    sl.update_cook(cook["id"], **fields)
    assert sl.schedules_for_week("2026-W39") == []


def test_unchanged_anchor_and_notes_preserve_timing(tmp_db):
    cook = create_unscheduled_cook()
    sl.schedule_cook(cook["id"], **valid_args())
    sl.move_cook(cook["id"], "2026-09-22", "dinner")
    sl.update_cook(cook["id"], date="2026-09-22", meal="dinner", notes="Bring bread")
    assert len(sl.schedules_for_week("2026-W39")) == 1


def test_delete_cascades_timing(tmp_db):
    cook = create_unscheduled_cook()
    sl.schedule_cook(cook["id"], **valid_args())
    sl.delete_cook(cook["id"])
    with inventory_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cook_schedule").fetchone()[0] == 0


def test_schedule_query_orders_by_start_then_cook_id(tmp_db):
    first, second, third = [create_unscheduled_cook() for _ in range(3)]
    sl.schedule_cook(first["id"], **valid_args(start="2026-09-22T19:00:00-05:00"))
    sl.schedule_cook(third["id"], **valid_args())
    sl.schedule_cook(second["id"], **valid_args())
    assert [r["cook_id"] for r in sl.schedules_for_week("2026-W39")] == [
        second["id"], third["id"], first["id"]]


def test_concurrent_schedule_retries_place_once(tmp_db):
    cook = create_unscheduled_cook(servings=1)
    barrier = Barrier(2)

    def schedule():
        barrier.wait(timeout=5)
        return sl.schedule_cook(cook["id"], **valid_args())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(schedule) for _ in range(2)]
        for future in futures:
            assert future.result(timeout=10)["unassigned"] == 0
    assert len(sl.get_cook(cook["id"])["placements"]) == 1
    assert len(sl.schedules_for_week("2026-W39")) == 1


def test_schedule_schema_upgrades_existing_database_without_losing_rows(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        conn.executescript("""
            CREATE TABLE cooks (id INTEGER PRIMARY KEY, recipe TEXT NOT NULL,
                week TEXT NOT NULL, date TEXT, meal TEXT, scale REAL,
                servings_produced REAL, cooked_at TEXT, notes TEXT,
                created_at TEXT DEFAULT (datetime('now')));
            INSERT INTO cooks (id, recipe, week, scale, servings_produced)
                VALUES (1, 'Chili', '2026-W39', 1, 8);
        """)
    saved = sl.schedule_cook(1, **valid_args())
    assert (saved["recipe"], saved["unassigned"]) == ("Chili", 7)


@pytest.mark.parametrize("duration", [14, 361])
def test_schedule_schema_enforces_duration_limits(tmp_db, duration):
    cook = create_unscheduled_cook()
    with inventory_db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO cook_schedule VALUES (?, ?, ?, ?)", (
                cook["id"], "2026-09-22T18:00:00-05:00", "America/Chicago", duration))


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_api_schedule_persists_and_regenerates_week(client, tmp_db, tmp_vault):
    cook = create_unscheduled_cook()
    response = client.post(f"/api/cooks/{cook['id']}/schedule", json=valid_args())
    assert response.status_code == 200
    assert response.get_json()["unassigned"] == 7
    assert len(sl.schedules_for_week("2026-W39")) == 1
    assert "[[Chili]]" in (tmp_vault / "Meal Plans" / "2026-W39.md").read_text()


@pytest.mark.parametrize("body", [None, [], {},
    {k: v for k, v in valid_args().items() if k != "start"},
    valid_args(extra="bad"), valid_args(start="wrong"),
])
def test_api_schedule_bad_body_returns_400_without_mutation(client, tmp_db, body):
    cook = create_unscheduled_cook()
    response = client.post(f"/api/cooks/{cook['id']}/schedule", json=body)
    assert response.status_code == 400
    assert response.is_json
    assert sl.get_cook(cook["id"]) == cook


def test_api_schedule_missing_cook_returns_404(client, tmp_db):
    response = client.post("/api/cooks/999/schedule", json=valid_args())
    assert response.status_code == 404


def test_api_schedule_capacity_returns_409(client, tmp_db):
    cook = create_unscheduled_cook(servings=1)
    response = client.post(f"/api/cooks/{cook['id']}/schedule",
                           json=valid_args(servings_to_eat=2))
    assert response.status_code == 409
    assert sl.get_cook(cook["id"]) == cook


def test_api_schedule_requires_remote_token(client, tmp_db, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "schedule-test-token")
    cook = create_unscheduled_cook()
    url = f"/api/cooks/{cook['id']}/schedule"
    response = client.post(url, json=valid_args(),
                           environ_overrides={"REMOTE_ADDR": "192.0.2.1"})
    assert response.status_code == 401
    assert sl.get_cook(cook["id"]) == cook
    response = client.post(url, json=valid_args(),
        environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
        headers={"Authorization": "Bearer schedule-test-token"})
    assert response.status_code == 200


def test_concurrent_api_retries_place_once(tmp_db):
    cook = create_unscheduled_cook(servings=1)
    barrier = Barrier(2)

    def schedule():
        with app.test_client() as client:
            barrier.wait(timeout=5)
            return client.post(f"/api/cooks/{cook['id']}/schedule", json=valid_args())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(schedule) for _ in range(2)]
        assert [f.result(timeout=10).status_code for f in futures] == [200, 200]
    assert len(sl.get_cook(cook["id"])["placements"]) == 1


def test_api_schedule_busy_returns_503(client, tmp_db, monkeypatch):
    cook = create_unscheduled_cook()

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    # Fault injection at the DB connection boundary leaves the route's real
    # error handling in place, without a five-second deliberate write lock.
    monkeypatch.setattr(inventory_db, "connect", locked)
    response = client.post(f"/api/cooks/{cook['id']}/schedule", json=valid_args())
    assert response.status_code == 503
    assert response.get_json()["error"] == "ledger busy, retry"
