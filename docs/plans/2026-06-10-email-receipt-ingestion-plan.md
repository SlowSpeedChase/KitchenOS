# Email Receipt Ingestion & Price History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ingest HEB receipt emails via IMAP into a unified SQLite inventory + price ledger, with `Inventory.md` as a generated view and an Obsidian price/spending dashboard.

**Architecture:** A new `data/kitchenos.db` (stdlib sqlite3) holds three tables: `trips`, `purchases` (append-only price ledger), and `inventory` (current stock). `lib/inventory.py` keeps its public API but becomes DB-backed, regenerating `Inventory.md` as a read-only view on every write; `lib/pantry.py` becomes a thin adapter over the same table so shopping-list code is untouched. A new `ingest_receipts.py` (hourly LaunchAgent) pulls HEB emails over IMAP, parses them with Ollama, validates totals, and writes trips/purchases/inventory. `generate_price_dashboard.py` renders `Price Tracker.md`.

**Tech Stack:** Python 3.11, stdlib `sqlite3` + `imaplib` + `email`, BeautifulSoup (already a dep), Ollama `mistral:7b` (existing pattern in `recipe_sources.py`), Flask API, FastMCP, pytest.

**Design doc:** `docs/plans/2026-06-10-email-receipt-ingestion-design.md`

**Test command:** `.venv/bin/python -m pytest tests/ -v` (run from `/Users/chaseeasterling/KitchenOS`)

**Conventions that apply (from `lib/CLAUDE.md`):**
- Vault paths only via `lib/paths.py` helpers.
- Atomic JSON writes: `tmp + replace` pattern (see `lib/pantry.py:save_pantry`).
- Money is integer cents everywhere in the DB.

---

### Task 1: DB module — schema, connection, trips

**Files:**
- Create: `lib/inventory_db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_inventory_db.py`

**Step 1: Write shared fixtures**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures."""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_vault(monkeypatch):
    """Point the vault at a temp dir for the duration of a test."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("KITCHENOS_VAULT", tmp)
        yield Path(tmp)


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the KitchenOS DB at a temp file for the duration of a test."""
    db = tmp_path / "test_kitchenos.db"
    monkeypatch.setenv("KITCHENOS_DB", str(db))
    yield db
```

**Step 2: Write the failing tests**

Create `tests/test_inventory_db.py`:

```python
"""Tests for lib/inventory_db.py — schema, trips, purchases, inventory rows."""
import sqlite3

import pytest

from lib import inventory_db as idb


def test_connect_creates_schema(tmp_db):
    conn = idb.connect()
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert {"trips", "purchases", "inventory"} <= tables


def test_record_trip_and_dedup(tmp_db):
    trip = {
        "date": "2026-06-09",
        "store": "HEB",
        "source": "email_receipt",
        "source_id": "<msg-123@heb.com>",
        "total_cents": 4523,
    }
    purchases = [
        {"raw_name": "HCF BNLS SKNLS BRST", "canonical_name": "chicken breast",
         "quantity": 2.1, "unit": "lb", "unit_price_cents": 549,
         "total_cents": 1153, "category": "meat"},
        {"raw_name": "TX SALES TAX", "canonical_name": "sales tax",
         "quantity": 1, "unit": "ct", "unit_price_cents": 370,
         "total_cents": 370, "category": "fee"},
    ]
    trip_id = idb.record_trip(trip, purchases)
    assert isinstance(trip_id, int)
    assert idb.trip_exists("<msg-123@heb.com>") is True

    # Same source_id again → no-op, returns None, no duplicate rows
    assert idb.record_trip(trip, purchases) is None
    conn = idb.connect()
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 2
    conn.close()


def test_trip_exists_false_for_unknown(tmp_db):
    assert idb.trip_exists("<nope>") is False


def test_needs_review_trip_keeps_raw_text(tmp_db):
    trip = {
        "date": "2026-06-09", "store": "HEB", "source": "email_curbside",
        "source_id": "<msg-456@heb.com>", "total_cents": None,
        "needs_review": True, "raw_text": "garbled receipt text",
    }
    trip_id = idb.record_trip(trip, [])
    conn = idb.connect()
    row = conn.execute(
        "SELECT needs_review, raw_text FROM trips WHERE id=?", (trip_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] == "garbled receipt text"


def test_inventory_rows_roundtrip(tmp_db):
    rows = [
        {"name": "Chicken breast", "quantity": 2.0, "unit": "lb",
         "category": "meat", "location": "fridge", "purchased": "2026-06-09",
         "source": "receipt", "notes": ""},
    ]
    idb.replace_inventory_rows(rows)
    out = idb.fetch_inventory_rows()
    assert len(out) == 1
    assert out[0]["name"] == "Chicken breast"
    assert out[0]["quantity"] == 2.0
    assert out[0]["location"] == "fridge"
```

**Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inventory_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.inventory_db'`

**Step 4: Write the implementation**

Create `lib/inventory_db.py`:

```python
"""SQLite store for unified inventory + price history.

Single DB at ``data/kitchenos.db`` (override with ``KITCHENOS_DB`` env var —
tests use this). Three tables:

- ``trips``      one row per receipt (email, photo, manual). ``source_id`` is
                 UNIQUE (Gmail Message-ID or photo hash) so re-ingesting the
                 same receipt is always a no-op.
- ``purchases``  append-only price ledger, one row per receipt line item.
                 Never deleted. ``category='fee'`` rows (tax, totes, tips)
                 count toward spending but never touch inventory.
- ``inventory``  current on-hand stock, merged by (name, unit, location)
                 case-insensitively.

All money columns are integer cents.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT 'HEB',
    source TEXT NOT NULL,
    source_id TEXT UNIQUE,
    total_cents INTEGER,
    needs_review INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id),
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    unit_price_cents INTEGER,
    total_cents INTEGER,
    category TEXT NOT NULL DEFAULT 'other'
);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT 'ct' COLLATE NOCASE,
    category TEXT NOT NULL DEFAULT 'other',
    location TEXT NOT NULL DEFAULT 'pantry' COLLATE NOCASE,
    purchased TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(name, unit, location)
);
"""

_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes",
)


def db_path() -> Path:
    raw = os.environ.get("KITCHENOS_DB")
    if raw:
        return Path(os.path.expanduser(raw))
    return Path(__file__).resolve().parent.parent / "data" / "kitchenos.db"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the DB, creating file + schema if needed."""
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def trip_exists(source_id: str) -> bool:
    if not source_id:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM trips WHERE source_id = ?", (source_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_trip(trip: dict, purchases: list[dict]) -> Optional[int]:
    """Insert a trip and its purchase lines atomically.

    Returns the new trip id, or None if ``source_id`` already exists
    (duplicate receipt — nothing is written).
    """
    conn = connect()
    try:
        with conn:
            try:
                cur = conn.execute(
                    "INSERT INTO trips"
                    " (date, store, source, source_id, total_cents,"
                    "  needs_review, raw_text)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        trip["date"],
                        trip.get("store", "HEB"),
                        trip["source"],
                        trip.get("source_id"),
                        trip.get("total_cents"),
                        1 if trip.get("needs_review") else 0,
                        trip.get("raw_text"),
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            trip_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO purchases"
                " (trip_id, raw_name, canonical_name, quantity, unit,"
                "  unit_price_cents, total_cents, category)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        trip_id,
                        p["raw_name"],
                        p["canonical_name"],
                        p.get("quantity"),
                        p.get("unit"),
                        p.get("unit_price_cents"),
                        p.get("total_cents"),
                        p.get("category", "other"),
                    )
                    for p in purchases
                ],
            )
        return trip_id
    finally:
        conn.close()


def fetch_inventory_rows() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_INVENTORY_COLS)} FROM inventory"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def replace_inventory_rows(rows: list[dict]) -> None:
    """Overwrite the inventory table with ``rows`` atomically."""
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM inventory")
            conn.executemany(
                f"INSERT INTO inventory ({', '.join(_INVENTORY_COLS)})"
                f" VALUES ({', '.join('?' * len(_INVENTORY_COLS))})",
                [
                    tuple(r.get(c) if c != "notes" else (r.get(c) or "")
                          for c in _INVENTORY_COLS)
                    for r in rows
                ],
            )
    finally:
        conn.close()
```

**Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inventory_db.py -v`
Expected: 5 PASS

**Step 6: Commit**

