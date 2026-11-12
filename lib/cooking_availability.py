"""Bounded calendar availability snapshot; no event details are stored."""

from datetime import date, datetime, timedelta, timezone
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
    return {
        "days": {
            (monday + timedelta(days=i)).isoformat(): stored.get(
                (monday + timedelta(days=i)).isoformat(), "unknown"
            )
            for i in range(7)
        },
        "synced_at": row["synced_at"] if row else None,
        "fresh": fresh,
    }


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
