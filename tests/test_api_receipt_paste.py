"""API tests for the photo-receipt paste endpoint + prompt endpoint."""
import json
from pathlib import Path

import pytest

from api_server import app
from lib import inventory_db as idb
from lib.receipt_ingest import content_source_id

FIXTURES = Path(__file__).parent / "fixtures"
PARSED_OK = json.loads((FIXTURES / "parsed_ereceipt.json").read_text())


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def alias_tmp(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")


def test_paste_preview_then_commit(client, tmp_db, tmp_vault, alias_tmp):
    body = {"json": json.dumps(PARSED_OK)}
    sid = content_source_id(PARSED_OK)

    r = client.post("/api/receipt/paste", json=body)
    assert r.status_code == 200
    data = r.get_json()
    assert data["mode"] == "preview"
    assert data["count"] == 4
    assert not idb.trip_exists(sid)  # preview writes nothing

    r2 = client.post("/api/receipt/paste", json={**body, "commit": True})
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["mode"] == "committed"
    assert d2["status"] == "ingested"
    assert idb.trip_exists(sid)


def test_paste_missing_body_400(client, tmp_db, tmp_vault):
    assert client.post("/api/receipt/paste", json={}).status_code == 400


def test_paste_bad_json_400(client, tmp_db, tmp_vault):
    r = client.post("/api/receipt/paste", json={"json": "nope"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_prompt_endpoint_returns_schema(client):
    r = client.get("/api/receipt/prompt")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "raw_name" in text and "canonical_name" in text
