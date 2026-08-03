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
import re
import sqlite3
import uuid
from datetime import date as _date
from typing import Optional

from lib import inventory_db

MEALS = ("breakfast", "lunch", "snack", "dinner")
DESTINATIONS = ("slot", "freezer", "trash")
_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")

_COOK_FIELDS = ("scale", "servings_produced", "date", "meal", "notes", "cooked_at",
                "make_again", "cook_note")
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


def _coerce_verdict(value) -> Optional[int]:
    """Normalize a make_again verdict to 1 / 0 / None.

    Strict about the binary contract: a stray 4 (a habit from star ratings)
    would otherwise store as truthy and silently read back as "make again".
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    raise ValueError(
        f"make_again must be True, False, or None (got {value!r}) — "
        "the verdict is binary by design, not a scale"
    )


def _validate_date(date_str: Optional[str]) -> None:
    """Reject non-ISO dates before any row is written (a bad date would
    otherwise commit, then blow up in the caller's week-regen step)."""
    if date_str is None:
        return
    try:
        _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise ValueError(f"invalid date (expected YYYY-MM-DD): {date_str!r}") from None


def _validate_placement(destination: str, date: Optional[str], meal: Optional[str]):
    if destination not in DESTINATIONS:
        raise ValueError(f"destination must be one of {DESTINATIONS}")
    if destination == "slot":
        if not date or not meal:
            raise ValueError("slot placements require date and meal")
        if meal not in MEALS:
            raise ValueError(f"meal must be one of {MEALS}")
    _validate_date(date)


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


def _validate_cook(recipe: str, week: str, servings_produced, date, meal) -> None:
    """The rules every new cook row obeys, whether created alone or in a bundle.

    Separated so ``create_bundle`` can validate *every* member before writing
    any of them — a plate that half-lands is worse than one that is refused.
    """
    if not recipe or not week:
        raise ValueError("recipe and week are required")
    if not _WEEK_RE.match(week):
        raise ValueError(f"invalid week (expected YYYY-WNN): {week!r}")
    _validate_date(date)
    if servings_produced is None or servings_produced <= 0:
        raise ValueError("servings_produced is required and must be > 0")
    if meal is not None and meal not in MEALS:
        raise ValueError(f"meal must be one of {MEALS}")


def _insert_cook(conn, recipe: str, week: str, date, meal, scale,
                 servings_produced, notes,
                 bundle_id: Optional[str] = None,
                 bundle_name: Optional[str] = None) -> int:
    """Write one cook row and return its id. Caller owns the transaction."""
    cur = conn.execute(
        "INSERT INTO cooks (recipe, week, date, meal, scale, servings_produced,"
        " notes, bundle_id, bundle_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (recipe, week, date, meal, float(scale), float(servings_produced),
         notes, bundle_id, bundle_name),
    )
    return cur.lastrowid


def create_cook(recipe: str, week: str, scale: float = 1.0,
                servings_produced: Optional[float] = None,
                date: Optional[str] = None, meal: Optional[str] = None,
                initial_placement_count: float = 1.0,
                notes: Optional[str] = None) -> dict:
    _validate_cook(recipe, week, servings_produced, date, meal)
    conn = inventory_db.connect()
    try:
        with conn:
            cook_id = _insert_cook(conn, recipe, week, date, meal, scale,
                                   servings_produced, notes)
            if date and meal and initial_placement_count > 0:
                _merge_or_insert(conn, cook_id, "slot", date, meal,
                                 min(float(initial_placement_count),
                                     float(servings_produced)))
        return get_cook(cook_id)
    finally:
        conn.close()


