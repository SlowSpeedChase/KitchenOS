"""Tests for lib/inventory_db.py — schema, trips, purchases, inventory rows."""
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
