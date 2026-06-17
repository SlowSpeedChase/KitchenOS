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