def find_recent_duplicate(recipe: str, week: str, date, meal,
                          window_s: float) -> Optional[dict]:
    """An identical cook created within ``window_s`` seconds, or None.

    Exists to absorb a double-tap, not to prevent cooking the same dish twice:
    the window is seconds, so a deliberate repeat later in the week still
    creates its own row. The live ledger shows why it is needed — cooks 20 and
    21 are the same recipe, same week, no date, no meal, created three seconds
    apart, because the "add to this week" button renders its result only inside
    the Freezer tab's Unscheduled tray and so looked like it had failed.

    ``date``/``meal`` are matched with ``IS`` rather than ``=`` because the real
    duplicates carry NULL for both, and NULL = NULL is never true in SQL.
    """
    if window_s <= 0 or not recipe or not week:
        return None
    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM cooks"
            " WHERE recipe = ? AND week = ? AND date IS ? AND meal IS ?"
            "   AND created_at >= datetime('now', ?)"
            " ORDER BY id DESC LIMIT 1",
            (recipe, week, date, meal, f"-{float(window_s)} seconds"),
        ).fetchone()
    finally:
        conn.close()
    return get_cook(row["id"]) if row else None


def get_cook(cook_id: int) -> Optional[dict]:
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
        if row is None:
            return None
        cook = _row_to_dict(row)
        # SQLite has no bool: round-trip 0/1 back to True/False while keeping
        # NULL as None, so "not judged yet" stays distinct from "never again".
        if cook.get("make_again") is not None:
            cook["make_again"] = bool(cook["make_again"])
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
    if "date" in fields:
        _validate_date(fields["date"])
    if "make_again" in fields:
        fields["make_again"] = _coerce_verdict(fields["make_again"])
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


def move_cook(cook_id: int, date: str, meal: str) -> dict:
    """Re-anchor a cook to another slot, taking its home servings with it.

    The card and the servings eaten *at* it move together; slot placements in
    other cells are planned leftovers and stay where they are. Moving the
    anchor alone would strand a card in a slot with no servings beside an
    orphaned foreign chip, which reads as a bug rather than as a plan.

    Total placed is conserved, so no capacity check is needed — the same
    reasoning ``move_servings`` records.
    """
    _validate_placement("slot", date, meal)
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            _move_cook_in_txn(conn, cook_id, date, meal)
    finally:
        conn.close()
    return get_cook(cook_id)


def _move_cook_in_txn(conn, cook_id: int, date: str, meal: str) -> None:
    """Re-anchor one cook. Caller owns validation and the transaction.

    Extracted so ``move_bundle`` moves its members through the same rules in one
    transaction — the week check and the bring-your-home-servings behaviour must
    not fork between moving a cook and moving a plate.
    """
    row = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
    if row is None:
        raise ValueError(f"cook {cook_id} not found")
    # `week` is not in _COOK_FIELDS and cooks_for_week() filters on it, so a
    # cook whose date left its week renders on no board at all. Reject rather
    # than half-apply: the grid shows one week, so a drag cannot produce this,
    # but the endpoint is public.
    year, week_no, _ = _date.fromisoformat(date).isocalendar()
    if f"{year}-W{week_no:02d}" != row["week"]:
        raise ValueError(
            f"date {date} falls outside the cook's week {row['week']}")

    old_date, old_meal = row["date"], row["meal"]
    if (old_date, old_meal) == (date, meal):
        return
    conn.execute("UPDATE cooks SET date = ?, meal = ? WHERE id = ?",
                 (date, meal, cook_id))
    # `IS` rather than `=` so a NULL old anchor matches nothing instead of
    # everything — an unscheduled cook has no home servings to bring along.
    movers = conn.execute(
        "SELECT * FROM placements WHERE cook_id = ?"
        " AND destination = 'slot' AND date IS ? AND meal IS ?",
        (cook_id, old_date, old_meal),
    ).fetchall()
    for p in movers:
        conn.execute("DELETE FROM placements WHERE id = ?", (p["id"],))
        _merge_or_insert(conn, cook_id, "slot", date, meal, float(p["count"]))


