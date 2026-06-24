# Siri Backend (Phase 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two deterministic backend capabilities the Siri App Intents need — server-side ingredient search on `/api/recipes`, and optional bearer-token auth for remote (Tailscale) access — fully test-driven.

**Architecture:** Both changes are additive to the existing Flask app in `api_server.py`. Ingredient search reuses `lib/recipe_index.get_recipe_index(..., include_ingredients=True)` and filters in the route. Auth is a decorator that is a no-op until `KITCHENOS_API_TOKEN` is set, and always exempts localhost (so the Mac app on `localhost` and the local browser meal-planner keep working; only remote/Tailscale callers like the iPad must present the token).

**Tech Stack:** Python 3.11, Flask, pytest (`.venv/bin/python -m pytest`).

## Global Constraints

- Python 3.11; run everything through `.venv/bin/python`.
- Vault paths always via `lib/paths.py` helpers — never hardcode. (Not directly touched here, but do not introduce new hardcoded paths.)
- Changes must be backward compatible: with `KITCHENOS_API_TOKEN` unset and no `ingredient` query param, every existing endpoint behaves exactly as before.
- Tests must not require network, Ollama, or Claude. Patch `api_server.get_recipe_index` rather than building real recipe files where possible.
- Work happens on branch `siri-app-intents` (already checked out). Commit after each task.

---

### Task 1: Server-side ingredient filtering on `GET /api/recipes`

Add an optional `?ingredient=<term>` query param. When present, return only recipes whose ingredient list contains the term (case-insensitive substring). When absent, behavior is unchanged.

**Files:**
- Modify: `api_server.py` — the `api_recipes()` route (currently at ~line 212) and add a second cache dict next to `_recipe_cache`.
- Test: `tests/test_api_recipes_ingredient.py` (create)

