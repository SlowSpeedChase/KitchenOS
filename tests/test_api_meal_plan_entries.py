"""Legacy viewing retains every entry while old day fields keep their shape."""

import pytest

import api_server
from lib.meal_loader import Meal, SubRecipe, save_meal
from lib.meal_plan_parser import MealEntry, parse_meal_plan


CONTENT = """# Plan
[[Preamble only]]
## Friday (Oct 23)
### Dinner
[[Rice & Beans 100%]] x1.5
[[Side 50%]]
### Notes
Remember [[Prose reference]].
## Saturday (Oct 24)
### Lunch
[[Meal: Rice Plate]] x2
[[Extra Side]]
### Notes
[[Another prose reference]]
"""


@pytest.fixture
def legacy_plan(tmp_vault, monkeypatch):
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(exist_ok=True)
    path = plans / "2026-W43.md"
    path.write_text(CONTENT)
    monkeypatch.setattr(api_server, "MEAL_PLANS_PATH", plans)
    monkeypatch.setattr(api_server, "OBSIDIAN_RECIPES_PATH", tmp_vault / "Recipes")
    return path


def test_opt_in_parser_collects_all_entries_and_preserves_default():
    ordinary = parse_meal_plan(CONTENT, 2026, 43)
    assert ordinary[4]["dinner"] == MealEntry("Rice & Beans 100%", 1.5)
    all_entries = parse_meal_plan(CONTENT, 2026, 43, all_entries=True)
    assert all_entries[4]["dinner"] == [
        MealEntry("Rice & Beans 100%", 1.5),
        MealEntry("Side 50%"),
    ]
    assert all_entries[5]["lunch"] == [
        MealEntry("Rice Plate", 2, "meal"),
        MealEntry("Extra Side"),
    ]
    assert all_entries[0]["dinner"] == []
    names = [
        entry.name
        for day in all_entries
        for slot in ("breakfast", "lunch", "snack", "dinner")
        for entry in day[slot]
    ]
    assert names == ["Rice & Beans 100%", "Side 50%", "Rice Plate", "Extra Side"]


def test_api_flat_projection_includes_both_recipes_without_changing_native_days(
    legacy_plan,
):
    with api_server.app.test_client() as client:
        response = client.get("/api/meal-plan/2026-W43")
    assert response.status_code == 200
    data = response.json
    assert data["days"][4]["dinner"] == {
        "name": "Rice & Beans 100%",
        "servings": 1.5,
        "kind": "recipe",
    }
    assert data.get("planned_meals", [])[:2] == [
        {
            "date": "2026-10-23",
            "meal": "dinner",
            "name": "Rice & Beans 100%",
            "servings": 1.5,
            "kind": "recipe",
        },
        {
            "date": "2026-10-23",
            "meal": "dinner",
            "name": "Side 50%",
            "servings": 1.0,
            "kind": "recipe",
        },
    ]
    assert len(data.get("planned_meals", [])) == 4


def test_recipe_and_plate_use_same_serializer_as_native_days(legacy_plan, tmp_vault):
    save_meal(
        Meal(
            name="Rice Plate",
            sub_recipes=[
                SubRecipe(recipe="Rice A", servings=1.5),
                SubRecipe(recipe="Rice B", servings=0.5),
            ],
        )
    )
    with api_server.app.test_client() as client:
        data = client.get("/api/meal-plan/2026-W43").json
    rows = data.get("planned_meals", [])
    assert len(rows) == 4
    assert rows[2] == {
        "date": "2026-10-24",
        "meal": "lunch",
        **data["days"][5]["lunch"],
    }
    assert rows[2]["sub_recipes"] == [
        {"recipe": "Rice A", "servings": 1.5},
        {"recipe": "Rice B", "servings": 0.5},
    ]
    assert rows[2]["servings"] == 2
    assert rows[3]["name"] == "Extra Side"
    assert rows[3]["kind"] == "recipe"


def test_projection_read_does_not_rewrite_note_or_import_ledger(legacy_plan, tmp_db):
    from lib import inventory_db

    conn = inventory_db.connect()
    conn.close()
    before = legacy_plan.read_bytes()
    before_mtime = legacy_plan.stat().st_mtime_ns
    with api_server.app.test_client() as client:
        assert (
            len(client.get("/api/meal-plan/2026-W43").json.get("planned_meals", []))
            == 4
        )
    assert legacy_plan.read_bytes() == before
    assert legacy_plan.stat().st_mtime_ns == before_mtime
    conn = inventory_db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM cooks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM placements").fetchone()[0] == 0
    finally:
        conn.close()


def test_missing_legacy_plan_has_empty_projection_without_creating_file(legacy_plan):
    missing = legacy_plan.parent / "2026-W44.md"
    with api_server.app.test_client() as client:
        assert client.get("/api/meal-plan/2026-W44").json.get("planned_meals") == []
    assert not missing.exists()