def create_bundle(bundle_name: str, members: list, week: str,
                  date: Optional[str] = None,
                  meal: Optional[str] = None) -> dict:
    """One composite plate as N ordinary cooks sharing a bundle id.

    Every ledger row stays "one recipe at one scale", which is the entire point:
    ``day_totals``, the shopping list, the freezer, ``cook_history``,
    ``on_track``, ``verdict_nudge`` and ``cook_sweep`` need no bundle awareness
    at all. The bundle is a creation transaction and a display grouping, never a
    placement constraint — a member can still be moved or deleted on its own.

    ``members`` is a list of plain dicts, ``{recipe, scale, servings_produced,
    initial_placement_count?, notes?}``, rather than ``meal_loader`` objects:
    ``meal_loader`` imports ``MEALS`` from this module, so the reverse import
    would be circular. ``lib/meal_bundle.plan_bundle`` owns the Meal -> members
    rule, including that ``initial_placement_count`` must be the member's
    *share* — that is what makes a plate's day-total contribution equal its
    card's figure.

    All-or-nothing: every member is validated before the first INSERT and the
    transaction rolls back on any failure, so a half-placed plate is impossible.

    Returns ``{bundle_id, bundle_name, week, date, meal, cooks: [...]}``.
    """
    if not bundle_name:
        raise ValueError("bundle_name is required")
    if not members:
        raise ValueError("a bundle needs at least one member")
    for m in members:
        _validate_cook(m.get("recipe"), week, m.get("servings_produced"),
                       date, meal)

    bundle_id = uuid.uuid4().hex
    conn = inventory_db.connect()
    try:
        # A plain `with conn:` rather than _write_txn: BEGIN IMMEDIATE exists for
        # check-then-write races, and this reads nothing it is about to mutate —
        # the cook ids do not exist yet, so _merge_or_insert's SELECT can only
        # match rows this transaction just wrote. `with conn:` already gives
        # atomicity and rollback.
        with conn:
            ids = []
            for m in members:
                cook_id = _insert_cook(
                    conn, m["recipe"], week, date, meal,
                    m.get("scale", 1.0), m["servings_produced"], m.get("notes"),
                    bundle_id=bundle_id, bundle_name=bundle_name)
                ids.append(cook_id)
                count = float(m.get("initial_placement_count") or 0)
                if date and meal and count > 0:
                    _merge_or_insert(conn, cook_id, "slot", date, meal,
                                     min(count, float(m["servings_produced"])))
    finally:
        conn.close()
    # get_cook opens its own connection, so it runs after the write commits.
    return {"bundle_id": bundle_id, "bundle_name": bundle_name, "week": week,
            "date": date, "meal": meal, "cooks": [get_cook(i) for i in ids]}


def get_bundle(bundle_id: str) -> Optional[dict]:
    """Every cook sharing ``bundle_id``, or None once the last one is gone.

    ``week``/``date``/``meal`` are the *first* member's, for callers that need a
    week to regenerate. Members may legitimately differ: moving one member out
    of the plate is allowed, and the planner renders it as its own card there.
    """
    if not bundle_id:
        return None
    conn = inventory_db.connect()
    try:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cooks WHERE bundle_id = ? ORDER BY id",
            (bundle_id,)).fetchall()]
    finally:
        conn.close()
    if not ids:
        return None
    cooks = [get_cook(i) for i in ids]
    head = cooks[0]
    return {"bundle_id": bundle_id, "bundle_name": head["bundle_name"],
            "week": head["week"], "date": head["date"], "meal": head["meal"],
            "cooks": cooks}


def find_recent_bundle(bundle_name: str, week: str, date, meal,
                       window_s: float) -> Optional[dict]:
    """A bundle of the same plate placed in the same slot within ``window_s``.

    The bundle counterpart of ``find_recent_duplicate``, and needed more: without
    it a double-tapped plate creates 2N cook rows rather than one duplicate.
    Same ``IS``-not-``=`` treatment for a NULL date/meal.
    """
    if window_s <= 0 or not bundle_name or not week:
        return None
    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT bundle_id FROM cooks"
            " WHERE bundle_name = ? AND week = ? AND date IS ? AND meal IS ?"
            "   AND bundle_id IS NOT NULL AND created_at >= datetime('now', ?)"
            " ORDER BY id DESC LIMIT 1",
            (bundle_name, week, date, meal, f"-{float(window_s)} seconds"),
        ).fetchone()
    finally:
        conn.close()
    return get_bundle(row["bundle_id"]) if row else None


