"""SQLite store for unified inventory + price history.

Single DB at ``data/kitchenos.db`` (override with ``KITCHENOS_DB`` env var —
tests use this). Three tables:

- ``trips``      one row per receipt (email, photo, manual). ``source_id`` is
                 UNIQUE (Gmail Message-ID or photo hash) so re-ingesting the
                 same receipt is always a no-op.
- ``purchases``  append-only price ledger, one row per receipt line item.
                 Never deleted. ``category='fee'`` rows (tax, totes, tips)
                 count toward spending but never touch inventory.
- ``inventory``  current on-hand stock. The schema enforces case-insensitive
                 uniqueness on (name, unit, location); merging duplicate
                 items is the caller's job (see ``lib/inventory.py``).

All money columns are integer cents.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT 'HEB',
    source TEXT NOT NULL,
    source_id TEXT UNIQUE,
    total_cents INTEGER,
    needs_review INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id),
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    unit_price_cents INTEGER,
    total_cents INTEGER,
    category TEXT NOT NULL DEFAULT 'other',
    for_recipe TEXT
);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT 'ct' COLLATE NOCASE,
    category TEXT NOT NULL DEFAULT 'other',
    location TEXT NOT NULL DEFAULT 'pantry' COLLATE NOCASE,
    purchased TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    notes TEXT NOT NULL DEFAULT '',
    for_recipe TEXT,
    expires TEXT,
    location_source TEXT,
    UNIQUE(name, unit, location)
);
CREATE TABLE IF NOT EXISTS food_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_norm TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    description TEXT,
    per_100g_json TEXT NOT NULL,
    portions_json TEXT,
    density_g_per_ml REAL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(query_norm, source)
);
CREATE TABLE IF NOT EXISTS food_resolution (
    query_norm TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    resolver TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe TEXT NOT NULL,
    week TEXT NOT NULL,
    date TEXT,
    meal TEXT,
    scale REAL NOT NULL DEFAULT 1.0,
    servings_produced REAL NOT NULL,
    cooked_at TEXT,
    notes TEXT,
    -- Verdict on this cook. NULL = not judged yet, which is distinct from 0
    -- ("never again"): most cooks are never judged and that must not read as
    -- a bad review. `notes` is the plan-time note; `cook_note` is written
    -- after eating, so they are deliberately separate columns.
    make_again INTEGER,
    cook_note TEXT,
    -- A composite plate placed on the board expands to one ordinary cook per
    -- sub-recipe, all sharing a bundle_id, so day_totals / the shopping list /
    -- the freezer / cook_history keep seeing "one recipe per row" and need no
    -- bundle awareness at all. `bundle_name` is denormalised on purpose: the
    -- .meal.md file can be renamed or deleted afterwards and the week must
    -- still render what was actually placed. Neither column is in
    -- serving_ledger._COOK_FIELDS, so like `recipe` and `week` they are written
    -- once and immutable. NULL on both means an ordinary standalone cook.
    bundle_id TEXT,
    bundle_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS placements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cook_id INTEGER NOT NULL REFERENCES cooks(id) ON DELETE CASCADE,
    destination TEXT NOT NULL CHECK (destination IN ('slot','freezer','trash')),
    date TEXT,
    meal TEXT,
    count REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_cooks_week ON cooks(week);
CREATE INDEX IF NOT EXISTS idx_placements_cook ON placements(cook_id);
"""

_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes", "for_recipe", "expires",
    "last_used", "use_count",
    "location_source",
)

# Columns added after the original schema shipped. ``connect()`` adds any that
# an existing DB is missing — SQLite ``ADD COLUMN`` is cheap and append-only.
_MIGRATIONS = {
    "inventory": (
        ("for_recipe", "TEXT"), ("expires", "TEXT"),
        # Set when a cook uses a row it cannot safely decrement (a container).
        ("last_used", "TEXT"), ("use_count", "INTEGER NOT NULL DEFAULT 0"),
        # Nullable on purpose: normalize_location_source reads NULL as
        # "default", which is the fail-toward-being-asked direction. A NOT NULL
        # here would also need a _NOT_NULL_FALLBACKS entry.
        ("location_source", "TEXT"),
    ),
    "purchases": (("for_recipe", "TEXT"),),
    "cooks": (("make_again", "INTEGER"), ("cook_note", "TEXT"),
              ("bundle_id", "TEXT"), ("bundle_name", "TEXT")),
}