```bash
git add lib/inventory_db.py tests/conftest.py tests/test_inventory_db.py
git commit -m "feat(db): SQLite store for trips, purchases, inventory"
```

---

### Task 2: Make `lib/inventory.py` DB-backed; `Inventory.md` becomes a generated view

The public API (`read_inventory`, `write_inventory`, `add_items`, `remove_item`, `update_quantity`, `InventoryItem`) is unchanged. `read_inventory()` reads the DB; `write_inventory()` writes the DB **and** regenerates `Inventory.md`. The old markdown-parsing loop is kept as `parse_inventory_markdown()` for the migration script.

**Files:**
- Modify: `lib/inventory.py`
- Modify: `tests/test_inventory.py` (existing tests need the `tmp_db` fixture)

**Step 1: Update existing tests to use both fixtures**

In `tests/test_inventory.py`: delete its local `tmp_vault` fixture (now in `conftest.py`) and add `tmp_db` to every test's parameters alongside `tmp_vault` (e.g. `def test_add_items(tmp_vault, tmp_db):`). Add one new test:

```python
def test_inventory_md_is_generated_view(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, inventory_path
    add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                             category="dairy", location="fridge")])
    content = inventory_path().read_text(encoding="utf-8")
    assert "| Milk | 1 | gal | dairy | fridge |" in content
    assert "generated" in content.lower()  # view banner present


def test_parse_inventory_markdown_still_works(tmp_vault, tmp_db):
    from lib.inventory import parse_inventory_markdown
    md = (
        "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |\n"
        "|------|----------|------|----------|----------|-----------|--------|-------|\n"
        "| Eggs | 12 | ct | dairy | fridge | 2026-06-01 | receipt |  |\n"
    )
    items = parse_inventory_markdown(md)
    assert items[0].name == "Eggs"
    assert items[0].quantity == 12.0
```

**Step 2: Run to verify the new tests fail**

Run: `.venv/bin/python -m pytest tests/test_inventory.py -v`
Expected: new tests FAIL (`parse_inventory_markdown` not defined; view banner missing); old tests may fail too once fixtures change — that's fine until Step 3.

**Step 3: Refactor `lib/inventory.py`**

Keep everything above `read_inventory()` as-is (dataclass, normalizers, `_format_quantity`, `_parse_quantity`, `HEADER`, `SEPARATOR`, `inventory_path`). Replace `read_inventory()` / `write_inventory()` with:

```python
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
        )
        for r in inventory_db.fetch_inventory_rows()
    ]


def render_inventory_md(items: list[InventoryItem]) -> str:
    """Render the read-only Obsidian view of current stock."""
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
    return (
        "---\n"
        "type: inventory\n"
        f"last_updated: {date.today().isoformat()}\n"
        "---\n\n"
        "# Pantry Inventory\n\n"
        "> ⚠️ This file is **generated** from the KitchenOS database. "
        "Do not edit here — changes will be overwritten. "
        "Update inventory via Claude (MCP tools) or the API.\n\n"
        + "\n".join(rows)
        + "\n"
    )


def write_inventory(items: list[InventoryItem]) -> None:
    """Persist to the DB and regenerate the Inventory.md view."""
    from lib import inventory_db

    inventory_db.replace_inventory_rows([it.to_dict() for it in items])
    path = inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_inventory_md(items), encoding="utf-8")
```

`add_items`, `remove_item`, `update_quantity` need **no changes** — they already work through `read_inventory()`/`write_inventory()`.

**Step 4: Run the full inventory + API test files**

Run: `.venv/bin/python -m pytest tests/test_inventory.py tests/test_api_server.py -v`
Expected: PASS. If any `test_api_server.py` inventory tests fail for missing `tmp_db`, add the fixture to those tests the same way.

**Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py tests/test_api_server.py
git commit -m "refactor(inventory): back Inventory.md with SQLite; md becomes generated view"
```

---

### Task 3: One-time migration script

**Files:**
- Create: `migrate_inventory_db.py`
- Test: `tests/test_migrate_inventory_db.py`

**Step 1: Write the failing test**

```python
"""Tests for migrate_inventory_db.py."""
from lib.inventory import inventory_path, read_inventory
from migrate_inventory_db import migrate

LEGACY_MD = """---
type: inventory
last_updated: 2026-06-01
---

# Pantry Inventory

| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |
|------|----------|------|----------|----------|-----------|--------|-------|
| Eggs | 12 | ct | dairy | fridge | 2026-06-01 | receipt |  |
| Rice | 2 | lb | pantry | pantry |  | manual |  |
"""


def test_migrate_imports_legacy_rows(tmp_vault, tmp_db):
    inventory_path().write_text(LEGACY_MD, encoding="utf-8")
    result = migrate()
    assert result["imported"] == 2
    names = {it.name for it in read_inventory()}
    assert names == {"Eggs", "Rice"}
    # backup left behind, view regenerated with banner
    assert inventory_path().with_suffix(".md.bak").exists()
    assert "generated" in inventory_path().read_text(encoding="utf-8").lower()


def test_migrate_no_file_is_noop(tmp_vault, tmp_db):
    result = migrate()
    assert result["imported"] == 0
```

**Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_inventory_db.py -v`
Expected: FAIL — `No module named 'migrate_inventory_db'`

**Step 3: Implement**

Create `migrate_inventory_db.py`:

```python
#!/usr/bin/env python3
"""One-time migration: import legacy Inventory.md into data/kitchenos.db.

Parses the existing markdown table, inserts rows into the inventory table,
leaves Inventory.md.bak behind, and regenerates Inventory.md as the new
read-only view. Idempotent: re-running re-imports from the .bak only if the
DB inventory table is empty.

Usage: .venv/bin/python migrate_inventory_db.py [--dry-run]
"""
import argparse
import shutil

from lib.inventory import (
    inventory_path,
    parse_inventory_markdown,
    read_inventory,
    write_inventory,
)


def migrate(dry_run: bool = False) -> dict:
    path = inventory_path()
    if not path.exists():
        print("No Inventory.md found — nothing to migrate.")
        return {"imported": 0}
    if read_inventory():
        print("DB inventory table is not empty — refusing to overwrite.")
        return {"imported": 0}

    items = parse_inventory_markdown(path.read_text(encoding="utf-8"))
    print(f"Parsed {len(items)} items from {path}")
    if dry_run:
        for it in items:
            print(f"  {it.name} — {it.quantity} {it.unit} ({it.location})")
        return {"imported": 0}

    shutil.copy2(path, path.with_suffix(".md.bak"))
    write_inventory(items)  # writes DB + regenerates the view
    # verify round-trip
    assert len(read_inventory()) == len(items), "round-trip count mismatch"
    print(f"Imported {len(items)} items. Backup at {path}.bak")
    return {"imported": len(items)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    migrate(dry_run=ap.parse_args().dry_run)
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_migrate_inventory_db.py -v`
Expected: 2 PASS

**Step 5: Commit**

```bash
git add migrate_inventory_db.py tests/test_migrate_inventory_db.py
git commit -m "feat(db): one-time Inventory.md -> SQLite migration script"
```

---

### Task 4: Make `lib/pantry.py` an adapter over the inventory table

`load_pantry()` returns the same `[{item, amount, unit}]` shape, sourced from the DB (duplicate `(name, unit)` across locations are summed). `save_pantry()` reconciles the new list back into inventory rows. Pure functions (`split_against_pantry`, `apply_decisions`, `find_match`) are untouched.

**Files:**
- Modify: `lib/pantry.py`
- Test: `tests/test_pantry.py` (existing — add new tests, add `tmp_db`/`tmp_vault` fixtures to tests that hit load/save)

**Step 1: Write the failing tests** (append to `tests/test_pantry.py`)

