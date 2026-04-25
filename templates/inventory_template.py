"""Render an empty Inventory.md skeleton from the layout config."""

from __future__ import annotations

from datetime import date

from lib.inventory import Layout, _TABLE_HEADER, _TABLE_SEPARATOR


def render_skeleton(layout: Layout, updated: date | None = None) -> str:
    """One ``## Zone — Shelf`` section per shelf, each with an empty table."""
    updated = updated or date.today()
    out: list[str] = [
        "# Kitchen Inventory",
        f"Last updated: {updated.isoformat()}",
        "",
        "> Edit any cell directly. New rows can also be added via the receipt paste flow:",
        "> `POST /api/inventory/paste` or `manage_inventory.py --paste`.",
        "",
    ]
    for shelf in layout.shelves:
        out.append(f"## {shelf.section_heading}")
        out.append(_TABLE_HEADER)
        out.append(_TABLE_SEPARATOR)
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"
