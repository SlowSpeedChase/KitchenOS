"""Tests for ingredient filtering on GET /api/recipes."""
import pytest

import api_server


@pytest.fixture
def client():
    with api_server.app.test_client() as client:
        yield client


FAKE_INDEX = [
    {"name": "Butter Chicken", "protein": "chicken",
     "ingredient_items": ["chicken thighs", "garam masala", "cream"]},
    {"name": "Beef Stew", "protein": "beef",
     "ingredient_items": ["beef chuck", "carrots", "onion"]},
    {"name": "Chicken Soup", "protein": "chicken",
     "ingredient_items": ["Chicken breast", "celery", "noodles"]},
]


@pytest.fixture(autouse=True)
def _reset_caches_and_index(monkeypatch):
    # Patch the index loader to a deterministic list and clear caches.
    monkeypatch.setattr(
        api_server, "get_recipe_index",
        lambda path, include_ingredients=False: FAKE_INDEX,
    )
    api_server._recipe_cache["data"] = None
    api_server._recipe_ingredient_cache["data"] = None
    yield


def test_ingredient_filter_matches_substring(client):
    resp = client.get("/api/recipes?ingredient=chicken")
    assert resp.status_code == 200
    names = sorted(r["name"] for r in resp.get_json())
    assert names == ["Butter Chicken", "Chicken Soup"]


def test_ingredient_filter_is_case_insensitive(client):
    resp = client.get("/api/recipes?ingredient=CHICKEN")
    names = sorted(r["name"] for r in resp.get_json())
    assert names == ["Butter Chicken", "Chicken Soup"]


def test_ingredient_filter_no_match_returns_empty(client):
    resp = client.get("/api/recipes?ingredient=tofu")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_no_ingredient_param_returns_full_index(client):
    resp = client.get("/api/recipes")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 3
