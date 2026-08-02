"""Shared pytest fixtures."""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_vault(monkeypatch):
    """Point the vault at a temp dir for the duration of a test."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("KITCHENOS_VAULT", tmp)
        yield Path(tmp)


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the KitchenOS DB at a temp file for the duration of a test."""
    db = tmp_path / "test_kitchenos.db"
    monkeypatch.setenv("KITCHENOS_DB", str(db))
    yield db


@pytest.fixture(autouse=True)
def _isolate_db(request, monkeypatch, tmp_path):
    """Never let a test read or write the real data/kitchenos.db.

    Several suites exercise DB-backed code (nutrition_engine, food_db,
    food_resolver, fdc_local, the ledgers) without asking for `tmp_db`, so they
    were resolving KITCHENOS_DB to the developer's live database. That couples
    results to whatever the running API server, a backfill script, or a parallel
    pytest process happens to be doing — and lets a test *write* cache rows into
    real data.

    Tests that request `tmp_db` explicitly keep their own path; this only fills
    in for the ones that never thought about it.
    """
    if "tmp_db" in request.fixturenames:
        return
    monkeypatch.setenv("KITCHENOS_DB", str(tmp_path / "autouse_kitchenos.db"))


@pytest.fixture(autouse=True)
def _isolate_storage_table(monkeypatch, tmp_path):
    """Never let a test write the real config/storage_locations.json.

    Since a move teaches the table, *any* test that moves, freezes or bulk-moves
    a row now writes an override — and `save_table` rewrites the whole file with
    sorted keys. Without this, the ordinary move tests rewrote the developer's
    real config: they flipped `bread` from counter to pantry, injected their
    fixture item names, and reordered `by_category`, which then broke
    `test_category_fallback` on the next run.

    The real table is *copied* rather than replaced with empty tiers, because
    some tests legitimately depend on its contents. Reads see the real data;
    writes land on the copy. Tests wanting a known table monkeypatch TABLE_PATH
    themselves — their patch is applied after this one and wins.

    Sets the env var rather than patching the attribute, because
    `table_path()` checks the env var *first*: patching only the attribute would
    leave a stray KITCHENOS_STORAGE_TABLE in the environment silently overriding
    this fixture. Using the same knob also means any subprocess a future test
    spawns inherits the isolation, not just in-process code.
    """
    from lib import storage_locations

    real = storage_locations.TABLE_PATH
    copy = tmp_path / "storage_locations.json"
    if real.exists():
        copy.write_bytes(real.read_bytes())
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(copy))


@pytest.fixture(autouse=True)
def _no_background_precompute(monkeypatch):
    """Keep prep-task precompute threads out of the suite.

    `_regen_weeks` spawns a daemon thread on every ledger mutation to rebuild
    the week's prep sidecar off-request. That is right in production and wrong
    in tests: the thread outlives the test and writes into `tmp_path` while
    pytest is removing it, which surfaced as a teardown
    `OSError: Directory not empty: 'Meal Plans'` in an unrelated move test.

    The precompute's own tests bind the real function at import time
    (`_REAL_PRECOMPUTE` in tests/test_api_ledger.py), so they are unaffected by
    this patch and still exercise the threading for real.
    """
    import api_server
    monkeypatch.setattr(api_server, "_precompute_tasks_async", lambda week: None)
