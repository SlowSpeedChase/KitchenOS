"""End-to-end ingest tests with mocked email fetch + Ollama."""
import json
from pathlib import Path

import pytest

import ingest_receipts as ir
from lib import inventory_db as idb
from lib.inventory import read_inventory

FIXTURES = Path(__file__).parent / "fixtures"

PARSED_OK = json.loads((FIXTURES / "parsed_ereceipt.json").read_text())


@pytest.fixture(autouse=True)
def _stub_csa(monkeypatch):
    """Keep receipt-ingest tests hermetic: the run() tail also pulls CSA
    newsletters over the network — stub that out here."""
    import ingest_csa
    monkeypatch.setattr(ingest_csa, "run", lambda *a, **k: {"ingested": 0})


@pytest.fixture
def alias_tmp(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")


def _email(msg_id="<m1@heb.com>"):
    return {
        "message_id": msg_id,
        "from": "receipts@heb.com",
        "subject": "Your H-E-B eReceipt",
        "date": "Mon, 09 Jun 2026 18:00:00 -0500",
        "html": (FIXTURES / "heb_ereceipt.html").read_text(),
    }


def test_ingest_writes_trip_purchases_inventory(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(
        ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK)
    )
    summary = ir.ingest()
    assert summary["ingested"] == 1
    assert idb.trip_exists("<m1@heb.com>")
    names = {it.name for it in read_inventory()}
    assert "chicken breast" in names
    assert "sales tax" not in names  # fee lines never touch inventory
    # Inventory.md view regenerated
    assert (tmp_vault / "Inventory.md").exists()


def test_ingest_skips_already_processed(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK))
    ir.ingest()
    summary = ir.ingest()
    assert summary["ingested"] == 0
    assert summary["skipped"] == 1


def test_ingest_invalid_receipt_flags_needs_review(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    bad = dict(PARSED_OK, total=999.99)
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email("<m2@heb.com>")])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: bad)
    summary = ir.ingest()
    assert summary["needs_review"] == 1
    assert read_inventory() == []  # no inventory updates for flagged trips
    conn = idb.connect()
    row = conn.execute("SELECT needs_review, raw_text FROM trips").fetchone()
    conn.close()
    assert row[0] == 1 and row[1]


def test_ingest_dry_run_writes_nothing(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK))
    summary = ir.ingest(dry_run=True)
    assert summary["ingested"] == 1  # counted, not written
    assert not idb.trip_exists("<m1@heb.com>")


def test_ingest_dedups_emails_without_message_id(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    email = _email(msg_id="")
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [email])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK))
    assert ir.ingest()["ingested"] == 1
    summary = ir.ingest()  # same content refetched
    assert summary["ingested"] == 0
    assert summary["skipped"] == 1
