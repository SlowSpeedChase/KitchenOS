"""Contract for the Cook Now API used by the /cook-now page."""

import pytest

from api_server import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def _setup_vault(tmp_vault):
    """Create vault structure with sample recipes."""
    recipes_dir = tmp_vault / "Recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)

    # Create sample recipes with ingredients
    recipes_dir.joinpath("Chicken Dinner.md").write_text(
        "---\ntitle: Chicken Dinner\ndish_type: main\n---\n\n"
        "# Chicken Dinner\n\n"
        "## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n"
        "|--------|------|------------|\n"
        "| 2 | lb | chicken breast |\n"
        "| 2 | cup | rice |\n"
        "| 1 | bunch | broccoli |\n\n"
        "## Instructions\n\n1. Cook it.\n",
        encoding="utf-8",
    )

    recipes_dir.joinpath("Pancakes.md").write_text(
        "---\ntitle: Pancakes\ndish_type: breakfast\n---\n\n"
        "# Pancakes\n\n"
        "## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n"
        "|--------|------|------------|\n"
        "| 2 | cup | flour |\n"
        "| 1 | cup | milk |\n"
        "| 2 | each | eggs |\n\n"
        "## Instructions\n\n1. Cook it.\n",
        encoding="utf-8",
    )

    recipes_dir.joinpath("Carrot Salad.md").write_text(
        "---\ntitle: Carrot Salad\ndish_type: side\n---\n\n"
        "# Carrot Salad\n\n"
        "## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n"
        "|--------|------|------------|\n"
        "| 3 | medium | carrots |\n"
        "| 2 | tbsp | olive oil |\n"
        "| 1 | tsp | salt |\n\n"
        "## Instructions\n\n1. Cook it.\n",
        encoding="utf-8",
    )


def test_returns_recipes_list(client, tmp_db, tmp_vault):
    _setup_vault(tmp_vault)
    resp = client.get("/api/cook-now")
    assert resp.status_code == 200
    assert "recipes" in resp.get_json()


def test_every_recipe_carries_a_group(client, tmp_db, tmp_vault):
    """The page filters on `group`; a recipe without one cannot be shown."""
    _setup_vault(tmp_vault)
    from lib import cook_now
    resp = client.get("/api/cook-now")
    for recipe in resp.get_json()["recipes"]:
        assert recipe["group"] in cook_now.DISH_TYPE_GROUPS


def test_limit_caps_each_chip_group(client, tmp_db, tmp_vault):
    """`limit` is per chip group, so every chip keeps depth.

    Used to assert `len(recipes) <= limit` over the whole payload. That cap,
    taken after the meal-tier weighting, is exactly how the Desserts, Snacks
    and Drinks chips went dead on the real pantry: nothing in those groups
    ever ranked inside a global top-60. What the old assertion protected —
    the limit is honoured, not ignored — is kept: no group exceeds it.
    """
    _setup_vault(tmp_vault)   # one main, one breakfast, one side
    resp = client.get("/api/cook-now?limit=1")
    recipes = resp.get_json()["recipes"]
    per_group = {}
    for r in recipes:
        per_group[r["group"]] = per_group.get(r["group"], 0) + 1
    assert per_group and all(n <= 1 for n in per_group.values()), per_group
    # ...and a group with a cookable recipe is present, not squeezed out.
    assert set(per_group) == {"Mains", "Breakfast", "Sides"}, per_group


def test_limit_zero_returns_empty_list(client, tmp_db, tmp_vault):
    """`?limit=0` must honour the request, not silently fall back to 30."""
    _setup_vault(tmp_vault)
    resp = client.get("/api/cook-now?limit=0")
    assert resp.status_code == 200
    assert resp.get_json()["recipes"] == []


def test_negative_limit_is_clamped_to_zero(client, tmp_db, tmp_vault):
    """A negative limit must not slice from the end and return the worst matches."""
    _setup_vault(tmp_vault)
    resp = client.get("/api/cook-now?limit=-5")
    assert resp.status_code == 200
    assert resp.get_json()["recipes"] == []


def test_page_renders(client, tmp_db, tmp_vault):
    resp = client.get("/cook-now")
    assert resp.status_code == 200
    assert b"cook-now-chips" in resp.data


def test_page_is_registered_in_sections():
    """CLAUDE.md invariant: a browsable page must be in the SECTIONS registry."""
    from lib import web_dashboard as wd
    paths = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
    assert "/cook-now" in paths