def delete_bundle(bundle_id: str) -> list[dict]:
    """Remove every member. Returns them as they were, for the caller's hooks.

    Read first: the caller needs the recipe names for ``_sync_cook_history`` and
    the placement dates for ``_regen_weeks``, and after the DELETE both are gone.
    Placements cascade via the foreign key.
    """
    bundle = get_bundle(bundle_id)
    if bundle is None:
        return []
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM cooks WHERE bundle_id = ?", (bundle_id,))
    finally:
        conn.close()
    return bundle["cooks"]


def move_bundle(bundle_id: str, date: str, meal: str) -> dict:
    """Re-anchor every member of a plate together, in one transaction.

    One transaction rather than N calls to ``move_cook`` so a plate cannot
    half-move: if any member's new date falls outside its week, none of them
    moves. Each member goes through ``_move_cook_in_txn``, so the week check and
    the bring-your-home-servings rule are the same ones a single cook obeys.
    """
    _validate_placement("slot", date, meal)
    bundle = get_bundle(bundle_id)
    if bundle is None:
        raise ValueError(f"bundle {bundle_id} not found")
    conn = inventory_db.connect()
    try:
        with _write_txn(conn):
            for cook in bundle["cooks"]:
                _move_cook_in_txn(conn, cook["id"], date, meal)
    finally:
        conn.close()
    return get_bundle(bundle_id)


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
            " c.week AS cook_week, c.date AS cook_date, c.cooked_at, c.created_at"
            " FROM placements p JOIN cooks c ON c.id = p.cook_id"
            " WHERE p.destination = 'freezer' AND p.count > 0"
            " ORDER BY c.created_at",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def banked_recipes() -> set:
    """Names of recipes with servings currently in the freezer.

    The cheap half of ``freezer_summary``, for callers that only need to know
    *whether* something is banked. The suggester asks this once per render and
    tests it against the whole library, so it must not pay to read macros and
    recipe files it will never look at.
    """
    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT c.recipe FROM placements p"
            " JOIN cooks c ON c.id = p.cook_id"
            " WHERE p.destination = 'freezer' AND p.count > 0",
        ).fetchall()
        return {r["recipe"] for r in rows}
    finally:
        conn.close()


def _banked_on(row: dict) -> Optional[str]:
    """The day a frozen serving actually became food.

    ``date`` is an intention and ``created_at`` is when the row was typed;
    ``cooked_at`` is the only one of the three that means "this exists". Same
    precedence as ``cook_history``, for the same reason.
    """
    for value in (row.get("cooked_at"), row.get("cook_date"), row.get("created_at")):
        if value:
            return str(value)[:10]
    return None


def freezer_summary(recipes_dir) -> list[dict]:
    """The freezer as a list of meals, oldest first.

    Groups placements by recipe — cooking Chili twice is one thing to eat, not
    two rows to reconcile — and prices each group so the tray can answer the
    question the freezer exists to answer: *do I need to cook tonight?*

    Macros pass the ``implausible`` **bounds** only, for the reason a tray
    totalling 244 g of protein per serving would be a worse lie than a blank.
    When they don't survive it, ``servings`` is still reported — the food is real
    even when the numbers about it aren't.

    That is deliberately *looser* than ``day_totals``, which now applies the full
    ``eligible_macros`` gate. The two answer different questions: the day row is
    a claim about what you ate, so a recipe whose coverage says a third of its
    ingredients went unresolved has no business being summed into it — while the
    freezer is an inventory of real food, and a low-coverage portion is still a
    portion. Don't "unify" this without deciding that question again.
    """
    from lib.nutrition_quality import implausible

    groups: dict = {}
    for row in freezer_contents():
        name = row["recipe"]
        group = groups.setdefault(name, {
            "recipe": name, "servings": 0.0,
            "placement_ids": [], "banked_on": None,
        })
        group["servings"] = round(group["servings"] + float(row["count"]), 3)
        group["placement_ids"].append(row["placement_id"])
        day = _banked_on(row)
        if day and (group["banked_on"] is None or day < group["banked_on"]):
            group["banked_on"] = day

    out = []
    for group in groups.values():
        macros = recipe_macros(group["recipe"], recipes_dir)
        protein = calories = None
        if macros is not None:
            # recipe_macros is macro-shaped; implausible reads an index-shaped dict.
            bad, _reasons = implausible({
                "nutrition_calories": macros.get("calories"),
                "nutrition_protein": macros.get("protein"),
            })
            if not bad:
                protein, calories = macros["protein"], macros["calories"]
        group["protein"] = protein
        group["calories"] = calories
        group["total_protein"] = (
            round(protein * group["servings"], 1) if protein is not None else None)
        group["total_calories"] = (
            round(calories * group["servings"], 1) if calories is not None else None)
        out.append(group)

    # Oldest first: a freezer is FIFO or it's an archaeology site. Undated rows
    # sort last rather than first — "unknown" is not evidence of age.
    out.sort(key=lambda g: (g["banked_on"] or "9999-99-99", g["recipe"]))
    return out


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
    """Per-serving macros + coverage + servings from a recipe's frontmatter, or None.

    Any per-recipe failure (unreadable file, garbage frontmatter like
    ``nutrition_calories: "lots"``) degrades to None — the day shows as
    incomplete instead of the whole board 500ing.

    ``servings`` is carried so a caller can feed the same dict to
    ``nutrition_quality.macro_eligible`` (which gates on it) without a second
    file read; every caller indexes only the keys it knows, so it costs them
    nothing.
    """
    from lib.recipe_parser import parse_recipe_file
    try:
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
            "servings": fm.get("servings") or None,
        }
    except Exception:
        return None


