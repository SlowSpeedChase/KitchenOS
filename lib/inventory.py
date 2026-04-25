"""Kitchen inventory: layout config, Inventory.md round-trip, item routing.

The vault holds a single ``Inventory.md`` with one ``## Zone — Shelf`` section
per location. This module loads ``config/storage_locations.json`` (the source
of truth for kitchen layout) and provides:

- ``load_layout()`` — parse the JSON config into typed objects.
- ``parse_inventory_md(content)`` — read the markdown back into rows.
- ``render_inventory_md(rows, layout)`` — render rows back to markdown.
- ``route_item(item, layout)`` — pick the default group + shelf for a new row.
- ``apply_default_expiry(row, layout, today)`` — fill ``expires`` if blank.
- ``append_rows(rows, layout, vault_path)`` — merge new rows into Inventory.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from lib.ingredient_parser import normalize_unit, parse_amount

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "storage_locations.json"
INVENTORY_FILENAME = "Inventory.md"


# ---------------------------------------------------------------------------
# Item -> group lookup. ~50 common pantry/grocery items.
# Falls back to "dry-goods" if no match. Users can override per row.
# ---------------------------------------------------------------------------

ITEM_GROUP_MAP: dict[str, str] = {
    # proteins-fresh
    "chicken": "proteins-fresh",
    "chicken breast": "proteins-fresh",
    "chicken thigh": "proteins-fresh",
    "ground beef": "proteins-fresh",
    "beef": "proteins-fresh",
    "steak": "proteins-fresh",
    "pork": "proteins-fresh",
    "pork chop": "proteins-fresh",
    "ground pork": "proteins-fresh",
    "salmon": "proteins-fresh",
    "tilapia": "proteins-fresh",
    "cod": "proteins-fresh",
    "shrimp": "proteins-fresh",
    "tofu": "proteins-fresh",
    "bacon": "proteins-fresh",
    "sausage": "proteins-fresh",
    # proteins-frozen
    "frozen chicken": "proteins-frozen",
    "frozen shrimp": "proteins-frozen",
    "frozen salmon": "proteins-frozen",
    "frozen ground beef": "proteins-frozen",
    # dairy
    "milk": "dairy",
    "butter": "dairy",
    "cheese": "dairy",
    "cheddar": "dairy",
    "mozzarella": "dairy",
    "parmesan": "dairy",
    "feta": "dairy",
    "yogurt": "dairy",
    "greek yogurt": "dairy",
    "cream cheese": "dairy",
    "sour cream": "dairy",
    "heavy cream": "dairy",
    "eggs": "dairy",
    "egg": "dairy",
    # produce
    "onion": "produce",
    "garlic": "produce",
    "tomato": "produce",
    "potato": "produce",
    "carrot": "produce",
    "celery": "produce",
    "lettuce": "produce",
    "spinach": "produce",
    "kale": "produce",
    "broccoli": "produce",
    "cauliflower": "produce",
    "bell pepper": "produce",
    "cucumber": "produce",
    "lemon": "produce",
    "lime": "produce",
    "apple": "produce",
    "banana": "produce",
    "avocado": "produce",
    "mushroom": "produce",
    "ginger": "produce",
    "cilantro": "produce",
    "parsley": "produce",
    "basil": "produce",
    # frozen-veg
    "frozen peas": "frozen-veg",
    "frozen corn": "frozen-veg",
    "frozen broccoli": "frozen-veg",
    "frozen spinach": "frozen-veg",
    "frozen mixed vegetables": "frozen-veg",
    # dry-goods
    "rice": "dry-goods",
    "pasta": "dry-goods",
    "penne": "dry-goods",
    "spaghetti": "dry-goods",
    "noodles": "dry-goods",
    "flour": "dry-goods",
    "sugar": "dry-goods",
    "brown sugar": "dry-goods",
    "oats": "dry-goods",
    "quinoa": "dry-goods",
    "bread": "dry-goods",
    "tortilla": "dry-goods",
    # canned
    "black beans": "canned",
    "kidney beans": "canned",
    "chickpeas": "canned",
    "diced tomatoes": "canned",
    "tomato sauce": "canned",
    "tomato paste": "canned",
    "tuna": "canned",
    "coconut milk": "canned",
    # oils-vinegars
    "olive oil": "oils-vinegars",
    "vegetable oil": "oils-vinegars",
    "canola oil": "oils-vinegars",
    "sesame oil": "oils-vinegars",
    "soy sauce": "condiments",
    "vinegar": "oils-vinegars",
    "balsamic vinegar": "oils-vinegars",
    # spices
    "salt": "spices",
    "pepper": "spices",
    "black pepper": "spices",
    "paprika": "spices",
    "cumin": "spices",
    "oregano": "spices",
    "thyme": "spices",
    "chili powder": "spices",
    "cinnamon": "spices",
    # baking
    "baking soda": "baking",
    "baking powder": "baking",
    "vanilla": "baking",
    "vanilla extract": "baking",
    "yeast": "baking",
    "cocoa powder": "baking",
    # condiments
    "ketchup": "condiments",
    "mustard": "condiments",
    "mayo": "condiments",
    "mayonnaise": "condiments",
    "hot sauce": "condiments",
    "salsa": "condiments",
    "jam": "condiments",
    "honey": "condiments",
    "peanut butter": "condiments",
    # beverages
    "coffee": "beverages",
    "tea": "beverages",
    "juice": "beverages",
    "soda": "beverages",
    "beer": "beverages",
    "wine": "beverages",
    # snacks
    "chips": "snacks",
    "pretzels": "snacks",
    "crackers": "snacks",
    "popcorn": "snacks",
    "nuts": "snacks",
    "almonds": "snacks",
    "trail mix": "snacks",
}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    default_expiry_days: int | None


@dataclass(frozen=True)
class Shelf:
    space_id: str
    space_label: str
    shelf_id: str
    shelf_label: str
    groups: tuple[str, ...]

    @property
    def location_id(self) -> str:
        return f"{self.space_id}/{self.shelf_id}"

    @property
    def section_heading(self) -> str:
        # "Spice Cabinet" has a single shelf labeled the same as the space —
        # avoid the redundant "Spice Cabinet — Spice Cabinet" heading.
        if self.shelf_label == self.space_label:
            return self.space_label
        return f"{self.space_label} — {self.shelf_label}"


@dataclass
class Layout:
    groups: dict[str, Group]
    shelves: list[Shelf]  # ordered as they appear in JSON

    def shelf_by_location(self, location_id: str) -> Shelf | None:
        for s in self.shelves:
            if s.location_id == location_id:
                return s
        return None

    def shelf_by_heading(self, heading: str) -> Shelf | None:
        for s in self.shelves:
            if s.section_heading == heading:
                return s
        return None

    def default_shelf_for_group(self, group_id: str) -> Shelf | None:
        for s in self.shelves:
            if group_id in s.groups:
                return s
        return None


def load_layout(config_path: Path | None = None) -> Layout:
    """Load and validate the storage layout config."""
    path = Path(config_path) if config_path else CONFIG_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))

    groups = {
        gid: Group(id=gid, label=g["label"], default_expiry_days=g.get("default_expiry_days"))
        for gid, g in raw.get("groups", {}).items()
    }

    shelves: list[Shelf] = []
    seen: set[str] = set()
    for space_id, space in raw.get("spaces", {}).items():
        space_label = space["label"]
        for sh in space.get("shelves", []):
            shelf = Shelf(
                space_id=space_id,
                space_label=space_label,
                shelf_id=sh["id"],
                shelf_label=sh["label"],
                groups=tuple(sh.get("groups", [])),
            )
            if shelf.location_id in seen:
                raise ValueError(f"Duplicate shelf id within space: {shelf.location_id}")
            seen.add(shelf.location_id)
            for g in shelf.groups:
                if g not in groups:
                    raise ValueError(f"Shelf {shelf.location_id} references unknown group: {g}")
            shelves.append(shelf)

    if not shelves:
        raise ValueError("Layout has no shelves")
    return Layout(groups=groups, shelves=shelves)


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------


@dataclass
class InventoryRow:
    item: str
    qty: str
    unit: str
    group: str
    location: str  # "<space_id>/<shelf_id>"
    added: str  # ISO date "YYYY-MM-DD"
    expires: str = ""  # ISO date or empty
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "item": self.item,
            "qty": self.qty,
            "unit": self.unit,
            "group": self.group,
            "location": self.location,
            "added": self.added,
            "expires": self.expires,
            "notes": self.notes,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Routing & defaults
# ---------------------------------------------------------------------------


def _normalize_item_key(item: str) -> str:
    s = item.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # crude singularization for matching only
    if s.endswith("ies") and len(s) > 3:
        s = s[:-3] + "y"
    elif s.endswith("es") and len(s) > 3 and s[-3] in "shxz":
        s = s[:-2]
    elif s.endswith("s") and not s.endswith("ss") and len(s) > 3:
        s = s[:-1]
    return s


def lookup_group(item: str) -> str | None:
    """Map a raw item name to a group id, or None if no match."""
    if not item:
        return None
    raw = re.sub(r"\s+", " ", item.lower().strip())
    key = _normalize_item_key(item)
    # try exact match on raw lowercase, then singularized
    for candidate in (raw, key):
        if candidate in ITEM_GROUP_MAP:
            return ITEM_GROUP_MAP[candidate]
    # substring match: find the longest map key contained in raw or key
    best = None
    for k in ITEM_GROUP_MAP:
        if (k in raw or k in key) and (best is None or len(k) > len(best)):
            best = k
    return ITEM_GROUP_MAP[best] if best else None


def route_item(item: str, layout: Layout, group_override: str | None = None,
               location_override: str | None = None) -> tuple[str, str, list[str]]:
    """Pick the (group_id, location_id, warnings) for an item."""
    warnings: list[str] = []

    if location_override and layout.shelf_by_location(location_override):
        loc = location_override
        if group_override and group_override in layout.groups:
            return group_override, loc, warnings
        shelf = layout.shelf_by_location(loc)
        group = group_override or (shelf.groups[0] if shelf and shelf.groups else _fallback_group(layout))
        if group_override and group_override not in layout.groups:
            warnings.append(f"unknown group '{group_override}', using '{group}'")
        return group, loc, warnings

    group = group_override if group_override and group_override in layout.groups else lookup_group(item)
    if group_override and group_override not in layout.groups:
        warnings.append(f"unknown group '{group_override}'")
        group = lookup_group(item)

    if not group:
        group = _fallback_group(layout)
        warnings.append(f"no group match for '{item}', defaulting to '{group}'")

    shelf = layout.default_shelf_for_group(group)
    if shelf is None:
        # group exists in config but no shelf claims it — pick the first shelf as backstop.
        shelf = layout.shelves[0]
        warnings.append(f"no shelf claims group '{group}', defaulting to '{shelf.section_heading}'")

    return group, shelf.location_id, warnings


def _fallback_group(layout: Layout) -> str:
    for preferred in ("dry-goods", "pantry", "other"):
        if preferred in layout.groups:
            return preferred
    return next(iter(layout.groups))


def apply_default_expiry(row: InventoryRow, layout: Layout, today: date | None = None) -> None:
    """Fill row.expires from the group's default_expiry_days when blank."""
    if row.expires:
        return
    group = layout.groups.get(row.group)
    if group is None or group.default_expiry_days is None:
        return
    today = today or date.today()
    row.expires = (today + timedelta(days=group.default_expiry_days)).isoformat()


