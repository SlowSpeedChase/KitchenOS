"""Tests for the price dashboard generator."""
from lib import inventory_db as idb
from lib.price_dashboard import generate_dashboard


def _seed(tmp_db):
    idb.record_trip(
        {"date": "2026-06-02", "store": "HEB", "source": "email_receipt",
         "source_id": "<a>", "total_cents": 1000},
        [{"raw_name": "MILK", "canonical_name": "whole milk", "quantity": 1,
          "unit": "gal", "unit_price_cents": 398, "total_cents": 398,
          "category": "dairy"},
         {"raw_name": "TAX", "canonical_name": "sales tax", "quantity": 1,
          "unit": "ct", "unit_price_cents": 50, "total_cents": 50,
          "category": "fee"}],
    )
    idb.record_trip(
        {"date": "2026-06-09", "store": "HEB", "source": "email_receipt",
         "source_id": "<b>", "total_cents": 1200},
        [{"raw_name": "MILK", "canonical_name": "whole milk", "quantity": 1,
          "unit": "gal", "unit_price_cents": 425, "total_cents": 425,
          "category": "dairy"}],
    )
    idb.record_trip(
        {"date": "2026-06-09", "store": "HEB", "source": "email_curbside",
         "source_id": "<c>", "total_cents": None, "needs_review": True,
         "raw_text": "garbled"},
        [],
    )


def test_dashboard_sections(tmp_vault, tmp_db):
    _seed(tmp_db)
    md = generate_dashboard(today="2026-06-10")
    assert "# Price Tracker" in md
    assert "## Spending" in md
    assert "## Price Trends" in md
    assert "whole milk" in md
    assert "$4.25" in md          # latest price
    assert "▲" in md              # price went up vs average
    assert "## Needs Review" in md
    assert "<c>" in md or "curbside" in md


def test_dashboard_spending_totals(tmp_vault, tmp_db):
    _seed(tmp_db)
    md = generate_dashboard(today="2026-06-10")
    assert "$10.00" in md or "$12.00" in md or "$22.00" in md


def test_dashboard_survives_malformed_trip_date(tmp_vault, tmp_db):
    idb.record_trip(
        {"date": "06/09/2026", "store": "HEB", "source": "email_receipt",
         "source_id": "<bad-date>", "total_cents": 500},
        [{"raw_name": "EGGS", "canonical_name": "eggs", "quantity": 1,
          "unit": "ct", "unit_price_cents": 500, "total_cents": 500,
          "category": "dairy"}],
    )
    md = generate_dashboard(today="2026-06-10")
    assert "# Price Tracker" in md


def test_save_dashboard_writes_file(tmp_vault, tmp_db):
    _seed(tmp_db)
    from lib.price_dashboard import save_dashboard
    path = save_dashboard(today="2026-06-10")
    assert path.name == "Price Tracker.md"
    assert path.exists()
