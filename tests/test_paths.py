"""Tests for lib.paths vault location helper."""
from pathlib import Path


from lib import paths


def test_default_vault_is_home_kitchenos_vault(monkeypatch):
    monkeypatch.delenv("KITCHENOS_VAULT", raising=False)
    assert paths.vault_root() == Path.home() / "KitchenOS" / "vault"


def test_env_override_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.vault_root() == tmp_path


def test_env_override_expands_tilde(monkeypatch):
    monkeypatch.setenv("KITCHENOS_VAULT", "~/some/place")
    assert paths.vault_root() == Path.home() / "some" / "place"


def test_recipes_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.recipes_dir() == tmp_path / "Recipes"


def test_meal_plans_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.meal_plans_dir() == tmp_path / "Meal Plans"


def test_meals_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.meals_dir() == tmp_path / "Meals"


def test_shopping_lists_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.shopping_lists_dir() == tmp_path / "Shopping Lists"


def test_calendar_ics_path_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.calendar_ics_path() == tmp_path / "meal_calendar.ics"
