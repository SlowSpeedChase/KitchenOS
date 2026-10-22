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
    monkeypatch.delenv("KITCHENOS_AUTH_MODE", raising=False)
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
# token configuration is deployment-specific. See docs/API.md.
KNOWN_UNGATED = {
    # Authenticated by a one-use code and same-origin checks, not a bearer.
    "exchange_browser_handoff",
    "api_recipe_save", "api_recipe_import_text", "api_macro_targets",
    "api_pantry_get", "api_pantry_put",
    "api_shopping_list_preview",
    "api_tasks_get",
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


@pytest.mark.parametrize("peer,forwarded", [
    ("127.0.0.1", "100.64.0.5"),
    ("::1", "100.64.0.5"),
    ("::ffff:127.0.0.1", "100.64.0.5"),
    ("127.0.0.1", "127.0.0.1, 100.64.0.5"),
    ("127.0.0.1", "invalid"),
    ("100.64.0.5", "127.0.0.1"),
])
def test_forwarded_remote_cannot_take_local_auth_exemption(client, monkeypatch, peer, forwarded):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    response = client.get("/api/recipes", headers={"X-Forwarded-For": forwarded},
                          environ_base={"REMOTE_ADDR": peer})
    assert response.status_code == 401


def test_forwarded_remote_with_token_is_allowed(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    response = client.get("/api/recipes", headers={
        "X-Forwarded-For": "100.64.0.5", "Authorization": "Bearer secret"})
    assert response.status_code == 200


def test_forwarded_loopback_remains_local(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_API_TOKEN", "secret")
    assert client.get("/api/recipes", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 200


def test_health_identifies_reviewed_release_without_changing_body(client, monkeypatch):
    monkeypatch.setenv("KITCHENOS_RELEASE_SHA", "a" * 40)
    response = client.get('/health')
    assert response.json == {'status': 'ok'}
    assert response.headers.get('X-KitchenOS-Release') == 'a' * 40

@pytest.fixture
def viewing_setup(monkeypatch, tmp_vault):
    from lib.browser_handoff import BrowserHandoffStore
    clock = [1000.0]
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'secret')
    monkeypatch.setattr(api_server, 'browser_handoff_store', BrowserHandoffStore(clock=lambda: clock[0]))
    recipes = tmp_vault / 'Recipes'
    recipes.mkdir(exist_ok=True)
    for name in ('Rice & Beans', '豆 # 50% sauce', 'literal%2Fname'):
        (recipes / f'{name}.md').write_text('---\ntitle: Test\nservings: 2\n---\n\n## Instructions\n\n1. Simmer beans.\n')
    return clock


def mint(client, destination=None, origin='http://localhost'):
    return client.post('/api/browser-handoffs', json=destination or {
        'kind': 'recipe', 'name': 'Rice & Beans'},
        base_url=origin, headers={'Authorization': 'Bearer secret'}, **REMOTE)


def enter_view(client, destination=None, origin='http://localhost'):
    response = mint(client, destination, origin)
    assert response.status_code == 200
    code = response.json['handoff_path'].split('#code=')[1]
    return client.post('/api/browser-handoffs/exchange', json={'code': code},
                       base_url=origin, headers={'Origin': origin}, **REMOTE)


def test_handoff_requires_native_auth_remotely(client, monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'secret')
    response = client.post('/api/browser-handoffs', json={'kind': 'meal_plan', 'date': '2026-10-16'}, **REMOTE)
    assert response.status_code == 401


@pytest.mark.parametrize('destination,status', [
    ({'kind': 'recipe', 'name': 'Missing'}, 404),
    ({'kind': 'recipe', 'name': '../Rice & Beans'}, 400),
    ({'kind': 'recipe', 'name': 'Rice\\Beans'}, 400),
    ({'kind': 'recipe', 'name': ''}, 400),
    ({'kind': 'recipe', 'name': 'Rice & Beans', 'url': 'https://evil'}, 400),
    ({'kind': 'meal_plan', 'date': '2026-02-29'}, 400),
    ({'kind': 'meal_plan', 'date': '20261016'}, 400),
    ({'kind': 'url', 'url': 'https://evil'}, 400),
    ([], 400),
])
def test_handoff_rejects_invalid_destinations(client, viewing_setup, destination, status):
    response = client.post('/api/browser-handoffs', json=destination,
        headers={'Authorization': 'Bearer secret'}, **REMOTE)
    assert response.status_code == status


@pytest.mark.parametrize('descriptor,path', [
    ({'kind': 'recipe', 'name': 'Rice & Beans'}, '/recipe/Rice%20%26%20Beans'),
    ({'kind': 'recipe', 'name': '豆 # 50% sauce'}, '/recipe/%E8%B1%86%20%23%2050%25%20sauce'),
    ({'kind': 'recipe', 'name': 'literal%2Fname'}, '/recipe/literal%252Fname'),
    ({'kind': 'meal_plan', 'date': '2026-10-16'}, '/meal-planner?week=2026-W42&date=2026-10-16&view=calendar'),
    ({'kind': 'meal_plan', 'date': '2027-01-03'}, '/meal-planner?week=2026-W53&date=2027-01-03&view=calendar'),
])
def test_exchange_server_builds_exact_destination(client, viewing_setup, descriptor, path):
    response = enter_view(client, descriptor)
    assert response.status_code == 200
    assert response.json == {'redirect_path': path, 'expires_at': 1900}


@pytest.mark.parametrize('origin,secure', [('http://localhost', False), ('https://localhost', True)])
def test_cookie_retains_restriction_after_grant_expiry(client, viewing_setup, origin, secure):
    response = enter_view(client, origin=origin)
    cookie = response.headers['Set-Cookie']
    for attr in ('HttpOnly', 'SameSite=Strict', 'Path=/', 'Max-Age=86400'):
        assert attr in cookie
    assert ('Secure;' in cookie) == secure
    assert 'Domain=' not in cookie
    assert response.headers['Cache-Control'] == 'no-store'
    assert {'Cookie', 'Authorization'} <= set(response.vary)
    viewing_setup[0] += 900
    denied = client.get('/api/recipes', base_url=origin)
    assert denied.status_code == 401
    assert denied.json['error'] == 'browser_session_expired'
    assert 'Set-Cookie' not in denied.headers


def test_viewing_session_loads_real_recipe_json_remotely(client, viewing_setup):
    enter_view(client)
    response = client.get('/api/recipes/Rice%20%26%20Beans', **REMOTE)
    assert response.status_code == 200
    assert response.json['instructions'] == [{'step': 1, 'text': 'Simmer beans.', 'time': None}]
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('method,path,endpoint', [
    ('GET', '/refresh?recipe=Rice', 'refresh_recipe'),
    ('GET', '/refresh-nutrition?recipe=Rice', 'refresh_nutrition'),
    ('GET', '/reprocess?recipe=Rice', 'reprocess_recipe'),
    ('GET', '/api/freezer', 'api_freezer'),
    ('POST', '/extract', 'extract_recipe'),
    ('PUT', '/api/meal-plan/2026-W42', 'api_meal_plan_put'),
    ('POST', '/api/meals', 'api_meals_create'),
    ('POST', '/api/browser-handoffs', 'create_browser_handoff'),
])
@pytest.mark.parametrize('remote', [True, False])
def test_viewing_guard_blocks_legacy_and_nonallowlisted_routes(client, viewing_setup, monkeypatch, method, path, endpoint, remote):
    enter_view(client)
    # Resolve the real endpoint so the assertion guards even legacy route names.
    adapter = api_server.app.url_map.bind('localhost')
    endpoint = adapter.match(path.split('?')[0], method=method)[0]
    monkeypatch.setitem(api_server.app.view_functions, endpoint,
                        lambda **kwargs: pytest.fail('denied handler executed'))
    response = client.open(path, method=method, json={}, **(REMOTE if remote else {}))
    assert response.status_code == 403
    assert response.json['error'] == 'read_only_browser_session'


@pytest.mark.parametrize('endpoint,path', [
    ('api_recipe_detail', '/api/recipes/Rice'), ('api_recipes', '/api/recipes'),
    ('api_meal_plan_get', '/api/meal-plan/2026-W42'), ('api_week_board', '/api/week-board/2026-W42'),
    ('api_meals_list', '/api/meals'), ('api_macro_targets', '/api/macro-targets'),
    ('api_use_it_up', '/api/use-it-up'), ('get_cooking_availability', '/api/cooking-availability'),
    ('get_planning_calendar', '/api/planning-calendar/2026-W42'),
])
def test_exact_data_allowlist_passes_auth_guard(client, viewing_setup, monkeypatch, endpoint, path):
    enter_view(client)
    # Preserve the auth decorator, replacing only data work for this allowlist test.
    monkeypatch.setitem(api_server.app.view_functions, endpoint,
        api_server.require_token(lambda **kwargs: {'authorized': True}))
    rule = next(rule for rule in api_server.app.url_map.iter_rules(endpoint))
    path = rule.rule.replace('<name>', 'Rice').replace('<week>', '2026-W42')
    response = client.get(path, **REMOTE)
    assert response.status_code == 200
    assert response.json == {'authorized': True}


def test_explicit_valid_bearer_overrides_invalid_cookie(client, viewing_setup, monkeypatch):
    client.set_cookie('kitchenos_view', 'invalid')
    monkeypatch.setitem(api_server.app.view_functions, 'extract_recipe', lambda: {'native': True})
    response = client.post('/extract', headers={'Authorization': 'Bearer secret'}, **REMOTE)
    assert response.status_code == 200
    assert response.json == {'native': True}


@pytest.mark.parametrize('header', [{}, {'Authorization': 'Bearer wrong'}])
def test_invalid_marker_never_uses_loopback_exemption(client, viewing_setup, header):
    client.set_cookie('kitchenos_view', 'invalid')
    response = client.get('/api/recipes', headers=header)
    assert response.status_code == 401
    assert response.json['error'] == 'browser_session_expired'


def test_exchange_requires_same_origin_json_and_replay_fails(client, viewing_setup):
    issued = mint(client).json
    code = issued['handoff_path'].split('#code=')[1]
    for headers in ({}, {'Origin': 'http://evil.test'}, {'Origin': 'http://localhost:5001'}):
        assert client.post('/api/browser-handoffs/exchange', json={'code': code}, headers=headers).status_code == 403
    ok = client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={'Origin': 'http://localhost'})
    assert ok.status_code == 200
    assert client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={'Origin': 'http://localhost'}).status_code == 401


def test_expired_marker_can_renew_and_shell_has_no_credentials(client, viewing_setup):
    enter_view(client)
    viewing_setup[0] += 900
    expired = client.get('/meal-planner')
    assert expired.status_code == 200
    import json, re
    config = re.search(r'<script type="application/json" id="browser-view-config">(.*?)</script>', expired.text).group(1)
    assert json.loads(config) == {'state': 'expired', 'readOnly': True, 'expires_at': None}
    assert 'secret' not in config
    assert enter_view(client).status_code == 200
    assert client.get('/api/recipes', **REMOTE).status_code == 200


def test_unmarked_private_pages_and_denials_are_not_cacheable(client, viewing_setup):
    for path in ('/meal-planner', '/recipe/Rice%20%26%20Beans', '/api/recipes'):
        response = client.get(path, **REMOTE)
        assert response.headers.get('Cache-Control') == 'no-store'
        assert {'Cookie', 'Authorization'} <= set(response.vary)


@pytest.mark.parametrize('change', ['restart', 'rotation', 'origin'])
def test_existing_cookie_fails_closed_after_binding_changes(client, viewing_setup, monkeypatch, change):
    enter_view(client)
    kwargs = {}
    if change == 'restart':
        from lib.browser_handoff import BrowserHandoffStore
        monkeypatch.setattr(api_server, 'browser_handoff_store', BrowserHandoffStore(clock=lambda: viewing_setup[0]))
    elif change == 'rotation':
        monkeypatch.setenv('KITCHENOS_API_TOKEN', 'changed')
    else:
        kwargs['base_url'] = 'http://localhost:5002'
    response = client.get('/api/recipes', **kwargs)
    assert response.status_code == 401
    assert response.json['error'] == 'browser_session_expired'
    assert 'Set-Cookie' not in response.headers


def test_expired_recipe_shell_does_not_check_private_recipe(client, viewing_setup, monkeypatch):
    enter_view(client)
    viewing_setup[0] += 900
    monkeypatch.setattr(api_server, '_resolve_recipes_dir', lambda: pytest.fail('expired shell read private directory'))
    response = client.get('/recipe/Not%20Saved')
    assert response.status_code == 200
    assert '"state": "expired"' in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/images/test.jpg').status_code == 401


def test_empty_cookie_still_marks_restricted_browser(client, viewing_setup):
    client.set_cookie('kitchenos_view', '')
    assert client.post('/extract', json={'url': 'https://example.com'}).status_code == 401


def test_handoff_capacity_maps_to_429_without_credentials_in_errors(client, viewing_setup, monkeypatch):
    from lib import browser_handoff
    monkeypatch.setattr(browser_handoff, 'CAPACITY', 1)
    first = mint(client).json
    assert mint(client).status_code == 429
    code = first['handoff_path'].split('#code=')[1]
    response = client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={'Origin': 'http://localhost'})
    assert response.status_code == 200
    pending = mint(client).json['handoff_path'].split('#code=')[1]
    response = client.post('/api/browser-handoffs/exchange', json={'code': pending}, headers={'Origin': 'http://localhost'})
    assert response.status_code == 429
    assert pending not in response.text
    # Refreshing is still forbidden, so a full store cannot mint more access.
    assert client.post('/api/browser-handoffs', json={'kind': 'meal_plan', 'date': '2026-10-16'}).status_code == 403