# ---------------------------------------------------------------------------
# Markdown round-trip
# ---------------------------------------------------------------------------


_TABLE_HEADER = "| Item | Qty | Unit | Group | Added | Expires | Notes |"
_TABLE_SEPARATOR = "|---|---|---|---|---|---|---|"


def render_inventory_md(rows: Iterable[InventoryRow], layout: Layout,
                         updated: date | None = None) -> str:
    """Render rows back to markdown, grouped by location in layout order."""
    updated = updated or date.today()
    rows_by_location: dict[str, list[InventoryRow]] = {}
    for r in rows:
        rows_by_location.setdefault(r.location, []).append(r)

    out: list[str] = ["# Kitchen Inventory", f"Last updated: {updated.isoformat()}", ""]

    for shelf in layout.shelves:
        loc_rows = rows_by_location.get(shelf.location_id, [])
        if not loc_rows:
            continue
        out.append(f"## {shelf.section_heading}")
        out.append(_TABLE_HEADER)
        out.append(_TABLE_SEPARATOR)
        for r in loc_rows:
            out.append(_render_row(r))
        out.append("")

    # Drop trailing blank line for stability
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _render_row(r: InventoryRow) -> str:
    cells = [r.item, r.qty, r.unit, r.group, r.added, r.expires or "", r.notes or ""]
    return "| " + " | ".join(_escape_cell(c) for c in cells) + " |"


