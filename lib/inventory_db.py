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
    category TEXT NOT NULL DEFAULT 'other'
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
    UNIQUE(name, unit, location)
);
"""

_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes",
)


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
    return conn


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
                "  unit_price_cents, total_cents, category)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
