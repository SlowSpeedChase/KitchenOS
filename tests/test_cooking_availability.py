from datetime import datetime, timedelta, timezone
import pytest


def client():
    from api_server import app

    return app.test_client()


def test_missing_calendar_is_unknown():
    response = client().get("/api/cooking-availability/2026-W36")
    assert response.status_code == 200
    assert set(response.json["days"].values()) == {"unknown"}


def test_snapshot_roundtrip_and_clear():
    c = client()
    payload = {
        "days": {"2026-09-04": "possible", "2026-09-05": "busy", "2026-09-06": "good"}
    }
    assert c.post("/api/cooking-availability", json=payload).status_code == 200
    days = c.get("/api/cooking-availability/2026-W36").json["days"]
    assert [days[d] for d in payload["days"]] == ["possible", "busy", "good"]
    assert days["2026-09-03"] == "unknown"
    assert c.post("/api/cooking-availability", json={"days": {}}).status_code == 200
    assert set(c.get("/api/cooking-availability/2026-W36").json["days"].values()) == {
        "unknown"
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"days": {"bad": "good"}},
        {"days": {"2026-09-04": "free"}},
        {"days": {}, "title": "private"},
        {"days": []},
    ],
)
def test_invalid_snapshot_rejected(payload):
    assert client().post("/api/cooking-availability", json=payload).status_code == 400


def test_stale_data_is_unknown():
    from lib import cooking_availability as ca

    now = datetime.now(timezone.utc)
    ca.save_snapshot({"days": {"2026-09-04": "good"}}, now=now - timedelta(hours=7))
    assert set(ca.week_status("2026-W36", now=now)["days"].values()) == {"unknown"}


def test_invalid_week():
    assert client().get("/api/cooking-availability/2026-W99").status_code == 400


def test_remote_write_requires_token(monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "calendar-test-token")
    assert (
        client()
        .post(
            "/api/cooking-availability",
            json={"days": {}},
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        )
        .status_code
        == 401
    )


def test_bad_upload_does_not_replace_existing_snapshot():
    c = client()
    c.post("/api/cooking-availability", json={"days": {"2026-09-04": "busy"}})
    assert (
        c.post(
            "/api/cooking-availability", json={"days": {"2026-09-04": []}}
        ).status_code
        == 400
    )
    assert (
        c.get("/api/cooking-availability/2026-W36").json["days"]["2026-09-04"] == "busy"
    )


def test_expiry_boundary_and_future_timestamp():
    from lib import cooking_availability as ca

    now = datetime.now(timezone.utc)
    for synced_at in [now - timedelta(hours=6), now + timedelta(minutes=1)]:
        ca.save_snapshot({"days": {"2026-09-04": "good"}}, now=synced_at)
        assert ca.week_status("2026-W36", now=now)["days"]["2026-09-04"] == "unknown"


# --- Day labels follow the detailed calendar when it is fresh -----------------

DETAIL_NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)


def _detail(events):
    return dict(
        version=1,
        selection_id="c" * 64,
        generated_at=DETAIL_NOW.isoformat(),
        timezone="America/Chicago",
        coverage_start="2026-11-16",
        coverage_end="2026-11-23",
        events=events,
    )


def _event(ident, start, end, *, role="firm", all_day=False, title="Thing"):
    return dict(id=ident * 64, title=title, start=start, end=end, all_day=all_day, role=role)


WEEK_LONG = _event("d", "2026-11-16T00:00:00-06:00", "2026-11-23T00:00:00-06:00",
                   all_day=True, title="Validations")


def _labels(events, choice=None):
    from lib import cooking_availability as ca, planning_calendar as pc

    pc.save_snapshot(_detail(events), now=DETAIL_NOW)
    if choice:
        revision = pc.read_week("2026-W47", now=DETAIL_NOW)["revision"]
        pc.set_occurrence_choice(events[0]["id"], choice, revision, now=DETAIL_NOW)
    # The coarse summary from the app says busy; the detailed calendar wins.
    ca.save_snapshot({"days": {f"2026-11-{d}": "busy" for d in range(16, 23)}}, now=DETAIL_NOW)
    return ca.week_status("2026-W47", now=DETAIL_NOW)["days"]


def test_unchosen_all_day_event_is_possible_not_busy():
    assert set(_labels([WEEK_LONG]).values()) == {"possible"}


def test_background_all_day_event_leaves_days_good():
    assert set(_labels([WEEK_LONG], "background").values()) == {"good"}


def test_blocking_all_day_event_makes_days_busy():
    assert set(_labels([WEEK_LONG], "blocking").values()) == {"busy"}


def test_one_evening_commitment_keeps_the_day_good():
    days = _labels([_event("e", "2026-11-17T19:00:00-06:00", "2026-11-17T20:30:00-06:00")])
    assert days["2026-11-17"] == "good"


def test_commitments_until_late_make_the_day_busy():
    # Free only after 10 pm: outside the cooking window.
    days = _labels([_event("f", "2026-11-18T12:00:00-06:00", "2026-11-18T22:00:00-06:00")])
    assert days["2026-11-18"] == "busy"
    assert days["2026-11-19"] == "good"


def test_free_time_only_inside_time_blocking_is_possible():
    days = _labels([
        _event("1", "2026-11-19T12:00:00-06:00", "2026-11-19T18:00:00-06:00"),
        _event("2", "2026-11-19T18:00:00-06:00", "2026-11-19T21:30:00-06:00", role="flexible"),
    ])
    assert days["2026-11-19"] == "possible"
