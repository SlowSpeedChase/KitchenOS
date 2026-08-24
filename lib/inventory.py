"""Pantry inventory storage.

The SQLite database (``lib/inventory_db.py``) is the source of truth. The
``Inventory.md`` file at the vault root is a regenerated read-only view —
rewritten on every ``write_inventory()`` so the stock stays browsable in
Obsidian, but edits there are overwritten. Items with the same
``(name, unit, location)`` are merged on add — quantities sum.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from lib import paths
from lib.expiry import compute_expires, expiry_status

CATEGORIES = (
    "produce", "dairy", "meat", "seafood", "pantry",
    "frozen", "bakery", "beverages", "household", "other",
)
LOCATIONS = ("fridge", "freezer", "pantry", "counter", "other")
SOURCES = ("receipt", "manual", "claude", "csa", "staple")

# How a row's `location` was decided, ordered strongest first.
LOCATION_SOURCES = ("manual", "item", "category", "default")

# Suffix marking a location nothing actually resolved. Rendered by
# `_location_cell` into Inventory.md and mirrored on `/review`. Anything that
# *parses* a location cell must strip it and must not read a marked cell as a
# confirmed choice — `lib/receipt_paster.py` is the one such consumer.
UNSURE_MARKER = "?"

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
    # Written by consume-on-cook when a row is used but cannot safely be
    # decremented (a container). Must round-trip through write_inventory(),
    # which is DELETE-all + re-INSERT.
    last_used: Optional[str] = None
    use_count: int = 0
    # How `location` was decided. Provenance, deliberately not part of
    # merge_key() — adding it there would fragment rows.
    location_source: str = "default"

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


def normalize_location_source(src: Optional[str]) -> str:
    """Normalize provenance, defaulting to ``"default"``.

    A NULL from a pre-migration row, or anything not in the vocabulary, reads
    as ``"default"`` — the failure direction is always toward being asked
    again, never toward posing as confirmed.
    """
    if not src:
        return "default"
    s = src.lower().strip()
    return s if s in LOCATION_SOURCES else "default"


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
            last_used=r["last_used"] or None,
            use_count=int(r["use_count"] or 0),
            location_source=normalize_location_source(r["location_source"]),
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


def _location_cell(location: str, source: Optional[str]) -> str:
    """Location column text, marked '?' when nothing actually resolved it.

    Same marker the `/review` page shows, so the two views agree about what is
    known rather than one quietly presenting a guess as fact.
    """
    if normalize_location_source(source) == "default":
        return f"{location}{UNSURE_MARKER}"
    return location


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
            _location_cell(it.location, it.location_source),
            (it.for_recipe or "").replace("|", "\\|"),
            it.purchased or "",
            _expiry_cell(it.expires, status),
            it.source,
            it.notes.replace("|", "\\|"),
        ]
        rows.append("| " + " | ".join(cells) + " |")
    base = os.environ.get(
        "KITCHENOS_API_BASE", "http://chases-mac-mini.taila69703.ts.net:5001"
    )
    ssh_target = os.environ.get(
        "KITCHENOS_SSH_TARGET", "chaseeasterling@chases-mac-mini.taila69703.ts.net"
    )
    return (
        "---\n"
        "type: inventory\n"
        f"last_updated: {today.isoformat()}\n"
        "---\n\n"
        "# Pantry Inventory\n\n"
        "> ⚠️ This file is **generated** from the KitchenOS database. "
        "Do not edit here — changes will be overwritten. "
        "Update inventory via Claude (MCP tools) or the API.\n\n"
        f"**▶ [Open Review]({base}/review)** — remove or add time, tap-to-act\n\n"
        f"**🤖 [Launch Claude](ssh://{ssh_target})** — start a Claude session seeded "
        f"with your [[Claude Notes]]\n\n"
        + _expiry_warning_section(flagged)
        + "\n".join(rows)
        + "\n"
    )


def write_inventory(items: list[InventoryItem]) -> None:
    """Persist to the DB and regenerate the Inventory.md view."""
    from lib import inventory_db

    inventory_db.replace_inventory_rows([it.to_dict() for it in items])
    refresh_inventory_views()


def refresh_inventory_views() -> None:
    """Regenerate derived inventory views after a successful database commit."""
    # The DB (source of truth) has already committed at this point. A failed
    # view write must not propagate: raising would make the API return 500,
    # and a client retry would double-add quantities.
    #
    # Render from the committed rows, never from `items`. Cook Now (below) re-reads
    # the DB, so rendering this view off the caller's list gave the two notes two
    # different sources and let them disagree — a stale or empty caller list once
    # shipped an empty Inventory.md next to a populated Cook Now.md.
    try:
        path = inventory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_inventory_md(read_inventory()), encoding="utf-8")
    except OSError as e:
        print(f"⚠️  Inventory view write failed: {e}", file=sys.stderr)

    # Cook Now.md ranks recipes by on-hand coverage, so it must track every
    # inventory change too. Guarded broadly (it reads the DB + scans recipes,
    # so it can fail in more ways than a plain file write) so a view-refresh
    # failure never propagates past the already-committed DB mutation — that
    # would 500 the API and a client retry would double-add quantities. Lazy
    # import keeps cook_now off the hot path of a plain `import inventory`.
    try:
        from lib import cook_now
        cook_now.write_note()
    except Exception as e:
        print(f"⚠️  Cook Now view write failed: {e}", file=sys.stderr)


# Perishables this many days past their (estimated) expiry are assumed used or
# tossed and dropped from inventory. Keeps the list self-cleaning so it never
# becomes a chore — KitchenOS auto-adds from receipts and auto-ages out here,
# with no manual "I used this" step. A few days' grace past expiry stays so the
# Use-It-Up nudge still catches just-expired items.
PRUNE_GRACE_DAYS = 3

# Staples you always keep but nobody "stocks" as a countable pantry item.
_UNSTOCKABLE_STAPLES = frozenset({"water", "ice"})


def seed_pantry_staples(staples: Optional[set] = None) -> dict:
    """Add any pantry staple that isn't already stocked as a perpetual row.

    Staples were previously an invisible assumption: ``cook_now`` credited them
    as on-hand without them existing in inventory, so a recipe could read 100%
    while the fridge said otherwise. Materializing them makes the assumption
    visible and auditable in ``Inventory.md``.

    Rows are written with no ``expires``, so ``prune_expired`` never touches
    them and ``at_risk_items`` never nags — they persist until explicitly
    removed. Idempotent: a staple already covered by something stocked (a
    seeded "butter", or a receipt's "Salted Butter") is skipped rather than
    duplicated. Returns ``{"added": [...], "skipped": [...]}``.
    """
    from lib.use_it_up import _covers, _is_staple, _phrase

    if staples is None:
        from lib.meal_suggester import load_pantry_staples
        staples = load_pantry_staples()

    candidates = [
        (name, _phrase(name)) for name in sorted(staples)
        if name.lower() not in _UNSTOCKABLE_STAPLES
    ]
    # Generic before specific ("pepper" before "black pepper") so the broader
    # name is the one seeded and the narrower duplicate collapses into it.
    candidates.sort(key=lambda c: len(c[1].tokens))

    existing = read_inventory()
    stocked = [_phrase(it.name) for it in existing]
    added, skipped = [], []

    for name, phrase in candidates:
        if not phrase.tokens or _is_staple(phrase, stocked):
            skipped.append(name)
            continue
        if any(_covers(phrase, chosen) for chosen in
               (_phrase(a) for a in added)):
            skipped.append(name)
            continue
        added.append(name)
        stocked.append(phrase)

    if added:
        write_inventory(existing + [
            InventoryItem(name=name, quantity=1, unit="ct", category="pantry",
                          location="pantry", source="staple",
                          # Hand-authored in pantry_staples.json, so these are
                          # curated placements — not guesses to review.
                          location_source="item",
                          notes="always on hand")
            for name in added
        ])
    return {"added": added, "skipped": skipped}


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


def add_items(new_items: list[InventoryItem]) -> dict:
    """Add items, merging by (name, unit, location). Quantities sum on merge."""
    from lib import inventory_db

    for item in new_items:
        # Auto-fill expiry from the configured shelf-life windows when the
        # caller didn't supply one (category null window -> stays None).
        if item.expires is None:
            item.expires = compute_expires(
                item.purchased, item.name, item.category
            )
        item.location_source = normalize_location_source(item.location_source)

    result = inventory_db.merge_inventory_rows(
        [item.to_dict() for item in new_items]
    )
    refresh_inventory_views()
    return result


def remove_item(name: str, location: Optional[str] = None) -> bool:
    """Remove every ``(name, location)`` match. Returns True if anything went.

    Note the legacy addressing: this deletes *all* name+location matches
    regardless of unit. ``bulk_apply("remove", ...)`` addresses by the real
    ``(name, unit, location)`` key instead.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)
    if not matches:
        return False
    _apply_remove(items, matches)
    write_inventory(items)
    return True


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


