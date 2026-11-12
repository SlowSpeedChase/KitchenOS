"""Minimal, bounded local calendar snapshot. Never log calendar contents."""

from datetime import date, datetime, timedelta, timezone
import json
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from lib import inventory_db

MAX_BYTES = 2 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}")


class StaleSnapshot(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Expected timestamp")
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Timestamp needs offset")
    return value


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected date")
    return date.fromisoformat(value)


def week_dates(week):
    if not isinstance(week, str) or not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise ValueError("Invalid week")
    monday = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def _valid(payload, now):
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "selection_id",
        "generated_at",
        "timezone",
        "coverage_start",
        "coverage_end",
        "events",
    }:
        raise ValueError("Invalid snapshot shape")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported snapshot version")
    if not isinstance(payload["selection_id"], str) or not HEX.fullmatch(
        payload["selection_id"]
    ):
        raise ValueError("Invalid selection identity")
    try:
        zone = ZoneInfo(payload["timezone"])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("Invalid timezone") from None
    generated = timestamp(payload["generated_at"])
    if not timedelta(0) <= now - generated < timedelta(hours=6):
        raise ValueError("Invalid generation time")
    first, end = iso_date(payload["coverage_start"]), iso_date(payload["coverage_end"])
    if not 0 < (end - first).days <= 35:
        raise ValueError("Invalid coverage")
    events = payload["events"]
    if not isinstance(events, list) or len(events) > 5000:
        raise ValueError("Too many events")
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "id",
            "title",
            "start",
            "end",
            "all_day",
            "role",
        }:
            raise ValueError("Invalid event shape")
        identity = event["id"]
        if (
            not isinstance(identity, str)
            or not HEX.fullmatch(identity)
            or identity in seen
        ):
            raise ValueError("Invalid occurrence identity")
        seen.add(identity)
        if (
            not isinstance(event["title"], str)
            or len(event["title"]) > 300
            or type(event["all_day"]) is not bool
            or event["role"] not in ("firm", "flexible")
        ):
            raise ValueError("Invalid event")
        start, finish = timestamp(event["start"]), timestamp(event["end"])
        if (
            finish <= start
            or finish.astimezone(zone).date() < first
            or start.astimezone(zone).date() >= end
        ):
            raise ValueError("Invalid event interval")
        if event["all_day"] and any(
            v.astimezone(zone).time().isoformat() != "00:00:00" for v in (start, finish)
        ):
            raise ValueError("All-day boundaries must be local midnight")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Snapshot too large")


def clear_snapshot(*, now=None):
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM planning_calendar_snapshot")
            conn.execute("DELETE FROM planning_calendar_choices")
            conn.execute(
                "INSERT OR REPLACE INTO planning_calendar_barrier VALUES (1,?)",
                ((now or datetime.now(timezone.utc)).isoformat(),),
            )
    finally:
        conn.close()


def save_snapshot(payload, *, now=None):
    now = now or datetime.now(timezone.utc)
    _valid(payload, now)
    conn = inventory_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT payload_json FROM planning_calendar_snapshot WHERE id=1"
        ).fetchone()
        previous = json.loads(old["payload_json"]) if old else None
        barrier = conn.execute(
            "SELECT cleared_at FROM planning_calendar_barrier WHERE id=1"
        ).fetchone()
        if barrier and timestamp(payload["generated_at"]) <= timestamp(
            barrier["cleared_at"]
        ):
            raise StaleSnapshot("Snapshot predates clearing")
        if (
            previous
            and timestamp(previous["generated_at"])
            == timestamp(payload["generated_at"])
            and previous != payload
        ):
            raise StaleSnapshot("Conflicting snapshot generation")
        if previous and timestamp(previous["generated_at"]) > timestamp(
            payload["generated_at"]
        ):
            raise StaleSnapshot("Older snapshot")
        if previous and previous["selection_id"] != payload["selection_id"]:
            conn.execute("DELETE FROM planning_calendar_choices")
        ids = {e["id"] for e in payload["events"]}
        for row in conn.execute(
            "SELECT occurrence_id FROM planning_calendar_choices"
        ).fetchall():
            if row["occurrence_id"] not in ids:
                conn.execute(
                    "DELETE FROM planning_calendar_choices WHERE occurrence_id=?",
                    (row["occurrence_id"],),
                )
        revision = uuid.uuid4().hex
        conn.execute(
            "INSERT OR REPLACE INTO planning_calendar_snapshot VALUES (1,?,?,?)",
            (json.dumps(payload), now.isoformat(), revision),
        )
        conn.commit()
        return {"revision": revision}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load(conn, now):
    row = conn.execute("SELECT * FROM planning_calendar_snapshot WHERE id=1").fetchone()
    payload = json.loads(row["payload_json"]) if row else None
    fresh = bool(
        row
        and timedelta(0) <= now - timestamp(row["received_at"]) < timedelta(hours=6)
        and timedelta(0)
        <= now - timestamp(payload["generated_at"])
        < timedelta(hours=6)
    )
    return row, payload, fresh