```python
def test_load_pantry_reads_inventory_db(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items
    from lib.pantry import load_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Butter", quantity=1, unit="lb", location="fridge"),
        InventoryItem(name="Butter", quantity=0.5, unit="lb", location="freezer"),
    ])
    pantry = load_pantry()
    by_item = {e["item"]: e for e in pantry}
    assert by_item["Flour"]["amount"] == "5"
    assert by_item["Flour"]["unit"] == "lb"
    assert by_item["Butter"]["amount"] == "1.5"  # summed across locations


def test_save_pantry_decrements_and_removes(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, read_inventory
    from lib.pantry import load_pantry, save_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Sugar", quantity=2, unit="lb"),
    ])
    # simulate apply_decisions output: flour reduced, sugar used up
    save_pantry([{"item": "Flour", "amount": "3", "unit": "lb"}])
    items = {it.name: it for it in read_inventory()}
    assert items["Flour"].quantity == 3.0
    assert "Sugar" not in items
    assert load_pantry() == [{"item": "Flour", "amount": "3", "unit": "lb"}]


def test_save_pantry_inserts_new_items(tmp_vault, tmp_db):
    from lib.inventory import read_inventory
    from lib.pantry import save_pantry
    save_pantry([{"item": "Olive oil", "amount": "16", "unit": "oz"}])
    items = read_inventory()
    assert items[0].name == "Olive oil"
    assert items[0].location == "pantry"
    assert items[0].source == "manual"
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pantry.py -v`
Expected: new tests FAIL (load_pantry still reads `config/pantry.json`)

**Step 3: Replace `load_pantry` / `save_pantry` in `lib/pantry.py`**

Update the module docstring (storage is now the inventory table; `config/pantry.json` retired) and replace the two functions. Delete the `PANTRY_PATH` constant and `json`/`Path` imports if now unused.

```python
def load_pantry() -> list[dict]:
    """Pantry view of current stock: [{item, amount, unit}, ...].

    Sourced from the DB inventory table. Rows sharing (name, unit) across
    locations are summed — the shopping-list split doesn't care where an
    item lives.
    """
    from lib.inventory import read_inventory

    totals: dict[tuple[str, str], dict] = {}
    for it in read_inventory():
        key = (it.name.lower().strip(), it.unit.lower().strip())
        if key in totals:
            prev = parse_amount_to_float(totals[key]["amount"]) or 0.0
            totals[key]["amount"] = format_amount(prev + it.quantity)
        else:
            totals[key] = {
                "item": it.name,
                "amount": format_amount(it.quantity),
                "unit": it.unit,
            }
    return list(totals.values())


def save_pantry(items: list[dict]) -> None:
    """Reconcile a pantry list (post apply_decisions) into the inventory table.

    - (name, unit) present here and in DB → quantity updated. If the same
      (name, unit) exists in several locations, the first row (fridge order
      as returned) absorbs the new total and the duplicates are dropped —
      acceptable loss of location detail for the rare duplicate case.
    - (name, unit) missing here but in DB → row deleted (used up).
    - new (name, unit) → inserted with defaults (pantry/manual/other).
    """
    from lib.inventory import InventoryItem, read_inventory, write_inventory

    new_by_key: dict[tuple[str, str], dict] = {}
    for entry in items:
        name = (entry.get("item") or "").strip()
        if not name:
            continue
        key = (name.lower(), (entry.get("unit") or "").lower().strip())
        new_by_key[key] = entry

    kept: list[InventoryItem] = []
    seen: set[tuple[str, str]] = set()
    for it in read_inventory():
        key = (it.name.lower().strip(), it.unit.lower().strip())
        if key not in new_by_key:
            continue  # used up → drop row
        if key in seen:
            continue  # duplicate location row collapsed
        seen.add(key)
        amt = parse_amount_to_float(new_by_key[key].get("amount"))
        it.quantity = amt if amt is not None else it.quantity
        kept.append(it)

    for key, entry in new_by_key.items():
        if key not in seen:
            amt = parse_amount_to_float(entry.get("amount"))
            kept.append(InventoryItem(
                name=entry["item"].strip(),
                quantity=amt if amt is not None else 1.0,
                unit=(entry.get("unit") or "ct").strip() or "ct",
            ))

    write_inventory(kept)
```

**Step 4: Run the pantry + shopping-list tests**

Run: `.venv/bin/python -m pytest tests/test_pantry.py tests/ -v -k "pantry or shopping"`
Then the full suite: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS. Any test that previously seeded `config/pantry.json` directly must be updated to seed via `save_pantry()` or `add_items()` with the `tmp_db` fixture.

**Step 5: Delete `config/pantry.json` references**

Grep: `grep -rn "pantry.json" --include="*.py" .` — update `api_server.py` / `shopping_list.py` call sites if any pass explicit paths (the keyword-less `load_pantry()`/`save_pantry(items)` calls need no change; remove any `path=` arguments).

**Step 6: Commit**

```bash
git add lib/pantry.py tests/test_pantry.py
git commit -m "refactor(pantry): back pantry API with unified inventory table"
```

---

### Task 5: Canonical name aliases

**Files:**
- Create: `lib/item_aliases.py`
- Create: `config/item_aliases.json` (empty object `{}`)
- Test: `tests/test_item_aliases.py`

**Step 1: Write the failing tests**

```python
"""Tests for lib/item_aliases.py."""
import json

from lib import item_aliases


def test_canonicalize_prefers_saved_alias(tmp_path, monkeypatch):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"hcf bnls sknls brst": "chicken breast"}))
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", p)
    # saved alias wins over the model's suggestion
    assert item_aliases.canonicalize("HCF BNLS SKNLS BRST", "chicken") == "chicken breast"


def test_canonicalize_caches_model_suggestion(tmp_path, monkeypatch):
    p = tmp_path / "aliases.json"
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", p)
    assert item_aliases.canonicalize("GV WHL MLK 1G", "whole milk") == "whole milk"
    assert json.loads(p.read_text())["gv whl mlk 1g"] == "whole milk"


def test_canonicalize_falls_back_to_cleaned_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")
    assert item_aliases.canonicalize("  Bananas ", None) == "bananas"
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_item_aliases.py -v`
Expected: FAIL — module not found

**Step 3: Implement `lib/item_aliases.py`**

```python
"""Raw receipt string → canonical item name mapping.

``config/item_aliases.json`` maps lowercased raw receipt strings (e.g.
"hcf bnls sknls brst") to canonical names ("chicken breast"). The Ollama
extraction prompt proposes a canonical name per line; this cache makes the
mapping stable across receipts and hand-correctable in a text editor —
a saved alias always wins over the model's suggestion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "item_aliases.json"


def load_aliases() -> dict:
    if not ALIASES_PATH.exists():
        return {}
    try:
        data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_aliases(aliases: dict) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALIASES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(dict(sorted(aliases.items())), indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(ALIASES_PATH)


def canonicalize(raw_name: str, suggested: Optional[str]) -> str:
    """Resolve a raw receipt string to its canonical name.

    Priority: saved alias > model suggestion (which gets cached) >
    cleaned lowercase raw string.
    """
    key = (raw_name or "").lower().strip()
    aliases = load_aliases()
    if key in aliases:
        return aliases[key]
    canonical = (suggested or "").lower().strip() or key
    if key and canonical != key:
        aliases[key] = canonical
        save_aliases(aliases)
    return canonical
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_item_aliases.py -v`
Expected: 3 PASS

**Step 5: Create the empty config and commit**

```bash
echo '{}' > config/item_aliases.json
git add lib/item_aliases.py config/item_aliases.json tests/test_item_aliases.py
git commit -m "feat: item alias cache for receipt name canonicalization"
```

---

### Task 6: Receipt extraction prompt

**Files:**
- Create: `prompts/receipt_extraction.py`

No test needed (pure string template — exercised by Task 7 tests).

**Step 1: Create `prompts/receipt_extraction.py`**

```python
"""Prompt template for extracting structured data from grocery receipt emails."""

RECEIPT_SCHEMA = """{
  "store": "HEB",
  "date": "YYYY-MM-DD",
  "order_type": "in_store or curbside",
  "total": 45.23,
  "items": [
    {
      "raw_name": "exact item text from the receipt",
      "canonical_name": "plain english name, lowercase (e.g. 'chicken breast')",
      "quantity": 1,
      "unit": "lb, oz, gal, ct, ...",
      "unit_price": 5.49,
      "line_total": 11.53,
      "category": "produce|dairy|meat|seafood|pantry|frozen|bakery|beverages|household|fee|other"
    }
  ]
}"""


def build_receipt_prompt(text: str) -> str:
    return f"""You are a grocery receipt parser. Below is the plain text of an
email from HEB — either an in-store e-receipt or a curbside/delivery order
confirmation. Extract every line item.

Rules:
- Output ONLY valid JSON matching this schema:
{RECEIPT_SCHEMA}
- raw_name must be copied verbatim from the receipt line.
- canonical_name is your best plain-english name for the product, lowercase,
  no brand names (e.g. "HCF BNLS SKNLS BRST" -> "chicken breast").
- Tax, delivery fees, tips, bag fees, bottle deposits: include them as items
  with category "fee" and a sensible canonical_name ("sales tax", "delivery fee").
- Discounts/coupons: include as category "fee" with a NEGATIVE line_total.
- quantity defaults to 1; weight-priced items use the weight as quantity and
  the per-unit price as unit_price.
- date is the purchase/delivery date in the email, formatted YYYY-MM-DD.
- total is the receipt grand total in dollars.
- If you cannot find a value, use null. Do not invent items.

RECEIPT TEXT:
{text[:8000]}
"""
```