def db_path() -> Path:
    raw = os.environ.get("KITCHENOS_DB")
    if raw:
        return Path(os.path.expanduser(raw))
    return Path(__file__).resolve().parent.parent / "data" / "kitchenos.db"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the DB, creating file + schema if needed."""
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


@contextmanager
def write_transaction(conn: sqlite3.Connection | None = None):
    """Own one immediate write transaction, or borrow the caller's.

    A borrowed connection is already inside its caller's transaction. It must
    remain open and uncommitted so a larger operation can succeed or roll back
    as one unit.
    """
    if conn is not None:
        yield conn
        return

    owned = connect()
    try:
        owned.execute("BEGIN IMMEDIATE")
        yield owned
        owned.commit()
    except Exception:
        owned.rollback()
        raise
    finally:
        owned.close()


_read_tls = threading.local()


def read_conn() -> sqlite3.Connection:
    """A cached, thread-local connection for read-heavy hot paths (food/portion
    resolution runs per ingredient line). Avoids re-running schema+migrate on
    every call. Reconnects when the configured DB path changes so the per-test
    ``KITCHENOS_DB`` swap still works. Read-only use only — writes still go through
    ``connect()`` so they commit and are visible to all connections."""
    path = str(db_path())
    conn = getattr(_read_tls, "conn", None)
    if conn is None or getattr(_read_tls, "path", None) != path:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = connect()
        _read_tls.conn = conn
        _read_tls.path = path
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from a pre-existing DB (idempotent)."""
    for table, columns in _MIGRATIONS.items():
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for col, decl in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    # Classify rows with no provenance yet. Triggered by the NULLs rather than by
    # having just added the column, because those two are not atomic: ALTER TABLE
    # commits on its own, while the backfill UPDATEs commit at the end of this
    # function. A crash in between left the column present and every row NULL,
    # and a creation-triggered backfill then never ran again — permanently
    # stranding the whole table on "default", with no migration script to rerun.
    # Probing for a NULL is self-healing, also covers two processes racing the
    # first migration, and costs a short-circuiting LIMIT 1 against a table
    # `connect()` already runs executescript + three PRAGMAs over.
    if conn.execute(
        "SELECT 1 FROM inventory WHERE location_source IS NULL LIMIT 1"
    ).fetchone():
        _backfill_location_source(conn)
    # Indexes on migrated columns belong HERE, never in _SCHEMA. connect() runs
    # executescript(_SCHEMA) before this function, so on any pre-existing
    # database the column does not exist yet at that moment — an index on it
    # beside idx_cooks_week would raise "no such column" and break every single
    # connect(), taking inventory, the ledger and the nutrition cache with it.
    # Pinned by tests/test_inventory_db.py::
    # test_a_pre_bundle_database_gains_the_columns_and_the_index.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cooks_bundle ON cooks(bundle_id)")
    conn.commit()


def _backfill_location_source(conn: sqlite3.Connection) -> None:
    """Derive provenance for rows that predate the column.

    Only touches NULLs, so it never re-derives a placement the user has since
    confirmed by hand. Imported lazily: ``storage_locations`` imports
    ``lib.inventory``, which would be a cycle at module scope.
    """
    from lib.storage_locations import place_item

    rows = conn.execute(
        "SELECT id, name, category, location FROM inventory"
        " WHERE location_source IS NULL"
    ).fetchall()
    for r in rows:
        placement = place_item(r["name"], r["category"])
        # If the row is not where the router would put it, the router did not put
        # it there — a person did, and that is `manual`. Stamping the router's
        # own tier would claim a curated override chose this shelf while that
        # override names a different one: `frozen bananas` sits in the freezer,
        # but by_item["bananas"] says counter. Five live rows are like this.
        stored = (r["location"] or "").lower().strip()
        source = (placement.source
                  if placement.location.lower().strip() == stored
                  else "manual")
        conn.execute(
            "UPDATE inventory SET location_source = ? WHERE id = ?",
            (source, r["id"]),
        )


def trip_exists(source_id: str) -> bool:
    if not source_id:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM trips WHERE source_id = ?", (source_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_trip(trip: dict, purchases: list[dict]) -> Optional[int]:
    """Insert a trip and its purchase lines atomically.

    Returns the new trip id, or None if ``source_id`` already exists
    (duplicate receipt — nothing is written).
    """
    conn = connect()
    try:
        with conn:
            try:
                cur = conn.execute(
                    "INSERT INTO trips"
                    " (date, store, source, source_id, total_cents,"
                    "  needs_review, raw_text)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        trip["date"],
                        trip.get("store", "HEB"),
                        trip["source"],
                        trip.get("source_id"),
                        trip.get("total_cents"),
                        1 if trip.get("needs_review") else 0,
                        trip.get("raw_text"),
                    ),
                )
            except sqlite3.IntegrityError as e:
                if "trips.source_id" in str(e):
                    return None
                raise
            trip_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO purchases"
                " (trip_id, raw_name, canonical_name, quantity, unit,"
                "  unit_price_cents, total_cents, category, for_recipe)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        trip_id,
                        p["raw_name"],
                        p["canonical_name"],
                        p.get("quantity"),
                        p.get("unit"),
                        p.get("unit_price_cents"),
                        p.get("total_cents"),
                        p.get("category", "other"),
                        p.get("for_recipe"),
                    )
                    for p in purchases
                ],
            )
        return trip_id
    finally:
        conn.close()


