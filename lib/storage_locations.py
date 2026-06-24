"""Storage-location lookup — where incoming stock should be stored.

``config/storage_locations.json`` decides the storage location (fridge,
freezer, pantry, counter, other) for a purchased item. Two tiers, item wins:

- ``by_item``     canonical item name → location. Hand-correctable overrides
                  for cases the category default gets wrong (bananas and bread
                  belong on the counter, onions and potatoes in the pantry —
                  not the ``produce``/``bakery`` default).
- ``by_category`` coarse fallback by receipt category.

A purchase resolves by exact item name, then by any item key whose words are
all contained in the name (so "roma tomatoes" still matches "tomatoes"), then
by category, then ``"pantry"``. The file is plain JSON so it stays editable in
a text editor, mirroring ``config/item_aliases.json``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from lib.inventory import normalize_location

TABLE_PATH = Path(__file__).resolve().parent.parent / "config" / "storage_locations.json"

_DEFAULT_LOCATION = "pantry"


def load_table() -> dict:
    """Return the storage-location table, or empty tiers if missing/corrupt."""
    if not TABLE_PATH.exists():
        return {"by_item": {}, "by_category": {}}
    try:
        data = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"by_item": {}, "by_category": {}}
    if not isinstance(data, dict):
        return {"by_item": {}, "by_category": {}}
    data.setdefault("by_item", {})
    data.setdefault("by_category", {})
    return data


def save_table(table: dict) -> None:
    """Atomically persist the table (tmp + replace), keys sorted."""
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "by_item": dict(sorted(table.get("by_item", {}).items())),
        "by_category": dict(sorted(table.get("by_category", {}).items())),
    }
    tmp = TABLE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    tmp.replace(TABLE_PATH)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (s or "").lower()))


def resolve_location(name: str, category: Optional[str] = None) -> str:
    """Resolve where an item should be stored.

    Priority: exact item override > word-subset item override > category
    default > ``"pantry"``. Always returns a valid LOCATIONS vocab value.
    """
    table = load_table()
    by_item = table.get("by_item", {})

    n = (name or "").lower().strip()
    if n in by_item:
        return normalize_location(by_item[n])

    name_tokens = _tokens(n)
    if name_tokens:
        for key, loc in by_item.items():
            key_tokens = _tokens(key)
            if key_tokens and key_tokens <= name_tokens:
                return normalize_location(loc)

    by_category = table.get("by_category", {})
    cat = (category or "").lower().strip()
    if cat in by_category:
        return normalize_location(by_category[cat])

    return _DEFAULT_LOCATION


def save_item_override(name: str, location: str) -> None:
    """Remember a hand-correction: store this item here from now on."""
    n = (name or "").lower().strip()
    if not n:
        return
    table = load_table()
    table.setdefault("by_item", {})[n] = normalize_location(location)
    save_table(table)
