"""One-use credentials must expire, bind to their origin, and stay bounded."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib

import pytest


@pytest.fixture
def module():
    # An assertion gives a useful red result before the new module exists.
    assert importlib.util.find_spec('lib.browser_handoff'), 'browser handoff store missing'
    return importlib.import_module('lib.browser_handoff')


@pytest.fixture
def clock():
    return [1000.0]


@pytest.fixture
def store(module, clock):
    return module.BrowserHandoffStore(clock=lambda: clock[0])


def issue(store):
    return store.issue('/recipe/Rice%20%26%20Beans', 'http://kitchen:5001', 'token-hash')


def exchange(store, code):
    return store.exchange(code, 'http://kitchen:5001', 'token-hash')


def test_code_succeeds_at_59_seconds_and_is_single_use(store, clock):
    issued = issue(store)
    assert issued.expires_at == 1060
    clock[0] += 59
    grant = exchange(store, issued.code)
    assert grant.redirect_path == '/recipe/Rice%20%26%20Beans'
    assert grant.expires_at == 1959
    assert exchange(store, issued.code) is None


def test_code_fails_at_60_seconds(store, clock):
    issued = issue(store)
    clock[0] += 60
    assert exchange(store, issued.code) is None


def test_grant_expires_absolutely_at_900_seconds(store, clock):
    grant = exchange(store, issue(store).code)
    clock[0] += 899
    assert store.authorize(grant.session_id, 'http://kitchen:5001', 'token-hash')
    clock[0] += 1
    assert store.authorize(grant.session_id, 'http://kitchen:5001', 'token-hash') is None


def test_concurrent_exchange_has_one_winner(store):
    issued = issue(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: exchange(store, issued.code), range(8)))
    assert sum(result is not None for result in outcomes) == 1


@pytest.mark.parametrize('origin,fingerprint', [
    ('http://kitchen:5002', 'token-hash'),
    ('https://kitchen:5001', 'token-hash'),
    ('http://evil:5001', 'token-hash'),
    ('http://kitchen:5001', 'rotated'),
])
def test_code_and_session_bind_to_origin_and_token(store, origin, fingerprint):
    issued = issue(store)
    assert store.exchange(issued.code, origin, fingerprint) is None
    grant = exchange(store, issued.code)
    assert store.authorize(grant.session_id, origin, fingerprint) is None


def test_restart_revokes_existing_session(module, store):
    grant = exchange(store, issue(store).code)
    assert module.BrowserHandoffStore().authorize(
        grant.session_id, 'http://kitchen:5001', 'token-hash') is None


def test_codes_and_sessions_are_stored_as_hashes_only(store):
    issued = issue(store)
    assert issued.code not in repr(store.__dict__)
    assert hashlib.sha256(issued.code.encode()).hexdigest() in store._codes
    grant = exchange(store, issued.code)
    assert grant.session_id not in repr(store.__dict__)
    assert hashlib.sha256(grant.session_id.encode()).hexdigest() in store._sessions


def test_code_capacity_prunes_expired_entries(module, store, clock):
    for _ in range(1024):
        issue(store)
    with pytest.raises(module.CapacityExceeded):
        issue(store)
    clock[0] += 60
    assert issue(store)
    assert len(store._codes) == 1


def test_full_session_store_does_not_consume_valid_code(module, store, clock):
    for _ in range(1024):
        exchange(store, issue(store).code)
    clock[0] += 899
    pending = issue(store)
    with pytest.raises(module.CapacityExceeded):
        exchange(store, pending.code)
    clock[0] += 1
    assert exchange(store, pending.code) is not None


@pytest.mark.parametrize('destination', [
    'https://evil.test/', '//evil.test/', '/refresh', '/recipe/../refresh',
    '/recipe/a/b', '/recipe/a?next=evil', '/recipe/a#secret',
])
def test_store_rejects_non_view_destinations(store, destination):
    with pytest.raises(ValueError):
        store.issue(destination, 'http://kitchen:5001', 'token-hash')
