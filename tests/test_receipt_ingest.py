"""Tests for the shared receipt-ingest engine + the JSON-paste front door."""
import json
from pathlib import Path

import pytest

from lib import inventory_db as idb
from lib import receipt_ingest as ri
from lib.inventory import read_inventory

FIXTURES = Path(__file__).parent / "fixtures"
PARSED_OK = json.loads((FIXTURES / "parsed_ereceipt.json").read_text())


@pytest.fixture
def alias_tmp(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")


# --- ingest_parsed: the shared tail --------------------------------------

def test_ingest_parsed_writes_trip_and_inventory(tmp_vault, tmp_db, alias_tmp):
    res = ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt", source_id="photo-x")
    assert res["status"] == "ingested"
    assert idb.trip_exists("photo-x")
    names = {it.name for it in read_inventory()}
    assert "chicken breast" in names
    assert "sales tax" not in names  # fee lines never touch inventory


def test_ingest_parsed_dedups_on_source_id(tmp_vault, tmp_db, alias_tmp):
    ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt", source_id="photo-x")
    res = ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt", source_id="photo-x")
    assert res["status"] == "skipped"


def test_ingest_parsed_dry_run_writes_nothing(tmp_vault, tmp_db, alias_tmp):
    res = ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt",
                           source_id="photo-x", dry_run=True)
    assert res["status"] == "ingested"
    assert res["items"] and res["items"][0]["location"]  # routed preview present
    assert not idb.trip_exists("photo-x")


def test_ingest_parsed_bad_total_flags_needs_review(tmp_vault, tmp_db, alias_tmp):
    bad = dict(PARSED_OK, total=999.99)
    res = ri.ingest_parsed(bad, source="photo_receipt", source_id="photo-bad",
                           raw_text='{"json":true}')
    assert res["status"] == "needs_review"
    assert res["problems"]
    assert read_inventory() == []  # flagged trips don't touch inventory
    conn = idb.connect()
    row = conn.execute("SELECT needs_review, raw_text FROM trips").fetchone()
    conn.close()
    assert row[0] == 1 and row[1]


# --- preview / commit: the JSON paste helpers ----------------------------

def test_preview_no_writes_and_flags_already_ingested(tmp_vault, tmp_db, alias_tmp):
    text = json.dumps(PARSED_OK)
    res = ri.preview(text)
    assert "error" not in res
    assert res["count"] == len(PARSED_OK["items"])
    assert res["already_ingested"] is False
    assert not idb.trip_exists(ri.content_source_id(PARSED_OK))
    ri.commit(text)
    assert ri.preview(text)["already_ingested"] is True


def test_commit_writes_and_dedups(tmp_vault, tmp_db, alias_tmp):
    text = json.dumps(PARSED_OK)
    assert ri.commit(text)["status"] == "ingested"
    assert idb.trip_exists(ri.content_source_id(PARSED_OK))
    assert ri.commit(text)["status"] == "skipped"


def test_bad_json_returns_error(tmp_vault, tmp_db, alias_tmp):
    assert "error" in ri.preview("not json at all")
    assert "error" in ri.commit("{broken")


def test_parse_pasted_json_tolerates_code_fences():
    text = "Here you go:\n```json\n" + json.dumps(PARSED_OK) + "\n```"
    parsed = ri.parse_pasted_json(text)
    assert parsed["date"] == "2026-06-09"
    assert len(parsed["items"]) == 4


def test_content_source_id_is_stable_and_content_derived():
    a = ri.content_source_id(PARSED_OK)
    b = ri.content_source_id(dict(PARSED_OK))
    assert a == b and a.startswith("photo-")
    assert ri.content_source_id(dict(PARSED_OK, total=5.00)) != a
