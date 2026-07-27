"""Storage-location lookup — where incoming stock should be stored.

``config/storage_locations.json`` decides the storage location (fridge,
freezer, pantry, counter, other) for a purchased item. Two tiers, item wins:

- ``by_item``     canonical item name → location. Hand-correctable overrides
                  for cases the category default gets wrong (bananas and bread
                  belong on the counter, onions and potatoes in the pantry —
                  not the ``produce``/``bakery`` default).
- ``by_category`` coarse fallback by receipt category.

A purchase resolves by exact item name, then by the *longest* item key whose
words are all contained in the name (so "roma tomatoes" still matches
"tomatoes", but a taught "milk" never swallows "milk chocolate chips"), then by
category, then ``"pantry"``. ``place_item`` also reports which tier decided, so
callers can tell a hand-curated answer from a shrug. The file is plain JSON so
it stays editable in a text editor, mirroring ``config/item_aliases.json``.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lib.inventory import normalize_location

TABLE_PATH = Path(__file__).resolve().parent.parent / "config" / "storage_locations.json"

_DEFAULT_LOCATION = "pantry"


def table_path() -> Path:
    """Where the storage table lives. ``KITCHENOS_STORAGE_TABLE`` overrides.

    Resolved at call time, mirroring ``inventory_db.db_path``, so a *subprocess*
    launched with the var set writes to its own copy. The e2e harness needs
    this: it runs api_server.py out-of-process, so an in-process monkeypatch of
    TABLE_PATH can't reach it, and a move teaches the table — which meant the
    browser tests were rewriting the developer's real config.
    """
    raw = os.environ.get("KITCHENOS_STORAGE_TABLE")
    return Path(raw) if raw else TABLE_PATH


def load_table() -> dict:
    """Return the storage-location table, or empty tiers if missing/corrupt."""
    path = table_path()
    if not path.exists():
        return {"by_item": {}, "by_category": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"by_item": {}, "by_category": {}}
    if not isinstance(data, dict):
        return {"by_item": {}, "by_category": {}}
    data.setdefault("by_item", {})
    data.setdefault("by_category", {})
    return data


def save_table(table: dict) -> None:
    """Atomically persist the table (tmp + replace), keys sorted."""
    path = table_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "by_item": dict(sorted(table.get("by_item", {}).items())),
        "by_category": dict(sorted(table.get("by_category", {}).items())),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (s or "").lower()))


CATCH_ALL_CATEGORY = "other"


@dataclass(frozen=True)
class Placement:
    """Where an item goes, and how confidently we know it.

    ``source`` is one of ``item`` (a hand-curated by_item override matched),
    ``category`` (a by_category rule matched a real category), or ``default``
    (nothing meaningful matched). Callers store it on the row so a guess stays
    distinguishable from a placement the user confirmed.
    """

    location: str
    source: str


def place_item(name: str, category: Optional[str] = None) -> Placement:
    """Resolve where an item goes, and report which tier decided it.

    Priority: exact item override > longest word-subset item override >
    category default > ``"pantry"``.

    Two rules are worth stating outright:

    - **The longest matching key wins.** ``save_item_override`` grows
      ``by_item`` on every correction the user makes, and returning the first
      dict-order subset match would eventually let ``milk`` capture
      ``milk chocolate chips``. Most specific wins instead.
    - **The catch-all category is not a match.** ``normalize_category`` funnels
      every value it can't place into ``other``, so a location derived from
      ``other`` is the categoriser shrugging. The location still comes from the
      rule, but the source is ``default`` — which is the only thing that makes
      the ``default`` tier reachable at all, since ``by_category`` has an entry
      for all ten categories.
    """
    table = load_table()
    by_item = table.get("by_item", {})

    n = (name or "").lower().strip()
    if n in by_item:
        return Placement(normalize_location(by_item[n]), "item")

    name_tokens = _tokens(n)
    best_key: Optional[str] = None
    best_len = 0
    if name_tokens:
        for key in by_item:
            key_tokens = _tokens(key)
            if key_tokens and key_tokens <= name_tokens and len(key_tokens) > best_len:
                best_key, best_len = key, len(key_tokens)
    if best_key is not None:
        return Placement(normalize_location(by_item[best_key]), "item")

    by_category = table.get("by_category", {})
    cat = (category or "").lower().strip()
    if cat in by_category:
        source = "default" if cat == CATCH_ALL_CATEGORY else "category"
        return Placement(normalize_location(by_category[cat]), source)

    return Placement(_DEFAULT_LOCATION, "default")


def resolve_location(name: str, category: Optional[str] = None) -> str:
    """Resolve where an item should be stored.

    A thin wrapper over :func:`place_item` for callers that only need the
    location. Always returns a valid LOCATIONS vocab value.
    """
    return place_item(name, category).location


def save_item_override(name: str, location: str) -> None:
    """Remember a hand-correction: store this item here from now on."""
    n = (name or "").lower().strip()
    if not n:
        return
    table = load_table()
    table.setdefault("by_item", {})[n] = normalize_location(location)
    save_table(table)
