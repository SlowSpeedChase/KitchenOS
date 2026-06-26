"""Pantry inventory storage.

The SQLite database (``lib/inventory_db.py``) is the source of truth. The
``Inventory.md`` file at the vault root is a regenerated read-only view —
rewritten on every ``write_inventory()`` so the stock stays browsable in
Obsidian, but edits there are overwritten. Items with the same
``(name, unit, location)`` are merged on add — quantities sum.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from lib import paths
from lib.expiry import compute_expires, expiry_status

CATEGORIES = (
    "produce", "dairy", "meat", "seafood", "pantry",
    "frozen", "bakery", "beverages", "household", "other",
)
LOCATIONS = ("fridge", "freezer", "pantry", "counter", "other")
SOURCES = ("receipt", "manual", "claude", "csa")

HEADER = "| Item | Quantity | Unit | Category | Location | For Recipe | Purchased | Expires | Source | Notes |"
SEPARATOR = "|------|----------|------|----------|----------|------------|-----------|---------|--------|-------|"


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
    for_recipe: Optional[str] = None
    expires: Optional[str] = None

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
    norm = loc.lower().strip()
    return norm if norm in LOCATIONS else "other"


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


def parse_inventory_markdown(text: str) -> list[InventoryItem]:
    """Parse a legacy Inventory.md table. Used by the one-time migration."""
    items: list[InventoryItem] = []
    in_table = False
    for line in text.splitlines():
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


def read_inventory() -> list[InventoryItem]:
    """Current stock from the DB (source of truth)."""
    from lib import inventory_db

    return [
        InventoryItem(
            name=r["name"],
            quantity=float(r["quantity"]),
            unit=r["unit"] or "ct",
            category=normalize_category(r["category"]),
            location=normalize_location(r["location"]),
            purchased=r["purchased"] or None,
            source=normalize_source(r["source"]),
            notes=r["notes"] or "",
            for_recipe=r["for_recipe"] or None,
            expires=r["expires"] or None,
        )
        for r in inventory_db.fetch_inventory_rows()
    ]


def _earliest_expiry(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """The earlier of two ISO expiry dates; whichever is set if only one is."""
    candidates = [d for d in (a, b) if d]
    return min(candidates) if candidates else None


def _merge_recipes(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Union two comma-separated recipe-name strings, order preserved."""
    names: list[str] = []
    for src in (a, b):
        for part in (src or "").split(","):
            name = part.strip()
            if name and name not in names:
                names.append(name)
    return ", ".join(names) or None


def _expiry_cell(expires: Optional[str], status: Optional[str]) -> str:
    """Expires column text with a status marker (🔴 expired, 🟡 soon)."""
    if not expires:
        return ""
    if status == "expired":
        return f"🔴 {expires}"
    if status == "soon":
        return f"🟡 {expires}"
    return expires


def _expiry_warning_section(flagged: list[tuple[str, InventoryItem]]) -> str:
    """A '⚠️ Expiring Soon' list shown above the table (expired first)."""
    if not flagged:
        return ""
    order = {"expired": 0, "soon": 1}
    lines = ["## ⚠️ Expiring Soon", ""]
    for status, it in sorted(flagged, key=lambda f: (order[f[0]], f[1].expires or "")):
        label = "🔴 **Expired**" if status == "expired" else "🟡 Soon"
        lines.append(
            f"- {label} — **{it.name}** "
            f"({_format_quantity(it.quantity)} {it.unit}, {it.location}) "
            f"— expires {it.expires}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def render_inventory_md(items: list[InventoryItem]) -> str:
    """Render the read-only Obsidian view of current stock."""
    today = date.today()
    sorted_items = sorted(items, key=lambda i: (i.category, i.name.lower()))

    flagged: list[tuple[str, InventoryItem]] = []
    rows = [HEADER, SEPARATOR]
    for it in sorted_items:
        status = expiry_status(it.expires, today)
        if status in ("expired", "soon"):
            flagged.append((status, it))
        cells = [
            it.name,
            _format_quantity(it.quantity),
            it.unit,
            it.category,
            it.location,
            (it.for_recipe or "").replace("|", "\\|"),
            it.purchased or "",
            _expiry_cell(it.expires, status),
            it.source,
            it.notes.replace("|", "\\|"),
        ]
        rows.append("| " + " | ".join(cells) + " |")
    return (
        "---\n"
        "type: inventory\n"
        f"last_updated: {today.isoformat()}\n"
        "---\n\n"
        "# Pantry Inventory\n\n"
        "> ⚠️ This file is **generated** from the KitchenOS database. "
        "Do not edit here — changes will be overwritten. "
        "Update inventory via Claude (MCP tools) or the API.\n\n"
        + _expiry_warning_section(flagged)
        + "\n".join(rows)
        + "\n"
    )


def write_inventory(items: list[InventoryItem]) -> None:
    """Persist to the DB and regenerate the Inventory.md view."""
    from lib import inventory_db

    inventory_db.replace_inventory_rows([it.to_dict() for it in items])
    # The DB (source of truth) has already committed at this point. A failed
    # view write must not propagate: raising would make the API return 500,
    # and a client retry would double-add quantities.
    try:
        path = inventory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_inventory_md(items), encoding="utf-8")
    except OSError as e:
        print(f"⚠️  Inventory view write failed: {e}", file=sys.stderr)


# Perishables this many days past their (estimated) expiry are assumed used or
# tossed and dropped from inventory. Keeps the list self-cleaning so it never
# becomes a chore — KitchenOS auto-adds from receipts and auto-ages out here,
# with no manual "I used this" step. A few days' grace past expiry stays so the
# Use-It-Up nudge still catches just-expired items.
PRUNE_GRACE_DAYS = 3


def prune_expired(today: Optional[date] = None,
                  grace_days: int = PRUNE_GRACE_DAYS) -> int:
    """Drop perishables more than ``grace_days`` past expiry. Returns count removed.

    Shelf-stable items (no ``expires`` — household/other) and anything still
    within the grace window stay. Persists via write_inventory when something
    is removed.
    """
    today = today or date.today()
    kept, removed = [], 0
    for it in read_inventory():
        delta = None
        if it.expires:
            try:
                delta = (date.fromisoformat(it.expires) - today).days
            except ValueError:
                delta = None
        if delta is not None and delta < -grace_days:
            removed += 1
        else:
            kept.append(it)
    if removed:
        write_inventory(kept)
    return removed


# TODO(receipt-ingestion plan, task 9): read→merge→replace can lose updates
# with concurrent writers (Flask threads + ingest LaunchAgent). Switch to
# INSERT ... ON CONFLICT(name, unit, location) DO UPDATE SET
# quantity = quantity + excluded.quantity inside one transaction.
def add_items(new_items: list[InventoryItem]) -> dict:
    """Add items, merging by (name, unit, location). Quantities sum on merge."""
    existing = read_inventory()
    by_key: dict[tuple[str, str, str], InventoryItem] = {
        it.merge_key(): it for it in existing
    }

    added = 0
    merged = 0
    for new in new_items:
        # Auto-fill expiry from the configured shelf-life windows when the
        # caller didn't supply one (category null window -> stays None).
        if new.expires is None:
            new.expires = compute_expires(new.purchased, new.name, new.category)

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
            cur.for_recipe = _merge_recipes(cur.for_recipe, new.for_recipe)
            # Keep the earliest expiry so warnings fire for the oldest stock.
            cur.expires = _earliest_expiry(cur.expires, new.expires)
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