def day_totals(week: str, recipes_dir) -> dict:
    """Per-day macro totals for a week's placed servings.

    Each day carries ``excluded`` — recipes whose stored per-serving macros are
    outside plausible bounds and were therefore left out of the sum rather than
    added to it. Flagging such a day ``incomplete`` while still summing it was
    the old behaviour and it is not enough: two placements of a recipe claiming
    3009 kcal/serving reported a 6018 kcal day, and a warning beside a wrong
    number still leaves the wrong number on screen. This mirrors the
    exclude-and-name contract in ``meal_nutrition.meal_nutrition``.

    The gate is ``nutrition_quality.eligible_macros`` — the same one
    ``meal_nutrition`` applies to a plate's sub-recipes. That shared gate is what
    makes a composite meal's card and its contribution here agree: a plate placed
    on the board is N ordinary cooks, so

        day_totals[date]  ==  meal_nutrition(meal) x outer

    holds exactly, both sides being per-serving macros multiplied by the same
    servings. Two gates would have made the same food report two numbers with
    nothing on screen explaining the difference.

    This is stricter than the bounds-only check it replaces, and the cost is
    real: on the live corpus it excludes 107 further recipes of 403 — 90 for
    coverage below the threshold, 9 for an unknown serving count, 8 for both.
    Coverage fails in the *undercount* direction (unresolved ingredient lines),
    so those days now read low rather than high. That is the honest direction —
    a figure omitted and named beats a figure quietly missing a third of its
    ingredients — but it is only honest if the omission is visible, which is why
    ``week_view`` and ``print_week`` render the ``excluded`` list rather than
    just a warning glyph.

    ``eligible_macros`` is imported inside the function because
    ``nutrition_quality`` imports ``COVERAGE_REVIEW_THRESHOLD`` from this
    module — a module-level import here would be circular.
    """
    from lib.nutrition_quality import eligible_macros

    totals: dict = {}
    macro_cache: dict = {}
    for p in placements_for_week(week):
        day = totals.setdefault(p["date"], {
            "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
            "incomplete": False, "excluded": [],
        })
        name = p["recipe"]
        if name not in macro_cache:
            macro_cache[name] = recipe_macros(name, recipes_dir)
        macros = macro_cache[name]
        # A missing recipe reaches this as None and comes back "missing", so it
        # is named alongside the ones that failed on their numbers rather than
        # flagging the day with nothing to act on.
        eligible, _reasons = eligible_macros(macros)
        if not eligible:
            day["incomplete"] = True
            if name not in day["excluded"]:
                day["excluded"].append(name)
            continue
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