def fetch_inventory_rows() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_INVENTORY_COLS)} FROM inventory"
            " ORDER BY category, name COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_trips(limit: int = 100) -> list[dict]:
    """Recent shopping trips, newest first."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, date, store, source, total_cents, needs_review"
            " FROM trips ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_trip(trip_id: int) -> Optional[dict]:
    """One trip plus its purchase lines, or None if the trip doesn't exist."""
    conn = connect()
    try:
        trip = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if trip is None:
            return None
        purchases = conn.execute(
            "SELECT raw_name, canonical_name, quantity, unit,"
            " unit_price_cents, total_cents, category, for_recipe"
            " FROM purchases WHERE trip_id = ? ORDER BY id",
            (trip_id,),
        ).fetchall()
        return {"trip": dict(trip), "purchases": [dict(p) for p in purchases]}
    finally:
        conn.close()


# Every column the inventory schema declares NOT NULL with a DEFAULT. A caller
# may hand us a dict that omits one — `r.get()` then yields None, and binding an
# explicit NULL violates the constraint even though the column has a DEFAULT
# (the default only applies when the column is left out of the INSERT, and this
# INSERT always names all of them). Tested by `is None` rather than falsiness so
# a legitimate 0 or "" survives.
#
# Keep in sync with _SCHEMA: these values mirror its DEFAULT clauses. A NOT NULL
# column missing from this table is an IntegrityError waiting for the first
# caller that builds a row dict by hand.
_NOT_NULL_FALLBACKS = {
    "unit": "ct",
    "category": "other",
    "location": "pantry",
    "source": "manual",
    "notes": "",
    "use_count": 0,
}


def _inventory_row(row: dict) -> dict:
    """Return a complete row using the same defaults as full replacement."""
    return {
        column: (
            _NOT_NULL_FALLBACKS[column]
            if row.get(column) is None and column in _NOT_NULL_FALLBACKS
            else row.get(column)
        )
        for column in _INVENTORY_COLS
    }


def _merge_recipe_names(existing: str | None, incoming: str | None) -> str | None:
    """Union comma-separated recipe names in first-seen order."""
    names: list[str] = []
    for source in (existing, incoming):
        for part in (source or "").split(","):
            name = part.strip()
            if name and name not in names:
                names.append(name)
    return ", ".join(names) or None


def merge_inventory_rows(
    rows: list[dict], conn: sqlite3.Connection | None = None
) -> dict:
    """Add inventory rows atomically, merging on the case-insensitive key."""
    added = 0
    merged = 0
    placeholders = ", ".join("?" * len(_INVENTORY_COLS))
    upsert = (
        f"INSERT INTO inventory ({', '.join(_INVENTORY_COLS)})"
        f" VALUES ({placeholders})"
        " ON CONFLICT(name, unit, location) DO UPDATE SET"
        " quantity = inventory.quantity + excluded.quantity,"
        " purchased = COALESCE(NULLIF(excluded.purchased, ''), inventory.purchased),"
        " category = CASE WHEN excluded.category <> 'other'"
        " THEN excluded.category ELSE inventory.category END,"
        " notes = CASE WHEN inventory.notes = '' AND excluded.notes <> ''"
        " THEN excluded.notes ELSE inventory.notes END,"
        " for_recipe = excluded.for_recipe,"
        " expires = CASE"
        " WHEN inventory.expires IS NULL THEN excluded.expires"
        " WHEN excluded.expires IS NULL THEN inventory.expires"
        " ELSE MIN(inventory.expires, excluded.expires) END,"
        " location_source = CASE"
        " WHEN CASE excluded.location_source"
        " WHEN 'manual' THEN 3 WHEN 'item' THEN 2"
        " WHEN 'category' THEN 1 ELSE 0 END"
        " > CASE inventory.location_source"
        " WHEN 'manual' THEN 3 WHEN 'item' THEN 2"
        " WHEN 'category' THEN 1 ELSE 0 END"
        " THEN excluded.location_source ELSE inventory.location_source END"
    )

    with write_transaction(conn) as transaction:
        for input_row in rows:
            row = _inventory_row(input_row)
            existing = transaction.execute(
                "SELECT for_recipe FROM inventory"
                " WHERE name = ? AND unit = ? AND location = ?",
                (row["name"], row["unit"], row["location"]),
            ).fetchone()

            if existing is None:
                if not row["purchased"]:
                    row["purchased"] = date.today().isoformat()
                added += 1
            else:
                if not row["purchased"]:
                    row["purchased"] = None
                merged += 1

            row["for_recipe"] = _merge_recipe_names(
                existing["for_recipe"] if existing is not None else None,
                row["for_recipe"],
            )
            transaction.execute(
                upsert, tuple(row[column] for column in _INVENTORY_COLS)
            )

        total = transaction.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        return {"added": added, "merged": merged, "total": total}


