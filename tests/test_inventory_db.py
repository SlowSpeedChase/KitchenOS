"""Tests for lib/inventory_db.py — schema, trips, purchases, inventory rows."""
from datetime import date
import sqlite3

import pytest

from lib import inventory_db as idb


def test_connect_creates_schema(tmp_db):
    conn = idb.connect()
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert {"trips", "purchases", "inventory"} <= tables


def test_record_trip_and_dedup(tmp_db):
    trip = {
        "date": "2026-06-09",
        "store": "HEB",
        "source": "email_receipt",
        "source_id": "<msg-123@heb.com>",
        "total_cents": 4523,
    }
    purchases = [
        {"raw_name": "HCF BNLS SKNLS BRST", "canonical_name": "chicken breast",
         "quantity": 2.1, "unit": "lb", "unit_price_cents": 549,
         "total_cents": 1153, "category": "meat"},
        {"raw_name": "TX SALES TAX", "canonical_name": "sales tax",
         "quantity": 1, "unit": "ct", "unit_price_cents": 370,
         "total_cents": 370, "category": "fee"},
    ]
    trip_id = idb.record_trip(trip, purchases)
    assert isinstance(trip_id, int)
    assert idb.trip_exists("<msg-123@heb.com>") is True

    # Same source_id again → no-op, returns None, no duplicate rows
    assert idb.record_trip(trip, purchases) is None
    conn = idb.connect()
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 2
    conn.close()


def test_record_trip_raises_on_bad_data(tmp_db):
    # A NOT NULL violation (date=None) must surface, not be swallowed
    # as a "duplicate receipt" None return.
    with pytest.raises(sqlite3.IntegrityError):
        idb.record_trip(
            {"date": None, "source": "manual", "source_id": "<x@y>"}, []
        )


def test_trip_exists_false_for_unknown(tmp_db):
    assert idb.trip_exists("<nope>") is False


