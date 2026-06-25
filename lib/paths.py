"""Centralized vault path resolution.

The vault location is configurable via the KITCHENOS_VAULT environment
variable. Default is ~/KitchenOS/KitchenOSApp/.

All recipe-data paths in the codebase should be derived from these
helpers — never hardcoded.

This module loads the repo's .env on import so KITCHENOS_VAULT resolves
consistently for every entry point — including the cron scripts
(sync_calendar, generate_meal_plan, …) whose LaunchAgent plists set no
EnvironmentVariables and which don't call load_dotenv themselves. paths is
imported before any module-level path constant is computed, so it's the one
reliable chokepoint. override=False keeps a real env var (set by launchd, CI,
or a test) winning over the .env file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def vault_root() -> Path:
    """Return the Obsidian vault root directory."""
    raw = os.environ.get("KITCHENOS_VAULT")
    if raw:
        return Path(os.path.expanduser(raw))
    return Path.home() / "KitchenOS" / "KitchenOS_Vault"


def recipes_dir() -> Path:
    return vault_root() / "Recipes"


def meal_plans_dir() -> Path:
    return vault_root() / "Meal Plans"


def meals_dir() -> Path:
    return vault_root() / "Meals"


def shopping_lists_dir() -> Path:
    return vault_root() / "Shopping Lists"


def archive_dir() -> Path:
    """Vault-root folder for retired/duplicate notes.

    Sits beside Recipes/ (not inside it) so the recursive 'Recipes' Base/Dataview
    queries don't surface archived dupes. Add '_Archive/' to the Obsidian
    userIgnoreFilters to hide it from search too.
    """
    return vault_root() / "_Archive"


def calendar_ics_path() -> Path:
    return vault_root() / "meal_calendar.ics"