**Step 2: Commit**

```bash
git add prompts/receipt_extraction.py
git commit -m "feat: receipt extraction prompt template"
```

---

### Task 7: Receipt parser — HTML→text, Ollama call, validation

**Files:**
- Create: `lib/receipt_parser.py`
- Create: `tests/fixtures/heb_ereceipt.html`
- Create: `tests/fixtures/heb_curbside.html`
- Test: `tests/test_receipt_parser.py`

**Step 1: Create the fixtures**

`tests/fixtures/heb_ereceipt.html` — representative structure, not pixel-true (a real HEB email can be substituted later via `ingest_receipts.py --file`):

```html
<html><body>
<table><tr><td><h1>H-E-B</h1><p>Your eReceipt</p>
<p>Store #589 — Austin, TX</p><p>Date: 06/09/2026</p></td></tr>
<tr><td>
<table>
<tr><td>HCF BNLS SKNLS BRST</td><td>2.10 lb @ $5.49/lb</td><td>$11.53</td></tr>
<tr><td>GV WHL MLK 1G</td><td>1</td><td>$3.98</td></tr>
<tr><td>BANANAS</td><td>2.35 lb @ $0.49/lb</td><td>$1.15</td></tr>
<tr><td>TX SALES TAX</td><td></td><td>$0.34</td></tr>
</table>
<p><b>TOTAL: $17.00</b></p>
</td></tr></table>
</body></html>
```

`tests/fixtures/heb_curbside.html`:

```html
<html><body>
<h2>Your H-E-B curbside order is ready!</h2>
<p>Pickup date: June 9, 2026</p>
<ul>
<li>H-E-B Boneless Skinless Chicken Breast — 2 lb — $10.98</li>
<li>H-E-B Whole Milk, 1 gal — 1 — $3.98</li>
</ul>
<p>Curbside fee: $4.95</p>
<p>Order total: $19.91</p>
</body></html>
```

**Step 2: Write the failing tests**

`tests/test_receipt_parser.py`:

```python
"""Tests for lib/receipt_parser.py with a mocked Ollama call."""
import json
from pathlib import Path

import pytest

from lib import receipt_parser as rp

FIXTURES = Path(__file__).parent / "fixtures"

PARSED_OK = {
    "store": "HEB",
    "date": "2026-06-09",
    "order_type": "in_store",
    "total": 17.00,
    "items": [
        {"raw_name": "HCF BNLS SKNLS BRST", "canonical_name": "chicken breast",
         "quantity": 2.10, "unit": "lb", "unit_price": 5.49,
         "line_total": 11.53, "category": "meat"},
        {"raw_name": "GV WHL MLK 1G", "canonical_name": "whole milk",
         "quantity": 1, "unit": "gal", "unit_price": 3.98,
         "line_total": 3.98, "category": "dairy"},
        {"raw_name": "BANANAS", "canonical_name": "bananas",
         "quantity": 2.35, "unit": "lb", "unit_price": 0.49,
         "line_total": 1.15, "category": "produce"},
        {"raw_name": "TX SALES TAX", "canonical_name": "sales tax",
         "quantity": 1, "unit": "ct", "unit_price": 0.34,
         "line_total": 0.34, "category": "fee"},
    ],
}


def test_email_to_text_strips_html():
    html = (FIXTURES / "heb_ereceipt.html").read_text()
    text = rp.email_to_text(html)
    assert "<td>" not in text
    assert "HCF BNLS SKNLS BRST" in text
    assert "TOTAL: $17.00" in text


def test_to_cents():
    assert rp.to_cents(11.53) == 1153
    assert rp.to_cents("3.98") == 398
    assert rp.to_cents(None) is None
    assert rp.to_cents(-2.00) == -200


def test_parse_receipt_text_uses_ollama(monkeypatch):
    calls = {}

    def fake_ollama(prompt):
        calls["prompt"] = prompt
        return json.dumps(PARSED_OK)

    parsed = rp.parse_receipt_text("some receipt text", ollama_call=fake_ollama)
    assert parsed["date"] == "2026-06-09"
    assert len(parsed["items"]) == 4
    assert "some receipt text" in calls["prompt"]


def test_validate_receipt_ok():
    ok, problems = rp.validate_receipt(PARSED_OK)
    assert ok is True
    assert problems == []


def test_validate_receipt_total_mismatch():
    bad = dict(PARSED_OK, total=99.99)
    ok, problems = rp.validate_receipt(bad)
    assert ok is False
    assert any("total" in p for p in problems)


def test_validate_receipt_missing_date():
    bad = dict(PARSED_OK, date=None)
    ok, problems = rp.validate_receipt(bad)
    assert ok is False


def test_validate_receipt_no_items():
    bad = dict(PARSED_OK, items=[])
    ok, problems = rp.validate_receipt(bad)
    assert ok is False


def test_build_purchases_canonicalizes(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")
    purchases = rp.build_purchases(PARSED_OK)
    assert purchases[0]["canonical_name"] == "chicken breast"
    assert purchases[0]["unit_price_cents"] == 549
    assert purchases[0]["total_cents"] == 1153
    assert purchases[3]["category"] == "fee"
```

**Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_receipt_parser.py -v`
Expected: FAIL — module not found

**Step 4: Implement `lib/receipt_parser.py`**

```python
"""Parse HEB receipt emails into trip + purchase records.

Pipeline: HTML email body → plain text (BeautifulSoup) → Ollama structured
extraction (mistral:7b, same pattern as recipe_sources.py) → validation
(line totals must sum to the receipt total within tolerance) → purchase
dicts ready for inventory_db.record_trip().
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

from lib.item_aliases import canonicalize
from lib.inventory import normalize_category
from prompts.receipt_extraction import build_receipt_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

PURCHASE_CATEGORIES = (
    "produce", "dairy", "meat", "seafood", "pantry", "frozen",
    "bakery", "beverages", "household", "fee", "other",
)

# fridge/freezer guesses for incoming stock, by category
_LOCATION_BY_CATEGORY = {
    "produce": "fridge", "dairy": "fridge", "meat": "fridge",
    "seafood": "fridge", "frozen": "freezer",
}


def email_to_text(html: str) -> str:
    """Flatten email HTML to readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def to_cents(value) -> Optional[int]:
    """Dollars (float/str) → integer cents. None passes through."""
    if value is None:
        return None
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return None


def _call_ollama(prompt: str) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt,
              "stream": False, "format": "json"},
        timeout=180,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def parse_receipt_text(
    text: str, ollama_call: Callable[[str], str] = _call_ollama
) -> dict:
    """Extract structured receipt data. Raises on Ollama/JSON failure."""
    raw = ollama_call(build_receipt_prompt(text))
    return json.loads(raw)