def _escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def parse_inventory_md(content: str, layout: Layout) -> list[InventoryRow]:
    """Parse Inventory.md back into rows. Unknown headings are skipped with a warning."""
    rows: list[InventoryRow] = []
    section_pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(section_pattern.finditer(content))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        shelf = layout.shelf_by_heading(heading)
        if shelf is None:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section = content[start:end]
        rows.extend(_parse_section(section, shelf))
    return rows


def _parse_section(section: str, shelf: Shelf) -> list[InventoryRow]:
    rows: list[InventoryRow] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or cells[0].lower() == "item":
            continue
        # pad to 7 cells
        while len(cells) < 7:
            cells.append("")
        item, qty, unit, group, added, expires, notes = cells[:7]
        if not item:
            continue
        rows.append(InventoryRow(
            item=item,
            qty=qty or "1",
            unit=unit or "each",
            group=group or "",
            location=shelf.location_id,
            added=added or "",
            expires=expires or "",
            notes=notes or "",
        ))
    return rows


# ---------------------------------------------------------------------------
# Append (commit) — merge new rows into Inventory.md
# ---------------------------------------------------------------------------


def append_rows(new_rows: list[InventoryRow], layout: Layout,
                vault_path: Path, today: date | None = None) -> Path:
    """Merge new rows into Inventory.md, preserving existing rows.

    Combine rule: same (item, unit, location) → sum qty (numeric only); else
    append as a new row. Refresh ``Last updated`` line.
    """
    today = today or date.today()
    inv_path = Path(vault_path) / INVENTORY_FILENAME
    existing: list[InventoryRow] = []
    if inv_path.exists():
        existing = parse_inventory_md(inv_path.read_text(encoding="utf-8"), layout)

    by_key: dict[tuple[str, str, str], InventoryRow] = {}
    for r in existing:
        by_key[(r.item.lower(), r.unit.lower(), r.location)] = r

    for r in new_rows:
        key = (r.item.lower(), r.unit.lower(), r.location)
        if key in by_key:
            existing_row = by_key[key]
            combined = _combine_qty(existing_row.qty, r.qty)
            if combined is not None:
                existing_row.qty = combined
            else:
                # different qty formats — append as separate row
                existing.append(r)
            # use later expiry of the two when both present
            if r.expires and (not existing_row.expires or r.expires > existing_row.expires):
                existing_row.expires = r.expires
        else:
            existing.append(r)
            by_key[key] = r

    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inv_path.write_text(render_inventory_md(existing, layout, updated=today), encoding="utf-8")
    return inv_path


def _combine_qty(a: str, b: str) -> str | None:
    """Sum two qty strings if both are simple numbers; else None."""
    try:
        total = float(a) + float(b)
        if total == int(total):
            return str(int(total))
        return f"{total:.2f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_row_units(qty: str, unit: str) -> tuple[str, str]:
    """Run a row's qty/unit through the existing parsers."""
    return parse_amount(qty), normalize_unit(unit) or unit
