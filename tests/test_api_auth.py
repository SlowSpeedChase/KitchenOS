"""Tests for optional bearer-token auth on Siri-facing endpoints."""
import pytest

import api_server

REMOTE = {"environ_base": {"REMOTE_ADDR": "100.64.0.5"}}  # simulated Tailscale IP


@pytest.fixture
def client():
    with api_server.app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def _stub_index(monkeypatch):
    # /api/recipes must not touch the filesystem during auth tests.
    monkeypatch.setattr(
        api_server, "get_recipe_index",
        lambda path, include_ingredients=False: [],
    )
    api_server._recipe_cache["data"] = None
    api_server._recipe_ingredient_cache["data"] = None
    yield


def test_no_token_env_allows_remote_without_header(client, monkeypatch):
    monkeypatch.delenv("KITCHENOS_API_TOKEN", raising=False)
    resp = client.get("/api/recipes", **REMOTE)
    assert resp.status_code == 200


def test_token_set_localhost_exempt(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    # Flask test client default REMOTE_ADDR is 127.0.0.1
    resp = client.get("/api/recipes")
    assert resp.status_code == 200


def test_token_set_remote_without_header_rejected(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    resp = client.get("/api/recipes", **REMOTE)
    assert resp.status_code == 401


def test_token_set_remote_wrong_header_rejected(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    resp = client.get("/api/recipes", headers={"Authorization": "Bearer nope"}, **REMOTE)
    assert resp.status_code == 401


def test_token_set_remote_correct_header_allowed(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    resp = client.get("/api/recipes", headers={"Authorization": "Bearer secret"}, **REMOTE)
    assert resp.status_code == 200


def test_cook_remote_without_token_rejected(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    # Must not reach consume_recipe — this asserts the gate, not the cook path.
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: pytest.fail("consume_recipe reached without a token"))
    resp = client.post("/api/cook", json={"recipe": "Anything"}, **REMOTE)
    assert resp.status_code == 401


def test_cook_localhost_exempt(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: {"recipe": "Anything", "consumed": [],
                         "skipped_staples": [], "not_tracked": [],
                         "use_recorded": []})
    resp = client.post("/api/cook", json={"recipe": "Anything"})
    assert resp.status_code == 200


def test_cook_remote_with_valid_token_allowed(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    monkeypatch.setattr(
        "lib.cook.consume_recipe",
        lambda *a, **k: {"recipe": "Anything", "consumed": [],
                         "skipped_staples": [], "not_tracked": [],
                         "use_recorded": []})
    resp = client.post(
        "/api/cook", json={"recipe": "Anything"},
        headers={"Authorization": "Bearer secret"}, **REMOTE)
    assert resp.status_code == 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/meals"),
    ("POST", "/api/meals"),
    ("GET", "/api/meals/Osso%20Buco%20Plate"),
    ("PUT", "/api/meals/Osso%20Buco%20Plate"),
    ("DELETE", "/api/meals/Osso%20Buco%20Plate"),
    ("GET", "/api/freezer"),
])
def test_meal_and_freezer_routes_are_gated(client, monkeypatch, method, path):
    """The plate CRUD and the freezer are ledger-adjacent and must gate like it.

    These six shipped ungated while every neighbouring ledger route was gated —
    `/api/meals` can rewrite or delete a hand-authored plate, and `/api/freezer`
    reads the whole kitchen's banked stock.
    """
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    resp = client.open(path, method=method, json={}, **REMOTE)
    assert resp.status_code == 401, f"{method} {path} answered a remote caller"


# The set of /api/ routes deliberately left open, so that adding a *new* ungated
# route is a conscious act rather than an oversight. Two things this list is NOT:
# it is not an assertion that these are safe to expose, and it is not security on
# its own — `require_token` is a no-op unless KITCHENOS_API_TOKEN is set, and it
# is currently unset. See the note in docs/API.md.
KNOWN_UNGATED = {
    "api_recipe_save", "api_recipe_import_text", "api_macro_targets",
    "api_pantry_get", "api_pantry_put",
    "api_shopping_list_preview", "api_shopping_list_confirm",
    "api_tasks_get", "api_task_mark_done",
    "api_inventory_list", "api_use_it_up", "api_cook_now",
    "api_inventory_add", "api_inventory_paste", "api_inventory_remove",
    "api_inventory_update", "api_inventory_extend", "api_inventory_set_expiry",
    "api_inventory_set_category", "api_inventory_move", "api_inventory_freeze",
    "api_inventory_bulk",
    "api_receipt_paste", "api_receipt_prompt",
    "api_system_health",
}


def test_no_new_api_route_is_silently_ungated():
    """A new /api/ route must either gate itself or be added to KNOWN_UNGATED."""
    import re
    from pathlib import Path

    src = Path(api_server.__file__).read_text(encoding="utf-8")
    decorated = re.compile(
        r"@app\.route\(\s*['\"](/api[^'\"]*)['\"].*?\)\n((?:@\w+(?:\(.*?\))?\n)*)def (\w+)",
        re.S)
    ungated = {m.group(3) for m in decorated.finditer(src)
               if "require_token" not in m.group(2)}
    assert ungated - KNOWN_UNGATED == set(), \
        "new ungated /api route(s) — gate them or add them to KNOWN_UNGATED"
    assert KNOWN_UNGATED - ungated == set(), \
        "KNOWN_UNGATED lists route(s) that are now gated — drop them from the list"