def test_needs_review_trip_keeps_raw_text(tmp_db):
    trip = {
        "date": "2026-06-09", "store": "HEB", "source": "email_curbside",
        "source_id": "<msg-456@heb.com>", "total_cents": None,
        "needs_review": True, "raw_text": "garbled receipt text",
    }
    trip_id = idb.record_trip(trip, [])
    conn = idb.connect()
    row = conn.execute(
        "SELECT needs_review, raw_text FROM trips WHERE id=?", (trip_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] == "garbled receipt text"


def test_inventory_rows_roundtrip(tmp_db):
    rows = [
        {"name": "Chicken breast", "quantity": 2.0, "unit": "lb",
         "category": "meat", "location": "fridge", "purchased": "2026-06-09",
         "source": "receipt", "notes": ""},
    ]
    idb.replace_inventory_rows(rows)
    out = idb.fetch_inventory_rows()
    assert len(out) == 1
    assert out[0]["name"] == "Chicken breast"
    assert out[0]["quantity"] == 2.0
    assert out[0]["location"] == "fridge"


def test_merge_inventory_rows_preserves_compatibility_semantics(tmp_db):
    """The SQL merge must stay behaviorally identical to add_items' old merge."""
    idb.replace_inventory_rows([
        {
            "name": "Yogurt",
            "quantity": 1.0,
            "unit": "ct",
            "category": "other",
            "location": "fridge",
            "purchased": "2026-08-01",
            "source": "manual",
            "notes": "keep existing note",
            "for_recipe": "Parfait, Smoothie",
            "expires": "2026-08-30",
            "location_source": "category",
        },
    ])

    result = idb.merge_inventory_rows([
        {
            "name": "YOGURT",
            "quantity": 2.0,
            "unit": "CT",
            "category": "dairy",
            "location": "FRIDGE",
            "purchased": "2026-08-20",
            "source": "receipt",
            "notes": "discard incoming note",
            "for_recipe": "Smoothie, Labneh",
            "expires": "2026-08-25",
            "location_source": "manual",
        },
        {
            "name": "Rice",
            "quantity": 1.0,
            "unit": "lb",
            "category": "pantry",
            "location": "pantry",
            "source": "manual",
            "notes": "",
            "location_source": "item",
        },
    ])

    assert result == {"added": 1, "merged": 1, "total": 2}
    by_name = {row["name"].lower(): row for row in idb.fetch_inventory_rows()}
    yogurt = by_name["yogurt"]
    assert yogurt["quantity"] == 3.0
    assert yogurt["purchased"] == "2026-08-20"
    assert yogurt["notes"] == "keep existing note"
    assert yogurt["category"] == "dairy"
    assert yogurt["location_source"] == "manual"
    assert yogurt["for_recipe"] == "Parfait, Smoothie, Labneh"
    assert yogurt["expires"] == "2026-08-25"
    assert by_name["rice"]["purchased"] == date.today().isoformat()


def test_merge_inventory_rows_borrows_without_committing_or_closing(tmp_db):
    conn = idb.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        idb.merge_inventory_rows(
            [{"name": "Milk", "quantity": 1.0}], conn=conn
        )

        assert conn.in_transaction is True
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0
    finally:
        conn.close()


def test_every_not_null_column_has_a_fallback(tmp_db):
    """_NOT_NULL_FALLBACKS must cover the schema, or a hand-built row dict
    omitting a NOT NULL column raises IntegrityError.

    replace_inventory_rows names every column in the INSERT, so a column's
    DEFAULT never applies — an omitted key binds an explicit NULL. Derived from
    the live schema so adding a NOT NULL column fails here rather than in
    production.
    """
    conn = idb.connect()
    try:
        required = {
            r["name"] for r in conn.execute("PRAGMA table_info(inventory)")
            if r["notnull"] and r["dflt_value"] is not None
        }
    finally:
        conn.close()

    missing = required - set(idb._NOT_NULL_FALLBACKS)
    assert not missing, f"NOT NULL columns with no fallback: {sorted(missing)}"


def test_a_row_dict_omitting_defaulted_columns_still_inserts(tmp_db):
    """The minimum a caller can hand us: name and quantity."""
    idb.replace_inventory_rows([{"name": "Sparse", "quantity": 1.0}])
    [out] = idb.fetch_inventory_rows()
    assert out["name"] == "Sparse"
    assert out["unit"] == "ct"
    assert out["category"] == "other"
    assert out["location"] == "pantry"
    assert out["source"] == "manual"
    assert out["notes"] == ""
    assert out["use_count"] == 0


def test_location_source_is_added_to_a_db_that_predates_it(tmp_db):
    """An existing DB gains the column, and its rows get classified once."""
    import sqlite3

    conn = sqlite3.connect(tmp_db)
    conn.execute("""CREATE TABLE inventory (
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
        UNIQUE(name, unit, location))""")
    conn.executemany(
        "INSERT INTO inventory (name, quantity, category, location)"
        " VALUES (?, ?, ?, ?)",
        [("bananas", 1, "produce", "counter"),
         ("whole milk", 1, "dairy", "fridge"),
         ("psyllium husk", 1, "other", "pantry")],
    )
    conn.commit()
    conn.close()

    conn = idb.connect()
    try:
        got = {r["name"]: r["location_source"]
               for r in conn.execute("SELECT name, location_source FROM inventory")}
    finally:
        conn.close()

    assert got == {
        "bananas": "item",          # by_item override
        "whole milk": "category",   # dairy -> fridge
        "psyllium husk": "default",  # catch-all category, so not an answer
    }


def test_backfill_never_re_derives_a_hand_placed_row(tmp_db):
    """Re-running the migration must not overwrite a confirmed placement."""
    conn = idb.connect()
    conn.execute(
        "INSERT INTO inventory (name, quantity, category, location, location_source)"
        " VALUES ('bananas', 1, 'produce', 'freezer', 'manual')"
    )
    conn.commit()
    conn.close()

    idb.connect().close()   # migration runs again

    conn = idb.connect()
    try:
        row = conn.execute(
            "SELECT location_source FROM inventory WHERE name = 'bananas'"
        ).fetchone()
    finally:
        conn.close()
    assert row["location_source"] == "manual"


def test_backfill_recovers_from_an_interrupted_run(tmp_db, monkeypatch):
    """ALTER TABLE commits immediately; the backfill UPDATEs commit at the end.
    A crash between them left the column present and every row NULL — and a
    creation-triggered backfill never fires again, stranding the whole table on
    "default" permanently. The trigger must be the NULLs, not the ALTER."""
    import sqlite3

    from lib import storage_locations

    conn = sqlite3.connect(tmp_db)
    conn.execute("""CREATE TABLE inventory (
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
        UNIQUE(name, unit, location))""")
    conn.executemany(
        "INSERT INTO inventory (name, quantity, category, location)"
        " VALUES (?, ?, ?, ?)",
        [("bananas", 1, "produce", "counter"),
         ("whole milk", 1, "dairy", "fridge")],
    )
    conn.commit()
    conn.close()

    real = storage_locations.place_item
    monkeypatch.setattr(
        storage_locations, "place_item",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash mid-backfill")))
    with pytest.raises(RuntimeError):
        idb.connect().close()
    monkeypatch.setattr(storage_locations, "place_item", real)

    # The next connect must finish the job rather than skip it forever.
    conn = idb.connect()
    try:
        got = {r["name"]: r["location_source"]
               for r in conn.execute("SELECT name, location_source FROM inventory")}
    finally:
        conn.close()
    assert got == {"bananas": "item", "whole milk": "category"}


def test_backfill_marks_a_row_the_router_disagrees_with_as_manual(tmp_db):
    """If a row isn't where the router would put it, the router didn't put it
    there — a person did. Stamping the router's tier would claim a curated
    override chose this shelf while that override names a different one.

    Live data has five such rows: `frozen bananas` sits in the freezer, but
    `by_item["bananas"]` says counter.
    """
    conn = idb.connect()
    conn.execute(
        "INSERT INTO inventory (name, quantity, category, location, location_source)"
        " VALUES ('frozen bananas', 1, 'frozen', 'freezer', NULL)"
    )
    conn.commit()
    conn.close()

    idb.connect().close()   # trigger the backfill

    conn = idb.connect()
    try:
        row = conn.execute(
            "SELECT location, location_source FROM inventory"
            " WHERE name = 'frozen bananas'"
        ).fetchone()
    finally:
        conn.close()
    assert row["location"] == "freezer"
    assert row["location_source"] == "manual", (
        "a row the router would place elsewhere was stamped as router-placed"
    )


# --- Bundle columns --------------------------------------------------------
#
# A composite plate placed on the board expands to one ordinary cook per
# sub-recipe, all sharing a bundle id. See lib/meal_bundle.py.

def test_cooks_carries_the_bundle_columns(tmp_db):
    conn = idb.connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cooks)")}
    finally:
        conn.close()
    assert {"bundle_id", "bundle_name"} <= cols


def test_a_pre_bundle_database_gains_the_columns_and_the_index(tmp_db):
    """The migration path, which is the one that runs on the live DB.

    `connect()` runs `executescript(_SCHEMA)` *before* `_migrate`, so the
    `cooks` table has no `bundle_id` at the moment _SCHEMA executes. Putting
    `CREATE INDEX ... ON cooks(bundle_id)` in _SCHEMA beside `idx_cooks_week`
    therefore raises "no such column" and breaks **every** connect() on an
    existing database — inventory, ledger and nutrition cache alike. The index
    has to be created after the ALTERs, and this test is what pins that.
    """
    # Build a database the way it looked before the bundle columns existed.
    conn = sqlite3.connect(tmp_db)
    conn.executescript("""
        CREATE TABLE cooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe TEXT NOT NULL,
            week TEXT NOT NULL,
            date TEXT,
            meal TEXT,
            scale REAL NOT NULL DEFAULT 1.0,
            servings_produced REAL NOT NULL,
            cooked_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO cooks (recipe, week, servings_produced) VALUES ('Chili', '2026-W28', 4.0);
    """)
    conn.commit()
    conn.close()

    conn = idb.connect()          # must not raise
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cooks)")}
        indexes = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        row = conn.execute("SELECT recipe, bundle_id FROM cooks").fetchone()
    finally:
        conn.close()

    assert {"bundle_id", "bundle_name"} <= cols
    assert "idx_cooks_bundle" in indexes
    # The pre-existing row survives, unbundled.
    assert row["recipe"] == "Chili"
    assert row["bundle_id"] is None
