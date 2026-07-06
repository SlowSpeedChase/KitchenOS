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


def test_cook_create_regenerates_both_weeks_on_cross_week_date(client, tmp_db, tmp_vault):
    """cook.week and the week implied by `date` can differ; both must regen."""
    resp = _create_cook(client, week="2026-W28", date="2026-07-14")  # W28 -> W29
    assert resp.status_code == 201
    week_file = tmp_vault / "Meal Plans" / "2026-W28.md"
    cross_week_file = tmp_vault / "Meal Plans" / "2026-W29.md"
    assert week_file.exists()
    assert cross_week_file.exists()


def test_placement_patch_moving_date_regenerates_old_week(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    placement = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "slot",
        "date": "2026-07-07", "meal": "lunch", "count": 1}).get_json()

    old_week_file = tmp_vault / "Meal Plans" / "2026-W28.md"
    old_week_file.unlink()
    assert not old_week_file.exists()

    resp = client.patch(f"/api/placements/{placement['id']}", json={
        "date": "2026-07-14", "meal": "lunch"})  # moves into 2026-W29
    assert resp.status_code == 200
    assert old_week_file.exists(), "old week's markdown should be regenerated"
    assert (tmp_vault / "Meal Plans" / "2026-W29.md").exists()


def test_placement_create_unknown_cook_returns_404(client, tmp_db, tmp_vault):
    resp = client.post("/api/placements", json={
        "cook_id": 999999, "destination": "freezer", "count": 1})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "cook not found"


def test_placement_patch_unknown_id_returns_404(client, tmp_db, tmp_vault):
    resp = client.patch("/api/placements/999999", json={"count": 1})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "placement not found"


def test_placement_move_unknown_id_returns_404(client, tmp_db, tmp_vault):
    resp = client.post("/api/placements/999999/move", json={
        "count": 1, "destination": "freezer"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "placement not found"


def test_cook_create_null_scale_returns_400(client, tmp_db, tmp_vault):
    resp = _create_cook(client, scale=None)
    assert resp.status_code == 400


def test_import_legacy_week(client, tmp_db, tmp_vault):
    """A week's Markdown with [[links]] but no ledger cooks imports on demand:
    one cook per filled slot, scale = the entry's servings multiplier."""
    recipes_dir = tmp_vault / "Recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    (recipes_dir / "Chili.md").write_text(
        "---\nservings: 4\n---\n\nSome chili.\n", encoding="utf-8")

    plans_dir = tmp_vault / "Meal Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "2026-W28.md").write_text(
        "# Meal Plan\n\n"
        "## Monday (Jul 6)\n"
        "### Breakfast\n"
        "### Lunch\n"
        "### Snack\n"
        "### Dinner\n"
        "[[Chili]] x2\n"
        "### Notes\n\n"
        "## Tuesday (Jul 7)\n"
        "### Breakfast\n"
        "### Lunch\n"
        "### Snack\n"
        "### Dinner\n"
        "### Notes\n\n",
        encoding="utf-8")

    resp = client.post("/api/week-board/2026-W28/import-legacy")
    assert resp.status_code == 200
    assert len(resp.get_json()["imported"]) == 1

    board = client.get("/api/week-board/2026-W28").get_json()
    assert len(board["cooks"]) == 1
    cook = board["cooks"][0]
    assert cook["recipe"] == "Chili"
    assert cook["scale"] == 2.0
    assert cook["servings_produced"] == 8.0
    assert cook["meal"] == "dinner"
    # Legacy assumption: all produced servings are placed at that slot.
    assert cook["unassigned"] == 0.0


def test_import_legacy_falls_back_to_default_servings(client, tmp_db, tmp_vault):
    """No frontmatter servings on the recipe file -> base servings default to 4."""
    plans_dir = tmp_vault / "Meal Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "2026-W29.md").write_text(
        "## Monday (Jul 13)\n### Breakfast\n### Lunch\n### Snack\n"
        "### Dinner\n[[Mystery Stew]]\n### Notes\n\n",
        encoding="utf-8")

    resp = client.post("/api/week-board/2026-W29/import-legacy")
    assert resp.status_code == 200

    board = client.get("/api/week-board/2026-W29").get_json()
    cook = board["cooks"][0]
    assert cook["scale"] == 1.0
    assert cook["servings_produced"] == 4.0


def test_import_legacy_already_has_cooks_returns_409(client, tmp_db, tmp_vault):
    """Idempotence guard: a week the ledger already owns must not be re-imported."""
    _create_cook(client, week="2026-W28")
    resp = client.post("/api/week-board/2026-W28/import-legacy")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "week already has cooks"


def test_import_legacy_invalid_week_400(client, tmp_db, tmp_vault):
    resp = client.post("/api/week-board/garbage/import-legacy")
    assert resp.status_code == 400
