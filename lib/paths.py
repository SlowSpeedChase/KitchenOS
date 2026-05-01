"""Centralized vault path resolution.

The vault location is configurable via the KITCHENOS_VAULT environment
variable. Default is ~/KitchenOS/vault/.

All recipe-data paths in the codebase should be derived from these
helpers — never hardcoded.
"""
import os
from pathlib import Path


def vault_root() -> Path:
    """Return the Obsidian vault root directory."""
    raw = os.environ.get("KITCHENOS_VAULT")
    if raw:
        return Path(os.path.expanduser(raw))
    return Path.home() / "KitchenOS" / "vault"


def recipes_dir() -> Path:
    return vault_root() / "Recipes"


def meal_plans_dir() -> Path:
    return vault_root() / "Meal Plans"


def meals_dir() -> Path:
    return vault_root() / "Meals"


def shopping_lists_dir() -> Path:
    return vault_root() / "Shopping Lists"


def calendar_ics_path() -> Path:
    return vault_root() / "meal_calendar.ics"
