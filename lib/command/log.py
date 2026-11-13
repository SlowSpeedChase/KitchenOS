"""The command log: what was said, what was done, and how to undo it."""
import json
from typing import Optional

from lib import inventory_db

_JSON_COLUMNS = ("context", "answers", "plan", "response", "undo")
_UPDATABLE = ("status", "answers", "plan", "response", "undo")


def _encode(value):
    return json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value


def create(text: str, context: dict) -> int:
    conn = inventory_db.connect()
    try:
        with conn:
            cur = conn.execute("INSERT INTO command_log (text, context) VALUES (?, ?)",
                               (text, _encode(context)))
        return cur.lastrowid
    finally:
        conn.close()


def update(command_id: int, **fields) -> None:
    bad = set(fields) - set(_UPDATABLE)
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute(f"UPDATE command_log SET {assignments} WHERE id = ?",
                         (*[_encode(v) for v in fields.values()], command_id))
    finally:
        conn.close()


def _decode(row) -> dict:
    out = dict(row)
    for column in _JSON_COLUMNS:
        if out.get(column) is not None:
            out[column] = json.loads(out[column])
    return out


def get(command_id: int) -> Optional[dict]:
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM command_log WHERE id = ?", (command_id,)).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def recent_duplicate(text: str, context: dict, window_s: float) -> Optional[dict]:
    """The same sentence on the same screen, finished within ``window_s`` seconds."""
    if window_s <= 0:
        return None
    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM command_log WHERE text = ? AND context = ? AND status = 'done'"
            " AND created_at >= datetime('now', ?) ORDER BY id DESC LIMIT 1",
            (text, _encode(context), f"-{float(window_s)} seconds")).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def snap_cook(conn, cook_id: int) -> Optional[dict]:
    """A cook with its placements and schedule, exactly as stored. None if absent."""
    cook = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
    if cook is None:
        return None
    return {
        "cook": dict(cook),
        "placements": [dict(r) for r in conn.execute(
            "SELECT * FROM placements WHERE cook_id = ? ORDER BY id", (cook_id,))],
        "schedule": [dict(r) for r in conn.execute(
            "SELECT * FROM cook_schedule WHERE cook_id = ?", (cook_id,))],
    }


def _insert(conn, table: str, row: dict) -> None:
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))


def restore_cook(conn, cook_id: int, snapshot: Optional[dict]) -> None:
    """Make the cook exactly what ``snapshot`` says. None means "did not exist".

    The caller owns the transaction. Ids are preserved, so anything that pointed
    at the cook before still does.
    """
    conn.execute("DELETE FROM placements WHERE cook_id = ?", (cook_id,))
    conn.execute("DELETE FROM cook_schedule WHERE cook_id = ?", (cook_id,))
    conn.execute("DELETE FROM cooks WHERE id = ?", (cook_id,))
    if snapshot is None:
        return
    _insert(conn, "cooks", snapshot["cook"])
    for row in snapshot["placements"]:
        _insert(conn, "placements", row)
    for row in snapshot["schedule"]:
        _insert(conn, "cook_schedule", row)
