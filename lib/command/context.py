"""Validate what a page or the app says is on screen. It is untrusted input.

The context is typed, never a URL or a path: a recipe must be an existing
recipe *name*, a week a real ISO week, a date a real civil date.
"""
from datetime import date

from lib.safe_paths import parse_iso_week

SCREENS = {"home", "recipe", "planner", "inventory", "shopping", "cook-now", "other"}
_KEYS = {"screen", "recipe", "week", "date", "cook_id"}


def validate(raw) -> dict:
    if raw is None:
        return {"screen": "other"}
    if not isinstance(raw, dict):
        raise ValueError("context must be an object")
    unknown = set(raw) - _KEYS
    if unknown:
        raise ValueError(f"unknown context keys: {sorted(unknown)}")
    screen = raw.get("screen", "other")
    if screen not in SCREENS:
        raise ValueError(f"unknown screen: {screen!r}")
    out = {"screen": screen}

    if raw.get("recipe") is not None:
        from lib import paths
        names = {p.stem for p in paths.recipes_dir().glob("*.md")}
        if raw["recipe"] not in names:
            raise ValueError("unknown recipe")
        out["recipe"] = raw["recipe"]
    if raw.get("week") is not None:
        out["week"] = parse_iso_week(raw["week"])
    if raw.get("date") is not None:
        if not isinstance(raw["date"], str):
            raise ValueError("date must be YYYY-MM-DD")
        out["date"] = date.fromisoformat(raw["date"]).isoformat()
    if raw.get("cook_id") is not None:
        from lib import serving_ledger
        if not isinstance(raw["cook_id"], int) or serving_ledger.get_cook(raw["cook_id"]) is None:
            raise ValueError("unknown cook")
        out["cook_id"] = raw["cook_id"]
    return out
