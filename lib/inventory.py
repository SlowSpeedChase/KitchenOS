"""Pantry inventory storage.

Stores items in a single ``Inventory.md`` file at the vault root. The body is a
markdown table so it stays human-readable in Obsidian and machine-parseable
without a YAML library. Items with the same ``(name, unit, location)`` are
merged on add — quantities sum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from lib import paths

CATEGORIES = (
    "produce", "dairy", "meat", "seafood", "pantry",
    "frozen", "bakery", "beverages", "household", "other",
)
LOCATIONS = ("fridge", "freezer", "pantry", "counter", "other")
SOURCES = ("receipt", "manual", "claude")

HEADER = "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |"
SEPARATOR = "|------|----------|------|----------|----------|-----------|--------|-------|"


@dataclass
class InventoryItem:
    name: str
    quantity: float
    unit: str = "ct"
    category: str = "other"
    location: str = "pantry"
    purchased: Optional[str] = None
    source: str = "manual"
    notes: str = ""

    def merge_key(self) -> tuple[str, str, str]:
        return (
            self.name.lower().strip(),
            self.unit.lower().strip(),
            self.location.lower().strip(),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def inventory_path() -> Path:
    return paths.vault_root() / "Inventory.md"


def normalize_category(cat: Optional[str]) -> str:
    if not cat:
        return "other"
    c = cat.lower().strip()
    return c if c in CATEGORIES else "other"


def normalize_location(loc: Optional[str]) -> str:
    if not loc:
        return "pantry"
    l = loc.lower().strip()
    return l if l in LOCATIONS else "other"


def normalize_source(src: Optional[str]) -> str:
    if not src:
        return "manual"
    s = src.lower().strip()
    return s if s in SOURCES else "manual"


def _format_quantity(q: float) -> str:
    if q == int(q):
        return str(int(q))
    return f"{q:.2f}".rstrip("0").rstrip(".")


def _parse_quantity(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 1.0
    try:
        return float(s)
    except ValueError:
        return 1.0


def read_inventory() -> list[InventoryItem]:
    path = inventory_path()
    if not path.exists():
        return []

    items: list[InventoryItem] = []
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Item |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---") or line.startswith("| ---"):
            continue
        if not line.startswith("|"):
            in_table = False
            continue

        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 3 or not cells[0]:
            continue
        cells = (cells + [""] * 8)[:8]
        items.append(
            InventoryItem(
                name=cells[0],
                quantity=_parse_quantity(cells[1]),
                unit=cells[2] or "ct",
                category=normalize_category(cells[3]),
                location=normalize_location(cells[4]),
                purchased=cells[5] or None,
                source=normalize_source(cells[6]),
                notes=cells[7],
            )
        )
    return items


def write_inventory(items: list[InventoryItem]) -> None:
    path = inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    sorted_items = sorted(items, key=lambda i: (i.category, i.name.lower()))

    rows = [HEADER, SEPARATOR]
    for it in sorted_items:
        cells = [
            it.name,
            _format_quantity(it.quantity),
            it.unit,
            it.category,
            it.location,
            it.purchased or "",
            it.source,
            it.notes.replace("|", "\\|"),
        ]
        rows.append("| " + " | ".join(cells) + " |")

    content = (
        "---\n"
        "type: inventory\n"
        f"last_updated: {date.today().isoformat()}\n"
        "---\n\n"
        "# Pantry Inventory\n\n"
        "> Tracking what's on hand. Updated from grocery receipts and manual entries.\n\n"
        + "\n".join(rows)
        + "\n"
    )
    path.write_text(content, encoding="utf-8")


def add_items(new_items: list[InventoryItem]) -> dict:
    """Add items, merging by (name, unit, location). Quantities sum on merge."""
    existing = read_inventory()
    by_key: dict[tuple[str, str, str], InventoryItem] = {
        it.merge_key(): it for it in existing
    }

    added = 0
    merged = 0
    for new in new_items:
        key = new.merge_key()
        if key in by_key:
            cur = by_key[key]
            cur.quantity += new.quantity
            if new.purchased:
                cur.purchased = new.purchased
            if new.notes and not cur.notes:
                cur.notes = new.notes
            if new.category != "other":
                cur.category = new.category
            merged += 1
        else:
            by_key[key] = new
            added += 1

    write_inventory(list(by_key.values()))
    return {"added": added, "merged": merged, "total": len(by_key)}


def remove_item(name: str, location: Optional[str] = None) -> bool:
    items = read_inventory()
    target = name.lower().strip()
    target_loc = location.lower().strip() if location else None

    keep: list[InventoryItem] = []
    removed = False
    for it in items:
        if it.name.lower().strip() == target and (
            target_loc is None or it.location == target_loc
        ):
            removed = True
            continue
        keep.append(it)

    if removed:
        write_inventory(keep)
    return removed


def update_quantity(
    name: str, quantity: float, location: Optional[str] = None
) -> bool:
    items = read_inventory()
    target = name.lower().strip()
    target_loc = location.lower().strip() if location else None

    found = False
    for it in items:
        if it.name.lower().strip() == target and (
            target_loc is None or it.location == target_loc
        ):
            it.quantity = quantity
            found = True
            break

    if found:
        write_inventory(items)
    return found
