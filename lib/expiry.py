"""Default expiry windows for inventory items.

``config/expiry_windows.json`` maps items/categories to a shelf-life in days,
used to auto-fill an item's ``expires`` date on add. Two tiers, item wins —
mirroring ``storage_locations.py``:

- ``by_item``     canonical item name → days (perishables the category default
                  gets wrong, e.g. bananas spoil faster than generic produce).
- ``by_category`` coarse fallback by category.

A ``null`` window (e.g. household, other) means "no expiry" → no date is set.
Resolution: exact item, then any item key whose words are all in the name
("ground beef" matches "lean ground beef"), then category, else None.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

TABLE_PATH = Path(__file__).resolve().parent.parent / "config" / "expiry_windows.json"

# How many days before an item's expiry it counts as "expiring soon".
SOON_THRESHOLD_DAYS = 3


def load_table() -> dict:
    """Return the expiry table, or empty tiers if missing/corrupt."""
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


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (s or "").lower()))


def default_expiry_days(name: str, category: Optional[str] = None) -> Optional[int]:
    """Shelf-life in days for an item, or None when no window is configured."""
    table = load_table()
    by_item = table.get("by_item", {})

    n = (name or "").lower().strip()
    if n in by_item:
        return by_item[n]

    name_tokens = _tokens(n)
    if name_tokens:
        for key, days in by_item.items():
            key_tokens = _tokens(key)
            if key_tokens and key_tokens <= name_tokens:
                return days

    by_category = table.get("by_category", {})
    cat = (category or "").lower().strip()
    return by_category.get(cat)


def compute_expires(
    purchased: Optional[str],
    name: str,
    category: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[str]:
    """ISO expiry date = base date + shelf-life, or None if no window.

    Base date is ``purchased`` when present and parseable, else ``today``.
    """
    days = default_expiry_days(name, category)
    if days is None:
        return None

    base = None
    if purchased:
        try:
            base = date.fromisoformat(purchased)
        except ValueError:
            base = None
    if base is None:
        base = today or date.today()

    return (base + timedelta(days=days)).isoformat()


def expiry_status(expires: Optional[str], today: Optional[date] = None) -> Optional[str]:
    """Classify an expiry date: 'expired', 'soon', 'ok', or None if unset/bad."""
    if not expires:
        return None
    try:
        exp = date.fromisoformat(expires)
    except ValueError:
        return None
    today = today or date.today()
    delta = (exp - today).days
    if delta < 0:
        return "expired"
    if delta <= SOON_THRESHOLD_DAYS:
        return "soon"
    return "ok"
