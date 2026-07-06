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
    assert resp.get_json()["error"] == "week already has ledger rows"


def test_import_legacy_409_when_foreign_placement_exists(client, tmp_db, tmp_vault):
    """A week with no cooks but a foreign slot placement (leftover dragged in)
    is already ledger-rendered — importing its leftover line would duplicate it."""
    cook = _create_cook(client).get_json()          # anchored in 2026-W28
    client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "slot",
        "date": "2026-07-14", "meal": "lunch", "count": 1})  # lands in 2026-W29
    _write_legacy_plan(tmp_vault, "2026-W29",
                       "## Monday (Jul 13)\n### Breakfast\n### Lunch\n"
                       "### Snack\n### Dinner\n[[Chili]] (leftover x1)\n"
                       "### Notes\n")
    resp = client.post("/api/week-board/2026-W29/import-legacy")
    assert resp.status_code == 409


def test_import_legacy_skips_leftover_lines(client, tmp_db, tmp_vault):
    """Even when import runs on a file containing a '(leftover xN)' line and
    the week has no ledger rows, no cook is created from that line."""
    _write_legacy_plan(tmp_vault, "2026-W29",
                       "## Monday (Jul 13)\n### Breakfast\n### Lunch\n"
                       "### Snack\n### Dinner\n[[Chili]] (leftover x1)\n"
                       "### Notes\n")
    resp = client.post("/api/week-board/2026-W29/import-legacy")
    assert resp.status_code == 200
    assert resp.get_json()["imported"] == []
    board = client.get("/api/week-board/2026-W29").get_json()
    assert board["cooks"] == []


def test_import_legacy_invalid_week_400(client, tmp_db, tmp_vault):
    resp = client.post("/api/week-board/garbage/import-legacy")
    assert resp.status_code == 400


# --- C1: first ledger write into a legacy week must import-then-render -------

LEGACY_W28 = (
    "# Meal Plan - Week 28\n\n"
    "## Monday (Jul 6)\n"
    "### Breakfast\n### Lunch\n### Snack\n"
    "### Dinner\n[[Chili]] x2\n"
    "### Notes\nPrep beans overnight\n\n"
    "## Tuesday (Jul 7)\n"
    "### Breakfast\n### Lunch\n### Snack\n### Dinner\n### Notes\n\n")


def _write_legacy_plan(tmp_vault, week, body):
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True, exist_ok=True)
    f = plans / f"{week}.md"
    f.write_text(body, encoding="utf-8")
    return f


def test_first_cook_into_legacy_week_imports_and_backs_up(client, tmp_db, tmp_vault):
    """Creating the first ledger row in a hand-edited week converts the
    week's [[links]] into cooks (with a backup) instead of clobbering them."""
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    (recipes / "Chili.md").write_text(
        "---\nservings: 4\n---\n\nChili.\n", encoding="utf-8")
    plan = _write_legacy_plan(tmp_vault, "2026-W28", LEGACY_W28)

    resp = _create_cook(client, recipe="Soup", date="2026-07-08", meal="lunch")
    assert resp.status_code == 201

    board = client.get("/api/week-board/2026-W28").get_json()
    by_recipe = {c["recipe"]: c for c in board["cooks"]}
    assert set(by_recipe) == {"Chili", "Soup"}
    assert by_recipe["Chili"]["scale"] == 2.0
    assert by_recipe["Chili"]["servings_produced"] == 8.0

    text = plan.read_text(encoding="utf-8")
    assert "[[Chili]] x2" in text          # hand-edited link preserved as a cook
    assert "[[Soup]]" in text

    backups = list((tmp_vault / "Meal Plans" / ".history").glob("2026-W28_*.md"))
    assert len(backups) == 1
    assert "Prep beans overnight" in backups[0].read_text(encoding="utf-8")


def test_placement_move_into_legacy_week_imports_first(client, tmp_db, tmp_vault):
    """Dragging a frozen serving into a hand-edited week's slot converts
    that week before the mutation renders over it."""
    cook = _create_cook(client).get_json()          # 2026-W28
    frozen = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 2}).get_json()
    plan = _write_legacy_plan(
        tmp_vault, "2026-W29",
        "## Monday (Jul 13)\n### Breakfast\n### Lunch\n### Snack\n"
        "### Dinner\n[[Stew]]\n### Notes\n")

    resp = client.post(f"/api/placements/{frozen['id']}/move", json={
        "count": 1, "destination": "slot",
        "date": "2026-07-14", "meal": "lunch"})
    assert resp.status_code == 200

    text = plan.read_text(encoding="utf-8")
    assert "[[Stew]]" in text                       # legacy link survived
    assert "[[Chili]] (leftover x1)" in text        # the dropped serving
    assert list((tmp_vault / "Meal Plans" / ".history").glob("2026-W29_*.md"))


def test_placement_create_into_legacy_week_imports_first(client, tmp_db, tmp_vault):
    """An unassigned serving placed into a hand-edited week's slot converts
    that week before the mutation renders over it."""
    cook = _create_cook(client).get_json()          # 2026-W28, 5 unassigned
    plan = _write_legacy_plan(
        tmp_vault, "2026-W29",
        "## Monday (Jul 13)\n### Breakfast\n### Lunch\n### Snack\n"
        "### Dinner\n[[Stew]]\n### Notes\n")

    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "slot",
        "date": "2026-07-13", "meal": "dinner", "count": 1})
    assert resp.status_code == 201

    text = plan.read_text(encoding="utf-8")
    assert "[[Stew]]" in text
    assert "[[Chili]] (leftover x1)" in text


# --- C2: deleting the last ledger row leaves a clean empty skeleton ----------

def test_delete_last_cook_writes_empty_skeleton(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    plan = tmp_vault / "Meal Plans" / "2026-W28.md"
    assert "[[Chili]]" in plan.read_text(encoding="utf-8")

    resp = client.delete(f"/api/cooks/{cook['id']}")
    assert resp.status_code == 200

    text = plan.read_text(encoding="utf-8")
    assert "[[" not in text        # no phantom links for the grocery fallback
    assert "## Monday" in text and "### Dinner" in text


# --- I4: garbage recipe frontmatter must not 500 the board -------------------

def test_week_board_garbage_nutrition_returns_json_not_500(client, tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    (recipes / "Garbage Stew.md").write_text(
        "---\nservings: 4\nnutrition_calories: \"lots\"\n---\n\nMystery.\n",
        encoding="utf-8")
    _create_cook(client, recipe="Garbage Stew")
    resp = client.get("/api/week-board/2026-W28")
    assert resp.status_code == 200
    board = resp.get_json()
    assert board["day_totals"]["2026-07-07"]["incomplete"] is True


# --- I5: legacy PUT must not clobber a ledger-managed week --------------------

def test_meal_plan_put_409_when_ledger_owns_week(client, tmp_db, tmp_vault):
    _create_cook(client)
    resp = client.put("/api/meal-plan/2026-W28", json={
        "week": "2026-W28", "days": []})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "week is ledger-managed"