def set_occurrence_choice(occurrence_id, choice, revision, *, now=None):
    if choice not in ("blocking", "background"):
        raise ValueError("Invalid choice")
    conn = inventory_db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row, payload, fresh = _load(conn, now or datetime.now(timezone.utc))
        event = (
            next(
                (
                    e
                    for e in payload["events"]
                    if e["id"] == occurrence_id and e["all_day"]
                ),
                None,
            )
            if payload
            else None
        )
        if not fresh or row["revision"] != revision or event is None:
            raise StaleSnapshot("Refresh calendar before choosing")
        conn.execute(
            "INSERT OR REPLACE INTO planning_calendar_choices VALUES (?,?,?,?)",
            (payload["selection_id"], occurrence_id, event["end"], choice),
        )
        conn.commit()
        return {"status": "saved"}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_week(week, *, now=None, duration_minutes=90, exclude_cook_id=None):
    dates = week_dates(week)
    conn = inventory_db.connect()
    try:
        conn.execute("BEGIN")
        row, payload, fresh = _load(conn, now or datetime.now(timezone.utc))
        choices = (
            {
                r["occurrence_id"]: r["choice"]
                for r in conn.execute("SELECT * FROM planning_calendar_choices")
            }
            if fresh
            else {}
        )
    finally:
        conn.close()
    events = []
    if fresh:
        zone = ZoneInfo(payload["timezone"])
        first = datetime.combine(iso_date(dates[0]), datetime.min.time(), zone)
        end = first + timedelta(days=7)
        events = [
            e
            for e in payload["events"]
            if timestamp(e["start"]) < end and timestamp(e["end"]) > first
        ]
    from lib.cooking_windows import suggest_windows, valid_duration
    from lib.serving_ledger import schedules_for_week

    valid_duration(duration_minutes)
    schedules = schedules_for_week(week)
    days = {}
    for d in dates:
        covered = bool(
            fresh and payload["coverage_start"] <= d < payload["coverage_end"]
        )
        windows = (
            suggest_windows(
                d,
                payload["timezone"],
                events,
                choices,
                [s for s in schedules if s["cook_id"] != exclude_cook_id],
                duration_minutes,
            )
            if covered
            else []
        )
        days[d] = dict(
            covered=covered,
            windows=windows,
            unresolved_all_day_ids=sorted(
                {identity for w in windows for identity in w["unresolved_all_day_ids"]}
            ),
        )
    return dict(
        week=week,
        timezone=payload["timezone"] if payload else None,
        fresh=fresh,
        synced_at=row["received_at"] if row else None,
        revision=row["revision"] if row else None,
        coverage_start=payload["coverage_start"] if payload else None,
        coverage_end=payload["coverage_end"] if payload else None,
        events=events,
        choices={e["id"]: choices[e["id"]] for e in events if e["id"] in choices},
        days=days,
        schedules=schedules,
        duration_minutes=duration_minutes,
    )


def register_routes(app, require_token):
    from flask import jsonify, request
    from werkzeug.exceptions import RequestEntityTooLarge

    def body():
        # Limit the input stream before reading/parsing even for chunked requests.
        request.max_content_length = MAX_BYTES
        return request.get_json(silent=True)

    @app.post("/api/planning-calendar/snapshot")
    @require_token
    def upload_planning_calendar():
        try:
            payload = body()
            if (
                isinstance(payload, dict)
                and set(payload) == {"version", "clear"}
                and type(payload["version"]) is int
                and payload["version"] == 1
                and payload["clear"] is True
            ):
                clear_snapshot()
                return jsonify(status="cleared")
            return jsonify(save_snapshot(payload))
        except RequestEntityTooLarge:
            return jsonify(error="Calendar snapshot too large"), 413
        except StaleSnapshot:
            return jsonify(error="Refresh calendar before retrying"), 409
        except (ValueError, TypeError, OverflowError) as error:
            safe_reasons = {
                "Invalid snapshot shape",
                "Unsupported snapshot version",
                "Invalid selection identity",
                "Invalid timezone",
                "Invalid generation time",
                "Invalid coverage",
                "Too many events",
                "Invalid event shape",
                "Invalid occurrence identity",
                "Invalid event",
                "Invalid event interval",
                "All-day boundaries must be local midnight",
                "Snapshot too large",
                "Expected timestamp",
                "Timestamp needs offset",
                "Expected date",
            }
            reason = (
                str(error)
                if str(error) in safe_reasons
                else "Invalid date or timestamp"
            )
            app.logger.warning("Calendar snapshot rejected: %s", reason)
            return jsonify(error="Invalid calendar snapshot"), 400

    @app.get("/api/planning-calendar/<week>")
    @require_token
    def get_planning_calendar(week):
        try:
            duration = int(request.args.get("duration_minutes", "90"))
            if not 15 <= duration <= 360 or duration % 15:
                raise ValueError()
            exclude = request.args.get("exclude_cook_id")
            exclude = int(exclude) if exclude is not None else None
            return jsonify(
                read_week(week, duration_minutes=duration, exclude_cook_id=exclude)
            )
        except (ValueError, TypeError):
            return jsonify(error="Invalid week or duration"), 400

    @app.put("/api/planning-calendar/occurrences/<occurrence_id>")
    @require_token
    def choose_planning_occurrence(occurrence_id):
        try:
            payload = body()
            if not isinstance(payload, dict) or set(payload) != {"choice", "revision"}:
                raise ValueError()
            return jsonify(set_occurrence_choice(occurrence_id, **payload))
        except RequestEntityTooLarge:
            return jsonify(error="Request too large"), 413
        except StaleSnapshot:
            return jsonify(error="Calendar changed. Refresh and choose again."), 409
        except (ValueError, TypeError):
            return jsonify(error="Invalid calendar choice"), 400
