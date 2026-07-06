"""Serving ledger: cook events and where their servings went.

A *cook* is one preparation of a recipe at a fractional scale, producing
``servings_produced`` servings. Every serving is accounted for by a
*placement*: a (destination, date, meal, count) row. Destinations:

- ``slot``    eaten at a specific day/meal (date + meal required)
- ``freezer`` banked for later (no date; surfaces in the freezer tray)
- ``trash``   discarded (waste ledger)

Invariant: SUM(placements.count) <= servings_produced. The difference is
"unassigned" and surfaced by the UI. SQLite is authoritative; the weekly
Markdown file is a regenerated view (see lib/week_view.py).

Concurrency: the app is served by threaded Flask, so writers can overlap.
A bare SELECT does not start sqlite3's implicit transaction, so a
check-then-write sequence (read placed sum, compare to capacity, then
INSERT/UPDATE) is a TOCTOU race unless the read itself happens under the
write lock. Every write path that checks capacity (or otherwise reads a
row it is about to mutate) therefore opens its transaction explicitly with
``conn.execute("BEGIN IMMEDIATE")`` as the *first* statement, taking the
RESERVED lock before the read. A second connection attempting the same
thing blocks (up to ``busy_timeout``, 5000ms) or raises
``sqlite3.OperationalError: database is locked``. These paths do not use
``with conn:`` (which relies on the implicit transaction) — instead they
commit or roll back explicitly in a try/except/finally.
"""
from __future__ import annotations

import contextlib
import sqlite3
from typing import Optional

from lib import inventory_db

MEALS = ("breakfast", "lunch", "snack", "dinner")
DESTINATIONS = ("slot", "freezer", "trash")

_COOK_FIELDS = ("scale", "servings_produced", "date", "meal", "notes", "cooked_at")
_EPS = 1e-6


class OverplacementError(ValueError):
    """More servings placed than the cook produced."""