def validate_receipt(parsed: dict) -> tuple[bool, list[str]]:
    """Sanity-check a parsed receipt. Returns (ok, problems)."""
    problems: list[str] = []
    if not parsed.get("date"):
        problems.append("missing date")
    items = parsed.get("items") or []
    if not items:
        problems.append("no line items")
    for it in items:
        if not it.get("raw_name"):
            problems.append("item missing raw_name")
            break

    total_cents = to_cents(parsed.get("total"))
    if total_cents is None:
        problems.append("missing or unparseable total")
    elif items:
        line_sum = sum(to_cents(it.get("line_total")) or 0 for it in items)
        tolerance = max(100, abs(total_cents) // 50)  # $1 or 2%
        if abs(line_sum - total_cents) > tolerance:
            problems.append(
                f"line totals ({line_sum}c) don't match total ({total_cents}c)"
            )
    return (not problems, problems)


def build_purchases(parsed: dict) -> list[dict]:
    """Convert parsed items into purchase rows (cents, canonical names)."""
    purchases = []
    for it in parsed.get("items") or []:
        raw = (it.get("raw_name") or "").strip()
        if not raw:
            continue
        cat = (it.get("category") or "other").lower().strip()
        if cat not in PURCHASE_CATEGORIES:
            cat = normalize_category(cat)
        purchases.append({
            "raw_name": raw,
            "canonical_name": canonicalize(raw, it.get("canonical_name")),
            "quantity": it.get("quantity") if it.get("quantity") is not None else 1,
            "unit": (it.get("unit") or "ct").lower().strip() or "ct",
            "unit_price_cents": to_cents(it.get("unit_price")),
            "total_cents": to_cents(it.get("line_total")),
            "category": cat,
        })
    return purchases


def default_location(category: str) -> str:
    return _LOCATION_BY_CATEGORY.get(category, "pantry")
```

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_receipt_parser.py -v`
Expected: 8 PASS

**Step 6: Commit**

```bash
git add lib/receipt_parser.py tests/test_receipt_parser.py tests/fixtures/
git commit -m "feat: receipt parser — html to text, ollama extraction, validation"
```

---

### Task 8: Email fetcher (IMAP)

**Files:**
- Create: `lib/email_fetcher.py`
- Create: `config/receipt_senders.json`
- Test: `tests/test_email_fetcher.py`

**Step 1: Create `config/receipt_senders.json`**

```json
{
  "HEB": ["heb.com", "hebtoyou.net"]
}
```

(Sender **domains**, matched against the From header. **Manual follow-up for the user:** check an actual HEB email's From address and adjust — these are best guesses.)

**Step 2: Write the failing tests**

`tests/test_email_fetcher.py` — test the pure parts (message parsing, sender matching); the IMAP connection itself is a thin untested wrapper:

```python
"""Tests for lib/email_fetcher.py message parsing and sender matching."""
from email.message import EmailMessage

from lib import email_fetcher as ef


def _make_email(from_addr: str, html: str, msg_id: str = "<m1@heb.com>"):
    msg = EmailMessage()
    msg["From"] = f"H-E-B <{from_addr}>"
    msg["Subject"] = "Your H-E-B eReceipt"
    msg["Message-ID"] = msg_id
    msg["Date"] = "Mon, 09 Jun 2026 18:00:00 -0500"
    msg.set_content("plain fallback")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_extract_email_payload_prefers_html():
    raw = _make_email("receipts@heb.com", "<p>RECEIPT HTML</p>")
    payload = ef.extract_email_payload(raw)
    assert payload["message_id"] == "<m1@heb.com>"
    assert "RECEIPT HTML" in payload["html"]
    assert payload["from"] == "receipts@heb.com"


def test_sender_matches_domains():
    assert ef.sender_matches("receipts@heb.com", ["heb.com"]) is True
    assert ef.sender_matches("no-reply@hebtoyou.net", ["heb.com", "hebtoyou.net"]) is True
    assert ef.sender_matches("spam@hebx.com", ["heb.com"]) is False


def test_load_sender_domains():
    domains = ef.load_sender_domains()
    assert "heb.com" in domains
```

**Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_email_fetcher.py -v`
Expected: FAIL — module not found

**Step 4: Implement `lib/email_fetcher.py`**

```python
"""Fetch grocery receipt emails from Gmail over IMAP.

Credentials come from .env: GMAIL_ADDRESS + GMAIL_APP_PASSWORD (a Google
"app password" — requires 2-step verification on the account). Sender
domains per store live in config/receipt_senders.json.

Only message *reading* happens here; dedup against already-ingested
Message-IDs is the caller's job (ingest_receipts.py checks trips.source_id).
Messages are never deleted or marked read-only flags changed beyond IMAP's
implicit \\Seen.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import json
import os
from datetime import date, timedelta
from email.utils import parseaddr
from pathlib import Path

SENDERS_PATH = Path(__file__).resolve().parent.parent / "config" / "receipt_senders.json"
IMAP_HOST = "imap.gmail.com"


def load_sender_domains() -> list[str]:
    data = json.loads(SENDERS_PATH.read_text(encoding="utf-8"))
    return [d for domains in data.values() for d in domains]


def sender_matches(from_addr: str, domains: list[str]) -> bool:
    addr = (from_addr or "").lower()
    return any(addr.endswith("@" + d) or addr.endswith("." + d) for d in domains)


def extract_email_payload(raw_bytes: bytes) -> dict:
    """Parse a raw RFC822 message into {message_id, from, subject, date, html}."""
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    body = msg.get_body(preferencelist=("html", "plain"))
    html = body.get_content() if body else ""
    return {
        "message_id": msg.get("Message-ID", "").strip(),
        "from": parseaddr(msg.get("From", ""))[1],
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "html": html,
    }


def fetch_receipt_emails(since_days: int = 14) -> list[dict]:
    """Fetch candidate receipt emails from the last ``since_days`` days."""
    address = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env")

    domains = load_sender_domains()
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")

    results: list[dict] = []
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(address, password)
        conn.select("INBOX", readonly=True)
        for domain in domains:
            status, data = conn.search(
                None, f'(FROM "{domain}" SINCE {since})'
            )
            if status != "OK" or not data or not data[0]:
                continue
            for num in data[0].split():
                status, msg_data = conn.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                payload = extract_email_payload(msg_data[0][1])
                if sender_matches(payload["from"], domains):
                    results.append(payload)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return results
```

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_email_fetcher.py -v`
Expected: 3 PASS

**Step 6: Add env keys to `.env` (placeholder values) and commit**

Append to `.env` (do NOT commit `.env`; it's untracked):
```
GMAIL_ADDRESS=chase8732@gmail.com
GMAIL_APP_PASSWORD=
```
(**Manual follow-up for the user:** create an app password at https://myaccount.google.com/apppasswords and fill it in.)

```bash
git add lib/email_fetcher.py config/receipt_senders.json tests/test_email_fetcher.py
git commit -m "feat: IMAP email fetcher for HEB receipt emails"
```

---

### Task 9: Ingest orchestrator CLI

**Files:**
- Create: `ingest_receipts.py`
- Test: `tests/test_ingest_receipts.py`

**Step 1: Write the failing tests**

```python
"""End-to-end ingest tests with mocked email fetch + Ollama."""
import json
from pathlib import Path

import pytest

import ingest_receipts as ir
from lib import inventory_db as idb
from lib.inventory import read_inventory

FIXTURES = Path(__file__).parent / "fixtures"

PARSED_OK = json.loads((FIXTURES / "parsed_ereceipt.json").read_text())


@pytest.fixture
def alias_tmp(tmp_path, monkeypatch):
    from lib import item_aliases
    monkeypatch.setattr(item_aliases, "ALIASES_PATH", tmp_path / "a.json")


def _email(msg_id="<m1@heb.com>"):
    return {
        "message_id": msg_id,
        "from": "receipts@heb.com",
        "subject": "Your H-E-B eReceipt",
        "date": "Mon, 09 Jun 2026 18:00:00 -0500",
        "html": (FIXTURES / "heb_ereceipt.html").read_text(),
    }


def test_ingest_writes_trip_purchases_inventory(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(
        ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK)
    )
    summary = ir.ingest()
    assert summary["ingested"] == 1
    assert idb.trip_exists("<m1@heb.com>")
    names = {it.name for it in read_inventory()}
    assert "chicken breast" in names
    assert "sales tax" not in names  # fee lines never touch inventory
    # Inventory.md view regenerated
    assert (tmp_vault / "Inventory.md").exists()


def test_ingest_skips_already_processed(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK))
    ir.ingest()
    summary = ir.ingest()
    assert summary["ingested"] == 0
    assert summary["skipped"] == 1


def test_ingest_invalid_receipt_flags_needs_review(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    bad = dict(PARSED_OK, total=999.99)
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email("<m2@heb.com>")])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: bad)
    summary = ir.ingest()
    assert summary["needs_review"] == 1
    assert read_inventory() == []  # no inventory updates for flagged trips
    conn = idb.connect()
    row = conn.execute("SELECT needs_review, raw_text FROM trips").fetchone()
    conn.close()
    assert row[0] == 1 and row[1]


def test_ingest_dry_run_writes_nothing(tmp_vault, tmp_db, alias_tmp, monkeypatch):
    monkeypatch.setattr(ir, "fetch_receipt_emails", lambda since_days: [_email()])
    monkeypatch.setattr(ir, "parse_receipt_text", lambda text, **kw: dict(PARSED_OK))
    summary = ir.ingest(dry_run=True)
    assert summary["ingested"] == 1  # counted, not written
    assert not idb.trip_exists("<m1@heb.com>")
```

Also create `tests/fixtures/parsed_ereceipt.json` with the same content as `PARSED_OK` in Task 7's test (the 4-item parsed receipt — copy it verbatim so both tests share one source of truth; update Task 7's test to load it from the fixture too).

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ingest_receipts.py -v`
Expected: FAIL — module not found

**Step 3: Implement `ingest_receipts.py`**

```python
#!/usr/bin/env python3
"""Ingest HEB receipt emails into the KitchenOS DB.

Run hourly by ops/com.kitchenos.receipt-ingest.plist. For each new email
(dedup by Message-ID against trips.source_id): parse with Ollama, validate,
record trip + purchases, update inventory (skipping fee lines), regenerate
the Inventory.md view and the price dashboard.

Usage:
    .venv/bin/python ingest_receipts.py                 # normal hourly run
    .venv/bin/python ingest_receipts.py --dry-run       # parse, write nothing
    .venv/bin/python ingest_receipts.py --since-days 30
    .venv/bin/python ingest_receipts.py --file r.eml    # one local file (.eml or .html)
"""
import argparse
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lib.email_fetcher import extract_email_payload, fetch_receipt_emails  # noqa: E402
from lib.failure_logger import classify_error, log_failures  # noqa: E402
from lib.inventory import InventoryItem, add_items  # noqa: E402
from lib.inventory_db import record_trip, trip_exists  # noqa: E402
from lib.receipt_parser import (  # noqa: E402
    build_purchases,
    default_location,
    email_to_text,
    parse_receipt_text,
    to_cents,
    validate_receipt,
)


def _source_for(parsed: dict) -> str:
    return (
        "email_curbside"
        if (parsed.get("order_type") or "").startswith("curb")
        else "email_receipt"
    )


def process_email(payload: dict, dry_run: bool = False) -> str:
    """Process one email payload. Returns 'ingested'|'needs_review'|'skipped'."""
    msg_id = payload.get("message_id") or ""
    if msg_id and trip_exists(msg_id):
        return "skipped"

    text = email_to_text(payload.get("html") or "")
    parsed = parse_receipt_text(text)
    ok, problems = validate_receipt(parsed)
    purchases = build_purchases(parsed)

    trip = {
        "date": parsed.get("date") or "",
        "store": parsed.get("store") or "HEB",
        "source": _source_for(parsed),
        "source_id": msg_id or None,
        "total_cents": to_cents(parsed.get("total")),
        "needs_review": not ok,
        "raw_text": text if not ok else None,
    }

    if dry_run:
        status = "OK" if ok else f"NEEDS REVIEW ({'; '.join(problems)})"
        print(f"[dry-run] {trip['date']} {trip['source']} "
              f"total={trip['total_cents']} items={len(purchases)} — {status}")
        for p in purchases:
            print(f"    {p['canonical_name']:30s} {p['quantity']} {p['unit']}"
                  f"  {p['total_cents']}c  [{p['category']}]")
        return "ingested" if ok else "needs_review"

    if record_trip(trip, purchases) is None:
        return "skipped"

    if not ok:
        print(f"  ⚠️  needs review: {'; '.join(problems)}")
        return "needs_review"

    stock = [
        InventoryItem(
            name=p["canonical_name"],
            quantity=float(p["quantity"] or 1),
            unit=p["unit"],
            category=p["category"],
            location=default_location(p["category"]),
            purchased=trip["date"],
            source="receipt",
        )
        for p in purchases
        if p["category"] != "fee"
    ]
    if stock:
        add_items(stock)
    return "ingested"


def ingest(since_days: int = 14, dry_run: bool = False,
           file: str = None) -> dict:
    summary = {"ingested": 0, "skipped": 0, "needs_review": 0, "failed": 0}
    failures = []

    if file:
        p = Path(file)
        raw = p.read_bytes()
        if p.suffix == ".eml":
            emails = [extract_email_payload(raw)]
        else:
            emails = [{"message_id": f"<file-{p.name}>", "from": "file",
                       "subject": p.name, "date": "", "html": raw.decode("utf-8")}]
    else:
        emails = fetch_receipt_emails(since_days=since_days)

    print(f"Found {len(emails)} candidate email(s)")
    for payload in emails:
        try:
            result = process_email(payload, dry_run=dry_run)
            summary[result] += 1
        except Exception as e:
            summary["failed"] += 1
            failures.append({
                "subject": payload.get("subject", ""),
                "message_id": payload.get("message_id", ""),
                "error": str(e),
                "category": classify_error(str(e), type(e)),
                "traceback": traceback.format_exc(),
            })
            print(f"  ❌ {payload.get('subject', '?')}: {e}")

    if failures and not dry_run:
        log_failures(failures, total_processed=len(emails))

    if summary["ingested"] and not dry_run:
        try:
            from lib.price_dashboard import save_dashboard
            save_dashboard()
        except ImportError:
            pass  # dashboard module lands in a later task

    print(f"Done: {summary}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since-days", type=int, default=14)
    ap.add_argument("--file", help="parse one local .eml or .html file")
    args = ap.parse_args()
    try:
        ingest(since_days=args.since_days, dry_run=args.dry_run, file=args.file)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_ingest_receipts.py tests/test_receipt_parser.py -v`
Expected: PASS (including the Task 7 file after switching it to load `parsed_ereceipt.json`)

**Step 5: Commit**

```bash
git add ingest_receipts.py tests/test_ingest_receipts.py tests/fixtures/parsed_ereceipt.json tests/test_receipt_parser.py
git commit -m "feat: receipt ingest orchestrator with dry-run and dedup"
```

---

### Task 10: Price dashboard

**Files:**
- Create: `lib/price_dashboard.py`
- Create: `generate_price_dashboard.py`
- Test: `tests/test_price_dashboard.py`

**Step 1: Write the failing tests**

```python
"""Tests for the price dashboard generator."""
from lib import inventory_db as idb
from lib.price_dashboard import generate_dashboard


def _seed(tmp_db):
    idb.record_trip(
        {"date": "2026-06-02", "store": "HEB", "source": "email_receipt",
         "source_id": "<a>", "total_cents": 1000},
        [{"raw_name": "MILK", "canonical_name": "whole milk", "quantity": 1,
          "unit": "gal", "unit_price_cents": 398, "total_cents": 398,
          "category": "dairy"},
         {"raw_name": "TAX", "canonical_name": "sales tax", "quantity": 1,
          "unit": "ct", "unit_price_cents": 50, "total_cents": 50,
          "category": "fee"}],
    )
    idb.record_trip(
        {"date": "2026-06-09", "store": "HEB", "source": "email_receipt",
         "source_id": "<b>", "total_cents": 1200},
        [{"raw_name": "MILK", "canonical_name": "whole milk", "quantity": 1,
          "unit": "gal", "unit_price_cents": 425, "total_cents": 425,
          "category": "dairy"}],
    )
    idb.record_trip(
        {"date": "2026-06-09", "store": "HEB", "source": "email_curbside",
         "source_id": "<c>", "total_cents": None, "needs_review": True,
         "raw_text": "garbled"},
        [],
    )


def test_dashboard_sections(tmp_vault, tmp_db):
    _seed(tmp_db)
    md = generate_dashboard(today="2026-06-10")
    assert "# Price Tracker" in md
    assert "## Spending" in md
    assert "## Price Trends" in md
    assert "whole milk" in md
    assert "$4.25" in md          # latest price
    assert "▲" in md              # price went up vs average
    assert "## Needs Review" in md
    assert "<c>" in md or "curbside" in md


def test_dashboard_spending_totals(tmp_vault, tmp_db):
    _seed(tmp_db)
    md = generate_dashboard(today="2026-06-10")
    assert "$10.00" in md or "$12.00" in md or "$22.00" in md


def test_save_dashboard_writes_file(tmp_vault, tmp_db):
    _seed(tmp_db)
    from lib.price_dashboard import save_dashboard
    path = save_dashboard(today="2026-06-10")
    assert path.name == "Price Tracker.md"
    assert path.exists()
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_price_dashboard.py -v`
Expected: FAIL — module not found

**Step 3: Implement `lib/price_dashboard.py`**

```python
"""Generate the Price Tracker dashboard (markdown) from the purchases ledger.

Aggregation happens in Python (the data volume is tiny — a few thousand
ledger rows after years of use). Money is cents in the DB, dollars in the
rendered output.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from lib import paths
from lib.inventory_db import connect

TOP_ITEMS = 20


def _dollars(cents: Optional[int]) -> str:
    return f"${(cents or 0) / 100:.2f}"


def _iso_week(d: str) -> str:
    iso = date.fromisoformat(d).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _load_rows() -> tuple[list[dict], list[dict]]:
    conn = connect()
    try:
        trips = [dict(r) for r in conn.execute(
            "SELECT * FROM trips ORDER BY date").fetchall()]
        purchases = [dict(r) for r in conn.execute(
            "SELECT p.*, t.date AS trip_date FROM purchases p"
            " JOIN trips t ON t.id = p.trip_id"
            " WHERE t.needs_review = 0 ORDER BY t.date").fetchall()]
        return trips, purchases
    finally:
        conn.close()


def generate_dashboard(today: Optional[str] = None) -> str:
    """Render the full dashboard markdown. ``today`` is injectable for tests."""
    ref = date.fromisoformat(today) if today else date.today()
    trips, purchases = _load_rows()
    ok_trips = [t for t in trips if not t["needs_review"]]

    lines = [
        "---",
        "type: price-tracker",
        f"last_updated: {ref.isoformat()}",
        "---",
        "",
        "# Price Tracker",
        "",
        "> Generated from grocery receipts. Do not edit — regenerated on every ingest.",
        "",
        "## Spending",
        "",
    ]

    # --- per-week, last 4 ISO weeks ---
    week_totals: dict[str, int] = defaultdict(int)
    for t in ok_trips:
        if t["total_cents"] and t["date"]:
            week_totals[_iso_week(t["date"])] += t["total_cents"]
    recent_weeks = [
        f"{(ref - timedelta(weeks=i)).isocalendar().year}-W"
        f"{(ref - timedelta(weeks=i)).isocalendar().week:02d}"
        for i in range(3, -1, -1)
    ]
    lines += ["| Week | Spend |", "|------|-------|"]
    lines += [f"| {w} | {_dollars(week_totals.get(w, 0))} |" for w in recent_weeks]
    lines.append("")

    # --- by category, last 12 months ---
    cutoff = (ref - timedelta(days=365)).isoformat()
    cat_totals: dict[str, int] = defaultdict(int)
    for p in purchases:
        if p["trip_date"] >= cutoff and p["total_cents"]:
            cat_totals[p["category"]] += p["total_cents"]
    lines += ["**By category (last 12 months):**", "",
              "| Category | Spend |", "|----------|-------|"]
    for cat, cents in sorted(cat_totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {_dollars(cents)} |")
    lines.append("")

    # --- average trip ---
    totals = [t["total_cents"] for t in ok_trips if t["total_cents"]]
    if totals:
        lines += [f"**Average trip:** {_dollars(sum(totals) // len(totals))}"
                  f" across {len(totals)} trips", ""]

    # --- price trends: top items by purchase count ---
    lines += ["## Price Trends", ""]
    by_item: dict[str, list[dict]] = defaultdict(list)
    for p in purchases:
        if p["category"] != "fee" and p["unit_price_cents"]:
            by_item[p["canonical_name"]].append(p)
    top = sorted(by_item.items(), key=lambda kv: -len(kv[1]))[:TOP_ITEMS]
    cutoff_90 = (ref - timedelta(days=90)).isoformat()
    lines += ["| Item | Last price | 90-day avg | Trend |",
              "|------|-----------|------------|-------|"]
    for name, rows in top:
        last = rows[-1]["unit_price_cents"]
        recent = [r["unit_price_cents"] for r in rows if r["trip_date"] >= cutoff_90]
        avg = sum(recent) // len(recent) if recent else last
        marker = "▲" if last > avg else ("▼" if last < avg else "—")
        lines.append(
            f"| {name} | {_dollars(last)}/{rows[-1]['unit']} |"
            f" {_dollars(avg)} | {marker} |"
        )
    lines.append("")

    # --- per-item history, collapsible ---
    lines += ["<details><summary>Per-item price history</summary>", ""]
    for name, rows in top:
        lines += [f"**{name}**", "", "| Date | Price | Qty |", "|------|-------|-----|"]
        lines += [
            f"| {r['trip_date']} | {_dollars(r['unit_price_cents'])}/{r['unit']}"
            f" | {r['quantity']} |"
            for r in rows[-12:]
        ]
        lines.append("")
    lines += ["</details>", ""]

    # --- needs review ---
    flagged = [t for t in trips if t["needs_review"]]
    if flagged:
        lines += ["## Needs Review", ""]
        for t in flagged:
            lines.append(
                f"- {t['date'] or '?'} — {t['source']} — id `{t['source_id']}`"
            )
        lines.append("")

    return "\n".join(lines)


def save_dashboard(today: Optional[str] = None) -> Path:
    path = paths.vault_root() / "Price Tracker.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_dashboard(today=today), encoding="utf-8")
    return path
```

**Step 4: Implement `generate_price_dashboard.py`** (CLI, mirrors `generate_nutrition_dashboard.py`)

```python
#!/usr/bin/env python3
"""Generate the Price Tracker dashboard in the Obsidian vault.

Usage:
    .venv/bin/python generate_price_dashboard.py
    .venv/bin/python generate_price_dashboard.py --dry-run
"""
import argparse

from dotenv import load_dotenv

load_dotenv()

from lib.price_dashboard import generate_dashboard, save_dashboard  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print markdown without saving")
    args = ap.parse_args()
    if args.dry_run:
        print(generate_dashboard())
    else:
        path = save_dashboard()
        print(f"Wrote {path}")
```

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_price_dashboard.py -v`
Expected: 3 PASS

**Step 6: Commit**

```bash
git add lib/price_dashboard.py generate_price_dashboard.py tests/test_price_dashboard.py
git commit -m "feat: price tracker dashboard — spending + price trends"
```

---

### Task 11: API — accept prices/trip in `/api/inventory/add`

The photo flow (Claude Desktop → MCP → API) feeds the same ledger. Backward compatible: requests without `trip` behave exactly as today.

**Files:**
- Modify: `api_server.py` (handler `api_inventory_add`, ~line 1359)
- Test: `tests/test_api_server.py` (append)

**Step 1: Write the failing test** (append to `tests/test_api_server.py`, using its existing client fixture pattern)

```python
def test_inventory_add_with_trip_records_purchases(client, tmp_vault, tmp_db):
    payload = {
        "items": [
            {"name": "chicken breast", "quantity": 2, "unit": "lb",
             "category": "meat", "location": "fridge",
             "purchased": "2026-06-09", "source": "receipt",
             "unit_price": 5.49, "line_total": 10.98},
        ],
        "trip": {"date": "2026-06-09", "store": "HEB", "total": 10.98,
                 "source_id": "photo-abc123"},
    }
    resp = client.post("/api/inventory/add", json=payload)
    assert resp.status_code == 200
    from lib import inventory_db as idb
    assert idb.trip_exists("photo-abc123")
    conn = idb.connect()
    row = conn.execute("SELECT canonical_name, total_cents FROM purchases").fetchone()
    conn.close()
    assert row[0] == "chicken breast"
    assert row[1] == 1098


def test_inventory_add_without_trip_unchanged(client, tmp_vault, tmp_db):
    resp = client.post("/api/inventory/add", json={
        "items": [{"name": "rice", "quantity": 2, "unit": "lb"}]})
    assert resp.status_code == 200
    from lib import inventory_db as idb
    conn = idb.connect()
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0
    conn.close()
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -k inventory_add -v`
Expected: new tests FAIL

**Step 3: Extend `api_inventory_add` in `api_server.py`**

After the existing `add_items(...)` call and before building the response, add:

```python
    # Optional price ledger: a "trip" object turns this add into a recorded
    # shopping trip (photo receipts from the Claude flow).
    trip_payload = data.get("trip")
    if trip_payload:
        from lib.inventory_db import record_trip
        from lib.receipt_parser import to_cents

        purchases = [
            {
                "raw_name": it.get("notes") or it.get("name", ""),
                "canonical_name": (it.get("name") or "").lower().strip(),
                "quantity": it.get("quantity", 1),
                "unit": it.get("unit", "ct"),
                "unit_price_cents": to_cents(it.get("unit_price")),
                "total_cents": to_cents(it.get("line_total")),
                "category": it.get("category", "other"),
            }
            for it in data.get("items", [])
        ]
        record_trip(
            {
                "date": trip_payload.get("date", ""),
                "store": trip_payload.get("store", "HEB"),
                "source": trip_payload.get("source", "photo"),
                "source_id": trip_payload.get("source_id"),
                "total_cents": to_cents(trip_payload.get("total")),
            },
            purchases,
        )
```

(`it` here is each raw item dict from the request, captured **before** they're converted to `InventoryItem`s — place the loop accordingly, or keep a reference to the original `data["items"]` list.)

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_api_server.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add api_server.py tests/test_api_server.py
git commit -m "feat(api): /api/inventory/add accepts trip + prices for the ledger"
```

---

### Task 12: MCP tool — pass prices and trip through

**Files:**
- Modify: `lib/mcp_tools.py` (`add_to_inventory`, ~line 116)
- Modify: `mcp_server.py` (`add_to_inventory` tool, ~line 210)

**Step 1: Update `lib/mcp_tools.py`**

```python
def add_to_inventory(items: list, trip: dict = None) -> dict:
    """Add items to the kitchen inventory, optionally recording a shopping trip."""
    payload = {"items": items}
    if trip:
        payload["trip"] = trip
    try:
        r = requests.post(
            f"{API_BASE}/api/inventory/add", json=payload, timeout=15
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}
```

**Step 2: Update the tool in `mcp_server.py`** — add the `trip` parameter and extend the docstring (the docstring is the contract Claude Desktop sees):

```python
@mcp.tool()
def add_to_inventory(items: list[dict], trip: dict = None) -> str:
    """
    Add items to the kitchen inventory. Optionally record the shopping trip
    so prices land in the price-history ledger.

    Each item dict:
        - name, quantity, unit, category, location, purchased, source, notes
          (as before)
        - unit_price: price per unit in dollars (optional, e.g. 5.49)
        - line_total: total dollars for the line (optional)

    trip (optional, include when parsing a receipt with visible prices):
        - date: YYYY-MM-DD
        - store: e.g. "HEB"
        - total: receipt grand total in dollars
        - source_id: any stable id for dedup (e.g. "photo-<date>-<store>")
        - source: "photo" (default)

    Items matching by (name, unit, location) merge.
    """
    return _format(_add_to_inventory(items, trip))
```

(Match the existing return/formatting helper used by the other tools in `mcp_server.py` — check how `add_to_inventory` currently wraps `_add_to_inventory` and keep that style.)

**Step 3: Smoke test**

Run: `.venv/bin/python -c "import mcp_server"` — expect no import errors.
Run: `.venv/bin/python -m pytest tests/ -v` — full suite green.

**Step 4: Commit**

```bash
git add lib/mcp_tools.py mcp_server.py
git commit -m "feat(mcp): add_to_inventory accepts prices and trip metadata"
```

---

### Task 13: LaunchAgent + logs

**Files:**
- Create: `ops/com.kitchenos.receipt-ingest.plist`

**Step 1: Create the plist** (hourly at :25 — offset from batch-extract's :10):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kitchenos.receipt-ingest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/chaseeasterling/KitchenOS/.venv/bin/python</string>
        <string>/Users/chaseeasterling/KitchenOS/ingest_receipts.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Minute</key>
        <integer>25</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/chaseeasterling/KitchenOS/logs/receipt_ingest.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/chaseeasterling/KitchenOS/logs/receipt_ingest.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/chaseeasterling/KitchenOS</string>
</dict>
</plist>
```

**Note:** the existing plists in `ops/` reference `/Users/chaseeasterling/GitHub/KitchenOS` — verify which path is real on this machine (`ls -ld ~/GitHub/KitchenOS /Users/chaseeasterling/KitchenOS`) and use the one that resolves; if `~/GitHub/KitchenOS` is a symlink to the repo, match the existing plists instead.

**Step 2: Install (manual, after GMAIL_APP_PASSWORD is set)**

```bash
cp ops/com.kitchenos.receipt-ingest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist
```

**Step 3: Commit**

```bash
git add ops/com.kitchenos.receipt-ingest.plist
git commit -m "feat(ops): hourly receipt-ingest LaunchAgent"
```

---

### Task 14: Run migration + end-to-end verification (manual gates)

**Step 1: Migrate real data**

```bash
.venv/bin/python migrate_inventory_db.py --dry-run   # review
.venv/bin/python migrate_inventory_db.py
```
Expected: item count matches the old `Inventory.md`; `.bak` exists; new `Inventory.md` has the generated banner; open in Obsidian to verify.

**Step 2: Verify a real email end-to-end**

Requires `GMAIL_APP_PASSWORD` in `.env` and Ollama running (`curl http://localhost:11434/api/tags`).

```bash
.venv/bin/python ingest_receipts.py --dry-run --since-days 30
```
Expected: candidate HEB emails listed with parsed items. If sender domains are wrong, fix `config/receipt_senders.json`. Then:

```bash
.venv/bin/python ingest_receipts.py --since-days 30
.venv/bin/python generate_price_dashboard.py --dry-run | head -50
```
Expected: trips recorded, inventory updated, `Price Tracker.md` renders. Re-run `ingest_receipts.py` — everything reports `skipped` (dedup works).

**Step 3: Full test suite + lint**

```bash
.venv/bin/python -m pytest tests/ -v
.venv/bin/ruff check .
```
Expected: all green.

---

### Task 15: Documentation updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**CLAUDE.md changes:**
1. **Running Commands**: add sections for `ingest_receipts.py` (with `--dry-run`, `--since-days`, `--file`), `generate_price_dashboard.py`, `migrate_inventory_db.py`.
2. **Receipt → Inventory Workflow**: rewrite — storage is now `data/kitchenos.db`; `Inventory.md` is a generated read-only view; email path is automatic via the receipt-ingest LaunchAgent; photo path unchanged but now records prices via the optional `trip` arg.
3. **Architecture → Core Components**: add rows for `ingest_receipts.py`, `lib/inventory_db.py`, `lib/receipt_parser.py`, `lib/email_fetcher.py`, `lib/item_aliases.py`, `lib/price_dashboard.py`, `prompts/receipt_extraction.py`, `config/receipt_senders.json`, `config/item_aliases.json`, `migrate_inventory_db.py`.
4. **Function Reference invariants**: add — "Inventory/pantry truth lives in `data/kitchenos.db` (`lib/inventory_db.py`); `Inventory.md` and `config/pantry.json` are no longer sources of truth (the latter is gone). All money columns are integer cents. `trips.source_id` is UNIQUE — ingest dedup depends on it."
5. **Development Environment**: add `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` to the `.env` key list.
6. **LaunchAgent section**: add `com.kitchenos.receipt-ingest.plist` management block (mirror batch-extract's).
7. **Future Enhancements**: remove "Email IMAP polling for receipts"; update "Inventory ↔ shopping list integration" row (subtraction now exists via unified store; remaining idea is the restock pass).
8. **MCP Available Tools table**: note `add_to_inventory` now takes optional prices + trip.

**README.md:** add a short "Grocery receipts & price tracking" section (what it does, the three intake paths, where the dashboard lives).

**lib/CLAUDE.md:** add one convention bullet — "DB access goes through `lib/inventory_db.py`; never open sqlite3 connections elsewhere. Tests point the DB at a temp file via the `KITCHENOS_DB` env var (`tmp_db` fixture in `tests/conftest.py`)."

**Commit:**

```bash
git add CLAUDE.md README.md lib/CLAUDE.md
git commit -m "docs: receipt ingestion, unified inventory DB, price tracker"
```

---

## Task Order & Dependencies

```
1 (DB) → 2 (inventory refactor) → 3 (migration) → 4 (pantry adapter)
1 → 5 (aliases) → 6 (prompt) → 7 (parser) → 8 (fetcher) → 9 (orchestrator)
1 → 10 (dashboard)   [9 references 10 via lazy import — either order works]
2 → 11 (API) → 12 (MCP)
9 → 13 (LaunchAgent) → 14 (manual E2E) → 15 (docs)
```

## Out of Scope (YAGNI — confirmed in design)

- Refund / substitution email handling
- Other stores (config is ready; just add domains)
- Deal detection / shopping-list cost estimation
- IMAP idle/push (hourly polling is fine)
- Editing inventory by hand-editing Inventory.md (now read-only)
