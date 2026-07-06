"""Tests for ledger + week-board API routes."""

import json
import sqlite3

import pytest

from api_server import app
from lib import serving_ledger


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def _create_cook(client, **over):
    body = dict(recipe="Chili", week="2026-W28", scale=1.5,
                servings_produced=6.0, date="2026-07-07", meal="dinner")
    body.update(over)
    return client.post("/api/cooks", json=body)


def test_create_and_board(client, tmp_db, tmp_vault):
    resp = _create_cook(client)
    assert resp.status_code == 201
    cook = resp.get_json()
    assert cook["unassigned"] == 5.0

    board = client.get("/api/week-board/2026-W28").get_json()
    assert len(board["cooks"]) == 1
    assert board["week"] == "2026-W28"


def test_overplacement_returns_409(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 99})
    assert resp.status_code == 409


def test_bad_destination_returns_400(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "compost", "count": 1})
    assert resp.status_code == 400


def test_move_endpoint(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    frozen = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 3}).get_json()
    resp = client.post(f"/api/placements/{frozen['id']}/move", json={
        "count": 2, "destination": "slot",
        "date": "2026-07-14", "meal": "lunch"})
    assert resp.status_code == 200
    assert resp.get_json()["to"]["count"] == 2.0


def test_mutations_regenerate_markdown(client, tmp_db, tmp_vault):
    _create_cook(client)
    plan = tmp_vault / "Meal Plans" / "2026-W28.md"
    assert plan.exists()
    assert "[[Chili]] x1.5" in plan.read_text(encoding="utf-8")


def test_week_board_invalid_week_400(client, tmp_db, tmp_vault):
    assert client.get("/api/week-board/garbage").status_code == 400


def test_ledger_busy_returns_503(client, tmp_db, tmp_vault, monkeypatch):
    """A concurrent writer holding the write lock surfaces as 503, not 500."""
    cook = _create_cook(client).get_json()

    def _locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(serving_ledger, "add_placement", _locked)
    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 1})
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "ledger busy, retry"