def extend_expiry(
    name: str,
    days: int,
    location: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[InventoryItem]:
    """Add ``days`` to the first ``(name, location)`` match's expiry.

    Cumulative: counted from the row's own expiry, or from today when that has
    passed or is unset — see ``_apply_extend``. Works on no-expiry items.
    Returns the updated item, or None if nothing matched.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    updated = _apply_extend(items, matches, days, today=today)
    write_inventory(items)
    return updated[0]


def _match(it: InventoryItem, target: str, target_loc: Optional[str]) -> bool:
    """True when an item matches by lowercased name (+ optional location)."""
    return it.name.lower().strip() == target and (
        target_loc is None or it.location == target_loc
    )


def _drop(items: list[InventoryItem], victim: InventoryItem) -> None:
    """Remove ``victim`` from ``items`` by identity.

    ``InventoryItem`` is a plain dataclass, so ``list.remove`` would match by
    value and could drop a different but equal row.
    """
    for i, it in enumerate(items):
        if it is victim:
            del items[i]
            return


def _match_by_name(
    items: list[InventoryItem], name: str, location: Optional[str]
) -> list[InventoryItem]:
    """Every row matching by lowercased name (+ optional location), in order.

    This is the legacy ``(name, location)`` addressing the single-item functions
    use. The bulk path addresses by the real ``(name, unit, location)`` key
    instead — see ``bulk_apply``.
    """
    target = name.lower().strip()
    target_loc = location.lower().strip() if location else None
    return [it for it in items if _match(it, target, target_loc)]


# --- Pure mutators -----------------------------------------------------------
# Each takes the full item list plus the already-matched rows, mutates the list
# in place, and does no I/O. The read/write cycle belongs to the caller, so one
# selection of N items costs one write instead of N.
#
# All six share the (items, matches, *params) shape even though the three
# field-setters don't need `items` — that uniformity is what lets bulk_apply
# dispatch to any of them, and _apply_remove/_apply_move/_apply_freeze do need
# the full list to drop and merge rows.


def _apply_remove(
    items: list[InventoryItem], matches: list[InventoryItem]
) -> list[InventoryItem]:
    """Drop every matched row. Returns the removed rows (for undo)."""
    for it in matches:
        _drop(items, it)
    return list(matches)


def _apply_extend(
    items: list[InventoryItem],
    matches: list[InventoryItem],
    days: int,
    today: Optional[date] = None,
) -> list[InventoryItem]:
    """Add ``days`` to every matched row's expiry.

    Counted from the row's **own** expiry when that is still in the future, so
    the ``+3d`` / ``+7d`` buttons mean what they say and repeated taps
    accumulate. Counted from today when the row has no expiry or has already
    lapsed — adding to a stale date would leave the item expired, which is the
    whole reason someone is extending it.

    Each row therefore computes its own date. A single shared date (the
    previous behaviour) silently flattened a mixed selection onto one expiry.
    """
    base = today or date.today()
    for it in matches:
        start = base
        if it.expires:
            try:
                current = date.fromisoformat(it.expires)
            except ValueError:
                current = None      # unparseable: treat as having no expiry
            if current and current > base:
                start = current
        it.expires = (start + timedelta(days=days)).isoformat()
    return list(matches)


def _apply_set_expiry(
    items: list[InventoryItem],
    matches: list[InventoryItem],
    expires: Optional[str],
) -> list[InventoryItem]:
    """Set every matched row's expiry to an absolute date, or clear it."""
    for it in matches:
        it.expires = expires or None
    return list(matches)


def _apply_set_category(
    items: list[InventoryItem], matches: list[InventoryItem], category: str
) -> list[InventoryItem]:
    """Set every matched row's category (normalized against CATEGORIES)."""
    cat = normalize_category(category)
    for it in matches:
        it.category = cat
    return list(matches)


def _teach_location(name: str, to_location: str) -> None:
    """Remember a hand-correction so future purchases of this item file right.

    Never lets a config-write failure sink the move: the row is already
    committed and the lesson is a side effect. ``save_item_override`` writes
    tmp+replace, so a failure leaves the previous table intact.
    """
    from lib import storage_locations

    try:
        storage_locations.save_item_override(name, to_location)
    except OSError as e:
        print(f"⚠️  Couldn't record storage override for {name}: {e}",
              file=sys.stderr)


def _apply_move(
    items: list[InventoryItem], matches: list[InventoryItem], to_location: str
) -> list[InventoryItem]:
    """Move every matched row to ``to_location``, merging on collision.

    Because ``(name, unit, location)`` is the uniqueness key, a move can collide
    with an existing row at the destination — quantities sum into the
    destination row and the source row is dropped. Matches are processed
    sequentially against the shared list, so two *selected* rows moving to the
    same destination also merge into one another. The returned list is
    deduplicated, so a merged pair reports as the single surviving row.
    """
    dest = normalize_location(to_location)
    results: list[InventoryItem] = []
    for source in matches:
        if source.location == dest:
            results.append(source)
            continue
        existing = next(
            (
                it
                for it in items
                if it is not source
                and it.name.lower().strip() == source.name.lower().strip()
                and it.unit.lower().strip() == source.unit.lower().strip()
                and it.location == dest
            ),
            None,
        )
        if existing is not None:
            existing.quantity += source.quantity
            _drop(items, source)
            results.append(existing)
        else:
            source.location = dest
            results.append(source)

    seen: set[int] = set()
    unique: list[InventoryItem] = []
    for r in results:
        if id(r) not in seen:
            seen.add(id(r))
            unique.append(r)
    # A move is the user asserting where this belongs — including the case where
    # it was already there. Stamped here rather than in the callers so freeze
    # (which moves to the freezer) is confirmed too, without also teaching.
    for r in unique:
        r.location_source = "manual"
    return unique


def _apply_freeze(
    items: list[InventoryItem], matches: list[InventoryItem]
) -> list[InventoryItem]:
    """Freeze every matched row: move to the freezer, category=frozen, no expiry.

    Freezing stops the expiry clock, so the date is cleared rather than extended.
    """
    moved = _apply_move(items, matches, "freezer")
    for it in moved:
        it.category = "frozen"
        it.expires = None
    return moved


BULK_ACTIONS = (
    "remove", "extend", "set-expiry", "set-category", "move", "freeze",
)


def _resolve_ref(ref: dict) -> tuple[str, str, str]:
    """A ``{name, unit, location}`` ref as a ``merge_key()``-comparable tuple.

    All three fields are required. Falling back to ``(name, location)`` matching
    when ``unit`` is absent would silently widen the match — that is exactly the
    bug this path exists to fix — so a partial ref is an error, not a guess.
    """
    if not isinstance(ref, dict):
        raise ValueError(f"each ref must be an object, got {type(ref).__name__}")
    missing = [f for f in ("name", "unit", "location") if not ref.get(f)]
    if missing:
        raise ValueError(f"ref is missing required field(s): {', '.join(missing)}")
    return (
        str(ref["name"]).lower().strip(),
        str(ref["unit"]).lower().strip(),
        str(ref["location"]).lower().strip(),
    )


def _require(params: dict, key: str):
    """Fetch a required action parameter, or raise ValueError naming it."""
    if key not in params:
        raise ValueError(f"action requires '{key}'")
    return params[key]


def bulk_apply(action: str, refs: list[dict], **params) -> dict:
    """Apply one action to many items in a single read-modify-write cycle.

    ``refs`` address rows by the real uniqueness key ``(name, unit, location)``,
    unlike the single-item functions which match on ``(name, location)``.

    Refs that match nothing land in ``not_found`` rather than aborting the call
    — the client's list can be stale, and one dead ref must not discard a dozen
    good edits. Nothing is written when no ref matches.

    Returns ``{applied, items, removed, not_found}``. ``items`` carries the
    resulting rows for every action except ``remove``; ``removed`` carries the
    full pre-delete rows for ``remove``. Both keys are always present.
    """
    if action not in BULK_ACTIONS:
        raise ValueError(
            f"unknown action '{action}' (expected one of {', '.join(BULK_ACTIONS)})"
        )

    keys = [_resolve_ref(r) for r in refs]

    # Validate action parameters before touching the DB, so a request that
    # happens to match nothing still fails loudly on a malformed body rather
    # than quietly reporting "applied: 0".
    days = expires = category = to_location = None
    if action == "extend":
        raw = _require(params, "days")
        try:
            days = int(raw)
        except (TypeError, ValueError):
            raise ValueError("'days' must be an integer") from None
    elif action == "set-expiry":
        expires = _require(params, "expires")   # None is valid — it clears
    elif action == "set-category":
        category = _require(params, "category")
    elif action == "move":
        to_location = _require(params, "to_location")

    items = read_inventory()
    by_key: dict[tuple[str, str, str], InventoryItem] = {
        it.merge_key(): it for it in items
    }

    matches: list[InventoryItem] = []
    not_found: list[dict] = []
    for ref, key in zip(refs, keys):
        found = by_key.get(key)
        if found is None:
            not_found.append(ref)
        else:
            matches.append(found)

    updated: list[InventoryItem] = []
    removed: list[InventoryItem] = []

    if matches:
        if action == "remove":
            removed = _apply_remove(items, matches)
        elif action == "extend":
            updated = _apply_extend(items, matches, days, today=params.get("today"))
        elif action == "set-expiry":
            updated = _apply_set_expiry(items, matches, expires)
        elif action == "set-category":
            updated = _apply_set_category(items, matches, category)
        elif action == "move":
            # Captured before the move: a colliding row is dropped from `items`,
            # so reading names off the result would miss the merged-away source.
            moved_names = [m.name for m in matches]
            updated = _apply_move(items, matches, to_location)
        elif action == "freeze":
            updated = _apply_freeze(items, matches)

        write_inventory(items)

        if action == "move":
            for moved_name in moved_names:
                _teach_location(moved_name, to_location)

    return {
        "applied": len(matches),
        "items": updated,
        "removed": removed,
        "not_found": not_found,
    }


def set_expiry(
    name: str, expires: Optional[str], location: Optional[str] = None
) -> Optional[InventoryItem]:
    """Set the first match's expiry to an absolute ISO date, or clear it (None).

    Returns the updated item, or None if no row matched.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    updated = _apply_set_expiry(items, matches, expires)
    write_inventory(items)
    return updated[0]


def set_category(
    name: str, category: str, location: Optional[str] = None
) -> Optional[InventoryItem]:
    """Set the first match's category (normalized against CATEGORIES).

    Returns the updated item, or None if no row matched.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    updated = _apply_set_category(items, matches, category)
    write_inventory(items)
    return updated[0]


def move_item(
    name: str, to_location: str, location: Optional[str] = None
) -> Optional[InventoryItem]:
    """Move the first match to ``to_location``, merging on collision.

    Because ``(name, unit, location)`` is the uniqueness key, moving can collide
    with an existing row at the destination — quantities sum into the
    destination row and the source row is dropped. Returns the resulting item at
    the destination, or None if no row matched.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    # Already there. Normally a no-op, so we return without a write rather than
    # churning the DB and regenerating two vault notes for nothing — but if the
    # row's placement was only ever a guess, the tap is the user confirming it,
    # which is worth the write and worth teaching.
    if matches[0].location == normalize_location(to_location):
        if matches[0].location_source == "manual":
            return matches[0]
        matches[0].location_source = "manual"
        write_inventory(items)
        _teach_location(name, to_location)
        return matches[0]
    result = _apply_move(items, matches, to_location)
    write_inventory(items)
    # After the write: a config failure must not precede a failed DB write.
    _teach_location(name, to_location)
    return result[0]


def freeze_item(
    name: str, location: Optional[str] = None
) -> Optional[InventoryItem]:
    """Mark the first match as frozen: move to the freezer, category=frozen, and
    clear its expiry (freezing stops the expiry clock).

    Handles the destination-merge case. One write cycle — the previous
    implementation chained move + set_category + set_expiry for three writes and
    six view regenerations, with no atomicity between them.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    result = _apply_freeze(items, matches)
    write_inventory(items)
    return result[0]
