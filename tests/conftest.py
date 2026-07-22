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
