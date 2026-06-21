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