**Interfaces:**
- Consumes: `get_recipe_index(recipes_dir, include_ingredients=True)` from `lib/recipe_index.py`, which returns dicts that include `"ingredient_items": list[str]` when `include_ingredients=True`.
- Produces: `GET /api/recipes?ingredient=<term>` → JSON array of recipe dicts (same shape as the existing index entries, plus `ingredient_items`), filtered to matches. The Swift `FindRecipesByIngredient` intent consumes this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_recipes_ingredient.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_recipes_ingredient.py -v`
Expected: FAIL — `AttributeError: module 'api_server' has no attribute '_recipe_ingredient_cache'` (and/or the filter assertions fail).

- [ ] **Step 3: Add the ingredient cache**

In `api_server.py`, find the existing `_recipe_cache` definition (grep: `_recipe_cache = `). Directly below it, add:

```python
_recipe_ingredient_cache = {"data": None, "timestamp": 0}
```

- [ ] **Step 4: Implement filtering in the route**

Replace the body of `api_recipes()` with:

```python
@app.route('/api/recipes', methods=['GET'])
def api_recipes():
    """Return recipe metadata for meal planner sidebar.

    Optional query param:
        ingredient: case-insensitive substring. When provided, only recipes
            whose ingredient list contains a match are returned.
    """
    ingredient = request.args.get("ingredient", "").strip()
    now = time.time()

    if ingredient:
        cache = _recipe_ingredient_cache
        if cache["data"] is None or (now - cache["timestamp"]) > RECIPE_CACHE_TTL:
            cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH, include_ingredients=True)
            cache["timestamp"] = now
        term = ingredient.lower()
        matches = [
            r for r in cache["data"]
            if any(term in item.lower() for item in r.get("ingredient_items", []))
        ]
        return jsonify(matches)

    if _recipe_cache["data"] is None or (now - _recipe_cache["timestamp"]) > RECIPE_CACHE_TTL:
        _recipe_cache["data"] = get_recipe_index(OBSIDIAN_RECIPES_PATH)
        _recipe_cache["timestamp"] = now
    return jsonify(_recipe_cache["data"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_recipes_ingredient.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the broader API test suite for regressions**

Run: `.venv/bin/python -m pytest tests/test_api_server.py tests/test_api_endpoints.py tests/test_recipe_index.py -v`
Expected: PASS (no regressions from the route change).

- [ ] **Step 7: Commit**

```bash
git add api_server.py tests/test_api_recipes_ingredient.py
git commit -m "feat(api): ingredient filter on GET /api/recipes for Siri search"
```

---

### Task 2: Optional bearer-token auth for remote callers

Add a `require_token` decorator. It is a no-op when `KITCHENOS_API_TOKEN` is unset, always lets localhost through (Mac app + local browser UI), and requires `Authorization: Bearer <token>` for any other remote address (the iPad over Tailscale).

**Files:**
- Modify: `api_server.py` — add the decorator near the top (after imports / `app = Flask(__name__)`), and apply it to the Siri-facing routes: `api_recipes`, `api_meal_plan_get`, `api_meal_plan_put`, `api_suggest_meal`, and `api_recipe_detail`.
- Test: `tests/test_api_auth.py` (create)

**Interfaces:**
- Consumes: `KITCHENOS_API_TOKEN` from the environment; `request.remote_addr`, `request.headers`.
- Produces: `require_token(view)` decorator. Protected endpoints return `401 {"error": "Unauthorized"}` for remote callers with a missing/incorrect token when the env var is set. The Swift `KitchenOSClient` sends `Authorization: Bearer <token>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_auth.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v`
Expected: FAIL — `test_token_set_remote_without_header_rejected` and `test_token_set_remote_wrong_header_rejected` return 200 instead of 401 (no auth exists yet).

- [ ] **Step 3: Add the decorator**

In `api_server.py`, add near the other imports:

```python
import functools
```

(If `import os` is not already present, add it too — grep `^import os`.) Then, after `app = Flask(__name__)`, add:

```python
def require_token(view):
    """Require a bearer token for non-localhost callers when KITCHENOS_API_TOKEN is set.

    No-op when the env var is unset. Localhost (Mac app, local browser UI) is always
    exempt; remote callers (iPad over Tailscale) must send Authorization: Bearer <token>.
    """
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        token = os.environ.get("KITCHENOS_API_TOKEN")
        if not token:
            return view(*args, **kwargs)
        if request.remote_addr in ("127.0.0.1", "::1"):
            return view(*args, **kwargs)
        if request.headers.get("Authorization", "") == f"Bearer {token}":
            return view(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper
```

- [ ] **Step 4: Apply the decorator to the Siri-facing routes**

For each of these routes, add `@require_token` on the line directly below the `@app.route(...)` decorator (above the `def`): `api_recipes`, `api_meal_plan_get`, `api_meal_plan_put`, `api_suggest_meal`, `api_recipe_detail`. Example:

```python
@app.route('/api/recipes', methods=['GET'])
@require_token
def api_recipes():
    ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Run the broader API suite for regressions**

Run: `.venv/bin/python -m pytest tests/test_api_server.py tests/test_api_endpoints.py tests/test_api_recipes_ingredient.py -v`
Expected: PASS — existing tests use the default localhost client, so the token (unset in those tests) and localhost exemption keep them green.

- [ ] **Step 7: Commit**

```bash
git add api_server.py tests/test_api_auth.py
git commit -m "feat(api): optional bearer-token auth for remote Siri callers"
```

---

### Task 3: Document the new param, env var, and Tailscale token

**Files:**
- Modify: `CLAUDE.md` — note the `ingredient=` param and the `KITCHENOS_API_TOKEN` env var.
- Modify: `.env.example` if it exists (grep for it); otherwise skip and note in the commit.

- [ ] **Step 1: Document the `ingredient` param**

In `CLAUDE.md`, under the "Endpoints" table, add a row:

```markdown
| `/api/recipes?ingredient=<term>` (GET) | Filters the recipe index to recipes whose ingredient list contains the case-insensitive substring. Backs the Siri "recipes with X" intent. |
```

- [ ] **Step 2: Document the auth env var**

In `CLAUDE.md`, under "Development Environment" → API Keys list, add:

```markdown
  - `KITCHENOS_API_TOKEN` - Optional. When set, remote (non-localhost) callers of the Siri-facing endpoints must send `Authorization: Bearer <token>`. Localhost is always exempt. Used by the iPad App-Intents app over Tailscale.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document ingredient filter and KITCHENOS_API_TOKEN"
```

---

## Self-Review

**Spec coverage:** This plan implements the two backend gaps the spec named as *additive backend changes*: (1) "Ingredient search — extend `/api/recipes` with an `ingredient=` param" → Task 1; (2) "A static bearer token on these endpoints" → Task 2. The spec's third backend item — the "Siri-friendly suggestion wrapper" — is intentionally **deferred to Plan B (Swift phase)** because it depends on `lib/meal_suggester.py`, which calls Claude/Ollama (non-deterministic, network-bound) and is unsuitable for an unattended TDD run. The existing `/api/suggest-meal` already satisfies the `SuggestForMealPlan` intent when given week/day/meal, which the Swift client can supply. `GetMealPlan`, `AddRecipeToMealPlan`, and `GetRecipeNutrition` use existing endpoints (`/api/meal-plan/<week>` GET/PUT, `/api/recipes/<name>`) unchanged.

**Placeholder scan:** No TBD/TODO; every code and test block is complete; commands have expected output.

**Type consistency:** `_recipe_ingredient_cache` (added Task 1) is referenced by name in both the implementation and the autouse fixtures of both test files — consistent. `require_token` is defined once and applied by name. `get_recipe_index(..., include_ingredients=True)` matches the real signature in `lib/recipe_index.py`.

## Execution Handoff

Two execution options:
1. **Subagent-Driven (recommended)** — a fresh subagent per task with review between tasks.
2. **Inline Execution** — execute tasks in-session with checkpoints.

This plan is self-contained, deterministic, and offline — suitable for an unattended overnight run.
