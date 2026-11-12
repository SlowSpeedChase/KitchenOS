"""Recipe detail: extended API payload + page route."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from api_server import app


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


RECIPE_MD = """---
title: Chili
servings: 4
source_url: "https://example.com/chili"
nutrition_calories: 500
nutrition_protein: 30
nutrition_carbs: 40
nutrition_fat: 20
nutrition_coverage: 0.95
nutrition_confidence: 0.8
nutrition_source: "usda"
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | dried beans |
| 1 | lb | ground beef |

## Instructions

1. Cook it.
"""


def _write(tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "Chili.md").write_text(RECIPE_MD, encoding="utf-8")


def test_api_recipe_includes_ingredients_and_nutrition(client, tmp_vault):
    _write(tmp_vault)
    resp = client.get("/api/recipes/Chili")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["servings"] == 4
    assert len(data["ingredients"]) == 2
    assert data["ingredients"][0]["item"] == "dried beans"
    assert "## Ingredients" in data["body_markdown"]
    assert data["nutrition"]["calories"] == 500
    assert data["nutrition"]["coverage"] == 0.95


def test_api_recipe_nutrition_null_when_absent(client, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    bare = RECIPE_MD.split("nutrition_calories")[0] + "---\n\n## Ingredients\n"
    (recipes / "Bare.md").write_text(bare, encoding="utf-8")
    data = client.get("/api/recipes/Bare").get_json()
    assert data["nutrition"] is None


def test_recipe_page_renders(client, tmp_vault):
    _write(tmp_vault)
    resp = client.get("/recipe/Chili")
    assert resp.status_code == 200
    assert 'id="scale-select"' in resp.get_data(as_text=True)


class _ObsidianLink(HTMLParser):
    href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("id") == "obsidian-link":
            self.href = attrs.get("href")


def test_obsidian_link_works_before_unauthorized_recipe_fetch(client, tmp_vault, monkeypatch):
    """A remote reader must still get a real app link when the JSON API is gated."""
    _write(tmp_vault)
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "test-secret")
    remote = {"environ_overrides": {"REMOTE_ADDR": "100.64.0.5"}}
    assert client.get("/api/recipes/Chili", **remote).status_code == 401
    response = client.get("/recipe/Chili", **remote)
    assert response.status_code == 200
    link = _ObsidianLink()
    link.feed(response.get_data(as_text=True))
    uri = urlsplit(link.href)
    assert (uri.scheme, uri.netloc) == ("obsidian", "open")
    assert parse_qs(uri.query) == {"vault": [tmp_vault.name], "file": ["Recipes/Chili"]}
    assert "test-secret" not in response.get_data(as_text=True)


def test_obsidian_link_encodes_vault_and_recipe_identity(client, tmp_vault, monkeypatch):
    vault = tmp_vault / "Chase's Kitchen & Notes"
    recipes = vault / "Recipes"
    recipes.mkdir(parents=True)
    name = 'Chili + Beans #1 (50%) & "Rice"'
    (recipes / f"{name}.md").write_text(RECIPE_MD, encoding="utf-8")
    monkeypatch.setenv("KITCHENOS_VAULT", str(vault))
    response = client.get("/recipe/" + quote(name, safe=""))
    assert response.status_code == 200
    link = _ObsidianLink()
    link.feed(response.get_data(as_text=True))
    uri = urlsplit(link.href)
    assert (uri.scheme, uri.netloc) == ("obsidian", "open")
    assert parse_qs(uri.query) == {
        "vault": ["Chase's Kitchen & Notes"],
        "file": ['Recipes/Chili + Beans #1 (50%) & "Rice"'],
    }


def test_recipe_page_404(client, tmp_vault):
    _write(tmp_vault)
    assert client.get("/recipe/Nope").status_code == 404


def test_recipe_page_404_escapes_reflected_name(client, tmp_vault):
    """Recipe name is attacker-controlled URL input; must not be reflected raw."""
    _write(tmp_vault)
    payload = "<script>alert(1)</script>"
    resp = client.get(f"/recipe/{quote(payload, safe='')}")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "<script>alert" not in body
