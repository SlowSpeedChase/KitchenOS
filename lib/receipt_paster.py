"""Parse a pasted markdown inventory table into routed inventory rows.

Backs a 'preview then commit' bulk add: paste a markdown table, preview the
parsed + routed rows (storage location resolved, expiry computed), then commit
them via ``inventory.add_items``. Complementary to email/photo receipts — good
for ad-hoc manual adds (e.g. a table Claude formatted from a photo).

Only ``Item`` is required. Missing category falls back to ``other``, location
auto-resolves via ``storage_locations``, and expiry auto-fills from the
shelf-life windows. Column headers are matched case-insensitively with common
aliases (Qty/Quantity, Loc/Location, Expiry/Expires, …).
"""
from __future__ import annotations

from lib.inventory import (
    InventoryItem,
    _parse_quantity,
    normalize_category,
    normalize_location,
)
from lib.expiry import compute_expires
from lib.storage_locations import resolve_location

# Header label -> canonical field name.
_COLUMN_ALIASES = {
    "item": "name", "name": "name",
    "quantity": "quantity", "qty": "quantity", "amount": "quantity",
    "unit": "unit", "units": "unit",
    "category": "category", "cat": "category",
    "location": "location", "loc": "location",
    "expires": "expires", "expiry": "expires", "expiration": "expires",
    "purchased": "purchased", "bought": "purchased",
    "notes": "notes", "note": "notes",
}


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into trimmed cells."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    """True for a markdown header separator like |---|:--:|."""
    cells = _split_row(line)
    return bool(cells) and all(set(c) <= set("-: ") and "-" in c for c in cells)


def parse_inventory_table(markdown: str) -> dict:
    """Parse a markdown table into routed items + warnings.

    Returns ``{"items": [InventoryItem, ...], "warnings": [str, ...]}``.
    Routing (location, expiry) is applied here so a preview matches the commit.
    """
    warnings: list[str] = []
    lines = [ln for ln in (markdown or "").splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if ln.lstrip().startswith("|")]

    if not table_lines:
        return {"items": [], "warnings": ["No markdown table found (rows must start with '|')."]}

    header = _split_row(table_lines[0])
    field_by_index: dict[int, str] = {}
    for i, label in enumerate(header):
        field = _COLUMN_ALIASES.get(label.lower())
        if field:
            field_by_index[i] = field
        elif label:
            warnings.append(f"Ignoring unknown column: {label!r}")

    if "name" not in field_by_index.values():
        return {"items": [], "warnings": warnings + ["Table needs an 'Item' (or 'Name') column."]}

    items: list[InventoryItem] = []
    for line in table_lines[1:]:
        if _is_separator(line):
            continue
        cells = _split_row(line)
        row = {field_by_index[i]: cells[i] for i in field_by_index if i < len(cells)}

        name = (row.get("name") or "").strip()
        if not name:
            continue  # blank/spacer row

        category = normalize_category(row.get("category"))
        location = (
            normalize_location(row["location"])
            if row.get("location")
            else resolve_location(name, category)
        )
        purchased = (row.get("purchased") or "").strip() or None
        expires = (row.get("expires") or "").strip() or compute_expires(purchased, name, category)

        items.append(
            InventoryItem(
                name=name,
                quantity=_parse_quantity(row.get("quantity")),
                unit=(row.get("unit") or "ct").strip() or "ct",
                category=category,
                location=location,
                purchased=purchased,
                source="claude",
                notes=(row.get("notes") or "").strip(),
                expires=expires,
            )
        )

    if not items:
        warnings.append("No item rows parsed.")
    return {"items": items, "warnings": warnings}


def preview(markdown: str) -> dict:
    """Parsed rows as JSON-able dicts for a confirmation step (no DB writes)."""
    parsed = parse_inventory_table(markdown)
    return {
        "items": [it.to_dict() for it in parsed["items"]],
        "warnings": parsed["warnings"],
        "count": len(parsed["items"]),
    }


def commit(markdown: str) -> dict:
    """Parse and persist the table via inventory.add_items."""
    from lib.inventory import add_items

    parsed = parse_inventory_table(markdown)
    if not parsed["items"]:
        return {"added": 0, "merged": 0, "total": 0, "warnings": parsed["warnings"]}
    result = add_items(parsed["items"])
    result["warnings"] = parsed["warnings"]
    return result
