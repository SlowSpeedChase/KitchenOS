"""Nutrition review API: ranked queue, candidates, human match pinning."""
import pytest

from api_server import app
from lib import inventory_db

WEAK_MD = """---
title: Mystery Soup
servings: 4
source_url: "https://example.com/soup"
nutrition_calories: 100
nutrition_protein: 5
nutrition_carbs: 10
nutrition_fat: 2
nutrition_coverage: 0.4
nutrition_unmatched: "unicorn dust"
needs_review: true
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | cup | dried beans |
| 1 | tsp | unicorn dust |
"""

STRONG_MD = WEAK_MD.replace("title: Mystery Soup", "title: Solid Stew") \
                   .replace("nutrition_coverage: 0.4", "nutrition_coverage: 1.0") \
                   .replace('nutrition_unmatched: "unicorn dust"\n', "") \
                   .replace("needs_review: true\n", "")


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class _Rec:
    def __init__(self, source_id, description):
        self.source_id = source_id
        self.description = description
        self.per_100g = _Per()
        self.portions = []
        self.density_g_per_ml = None


class _Per:
    def to_dict(self):
        return {"calories": 100.0, "protein": 5.0, "carbs": 10.0, "fat": 2.0}


@pytest.fixture
def review_vault(tmp_db, tmp_vault, monkeypatch):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    (recipes / "Mystery Soup.md").write_text(WEAK_MD, encoding="utf-8")
    (recipes / "Solid Stew.md").write_text(STRONG_MD, encoding="utf-8")
    import lib.food_db as food_db
    monkeypatch.setattr(food_db, "usda_search",
                        lambda q: [_Rec("111", "Beans, dry"),
                                   _Rec("222", "Dust, unicorn")])
    monkeypatch.setattr(food_db, "usda_food_detail",
                        lambda fid: _Rec(fid, "Dust, unicorn"))
    return recipes


def test_review_list_ranked_worst_first(client, review_vault):
    resp = client.get("/api/nutrition-review/recipes")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert rows[0]["name"] == "Mystery Soup"
    assert rows[0]["coverage"] == 0.4
    assert "unicorn dust" in rows[0]["unmatched"]


def test_recipe_detail_includes_candidates_for_weak_lines(client, review_vault):
    resp = client.get("/api/nutrition-review/recipe/Mystery Soup")
    assert resp.status_code == 200
    data = resp.get_json()
    weak = [l for l in data["lines"] if l["needs_review"]
            or l["confidence"] < 0.8]
    assert weak and len(weak[0]["candidates"]) >= 1
    assert weak[0]["candidates"][0]["source_id"]


def test_resolve_pins_match_and_recomputes(client, review_vault):
    resp = client.post("/api/nutrition-review/resolve", json={
        "item": "unicorn dust", "source_id": "222", "recipe": "Mystery Soup"})
    assert resp.status_code == 200
    row = inventory_db.get_food_resolution("unicorn dust")
    assert row and row["resolver"] == "human"
    md = (review_vault / "Mystery Soup.md").read_text(encoding="utf-8")
    assert "nutrition_coverage: 1.0" in md


def test_resolve_negligible(client, review_vault):
    resp = client.post("/api/nutrition-review/resolve", json={
        "item": "unicorn dust", "negligible": True, "recipe": "Mystery Soup"})
    assert resp.status_code == 200
    row = inventory_db.get_food_resolution("unicorn dust")
    assert row and row["resolver"] == "human-negligible"
