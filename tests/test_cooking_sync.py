"""Calendar imports mutate only cooking schedules and home placement dates."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from lib import inventory_db as db, serving_ledger as sl, paths, week_view
from lib.apple_integration import store
from lib.apple_integration.models import RevisionConflict
from tests.test_cook_schedule import cook, args

WEEK = "2026-W39"
MOVE = {"start": "2026-09-23T00:30:00Z", "duration_minutes": 60}


@pytest.fixture
def active():
    store.register_owner(str(uuid4()))
    store.activate_scope("cooking", WEEK, "calendar")
    c = cook()
    sl.schedule_cook(c["id"], **args(servings_to_eat=2))
    return c["id"]


def export():
    from lib.apple_integration import cooking

    return store.refresh_source(cooking.collect(WEEK)[0])


def test_move_preserves_servings_leftovers_inventory_and_meal(active):
    from lib.apple_integration import cooking

    sl.update_cook(active, scale=1.5)
    sl.add_placement(active, "slot", 1, date="2026-09-25", meal="lunch")
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO inventory(name,quantity,unit,location_source) VALUES('rice',4,'kg','manual')"
        )
        inventory = [tuple(r) for r in conn.execute("SELECT * FROM inventory")]
    item = export()
    before = sl.get_cook(active)
    result = cooking.apply(item, {"start": "2026-09-24T00:30:00Z"}, str(uuid4()))
    after = sl.get_cook(active)
    assert result.fields["start"] == "2026-09-23T19:30:00-05:00"
    assert after["meal"] == "dinner" and after["date"] == "2026-09-23"
    assert {(p["date"], p["count"]) for p in after["placements"]} == {
        ("2026-09-23", 2),
        ("2026-09-25", 1),
    }
    for field in ("scale", "cooked_at", "servings_produced", "unassigned"):
        assert after[field] == before[field]
    with db.connect() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM inventory")] == inventory
    assert store.get_item(item.token).source_revision == result.source_revision
    assert store.get_item(item.token).revision > item.revision
    assert (
        "[[The Sexy Skillet Lasagna]]"
        in (paths.meal_plans_dir() / f"{WEEK}.md").read_text()
    )


def test_confirmed_delete_only_unschedules_and_retry_is_inert(active):
    from lib.apple_integration import cooking

    item = export()
    operation = str(uuid4())
    before = sl.get_cook(active)
    result = cooking.apply(item, {"unscheduled": True}, operation)
    assert result.state == "retired"
    assert sl.get_cook(active) == before
    assert sl.schedules_for_week(WEEK) == []
    assert cooking.apply(item, {"unscheduled": True}, operation) == result


@pytest.mark.parametrize(
    "change", ["scale", "placement", "cooked", "deleted", "anchor"]
)
def test_stale_source_cannot_mutate_ledger_or_journal(active, change):
    from lib.apple_integration import cooking

    item = export()
    if change == "scale":
        sl.update_cook(active, scale=2)
    if change == "placement":
        sl.add_placement(active, "freezer", 1)
    if change == "cooked":
        sl.update_cook(active, cooked_at="2026-09-22")
    if change == "deleted":
        sl.delete_cook(active)
    if change == "anchor":
        sl.move_cook(active, "2026-09-24", "lunch")
    before = sl.get_cook(active)
    with pytest.raises(RevisionConflict):
        cooking.apply(item, MOVE, str(uuid4()))
    assert sl.get_cook(active) == before
    assert store.get_item(item.token) == item
    assert store.pending_source_patches("cooking") == []


@pytest.mark.parametrize(
    "patch",
    [
        {"start": "2026-09-29T19:00:00-05:00"},
        {"duration_minutes": 17},
        {"all_day": True},
        {"recurrence": "daily"},
        {"start": "2026-09-22"},
        {"start": "2026-09-22T23:45:00-05:00"},
        {"timezone": "not/a-zone"},
        {"unscheduled": False},
        {},
        {"unscheduled": True, "duration_minutes": 30},
    ],
)
def test_unsupported_edits_are_conflicts_and_atomic(active, patch):
    from lib.apple_integration import cooking

    item = export()
    before = sl.get_cook(active)
    with pytest.raises(RevisionConflict):
        cooking.apply(item, patch, str(uuid4()))
    assert sl.get_cook(active) == before
    assert store.get_item(item.token) == item


def test_collect_only_exports_scheduled_cooks_and_retains_history(active):
    from lib.apple_integration import cooking

    cook()
    item = export()
    assert len(cooking.collect(WEEK)) == 1
    sl.update_cook(active, cooked_at="2026-09-22")
    source = cooking.collect(WEEK)[0]
    assert source.state == "history"
    history = store.refresh_source(source)
    assert history.fields == item.fields
    assert export() == history  # A cooked row still has its schedule, but stays frozen.
    sl.delete_cook(active)
    assert cooking.collect(WEEK)[0].state == "history"
    assert export() == history


def test_reschedule_after_history_creates_new_active_generation(active):
    """A detached prior generation must not hide a new eligible schedule."""
    from lib.apple_integration import cooking

    item = export()
    sl.unschedule_cook(active)
    history = store.refresh_source(replace(cooking.collect(WEEK)[0], state="history"))
    assert cooking.collect(WEEK)[0].state == "history"

    sl.schedule_cook(
        active, **args(date="2026-09-24", start="2026-09-24T18:00:00-05:00")
    )
    source = cooking.collect(WEEK)[0]
    assert source.state == "active"
    assert source.fields["start"] == "2026-09-24T18:00:00-05:00"
    replacement = store.refresh_source(source)
    assert replacement.generation == item.generation + 1
    assert replacement.token != item.token
    assert store.get_item(item.token) == history


def test_borrowed_write_rolls_back_ledger_and_sync_together(active):
    from lib.apple_integration import cooking

    item = export()
    before = sl.get_cook(active)
    with pytest.raises(RuntimeError):
        with db.write_transaction() as conn:
            result = cooking.apply(item, MOVE, str(uuid4()), conn=conn)
            assert result.fields["duration_minutes"] == 60
            assert (
                store.get_item(item.token, conn=conn).source_revision
                == result.source_revision
            )
            raise RuntimeError("outer transaction rollback")
    assert sl.get_cook(active) == before
    assert store.get_item(item.token) == item
    assert sl.schedules_for_week(WEEK)[0]["duration_minutes"] == 90


def test_view_failure_is_durable_and_recovery_uses_committed_ledger(
    active, monkeypatch
):
    from lib.apple_integration import cooking

    item = export()
    operation = str(uuid4())
    real = week_view.write_week_markdown

    def fail(week):
        raise OSError("disk unavailable")

    monkeypatch.setattr(week_view, "write_week_markdown", fail)
    with pytest.raises(OSError):
        cooking.apply(item, MOVE, operation)
    assert sl.schedules_for_week(WEEK)[0]["duration_minutes"] == 60
    assert store.get_item(item.token).revision > item.revision
    with db.connect() as conn:
        assert (
            conn.execute("SELECT week FROM pending_schedule_views").fetchone()[0]
            == WEEK
        )
    monkeypatch.setattr(week_view, "write_week_markdown", real)
    assert cooking.recover_pending() == []
    assert cooking.apply(item, MOVE, operation).fields["duration_minutes"] == 60
    with db.connect() as conn:
        assert list(conn.execute("SELECT * FROM pending_schedule_views")) == []


def test_simultaneous_ordinary_edit_and_import_cannot_apply_stale_revision(active):
    from lib.apple_integration import cooking

    item = export()
    with db.write_transaction() as conn:
        conn.execute("UPDATE cooks SET scale=2 WHERE id=?", (active,))
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(cooking.apply, item, MOVE, str(uuid4()))
            conn.commit()
            with pytest.raises(RevisionConflict):
                future.result(timeout=10)
    assert sl.get_cook(active)["scale"] == 2
    assert sl.schedules_for_week(WEEK)[0]["duration_minutes"] == 90


@pytest.mark.parametrize(
    "week,day,start,expected",
    [
        ("2026-W10", "2026-03-08", "2026-03-08T08:00:00Z", "2026-03-08T03:00:00-05:00"),
        ("2026-W44", "2026-11-01", "2026-11-01T07:30:00Z", "2026-11-01T01:30:00-06:00"),
    ],
)
def test_dst_uses_instant_in_iana_zone(week, day, start, expected):
    from lib.apple_integration import cooking

    store.register_owner(str(uuid4()))
    store.activate_scope("cooking", week, "calendar")
    c = sl.create_cook(recipe="Soup", week=week, servings_produced=4)
    sl.schedule_cook(
        c["id"],
        **args(
            date=day, start=f"{day}T19:00:00" + ("-05:00" if "03-" in day else "-06:00")
        ),
    )
    item = store.refresh_source(cooking.collect(week)[0])
    assert (
        cooking.apply(item, {"start": start}, str(uuid4())).fields["start"] == expected
    )


def test_finished_retry_refuses_source_or_generation_drift(active):
    from lib.apple_integration import cooking

    item = export()
    operation = str(uuid4())
    cooking.apply(item, MOVE, operation)
    sl.update_cook(active, scale=2)
    with pytest.raises(RevisionConflict):
        cooking.apply(item, MOVE, operation)


def test_render_revision_cannot_clear_newer_cooking_move(active, monkeypatch):
    from lib.apple_integration import cooking

    item = export()
    real = week_view.write_week_markdown
    moved = False

    def concurrent_move(week):
        nonlocal moved
        real(week)
        if not moved:
            moved = True
            with db.write_transaction() as conn:
                sl.schedule_cook(
                    active,
                    **args(date="2026-09-24", start="2026-09-24T19:00:00-05:00"),
                    conn=conn,
                )

    monkeypatch.setattr(week_view, "write_week_markdown", concurrent_move)
    cooking.apply(item, MOVE, str(uuid4()))
    with db.connect() as conn:
        assert list(conn.execute("SELECT * FROM pending_schedule_views")) == []
    content = (paths.meal_plans_dir() / f"{WEEK}.md").read_text()
    assert (
        "[[The Sexy Skillet Lasagna]] x1"
        in content.split("## Thursday (Sep 24)")[1].split("## Friday")[0]
    )
    assert (
        "[[The Sexy Skillet Lasagna]]"
        not in content.split("## Tuesday (Sep 22)")[1].split("## Wednesday")[0]
    )


def test_journal_failure_rolls_back_source_and_view_work(active, monkeypatch):
    from lib.apple_integration import cooking

    item = export()
    before = sl.get_cook(active)

    def fail(*a, **kw):
        raise RuntimeError("journal unavailable")

    monkeypatch.setattr(store, "finish_source_patch", fail)
    with pytest.raises(RuntimeError):
        cooking.apply(item, MOVE, str(uuid4()))
    assert sl.get_cook(active) == before
    assert store.get_item(item.token) == item
    assert sl.schedules_for_week(WEEK)[0]["duration_minutes"] == 90
    with db.connect() as conn:
        assert list(conn.execute("SELECT * FROM apple_source_patches")) == []
        assert list(conn.execute("SELECT * FROM pending_schedule_views")) == []


def test_replaced_generation_refuses_finished_retry(active):
    from lib.apple_integration import cooking

    item = export()
    operation = str(uuid4())
    result = cooking.apply(item, MOVE, operation)
    store.refresh_source(replace(result, state="retired"))
    replacement = store.refresh_source(result)
    assert replacement.generation == item.generation + 1
    with pytest.raises(RevisionConflict):
        cooking.apply(item, MOVE, operation)


def test_ordinary_renderer_cannot_overwrite_acknowledged_calendar_move(
    active, monkeypatch
):
    """An old API regen must finish before Calendar renders and clears its job."""
    from threading import Event, RLock, current_thread
    from lib import note_mutation
    from api_server import _regen_weeks
    from lib.apple_integration import cooking

    captured = Event()
    release_old_render = Event()
    drain_waiting_or_finished = Event()

    class ObservedRLock:
        """Keep real locking; signal contention instead of guessing with sleeps."""

        def __init__(self):
            self.lock = RLock()

        def __enter__(self):
            if not self.lock.acquire(blocking=False):
                drain_waiting_or_finished.set()
                self.lock.acquire()
            return self

        def __exit__(self, *exc):
            self.lock.release()

    path = paths.meal_plans_dir() / f"{WEEK}.md"
    monkeypatch.setitem(note_mutation._LOCKS, str(path.resolve()), ObservedRLock())
    real_render = week_view.render_week_markdown
    real_drain = sl.drain_schedule_views
    old_renderer_thread = None

    def paused_render(week, recipes_dir):
        content = real_render(week, recipes_dir)
        if current_thread() is old_renderer_thread:
            captured.set()
            assert release_old_render.wait(10)
        return content

    def ordinary_regen():
        nonlocal old_renderer_thread
        old_renderer_thread = current_thread()
        _regen_weeks(WEEK)

    def observed_drain():
        try:
            return real_drain()
        finally:
            drain_waiting_or_finished.set()

    monkeypatch.setattr(week_view, "render_week_markdown", paused_render)
    monkeypatch.setattr(sl, "drain_schedule_views", observed_drain)
    item = export()
    with ThreadPoolExecutor(2) as pool:
        old = pool.submit(ordinary_regen)
        assert captured.wait(10)
        newer = pool.submit(
            cooking.apply, item, {"start": "2026-09-24T00:30:00Z"}, str(uuid4())
        )
        try:
            # Release the old snapshot only when Calendar has either finished
            # (the regression) or is provably waiting for the ordinary writer.
            assert drain_waiting_or_finished.wait(10)
        finally:
            release_old_render.set()
        old.result(timeout=10)
        newer.result(timeout=10)

    content = (paths.meal_plans_dir() / f"{WEEK}.md").read_text()
    assert (
        "[[The Sexy Skillet Lasagna]] x1"
        in content.split("## Wednesday (Sep 23)")[1].split("## Thursday")[0]
    )
    assert (
        "[[The Sexy Skillet Lasagna]]"
        not in content.split("## Tuesday (Sep 22)")[1].split("## Wednesday")[0]
    )
    with db.connect() as conn:
        assert list(conn.execute("SELECT * FROM pending_schedule_views")) == []
