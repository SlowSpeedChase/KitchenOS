"""Bounded calendar availability snapshot; no event details are stored."""

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from lib import inventory_db

STATUSES = {"good", "possible", "busy", "unknown"}


def save_snapshot(payload, *, now=None):
    if not isinstance(payload, dict) or set(payload) != {"days"}:
        raise ValueError("Expected only a days object")
    days = payload["days"]
    if not isinstance(days, dict) or len(days) > 35:
        raise ValueError("Expected up to 35 dates")
    for key, status in days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
            raise ValueError("Expected ISO dates")
        date.fromisoformat(key)
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("Invalid availability status")
    now = now or datetime.now(timezone.utc)
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO cooking_availability (id, days_json, synced_at) VALUES (1, ?, ?)",
                (json.dumps(days), now.isoformat()),
            )
    finally:
        conn.close()


def week_status(week, *, now=None):
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise ValueError("Invalid week")
    monday = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    now = now or datetime.now(timezone.utc)
    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT days_json, synced_at FROM cooking_availability WHERE id=1"
        ).fetchone()
    finally:
        conn.close()
    fresh = bool(
        row
        and timedelta(0)
        <= now - datetime.fromisoformat(row["synced_at"])
        < timedelta(hours=6)
    )
    stored = json.loads(row["days_json"]) if fresh else {}
    days = {
        (monday + timedelta(days=i)).isoformat(): stored.get(
            (monday + timedelta(days=i)).isoformat(), "unknown"
        )
        for i in range(7)
    }
    synced_at = row["synced_at"] if row else None
    # The detailed calendar knows what the summary cannot: all-day choices
    # (blocks cooking / background) and exact free windows. When it is fresh,
    # its windows decide the label for every day it covers.
    from lib import planning_calendar

    detail = planning_calendar.read_week(week, now=now)
    if detail["fresh"]:
        for day, info in detail["days"].items():
            if info["covered"]:
                days[day] = label_from_windows(day, info["windows"])
        fresh = True
        synced_at = detail["synced_at"]
    return {"days": days, "synced_at": synced_at, "fresh": fresh}


# Cooking has to finish by 9:30 pm local to count for the day.
COOK_BY = time(21, 30)


def label_from_windows(day, windows):
    """good: a free window that is clear of Time Blocking and of undecided
    all-day events. possible: only windows that overlap Time Blocking or
    depend on an undecided all-day event. busy: no window."""
    usable = []
    for w in windows:
        end = datetime.fromisoformat(w["end"])
        if end.date().isoformat() == day and end.time() <= COOK_BY:
            usable.append(w)
    if any(not w["overlaps_flexible"] and not w["unresolved_all_day_ids"] for w in usable):
        return "good"
    return "possible" if usable else "busy"


def register_routes(app, require_token):
    from flask import jsonify, request

    @app.post("/api/cooking-availability")
    @require_token
    def update_cooking_availability():
        try:
            save_snapshot(request.get_json(silent=True))
        except (ValueError, TypeError):
            return jsonify(
                error="Expected up to 35 ISO dates with good, possible, busy, or unknown status"
            ), 400
        return jsonify(status="saved")

    @app.get("/api/cooking-availability/<week>")
    @require_token
    def get_cooking_availability(week):
        try:
            return jsonify(week_status(week))
        except ValueError:
            return jsonify(error="Invalid week"), 400
