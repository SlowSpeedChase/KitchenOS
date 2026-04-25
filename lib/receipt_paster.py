"""Parse a pasted markdown table into routed inventory rows.

Accepted formats (Claude is told to produce one of these in chat, then the
user pastes into the inventory UI or pipes into ``manage_inventory.py
--paste``):

Minimum:
    | Item            | Qty | Unit |
    |-----------------|-----|------|
    | chicken breast  | 2   | lb   |

Full (optional Group / Location / Expires / Notes overrides):
    | Item       | Qty | Unit | Group   | Location          | Expires    | Notes |
    | salmon     | 1   | lb   |         | fridge/middle     |            |       |
    | yogurt     | 1   | tub  | dairy   |                   | 2026-05-10 |       |

Header names are case-insensitive. Extra columns are ignored. Missing Qty/Unit
fall back to ``1`` / ``each`` (mirrors ``lib/ingredient_parser`` defaults).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from lib.inventory import (
    InventoryRow,
    Layout,
    apply_default_expiry,
    normalize_row_units,
    route_item,
)

HEADER_ALIASES: dict[str, str] = {
    "item": "item", "name": "item", "ingredient": "item", "product": "item",
    "qty": "qty", "quantity": "qty", "amount": "qty", "count": "qty",
    "unit": "unit", "units": "unit", "uom": "unit",
    "group": "group", "category": "group",
    "location": "location", "shelf": "location", "where": "location",
    "expires": "expires", "expiry": "expires", "expiration": "expires", "best by": "expires",
    "notes": "notes", "note": "notes", "comment": "notes",
}


def parse_table(markdown: str) -> tuple[list[dict[str, str]], list[str]]:
    """Pull the first markdown table out of ``markdown`` and return its rows.

    Returns (rows, warnings). Each row is a dict keyed by canonical column
    name (item/qty/unit/group/location/expires/notes). Missing fields are
    empty strings.
    """
    warnings: list[str] = []
    lines = [ln.rstrip() for ln in markdown.splitlines()]

    # find first line that looks like a table row
    header_idx = None
    for i, ln in enumerate(lines):
        if _looks_like_table_row(ln):
            header_idx = i
            break
    if header_idx is None:
        return [], ["no markdown table found in input"]

    header_cells = _split_row(lines[header_idx])
    canonical = [_canonicalize_header(c) for c in header_cells]
    if "item" not in canonical:
        return [], ["table is missing an 'Item' column"]

    # skip optional separator line
    body_start = header_idx + 1
    if body_start < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[body_start]):
        body_start += 1

    rows: list[dict[str, str]] = []
    for ln in lines[body_start:]:
        if not _looks_like_table_row(ln):
            if ln.strip() == "":
                continue
            break  # table ended
        cells = _split_row(ln)
        # pad/trim to header width
        while len(cells) < len(canonical):
            cells.append("")
        row = {col: "" for col in HEADER_ALIASES.values()}
        for col, val in zip(canonical, cells):
            if col is None:
                continue
            row[col] = val
        if not row.get("item"):
            continue
        rows.append(row)
    return rows, warnings


def rows_to_inventory(rows: Iterable[dict[str, str]], layout: Layout,
                      today: date | None = None) -> list[InventoryRow]:
    """Route each parsed row to a (group, location), normalize qty/unit, fill expiry."""
    today = today or date.today()
    result: list[InventoryRow] = []
    for row in rows:
        item = row.get("item", "").strip()
        if not item:
            continue
        qty_raw = row.get("qty", "").strip() or "1"
        unit_raw = row.get("unit", "").strip() or "each"
        qty, unit = normalize_row_units(qty_raw, unit_raw)

        group_override = row.get("group", "").strip().lower() or None
        location_override = _normalize_location(row.get("location", "").strip(), layout)

        group, location, warnings = route_item(
            item, layout,
            group_override=group_override,
            location_override=location_override,
        )

        expires_override = row.get("expires", "").strip()
        if expires_override and not _is_iso_date(expires_override):
            warnings.append(f"ignoring non-ISO expires '{expires_override}'")
            expires_override = ""

        inv = InventoryRow(
            item=item,
            qty=qty,
            unit=unit,
            group=group,
            location=location,
            added=today.isoformat(),
            expires=expires_override,
            notes=row.get("notes", "").strip(),
            warnings=warnings,
        )
        if not inv.expires:
            apply_default_expiry(inv, layout, today=today)
        result.append(inv)
    return result


def parse_paste(markdown: str, layout: Layout,
                today: date | None = None) -> tuple[list[InventoryRow], list[str]]:
    """Convenience: parse table + route rows in one call."""
    raw_rows, warnings = parse_table(markdown)
    if not raw_rows:
        return [], warnings
    return rows_to_inventory(raw_rows, layout, today=today), warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looks_like_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_row(line: str) -> list[str]:
    s = line.strip()
    # strip leading/trailing pipes once
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _canonicalize_header(header: str) -> str | None:
    key = header.strip().lower()
    return HEADER_ALIASES.get(key)


def _normalize_location(value: str, layout: Layout) -> str | None:
    """Accept 'fridge/middle', 'fridge - middle', or 'Fridge — Middle Shelf'."""
    if not value:
        return None
    v = value.strip()
    # exact location id (space_id/shelf_id)
    if "/" in v and layout.shelf_by_location(v.lower().replace(" ", "-")):
        return v.lower().replace(" ", "-")
    # try heading match (case-insensitive)
    for shelf in layout.shelves:
        if shelf.section_heading.lower() == v.lower():
            return shelf.location_id
        # tolerant match on dash variants
        normal = v.replace("—", "-").replace("–", "-").lower()
        heading_normal = shelf.section_heading.replace("—", "-").lower()
        if normal == heading_normal:
            return shelf.location_id
    # try "space - shelf" id form
    parts = re.split(r"[\s/—–-]+", v.lower())
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        candidate = f"{parts[0]}/{parts[-1]}"
        if layout.shelf_by_location(candidate):
            return candidate
    return None


def _is_iso_date(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
