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
"""

_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes", "for_recipe", "expires",
)

# Columns added after the original schema shipped. ``connect()`` adds any that
# an existing DB is missing — SQLite ``ADD COLUMN`` is cheap and append-only.
_MIGRATIONS = {
    "inventory": (("for_recipe", "TEXT"), ("expires", "TEXT")),
    "purchases": (("for_recipe", "TEXT"),),
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
    conn.commit()


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
                    tuple(r.get(c) if c != "notes" else (r.get(c) or "")
                          for c in _INVENTORY_COLS)
                    for r in rows
                ],
            )
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