@contextlib.contextmanager
def _write_txn(conn: sqlite3.Connection):
    """Explicit write transaction: BEGIN IMMEDIATE takes the write lock
    before the first read, so a check-then-write sequence (read placed
    sum / row, compare, then INSERT or UPDATE) can't race with another
    connection doing the same. See the module docstring. Commits on
    clean exit, rolls back and re-raises on any exception.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def _row_to_dict(row) -> dict:
    return dict(row)


def _validate_placement(destination: str, date: Optional[str], meal: Optional[str]):
    if destination not in DESTINATIONS:
        raise ValueError(f"destination must be one of {DESTINATIONS}")
    if destination == "slot":
        if not date or not meal:
            raise ValueError("slot placements require date and meal")
        if meal not in MEALS:
            raise ValueError(f"meal must be one of {MEALS}")


def _placed_sum(conn, cook_id: int, exclude_placement: Optional[int] = None) -> float:
    q = "SELECT COALESCE(SUM(count), 0) AS s FROM placements WHERE cook_id = ?"
    args = [cook_id]
    if exclude_placement is not None:
        q += " AND id != ?"
        args.append(exclude_placement)
    return float(conn.execute(q, args).fetchone()["s"])


def _check_capacity(conn, cook_id: int, adding: float,
                    exclude_placement: Optional[int] = None) -> None:
    row = conn.execute(
        "SELECT servings_produced FROM cooks WHERE id = ?", (cook_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"cook {cook_id} not found")
    placed = _placed_sum(conn, cook_id, exclude_placement)
    if placed + adding > float(row["servings_produced"]) + _EPS:
        raise OverplacementError(
            f"cook {cook_id}: placing {adding} exceeds capacity"
            f" ({placed} of {row['servings_produced']} already placed)"
        )


def _merge_or_insert(conn, cook_id: int, destination: str,
                     date: Optional[str], meal: Optional[str], count: float) -> dict:
    existing = conn.execute(
        "SELECT * FROM placements WHERE cook_id = ? AND destination = ?"
        " AND date IS ? AND meal IS ?",
        (cook_id, destination, date, meal),
    ).fetchone()
    if existing:
        new_count = float(existing["count"]) + count
        conn.execute("UPDATE placements SET count = ? WHERE id = ?",
                     (new_count, existing["id"]))
        return {**_row_to_dict(existing), "count": new_count}
    cur = conn.execute(
        "INSERT INTO placements (cook_id, destination, date, meal, count)"
        " VALUES (?, ?, ?, ?, ?)",
        (cook_id, destination, date, meal, count),
    )
    return {"id": cur.lastrowid, "cook_id": cook_id, "destination": destination,
            "date": date, "meal": meal, "count": count}


def create_cook(recipe: str, week: str, scale: float = 1.0,
                servings_produced: Optional[float] = None,
                date: Optional[str] = None, meal: Optional[str] = None,
                initial_placement_count: float = 1.0,
                notes: Optional[str] = None) -> dict:
    if not recipe or not week:
        raise ValueError("recipe and week are required")
    if servings_produced is None or servings_produced <= 0:
        raise ValueError("servings_produced is required and must be > 0")
    if meal is not None and meal not in MEALS:
        raise ValueError(f"meal must be one of {MEALS}")
    conn = inventory_db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO cooks (recipe, week, date, meal, scale,"
                " servings_produced, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (recipe, week, date, meal, float(scale),
                 float(servings_produced), notes),
            )
            cook_id = cur.lastrowid
            if date and meal and initial_placement_count > 0:
                _merge_or_insert(conn, cook_id, "slot", date, meal,
                                 min(float(initial_placement_count),
                                     float(servings_produced)))
        return get_cook(cook_id)
    finally:
        conn.close()


def get_cook(cook_id: int) -> Optional[dict]:
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
        if row is None:
            return None
        cook = _row_to_dict(row)
        placements = [
            _row_to_dict(p) for p in conn.execute(
                "SELECT * FROM placements WHERE cook_id = ? ORDER BY id", (cook_id,)
            ).fetchall()
        ]
        cook["placements"] = placements
        cook["unassigned"] = round(
            float(cook["servings_produced"]) - sum(p["count"] for p in placements), 3)
        return cook
    finally:
        conn.close()


def update_cook(cook_id: int, **fields) -> dict:
    bad = set(fields) - set(_COOK_FIELDS)
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if not fields:
        raise ValueError("no fields to update")
    if "meal" in fields and fields["meal"] is not None and fields["meal"] not in MEALS:
        raise ValueError(f"meal must be one of {MEALS}")
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            if "servings_produced" in fields:
                new_cap = float(fields["servings_produced"])
                placed = _placed_sum(conn, cook_id)
                if new_cap + _EPS < placed:
                    raise OverplacementError(
                        f"cook {cook_id}: {placed} servings already placed;"
                        f" cannot shrink to {new_cap}")
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE cooks SET {sets} WHERE id = ?",
                         (*fields.values(), cook_id))
    finally:
        conn.close()
    return get_cook(cook_id)


def delete_cook(cook_id: int) -> None:
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM cooks WHERE id = ?", (cook_id,))
    finally:
        conn.close()


def add_placement(cook_id: int, destination: str, count: float,
                  date: Optional[str] = None, meal: Optional[str] = None) -> dict:
    if count <= 0:
        raise ValueError("count must be > 0")
    if destination != "slot":
        date = meal = None
    _validate_placement(destination, date, meal)
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            _check_capacity(conn, cook_id, float(count))
            return _merge_or_insert(conn, cook_id, destination, date, meal, float(count))
    finally:
        conn.close()


def update_placement(placement_id: int, **fields) -> dict:
    allowed = {"destination", "date", "meal", "count"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            row = conn.execute("SELECT * FROM placements WHERE id = ?",
                               (placement_id,)).fetchone()
            if row is None:
                raise ValueError(f"placement {placement_id} not found")
            merged = {**_row_to_dict(row), **fields}
            if merged["destination"] != "slot":
                merged["date"] = merged["meal"] = None
            _validate_placement(merged["destination"], merged["date"], merged["meal"])
            if float(merged["count"]) <= 0:
                raise ValueError("count must be > 0")
            _check_capacity(conn, row["cook_id"],
                            float(merged["count"]), exclude_placement=placement_id)
            conn.execute(
                "UPDATE placements SET destination = ?, date = ?, meal = ?,"
                " count = ? WHERE id = ?",
                (merged["destination"], merged["date"], merged["meal"],
                 float(merged["count"]), placement_id))
            return merged
    finally:
        conn.close()


def delete_placement(placement_id: int) -> None:
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM placements WHERE id = ?", (placement_id,))
    finally:
        conn.close()


def move_servings(placement_id: int, count: float, destination: str,
                  date: Optional[str] = None, meal: Optional[str] = None) -> dict:
    """Move ``count`` servings out of a placement into a new destination."""
    if destination != "slot":
        date = meal = None
    _validate_placement(destination, date, meal)
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            src = conn.execute("SELECT * FROM placements WHERE id = ?",
                               (placement_id,)).fetchone()
            if src is None:
                raise ValueError(f"placement {placement_id} not found")
            if count <= 0 or count > float(src["count"]) + _EPS:
                raise ValueError(
                    f"cannot move {count} of {src['count']} servings")
            remaining = float(src["count"]) - float(count)
            if remaining <= _EPS:
                conn.execute("DELETE FROM placements WHERE id = ?", (placement_id,))
                src_out = None
            else:
                conn.execute("UPDATE placements SET count = ? WHERE id = ?",
                             (remaining, placement_id))
                src_out = {**_row_to_dict(src), "count": remaining}
            # Total placed is conserved, so no capacity check needed.
            dest = _merge_or_insert(conn, src["cook_id"], destination,
                                    date, meal, float(count))
        return {"from": src_out, "to": dest}
    finally:
        conn.close()


def cooks_for_week(week: str) -> list[dict]:
    conn = inventory_db.connect()
    try:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cooks WHERE week = ? ORDER BY id", (week,)).fetchall()]
    finally:
        conn.close()
    return [get_cook(i) for i in ids]


def freezer_contents() -> list[dict]:
    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT p.id AS placement_id, p.count, c.id AS cook_id, c.recipe,"
            " c.week AS cook_week, c.date AS cook_date, c.created_at"
            " FROM placements p JOIN cooks c ON c.id = p.cook_id"
            " WHERE p.destination = 'freezer' AND p.count > 0"
            " ORDER BY c.created_at",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def placements_for_week(week: str) -> list[dict]:
    """All slot placements whose date falls inside the given ISO week."""
    from lib.meal_plan_parser import get_week_start_date
    from datetime import timedelta
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    start = get_week_start_date(year, week_num)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    conn = inventory_db.connect()
    try:
        marks = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT p.*, c.recipe FROM placements p"
            f" JOIN cooks c ON c.id = p.cook_id"
            f" WHERE p.destination = 'slot' AND p.date IN ({marks})"
            f" ORDER BY p.date, p.id",
            dates,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


COVERAGE_REVIEW_THRESHOLD = 0.8


def recipe_macros(recipe_name: str, recipes_dir) -> Optional[dict]:
    """Per-serving macros + coverage from a recipe's frontmatter, or None."""
    from lib.recipe_parser import parse_recipe_file
    path = recipes_dir / f"{recipe_name}.md"
    if not path.exists():
        return None
    fm = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
    if fm.get("nutrition_calories") is None:
        return None
    coverage = fm.get("nutrition_coverage")
    return {
        "calories": int(fm.get("nutrition_calories") or 0),
        "protein": int(fm.get("nutrition_protein") or 0),
        "carbs": int(fm.get("nutrition_carbs") or 0),
        "fat": int(fm.get("nutrition_fat") or 0),
        "coverage": float(coverage) if coverage is not None else None,
    }


def day_totals(week: str, recipes_dir) -> dict:
    totals: dict = {}
    macro_cache: dict = {}
    for p in placements_for_week(week):
        day = totals.setdefault(p["date"], {
            "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
            "incomplete": False,
        })
        name = p["recipe"]
        if name not in macro_cache:
            macro_cache[name] = recipe_macros(name, recipes_dir)
        macros = macro_cache[name]
        if macros is None:
            day["incomplete"] = True
            continue
        if macros["coverage"] is not None and \
                macros["coverage"] < COVERAGE_REVIEW_THRESHOLD:
            day["incomplete"] = True
        for k in ("calories", "protein", "carbs", "fat"):
            day[k] += macros[k] * float(p["count"])
    return totals


def week_board(week: str, recipes_dir) -> dict:
    return {
        "week": week,
        "cooks": cooks_for_week(week),
        "freezer": freezer_contents(),
        "day_totals": day_totals(week, recipes_dir),
    }