def test_head_is_readable_but_options_and_post_are_denied(client, viewing_setup):
    enter_view(client)
    assert client.head('/api/recipes', **REMOTE).status_code == 200
    assert client.options('/api/recipes', **REMOTE).status_code == 403
    assert client.post('/api/recipes', json={}, **REMOTE).status_code == 403


def test_exchange_does_not_trust_forwarded_origin_or_scheme(client, viewing_setup):
    issued = mint(client).json
    code = issued['handoff_path'].split('#code=')[1]
    response = client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={
        'Origin': 'https://elsewhere', 'X-Forwarded-Host': 'elsewhere', 'X-Forwarded-Proto': 'https'})
    assert response.status_code == 403
    response = client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={
        'Origin': 'http://localhost', 'X-Forwarded-Proto': 'https'})
    assert response.status_code == 200
    assert 'Secure;' not in response.headers['Set-Cookie']


def test_exchange_rejects_cross_site_and_non_json_posts(client, viewing_setup):
    code = mint(client).json['handoff_path'].split('#code=')[1]
    assert client.post('/api/browser-handoffs/exchange', json={'code': code}, headers={
        'Origin': 'http://localhost', 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.post('/api/browser-handoffs/exchange', data={'code': code}, headers={
        'Origin': 'http://localhost'}).status_code == 403


_GATEWAY_HOST = 'chases-mac-mini.taila69703.ts.net'
_GATEWAY_ORIGIN = 'https://chases-mac-mini.taila69703.ts.net'


@pytest.fixture
def gateway_setup(viewing_setup, monkeypatch):
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', _GATEWAY_ORIGIN)
    return viewing_setup


def _gateway_headers(host=_GATEWAY_HOST):
    # Existing Caddy preserves Host, terminates TLS, and connects over loopback HTTP.
    return {'X-Forwarded-For': '100.64.0.5', 'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': host}


def _gateway_mint(client, host=_GATEWAY_HOST):
    return client.post('/api/browser-handoffs',
        json={'kind': 'recipe', 'name': 'Rice & Beans'},
        base_url='http://' + host,
        headers={**_gateway_headers(host), 'Authorization': 'Bearer secret'},
        environ_base={'REMOTE_ADDR': '127.0.0.1'})


def _gateway_exchange(client, code, host=_GATEWAY_HOST, peer='127.0.0.1', overrides=None):
    return client.post('/api/browser-handoffs/exchange', json={'code': code},
        base_url='http://' + host,
        headers={**_gateway_headers(host), 'Origin': 'https://' + host, **(overrides or {})},
        environ_base={'REMOTE_ADDR': peer})


@pytest.mark.parametrize('peer', ['127.0.0.1', '::1', '::ffff:127.0.0.1'])
def test_gateway_https_handoff_sets_secure_cookie_and_reads_real_recipe(client, gateway_setup, peer):
    minted = _gateway_mint(client)
    assert minted.status_code == 200
    code = minted.json['handoff_path'].split('#code=')[1]
    exchanged = _gateway_exchange(client, code, peer=peer)
    assert exchanged.status_code == 200
    assert exchanged.json == {'redirect_path': '/recipe/Rice%20%26%20Beans', 'expires_at': 1900}
    assert 'Secure;' in exchanged.headers['Set-Cookie']
    assert 'HttpOnly;' in exchanged.headers['Set-Cookie']
    assert 'SameSite=Strict' in exchanged.headers['Set-Cookie']
    # Flask receives HTTP even when the browser sent the Secure cookie over HTTPS.
    response = client.get('/api/recipes/Rice%20%26%20Beans',
        base_url='http://' + _GATEWAY_HOST, headers=_gateway_headers(),
        environ_base={'REMOTE_ADDR': peer})
    assert response.status_code == 200
    assert response.json['instructions'] == [{'step': 1, 'text': 'Simmer beans.', 'time': None}]
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('path,method', [('/api/recipes', 'GET'), ('/api/browser-handoffs', 'POST')])
@pytest.mark.parametrize('forwarded', ['100.64.0.5', '127.0.0.1, 100.64.0.5'])
def test_gateway_https_origin_does_not_exempt_forwarded_remote_auth(client, gateway_setup, path, method, forwarded):
    response = client.open(path, method=method,
        json={'kind': 'meal_plan', 'date': '2026-10-16'},
        base_url='http://' + _GATEWAY_HOST,
        headers={**_gateway_headers(), 'X-Forwarded-For': forwarded})
    assert response.status_code == 401


@pytest.mark.parametrize('peer,overrides', [
    ('100.64.0.5', {}),
    ('192.168.1.55', {}),
    ('100.64.0.5', {'X-Forwarded-For': '127.0.0.1'}),
    ('127.0.0.1', {'X-Forwarded-Host': 'elsewhere.test'}),
    ('127.0.0.1', {'X-Forwarded-Host': _GATEWAY_HOST + ':5443'}),
    ('127.0.0.1', {'X-Forwarded-Host': _GATEWAY_HOST + ', elsewhere.test'}),
    ('127.0.0.1', {'X-Forwarded-Proto': 'http'}),
    ('127.0.0.1', {'X-Forwarded-Proto': 'https, http'}),
    ('127.0.0.1', {'Host': 'elsewhere.test'}),
])
def test_gateway_https_origin_rejects_spoofed_or_mismatched_forwarding(client, gateway_setup, peer, overrides):
    code = _gateway_mint(client).json['handoff_path'].split('#code=')[1]
    rejected = _gateway_exchange(client, code, peer=peer, overrides=overrides)
    assert rejected.status_code == 403
    assert 'Set-Cookie' not in rejected.headers
    # The rejected attempt must not consume the code.
    assert _gateway_exchange(client, code).status_code == 200


def test_gateway_session_cannot_downgrade_to_direct_http_or_untrusted_peer(client, gateway_setup):
    code = _gateway_mint(client).json['handoff_path'].split('#code=')[1]
    assert _gateway_exchange(client, code).status_code == 200
    for headers, peer in [({}, '127.0.0.1'), (_gateway_headers(), '100.64.0.5')]:
        response = client.get('/api/recipes', base_url='http://' + _GATEWAY_HOST,
                              headers=headers, environ_base={'REMOTE_ADDR': peer})
        assert response.status_code == 401
        assert response.json['error'] == 'browser_session_expired'
        assert 'Set-Cookie' not in response.headers


def test_gateway_origin_retains_nondefault_port_and_code_binding(client, gateway_setup, monkeypatch):
    host = _GATEWAY_HOST + ':5443'
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', 'https://' + host)
    code = _gateway_mint(client, host).json['handoff_path'].split('#code=')[1]
    other = _GATEWAY_HOST + ':5444'
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', 'https://' + other)
    assert _gateway_exchange(client, code, host=other).status_code == 401
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', 'https://' + host)
    assert _gateway_exchange(client, code, host=host).status_code == 200
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', 'https://' + other)
    response = client.get('/api/recipes', base_url='http://' + other,
                          headers=_gateway_headers(other))
    assert response.status_code == 401
    assert response.json['error'] == 'browser_session_expired'


@pytest.mark.parametrize('configured', ['http://' + _GATEWAY_HOST, 'https://' + _GATEWAY_HOST + '/bad'])
def test_gateway_forwarding_requires_valid_configured_https_origin(client, gateway_setup, monkeypatch, configured):
    code = _gateway_mint(client).json['handoff_path'].split('#code=')[1]
    monkeypatch.setenv('KITCHENOS_WEB_BASE_URL', configured)
    assert _gateway_exchange(client, code).status_code == 403


def test_gateway_expired_marker_never_regains_local_access(client, gateway_setup):
    code = _gateway_mint(client).json['handoff_path'].split('#code=')[1]
    assert _gateway_exchange(client, code).status_code == 200
    gateway_setup[0] += 900
    response = client.get('/api/recipes', base_url='http://' + _GATEWAY_HOST,
                          headers={**_gateway_headers(), 'X-Forwarded-For': '127.0.0.1'})
    assert response.status_code == 401
    assert response.json['error'] == 'browser_session_expired'
    assert 'Set-Cookie' not in response.headers


def test_direct_custom_http_handoff_survives_gateway_origin_configuration(client, gateway_setup):
    response = enter_view(client, origin='http://custom-kitchen.test:5001')
    assert response.status_code == 200
    assert 'Secure;' not in response.headers['Set-Cookie']
    assert client.get('/api/recipes', base_url='http://custom-kitchen.test:5001', **REMOTE).status_code == 200


@pytest.mark.parametrize("cookie", [None, "expired-session"])
def test_open_mode_loads_recipe_data_without_browser_credentials(client, viewing_setup, monkeypatch, cookie):
    monkeypatch.setenv("KITCHENOS_AUTH_MODE", "open")
    if cookie is not None:
        client.set_cookie("kitchenos_view", cookie)
    response = client.get("/api/recipes/Rice%20%26%20Beans", **REMOTE)
    assert response.status_code == 200
    assert "Simmer beans" in response.text


def test_open_mode_old_cookie_does_not_lock_page_or_writes(client, viewing_setup, monkeypatch):
    import json, re
    monkeypatch.setenv("KITCHENOS_AUTH_MODE", "open")
    client.set_cookie("kitchenos_view", "expired-session")
    page = client.get("/recipe/Rice%20%26%20Beans", **REMOTE)
    config = json.loads(re.search(r'id="browser-view-config">(.*?)</script>', page.text).group(1))
    assert config == {"state": "active", "readOnly": False, "expires_at": None}
    # Real handler validation should be reached, without mutating recipe data.
    response = client.post("/api/browser-handoffs", json={}, **REMOTE)
    assert response.status_code == 400
    assert response.json["error"] == "Invalid destination"
    assert client.get("/health", **REMOTE).status_code == 200


@pytest.mark.parametrize("mode", ["required", "typo"])
def test_only_explicit_open_mode_disables_auth(client, viewing_setup, monkeypatch, mode):
    monkeypatch.setenv("KITCHENOS_AUTH_MODE", mode)
    assert client.get("/api/recipes", **REMOTE).status_code == 401