def replace_inventory_rows(rows: list[dict]) -> None:
    """Overwrite the inventory table with ``rows`` atomically."""
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM inventory")
            conn.executemany(
                f"INSERT INTO inventory ({', '.join(_INVENTORY_COLS)})"
                f" VALUES ({', '.join('?' * len(_INVENTORY_COLS))})",
                [
                    tuple(
                        _NOT_NULL_FALLBACKS[c]
                        if r.get(c) is None and c in _NOT_NULL_FALLBACKS
                        else r.get(c)
                        for c in _INVENTORY_COLS
                    )
                    for r in rows
                ],
            )
    finally:
        conn.close()


def stamp_inventory_use(refs: list[tuple[str, str]], when: str) -> int:
    """Mark inventory rows as used by a cook. Returns the number updated.

    ``refs`` are ``(name, unit)`` pairs, matched case-insensitively. A targeted
    UPDATE rather than the read-modify-write of ``write_inventory()``, so
    marking a recipe cooked does not rewrite all 222 rows or regenerate the
    Inventory.md and Cook Now.md views. A ref naming no row updates nothing —
    that is expected for a row the same cook just depleted and removed.
    """
    if not refs:
        return 0
    conn = connect()
    try:
        total = 0
        with conn:
            for name, unit in refs:
                # trim() on the DB side too: the Python side is stripped, so a
                # stored name with padding would silently match nothing. That
                # class of desync already bit once (8298c51).
                cur = conn.execute(
                    "UPDATE inventory"
                    " SET last_used = ?, use_count = COALESCE(use_count, 0) + 1"
                    " WHERE trim(lower(name)) = ? AND trim(lower(unit)) = ?",
                    (when, (name or "").lower().strip(),
                     (unit or "").lower().strip()),
                )
                total += cur.rowcount
        return total
    finally:
        conn.close()


# --- Nutrition food-data cache -------------------------------------------------
# Shared across all recipes so an ingredient is looked up / resolved once.
# ``food_cache`` stores normalized per-100g records from USDA/OFF; ``food_resolution``
# remembers which food a given ingredient text resolved to (and the portion grams
# the LLM estimated, keyed ``"<item>|<unit>"`` with resolver ``llm-portion``).


def get_food_cache(query_norm: str, source: str) -> Optional[dict]:
    """Return a cached food record (per_100g + portions parsed), or None."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM food_cache WHERE query_norm = ? AND source = ?",
            (query_norm, source),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = dict(row)
    d["per_100g"] = json.loads(d.pop("per_100g_json"))
    portions = d.pop("portions_json")
    d["portions"] = json.loads(portions) if portions else []
    return d


def put_food_cache(record: dict) -> None:
    """Upsert a food record. ``record`` keys: query_norm, source, source_id,
    description, per_100g (dict), portions (list), density_g_per_ml."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO food_cache"
                " (query_norm, source, source_id, description, per_100g_json,"
                "  portions_json, density_g_per_ml)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(query_norm, source) DO UPDATE SET"
                "  source_id=excluded.source_id, description=excluded.description,"
                "  per_100g_json=excluded.per_100g_json,"
                "  portions_json=excluded.portions_json,"
                "  density_g_per_ml=excluded.density_g_per_ml,"
                "  fetched_at=datetime('now')",
                (
                    record["query_norm"],
                    record["source"],
                    str(record.get("source_id", "")),
                    record.get("description", ""),
                    json.dumps(record["per_100g"]),
                    json.dumps(record.get("portions", [])),
                    record.get("density_g_per_ml"),
                ),
            )
    finally:
        conn.close()


def get_food_resolution(query_norm: str) -> Optional[dict]:
    """Return a remembered ingredient→food resolution, or None."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM food_resolution WHERE query_norm = ?", (query_norm,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def put_food_resolution(
    query_norm: str, source: str, source_id: str,
    confidence: float, resolver: str,
) -> None:
    """Upsert an ingredient→food resolution (or an llm-portion estimate)."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO food_resolution"
                " (query_norm, source, source_id, confidence, resolver)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(query_norm) DO UPDATE SET"
                "  source=excluded.source, source_id=excluded.source_id,"
                "  confidence=excluded.confidence, resolver=excluded.resolver,"
                "  resolved_at=datetime('now')",
                (query_norm, source, str(source_id), confidence, resolver),
            )
    finally:
        conn.close()
