# Inventory Location Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each inventory item's storage location on `/review`, group the list by location, and record on every row how its location was decided so a machine guess is distinguishable from a placement you confirmed.

**Architecture:** A new `place_item()` router in `lib/storage_locations.py` owns the tier ladder (hand-curated item override → category rule → nothing matched) and returns both a location and its provenance. That provenance is stored per row in a new `inventory.location_source` column, added through the existing append-only `_MIGRATIONS` mechanism and backfilled once. The `/review` page renders the location in each row's subline, marks unresolved ones, and gains a Location sort mode that blocks rows under headers. Correcting a location teaches `config/storage_locations.json` so the same wrong guess stops recurring.

**Tech Stack:** Python 3.11, SQLite (via `lib/inventory_db.py`), Flask (`api_server.py`), vanilla JS in a Jinja-less HTML template (`templates/review.html`), pytest, Playwright for browser tests.

**Spec:** `docs/superpowers/specs/2026-07-26-inventory-location-visibility-design.md`

**Branch:** `inventory-location-visibility` (already created, spec committed at `dbe2019`)

> **Rebased onto `main` @ `ffc742d` on 2026-07-27.** This plan was authored against
> `c33d867`, before `consume-on-cook` merged. That branch rewrote several of the files
> this plan edits, so the following were corrected in this refresh:
>
> - **Task 2's find/replace blocks** — `_INVENTORY_COLS`, `_MIGRATIONS`, the
>   `InventoryItem` dataclass and the `read_inventory` mapping all gained
>   `last_used`/`use_count`. The blocks below are the *current* text; the originals
>   would not have matched.
> - **Test counts** — the baseline is now `2715 passed`, not `1504`.
> - **Task 5 scope** — extended to surface `last_used` in the same subline, since
>   `consume-on-cook` left those columns write-only and Task 5 already rewrites the
>   one function where they belong. Rewriting `subline()` twice would be waste.
> - **`templates/review.html` is untouched by `consume-on-cook`**, so every line
>   number Tasks 5 and 6 cite is still exact.
>
> **Line numbers elsewhere are indicative, not exact.** `lib/inventory.py` shifted by
> about +7 and `api_server.py` by +19. Anchor on the quoted code, not the number:
>
> | Symbol | Plan says | Actually |
> |---|---|---|
> | `normalize_source` | 75–79 | 80–84 |
> | `read_inventory` | 132–150 | 137–157 |
> | `_expiry_cell` (ends) | 180 | 185 |
> | `render_inventory_md` location cell | 214 | 221 |
> | `add_items` merge branch | 396–397 | 403 |
> | `_apply_move` | 585 | 592 |
> | `bulk_apply` | 740–745 | 683+ |
> | `move_item` | 787–807 | 794–814 |
> | `_migrate` | 173–183 | 178–188 |
> | `api_server` `resolve_location` import | 2049 | 2068 |
> | `SOURCES`, `storage_locations.py`, `review.html` | — | unchanged ✓ |

## Global Constraints

- **Python 3.11.** Always run via `.venv/bin/python` and `.venv/bin/pytest` — never bare `python`/`pytest`.
- **All SQLite access goes through `lib/inventory_db.py`.** Never open `sqlite3` connections elsewhere in `lib/`. Tests may open one directly to build a fixture DB.
- **`data/kitchenos.db` is the single source of truth** for inventory. Never add a parallel JSON/markdown source of truth.
- **Generated views render from the DB after the commit**, never from the caller's list. `write_inventory()` already re-reads; don't change that.
- **Controlled vocabularies live in `lib/inventory.py`** beside `CATEGORIES`, `LOCATIONS`, `SOURCES`.
- **Atomic JSON writes** use the `tmp + replace` pattern. `save_table()` already does; don't bypass it.
- **`location_source` is provenance, not address.** `InventoryItem.merge_key()` stays `(name, unit, location)`. Adding `location_source` to it would fragment rows.
- **Exact vocabulary:** `location_source` is one of `manual`, `item`, `category`, `default`. A NULL or unknown value reads as `default`.
- **Exact precedence:** `manual` > `item` > `category` > `default`.
- **Only `default` renders as unsure** (a `?` suffix).
- **Location glyphs, verbatim:** fridge `❄️`, freezer `🥶`, pantry `🫙`, counter `🧺`, other `📍`. Do not use `🧊` — `templates/review.html:95` already uses it for the `frozen` *category*.
- **Commit message trailer**, on every commit in this plan:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
  ```
- **The unit suite must stay green and grow only as planned.** Baseline before this plan: `2715 passed` (post-`consume-on-cook`). This plan adds 22 unit tests, ending at `2737 passed`. Per-task running totals: T1 → 2721, T2 → 2725, T3 → 2729, T4 → 2733, T5 → 2735, T6 → 2736, T7 → 2737. Run `.venv/bin/pytest -q` at the end of every task and check against those. E2E tests are deselected by default via `pytest.ini`.
- **The worktree needs a DB copy for the e2e harness.** `tests/e2e/conftest.py` copies `data/kitchenos.db`; a fresh worktree has none. Copy it — never symlink — so nothing can write through to production. Already done for this worktree.
- **API restart caveat.** The `com.kitchenos.api` LaunchAgent holds `lib/*` and templates in memory. After any `lib/` or `templates/` edit, a running server serves stale code. This matters only for manual verification (Task 9), not for pytest.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `lib/storage_locations.py` | Owns the tier ladder; produces `Placement(location, source)` | 1 |
| `tests/test_storage_locations.py` | Router tiers, longest-key-wins, `resolve_location` regression | 1 |
| `lib/inventory.py` | `InventoryItem.location_source`, vocab, normalizer, read path | 2 |
| `lib/inventory_db.py` | Column in schema + migration, one-time backfill | 2 |
| `tests/test_inventory_db.py` | Migration adds + backfills; idempotent | 2 |
| `tests/test_inventory.py` | Round-trip, NULL-reads-as-default, merge precedence, move/freeze/teach | 2,3,4 |
| `lib/receipt_ingest.py`, `ingest_csa.py`, `lib/receipt_paster.py`, `api_server.py` | Record provenance at row creation | 3 |
| `tests/test_api_endpoints.py` | Explicit location is `manual`; page markup ships | 3,5,6 |
| `templates/review.html` | Subline location, Location sort mode, group headers, move re-home | 5,6 |
| `tests/e2e/test_location_visibility.py` | Browser coverage for the above | 8 |
| `docs/API.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md` | Document the field and the new invariant | 9 |

---

### Task 1: Placement router

**Files:**
- Modify: `lib/storage_locations.py` (module docstring, new dataclass, new `place_item`, rewrite `resolve_location` as a wrapper)
- Test: `tests/test_storage_locations.py`

**Interfaces:**
- Consumes: `lib.inventory.normalize_location(loc: Optional[str]) -> str` (already imported at `lib/storage_locations.py:24`)
- Produces:
  - `Placement` — frozen dataclass with `location: str` and `source: str`
  - `place_item(name: str, category: Optional[str] = None) -> Placement`
  - `resolve_location(name: str, category: Optional[str] = None) -> str` — unchanged signature and return values

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage_locations.py`:

```python
def test_place_item_reports_the_item_tier():
    p = sl.place_item("bananas", "produce")
    assert (p.location, p.source) == ("counter", "item")


def test_place_item_reports_the_category_tier():
    p = sl.place_item("whole milk", "dairy")
    assert (p.location, p.source) == ("fridge", "category")


def test_catch_all_category_is_not_an_answer():
    # `other` is where normalize_category sends anything it couldn't place, so
    # a location derived from it is a shrug, not a placement. The location it
    # yields is still pantry — only the confidence differs.
    p = sl.place_item("psyllium husk", "other")
    assert p.location == "pantry"
    assert p.source == "default"


def test_missing_category_is_default():
    assert sl.place_item("mystery item", None) == sl.Placement("pantry", "default")
    assert sl.place_item("", "") == sl.Placement("pantry", "default")


def test_longest_item_key_wins(monkeypatch, tmp_path):
    # Teaching grows by_item on every correction, so a short key must not
    # capture a longer, more specific one: "milk" must not swallow
    # "milk chocolate chips".
    table = tmp_path / "storage_locations.json"
    table.write_text(json.dumps({
        "by_item": {"milk": "fridge", "milk chocolate chips": "pantry"},
        "by_category": {},
    }))
    monkeypatch.setattr(sl, "TABLE_PATH", table)
    assert sl.place_item("milk chocolate chips", None).location == "pantry"
    assert sl.place_item("whole milk", None).location == "fridge"


def test_resolve_location_still_returns_a_bare_string():
    # Four callers depend on this contract; place_item must not leak through.
    assert sl.resolve_location("whole milk", "dairy") == "fridge"
    assert sl.resolve_location("bananas", "produce") == "counter"
    assert isinstance(sl.resolve_location("mystery item", None), str)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_storage_locations.py -v`

Expected: the six new tests FAIL with `AttributeError: module 'lib.storage_locations' has no attribute 'place_item'` (and `...has no attribute 'Placement'`). The seven pre-existing tests PASS.

- [ ] **Step 3: Write the implementation**

In `lib/storage_locations.py`, add `dataclass` to the imports:

```python
from dataclasses import dataclass
```

Replace the whole `resolve_location` function (currently `lib/storage_locations.py:62-87`) with:

```python
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
```

Then update the module docstring's closing paragraph (`lib/storage_locations.py:12-15`) to read:

```
A purchase resolves by exact item name, then by the *longest* item key whose
words are all contained in the name (so "roma tomatoes" still matches
"tomatoes", but a taught "milk" never swallows "milk chocolate chips"), then by
category, then ``"pantry"``. ``place_item`` also reports which tier decided, so
callers can tell a hand-curated answer from a shrug. The file is plain JSON so
it stays editable in a text editor, mirroring ``config/item_aliases.json``.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_storage_locations.py -v`
Expected: 13 passed.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2721 passed` (2715 + 6) — the four existing `resolve_location` callers are unaffected.

- [ ] **Step 5: Commit**

```bash
git add lib/storage_locations.py tests/test_storage_locations.py
git commit -m "$(cat <<'EOF'
feat: report which tier decided an item's storage location

place_item() returns both the location and its provenance, so callers can
tell a hand-curated override from a category guess from a shrug.
resolve_location() stays a thin wrapper with an identical contract.

Two behaviour changes ride along. The longest matching by_item key now
wins rather than the first in dict order — teaching grows that table on
every correction, and first-match would eventually let "milk" capture
"milk chocolate chips". And a by_category hit on the catch-all "other"
reports "default", because normalize_category funnels everything it
can't place there; without this the default tier is unreachable, since
by_category covers all ten categories.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 2: `location_source` column, migration, and backfill

**Files:**
- Modify: `lib/inventory.py` (vocab tuple, normalizer, dataclass field, `read_inventory`)
- Modify: `lib/inventory_db.py` (`_SCHEMA`, `_INVENTORY_COLS`, `_MIGRATIONS`, `_migrate`, new `_backfill_location_source`)
- Test: `tests/test_inventory_db.py`, `tests/test_inventory.py`

**Interfaces:**
- Consumes: `lib.storage_locations.place_item(name, category) -> Placement` from Task 1
- Produces:
  - `lib.inventory.LOCATION_SOURCES: tuple[str, ...]` = `("manual", "item", "category", "default")`
  - `lib.inventory.normalize_location_source(src: Optional[str]) -> str`
  - `InventoryItem.location_source: str` (defaults to `"default"`), carried by `to_dict()` via `asdict`
  - `inventory` table column `location_source TEXT`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inventory_db.py`:

```python
def test_location_source_is_added_to_a_db_that_predates_it(tmp_db):
    """An existing DB gains the column, and its rows get classified once."""
    import sqlite3

    conn = sqlite3.connect(tmp_db)
    conn.execute("""CREATE TABLE inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL COLLATE NOCASE,
        quantity REAL NOT NULL,
        unit TEXT NOT NULL DEFAULT 'ct' COLLATE NOCASE,
        category TEXT NOT NULL DEFAULT 'other',
        location TEXT NOT NULL DEFAULT 'pantry' COLLATE NOCASE,
        purchased TEXT,
        source TEXT NOT NULL DEFAULT 'manual',
        notes TEXT NOT NULL DEFAULT '',
        for_recipe TEXT,
        expires TEXT,
        UNIQUE(name, unit, location))""")
    conn.executemany(
        "INSERT INTO inventory (name, quantity, category, location)"
        " VALUES (?, ?, ?, ?)",
        [("bananas", 1, "produce", "counter"),
         ("whole milk", 1, "dairy", "fridge"),
         ("psyllium husk", 1, "other", "pantry")],
    )
    conn.commit()
    conn.close()

    conn = inventory_db.connect()
    try:
        got = {r["name"]: r["location_source"]
               for r in conn.execute("SELECT name, location_source FROM inventory")}
    finally:
        conn.close()

    assert got == {
        "bananas": "item",          # by_item override
        "whole milk": "category",   # dairy -> fridge
        "psyllium husk": "default", # catch-all category, so not an answer
    }


def test_backfill_never_re_derives_a_hand_placed_row(tmp_db):
    """Re-running the migration must not overwrite a confirmed placement."""
    conn = inventory_db.connect()
    conn.execute(
        "INSERT INTO inventory (name, quantity, category, location, location_source)"
        " VALUES ('bananas', 1, 'produce', 'freezer', 'manual')"
    )
    conn.commit()
    conn.close()

    inventory_db.connect().close()   # migration runs again

    conn = inventory_db.connect()
    try:
        row = conn.execute(
            "SELECT location_source FROM inventory WHERE name = 'bananas'"
        ).fetchone()
    finally:
        conn.close()
    assert row["location_source"] == "manual"
```

Append to `tests/test_inventory.py`:

```python
def test_location_source_round_trips_through_the_db(tmp_db, tmp_vault):
    inventory.write_inventory([
        inventory.InventoryItem(name="kale", quantity=1, category="produce",
                                location="fridge", location_source="manual"),
    ])
    [got] = inventory.read_inventory()
    assert got.location_source == "manual"


def test_a_missing_location_source_reads_as_default(tmp_db, tmp_vault):
    """A NULL must surface for review, never pose as confirmed."""
    from lib import inventory_db

    conn = inventory_db.connect()
    conn.execute(
        "INSERT INTO inventory (name, quantity, category, location)"
        " VALUES ('mystery', 1, 'produce', 'fridge')"
    )
    conn.commit()
    conn.close()

    [got] = inventory.read_inventory()
    assert got.location_source == "default"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inventory_db.py tests/test_inventory.py -v -k "location_source or backfill"`

Expected: FAIL — `sqlite3.OperationalError: no such column: location_source` on the DB tests, and `TypeError: InventoryItem.__init__() got an unexpected keyword argument 'location_source'` on the inventory tests.

- [ ] **Step 3: Write the implementation**

In `lib/inventory.py`, add the vocabulary after `SOURCES` (`lib/inventory.py:27`):

```python
# How a row's `location` was decided. Ordered weakest-last; see _SOURCE_RANK.
LOCATION_SOURCES = ("manual", "item", "category", "default")
```

Add the normalizer after `normalize_source` (`lib/inventory.py:75-79`):

```python
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
```

Add the field to `InventoryItem`, **after `use_count`** — `consume-on-cook` added two
fields between `expires` and `merge_key`, so anchor on `use_count`:

```python
    last_used: Optional[str] = None
    use_count: int = 0
    # How `location` was decided. Provenance, deliberately not part of merge_key().
    location_source: str = "default"

    def merge_key(self) -> tuple[str, str, str]:
```

In `read_inventory`, add the field to the constructed item after `use_count`:

```python
            last_used=r["last_used"] or None,
            use_count=int(r["use_count"] or 0),
            location_source=normalize_location_source(r["location_source"]),
        )
```

In `lib/inventory_db.py`, add the column to `_SCHEMA`'s `inventory` table, after `expires TEXT,` (`lib/inventory_db.py:62`):

```sql
    expires TEXT,
    location_source TEXT,
    UNIQUE(name, unit, location)
```

Add it to `_INVENTORY_COLS` — note the tuple now carries `last_used`/`use_count`:

```python
_INVENTORY_COLS = (
    "name", "quantity", "unit", "category",
    "location", "purchased", "source", "notes", "for_recipe", "expires",
    "last_used", "use_count",
    "location_source",
)
```

Add it to `_MIGRATIONS`, whose `inventory` tuple now has four entries and a comment:

```python
_MIGRATIONS = {
    "inventory": (
        ("for_recipe", "TEXT"), ("expires", "TEXT"),
        # Set when a cook uses a row it cannot safely decrement (a container).
        ("last_used", "TEXT"), ("use_count", "INTEGER NOT NULL DEFAULT 0"),
        ("location_source", "TEXT"),
    ),
    "purchases": (("for_recipe", "TEXT"),),
    "cooks": (("make_again", "INTEGER"), ("cook_note", "TEXT")),
}
```

**`location_source` stays nullable on purpose.** `_NOT_NULL_FALLBACKS` in
`lib/inventory_db.py` exists because `replace_inventory_rows` names every column in its
INSERT, so an omitted key binds an explicit NULL and violates a NOT NULL constraint even
with a DEFAULT. Declaring `location_source TEXT` (no NOT NULL) keeps it out of that
problem entirely — `normalize_location_source` already reads NULL as `"default"`, which
is the fail-toward-being-asked direction this design wants.

Replace `_migrate` (`lib/inventory_db.py:173-183`) with:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from a pre-existing DB (idempotent)."""
    added: list[tuple[str, str]] = []
    for table, columns in _MIGRATIONS.items():
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for col, decl in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                added.append((table, col))
    # Classify pre-existing rows exactly once, at the moment the column appears.
    # Doing it on every connect would re-scan the table for nothing; doing it
    # never would leave every legacy row NULL.
    if ("inventory", "location_source") in added:
        _backfill_location_source(conn)
    conn.commit()


def _backfill_location_source(conn: sqlite3.Connection) -> None:
    """Derive provenance for rows that predate the column.

    Only touches NULLs, so it never re-derives a placement the user has since
    confirmed by hand. Imported lazily: ``storage_locations`` imports
    ``lib.inventory``, which would be a cycle at module scope.
    """
    from lib.storage_locations import place_item

    rows = conn.execute(
        "SELECT id, name, category FROM inventory WHERE location_source IS NULL"
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE inventory SET location_source = ? WHERE id = ?",
            (place_item(r["name"], r["category"]).source, r["id"]),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inventory_db.py tests/test_inventory.py -v`
Expected: all pass, including the four new tests.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2725 passed` (2721 + 4).

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py lib/inventory_db.py tests/test_inventory.py tests/test_inventory_db.py
git commit -m "$(cat <<'EOF'
feat: record how each inventory row's location was decided

Adds inventory.location_source (manual | item | category | default)
through the existing append-only ADD COLUMN mechanism, and backfills
pre-existing rows once, at the moment the column appears, by running
place_item over each name and category.

merge_key() is deliberately untouched: provenance is an attribute of a
row, not part of its address. A NULL or unrecognised value normalizes to
"default" so anything that escapes the backfill surfaces for review
rather than posing as confirmed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 3: Record provenance at row creation, and merge it correctly

**Files:**
- Modify: `lib/inventory.py` (`_SOURCE_RANK`, `_stronger_source`, `add_items` merge branch, `seed_pantry_staples`)
- Modify: `lib/receipt_ingest.py:98-110`, `ingest_csa.py:86-97`, `lib/receipt_paster.py:85-105`, `api_server.py:2049,2080-2094`
- Test: `tests/test_inventory.py`, `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: `Placement`/`place_item` (Task 1), `InventoryItem.location_source` (Task 2)
- Produces: `lib.inventory._stronger_source(a: str, b: str) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inventory.py`:

```python
def test_merge_keeps_the_stronger_source(tmp_db, tmp_vault):
    """Restocking a hand-placed row must not downgrade it back to a guess."""
    inventory.write_inventory([
        inventory.InventoryItem(name="oat milk", quantity=1, unit="ct",
                                category="dairy", location="fridge",
                                location_source="manual"),
    ])
    inventory.add_items([
        inventory.InventoryItem(name="oat milk", quantity=2, unit="ct",
                                category="dairy", location="fridge",
                                location_source="category"),
    ])
    [got] = inventory.read_inventory()
    assert got.quantity == 3
    assert got.location_source == "manual"


def test_merge_upgrades_a_weaker_source(tmp_db, tmp_vault):
    inventory.write_inventory([
        inventory.InventoryItem(name="oat milk", quantity=1, unit="ct",
                                category="dairy", location="fridge",
                                location_source="default"),
    ])
    inventory.add_items([
        inventory.InventoryItem(name="oat milk", quantity=1, unit="ct",
                                category="dairy", location="fridge",
                                location_source="item"),
    ])
    [got] = inventory.read_inventory()
    assert got.location_source == "item"


def test_seeded_staples_are_not_flagged_for_review(tmp_db, tmp_vault):
    """pantry_staples.json is hand-authored, so its rows are curated, not guesses."""
    inventory.seed_pantry_staples({"olive oil"})
    [got] = inventory.read_inventory()
    assert got.name == "olive oil"
    assert got.location_source == "item"
```

Append to `tests/test_api_endpoints.py`:

```python
def test_add_records_the_resolved_placement(client, tmp_db, tmp_vault):
    """A resolved location carries its tier; an explicit one is the caller's call."""
    client.post('/api/inventory/add', json={'items': [
        {'name': 'PlacementTestMilk', 'quantity': 1, 'category': 'dairy'},
        {'name': 'PlacementTestHusk', 'quantity': 1, 'category': 'other'},
        {'name': 'PlacementTestPick', 'quantity': 1, 'category': 'dairy',
         'location': 'counter'},
    ], 'match_plan': False})

    rows = {i['name']: i for i in client.get('/api/inventory').get_json()}
    assert rows['PlacementTestMilk']['location_source'] == 'category'
    assert rows['PlacementTestHusk']['location_source'] == 'default'
    assert rows['PlacementTestPick']['location_source'] == 'manual'
    assert rows['PlacementTestPick']['location'] == 'counter'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inventory.py tests/test_api_endpoints.py -v -k "stronger_source or weaker_source or seeded_staples or resolved_placement"`

Expected: FAIL — the merge tests report `location_source == 'category'` where `'manual'` was expected; the staples test reports `'default'`; the API test reports `'default'` for all three rows.

- [ ] **Step 3: Write the implementation**

In `lib/inventory.py`, add above `add_items` (before the `TODO(receipt-ingestion plan...)` comment at `lib/inventory.py:369`):

```python
# Strongest wins when two rows merge. A hand-placed row must never be
# downgraded to a guess by a restock that happened to resolve weakly.
_SOURCE_RANK = {"manual": 3, "item": 2, "category": 1, "default": 0}


def _stronger_source(a: Optional[str], b: Optional[str]) -> str:
    """The more trustworthy of two provenances."""
    a, b = normalize_location_source(a), normalize_location_source(b)
    return a if _SOURCE_RANK[a] >= _SOURCE_RANK[b] else b
```

In `add_items`'s merge branch, after the `cur.category` line (`lib/inventory.py:396-397`):

```python
            if new.category != "other":
                cur.category = new.category
            cur.location_source = _stronger_source(
                cur.location_source, new.location_source
            )
```

In `seed_pantry_staples` (`lib/inventory.py:334-339`), add the field to the constructed item:

```python
            InventoryItem(name=name, quantity=1, unit="ct", category="pantry",
                          location="pantry", source="staple",
                          location_source="item",
                          notes="always on hand")
```

In `lib/receipt_ingest.py`, change the import at line 28:

```python
from lib.storage_locations import place_item
```

and replace the `stock = [...]` comprehension (`lib/receipt_ingest.py:98-110`) with a loop, because each row now needs two values from one call:

```python
    stock = []
    for p in purchases:
        if p["category"] == "fee":
            continue
        placement = place_item(p["canonical_name"], p["category"])
        stock.append(InventoryItem(
            name=p["canonical_name"],
            quantity=float(p["quantity"] or 1),
            unit=p["unit"],
            category=p["category"],
            location=placement.location,
            location_source=placement.source,
            purchased=date,
            source="receipt",
            for_recipe=p.get("for_recipe"),
        ))
```

In `ingest_csa.py`, change the import at line 32:

```python
from lib.storage_locations import place_item  # noqa: E402
```

and replace the `items = [...]` comprehension (`ingest_csa.py:86-97`) with:

```python
    items = []
    for name in parsed["items"]:
        placement = place_item(name, category)
        items.append(InventoryItem(
            name=name,
            quantity=1,
            unit="ct",
            category=category,
            location=placement.location,
            location_source=placement.source,
            purchased=purchased,
            source="csa",
            notes=f"CSA Week {parsed['week']}" if parsed["week"] else "CSA share",
        ))
```

In `lib/receipt_paster.py`, change the import at line 22:

```python
from lib.storage_locations import place_item
```

and replace the location block (`lib/receipt_paster.py:85-89`) with:

```python
        # An explicit location in the pasted row is the caller's stated choice,
        # not a guess, so it records as manual.
        if row.get("location"):
            location = normalize_location(row["location"])
            location_source = "manual"
        else:
            placement = place_item(name, category)
            location, location_source = placement.location, placement.source
```

and add the field to the `InventoryItem(...)` a few lines below (`lib/receipt_paster.py:99`):

```python
                location=location,
                location_source=location_source,
```

In `api_server.py`, change the import at line 2049:

```python
    from lib.storage_locations import place_item
```

and replace the location block (`api_server.py:2079-2082`) with:

```python
        # Explicit location wins; otherwise resolve from the storage table.
        # An explicit one is the caller's stated choice, so it records as manual.
        if raw.get('location'):
            location = normalize_location(raw['location'])
            location_source = 'manual'
        else:
            placement = place_item(name, category)
            location, location_source = placement.location, placement.source
```

and add the field to the `InventoryItem(...)` below (`api_server.py:2088`):

```python
            location=location,
            location_source=location_source,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inventory.py tests/test_api_endpoints.py tests/test_receipt_paster.py -v`
Expected: all pass.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2729 passed` (2725 + 4).

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py lib/receipt_ingest.py lib/receipt_paster.py ingest_csa.py api_server.py tests/test_inventory.py tests/test_api_endpoints.py
git commit -m "$(cat <<'EOF'
feat: capture placement provenance wherever inventory rows are created

The five row-creating paths — receipt ingest, CSA ingest, receipt paste,
/api/inventory/add, and staple seeding — now record which tier decided
the location. An explicit location in a request body is the caller's
stated choice, so it records as manual; hand-authored pantry staples
record as curated rather than pushing several dozen deliberately-listed
rows into the review queue.

When a purchase merges into an existing row the stronger provenance
wins (manual > item > category > default), so restocking something you
hand-placed never downgrades it back to a guess.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 4: Moves confirm the row and teach the table

**Files:**
- Modify: `lib/inventory.py` (`_teach_location`, `_apply_move`, `move_item`, `bulk_apply`)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `lib.storage_locations.save_item_override(name: str, location: str) -> None` (already exists at `lib/storage_locations.py:90`, currently uncalled)
- Produces: `lib.inventory._teach_location(name: str, to_location: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inventory.py`. Add these imports at the top of the file if absent: `import json`, `from lib import storage_locations`.

```python
@pytest.fixture
def empty_storage_table(monkeypatch, tmp_path):
    """An isolated, empty storage-locations table. Yields its path."""
    table = tmp_path / "storage_locations.json"
    table.write_text(json.dumps({"by_item": {}, "by_category": {}}))
    monkeypatch.setattr(storage_locations, "TABLE_PATH", table)
    return table


def _taught(table):
    return json.loads(table.read_text())["by_item"]


def test_move_confirms_the_row_and_teaches_the_table(
    tmp_db, tmp_vault, empty_storage_table
):
    inventory.write_inventory([
        inventory.InventoryItem(name="oat milk", quantity=1, unit="ct",
                                category="dairy", location="pantry",
                                location_source="default"),
    ])
    moved = inventory.move_item("oat milk", "fridge")
    assert moved.location == "fridge"
    assert moved.location_source == "manual"
    assert _taught(empty_storage_table) == {"oat milk": "fridge"}


def test_freeze_confirms_the_row_but_teaches_nothing(
    tmp_db, tmp_vault, empty_storage_table
):
    """Freezing rescues one item from spoiling; it does not say where bread lives."""
    inventory.write_inventory([
        inventory.InventoryItem(name="sourdough loaf", quantity=1, unit="ct",
                                category="bakery", location="counter",
                                location_source="category"),
    ])
    frozen = inventory.freeze_item("sourdough loaf")
    assert frozen.location == "freezer"
    assert frozen.location_source == "manual"
    assert _taught(empty_storage_table) == {}


def test_bulk_move_teaches_every_item(tmp_db, tmp_vault, empty_storage_table):
    inventory.write_inventory([
        inventory.InventoryItem(name="peas", quantity=1, unit="ct",
                                category="produce", location="fridge"),
        inventory.InventoryItem(name="corn", quantity=1, unit="ct",
                                category="produce", location="fridge"),
    ])
    result = inventory.bulk_apply(
        "move",
        [{"name": "peas", "unit": "ct", "location": "fridge"},
         {"name": "corn", "unit": "ct", "location": "fridge"}],
        to_location="freezer",
    )
    assert result["applied"] == 2
    assert all(it.location_source == "manual" for it in result["items"])
    assert _taught(empty_storage_table) == {"peas": "freezer", "corn": "freezer"}


def test_a_failed_override_write_still_commits_the_move(
    tmp_db, tmp_vault, empty_storage_table, monkeypatch
):
    """The row is the user's intent; the lesson is a side effect."""
    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(storage_locations, "save_item_override", boom)
    inventory.write_inventory([
        inventory.InventoryItem(name="oat milk", quantity=1, unit="ct",
                                category="dairy", location="pantry"),
    ])
    moved = inventory.move_item("oat milk", "fridge")
    assert moved.location == "fridge"
    assert moved.location_source == "manual"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inventory.py -v -k "teaches or confirms or failed_override"`

Expected: FAIL — `assert 'default' == 'manual'` on the move test (the row isn't stamped), and `assert {} == {'oat milk': 'fridge'}` (nothing is taught).

- [ ] **Step 3: Write the implementation**

In `lib/inventory.py`, add above `_apply_move` (`lib/inventory.py:585`):

```python
def _teach_location(name: str, to_location: str) -> None:
    """Remember a hand-correction so future purchases of this item file right.

    Never lets a config-write failure sink the move: the row is already
    committed and the lesson is a side effect. ``save_item_override`` writes
    tmp+replace, so a failure leaves the previous table intact.
    """
    from lib.storage_locations import save_item_override

    try:
        save_item_override(name, to_location)
    except OSError as e:
        print(f"⚠️  Couldn't record storage override for {name}: {e}",
              file=sys.stderr)
```

At the end of `_apply_move`, stamp the surviving rows. Replace the dedup block (`lib/inventory.py:622-628`) with:

```python
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
```

In `move_item` (`lib/inventory.py:787-807`), teach after the write:

```python
    result = _apply_move(items, matches, to_location)
    write_inventory(items)
    # After the write: a config failure must not precede a failed DB write.
    _teach_location(name, to_location)
    return result[0]
```

In `bulk_apply`, capture the names before the move mutates the list. Replace the `move` branch (`lib/inventory.py:740-741`):

```python
        elif action == "move":
            # Captured before the move: a colliding row is dropped from `items`,
            # so reading names off the result would miss the merged-away source.
            moved_names = [m.name for m in matches]
            updated = _apply_move(items, matches, to_location)
```

and after `write_inventory(items)` (`lib/inventory.py:745`), before the return:

```python
        write_inventory(items)

        if action == "move":
            for moved_name in moved_names:
                _teach_location(moved_name, to_location)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inventory.py -v`
Expected: all pass, including the four new tests.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2733 passed` (2729 + 4).

Confirm nothing wrote to the real config: `git status --short config/storage_locations.json`
Expected: no output. The tests monkeypatch `TABLE_PATH` to a tmp file; output here means a test escaped its fixture.

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "$(cat <<'EOF'
feat: a move confirms the row and teaches the storage table

Moving an item stamps location_source=manual and writes a by_item
override, so the next receipt files it correctly and the unsure list
shrinks permanently. This is the first caller of save_item_override,
which shipped tested but unused.

Freezing stamps the row but deliberately teaches nothing: it clears the
expiry, which marks it as rescuing one item from spoiling rather than
declaring where that food lives. Teaching there would file bread in the
freezer the first time you saved a loaf.

Teaching runs after the DB write and swallows OSError — the row is the
user's intent, the lesson is a side effect.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 5: Show the location — and the last-used stamp — on every `/review` row

**Files:**
- Modify: `templates/review.html` (new `LOC_EMOJI` map, new `locationLabel`, new `usedLabel`, rewritten `subline`, CSS)
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: `location_source`, `last_used` and `use_count` on each `/api/inventory` row (`location_source` from Task 2, the other two already shipped with `consume-on-cook`; all reach the client automatically via `asdict`)
- Produces: JS `LOC_EMOJI` object, `locationLabel(it) -> string` (HTML) used by Task 6's group headers, and `usedLabel(it) -> string`

**Scope note (added at the 2026-07-27 rebase).** `consume-on-cook` shipped `last_used` /
`use_count` but nothing reads them — 453 of the ingredient lines that now touch inventory
leave no user-visible trace beyond a transient toast. This task already rewrites
`subline()`, which is where they belong, so it surfaces them here rather than rewriting the
same function again later. A row's subline then answers both questions you actually have
when putting groceries away: *where does this go* and *did I just cook with it*.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_review_page_shows_storage_location(client):
    """The location, its glyphs, and the unsure marker ship in the page."""
    html = client.get('/review').data
    assert b'LOC_EMOJI' in html
    assert b'locationLabel' in html
    assert b'location_source' in html
    # The freezer glyph must not be the category emoji for `frozen`.
    assert '🥶'.encode() in html


def test_review_page_shows_the_last_used_stamp(client):
    """consume-on-cook writes last_used/use_count; this is the only view that
    reads them. Without this the columns are write-only."""
    html = client.get('/review').data
    assert b'usedLabel' in html
    assert b'last_used' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_endpoints.py::test_review_page_shows_storage_location -v`
Expected: FAIL with `assert b'LOC_EMOJI' in html`.

- [ ] **Step 3: Write the implementation**

In `templates/review.html`, add after the `LOCATIONS` const (`templates/review.html:99`):

```javascript
// Location glyphs, deliberately disjoint from the category EMOJI map above —
// `frozen` already owns 🧊, and a frozen item in the freezer must not render
// the same glyph twice.
const LOC_EMOJI = { fridge:"❄️", freezer:"🥶", pantry:"🫙", counter:"🧺", other:"📍" };
```

Add before `subline` (`templates/review.html:157`):

```javascript
function isUnsure(it){
  // A missing source reads as unsure: fail toward being asked, never toward
  // posing as confirmed.
  return (it.location_source || "default") === "default";
}
function locationLabel(it){
  const loc = it.location || "other";
  const unsure = isUnsure(it);
  const hint = unsure
    ? ' title="Nothing matched — this location is a guess"' : '';
  return `<span class="loc"${hint}>${LOC_EMOJI[loc] || "📍"} ${loc}`
       + `${unsure ? "?" : ""}</span>`;
}
function usedLabel(it){
  // consume-on-cook stamps a row it used but could not safely decrement (a
  // package). Surfacing it is what makes "marked cooked" visible at all for the
  // ~95% of rows that are containers — otherwise the write is invisible.
  if (!it.last_used) return "";
  const days = Math.floor((Date.now() - Date.parse(it.last_used)) / 86400000);
  const when = !Number.isFinite(days) ? "recently"
             : days <= 0 ? "today"
             : days === 1 ? "yesterday"
             : `${days}d ago`;
  const n = it.use_count || 0;
  // The count is a tooltip, not inline: on a shelf you want "did I use this",
  // and the tally only matters when you're wondering why a jar is empty.
  const tally = n > 1 ? ` title="used ${n} times"` : '';
  return `<span class="used"${tally}>· used ${when}</span>`;
}
```

Replace `subline` (`templates/review.html:157-163`) with:

```javascript
function subline(it){
  const exp = it.expires ? "exp " + it.expires : "no expiry";
  // Show the date being sorted on, otherwise the "Added" order looks arbitrary.
  const add = sortMode === "added"
    ? " · added " + (it.purchased || "unknown") : "";
  const used = usedLabel(it);
  return locationLabel(it) + " · " + exp + add
       + (used ? " " + used : "") + badge(it);
}
```

Add to the `<style>` block, before its closing `</style>` (`templates/review.html:68`):

```css
  .loc { white-space: nowrap; }
  .loc[title] { border-bottom: 1px dotted currentColor; }
  .used { white-space: nowrap; opacity: .75; }
  .used[title] { border-bottom: 1px dotted currentColor; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_api_endpoints.py -v -k review`
Expected: 4 passed.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2735 passed` (2733 + 2 — location markup and the last-used stamp).

- [ ] **Step 5: Commit**

```bash
git add templates/review.html tests/test_api_endpoints.py
git commit -m "$(cat <<'EOF'
feat: show each item's storage location on the review page

The location leads every row's subline, so the page you use to put
groceries away can finally tell you where something is filed. A row
whose location nothing actually resolved takes a "?" and a tooltip
explaining why.

Location glyphs are deliberately disjoint from the category emoji map —
`frozen` already owns 🧊, so the freezer uses 🥶 rather than rendering
the same glyph twice on a frozen item in the freezer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 6: Location sort mode, group headers, and move re-homing

**Files:**
- Modify: `templates/review.html` (`<option>`, `SORTS.location`, `placeRows`, `groupHeader`, `load`, `resort`, `rowTarget.run`, CSS)
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: `LOC_EMOJI`, `isUnsure(it)`, `locationLabel(it)` (Task 5); existing `SORTS`, `keyOf`, `rows`, `flash`, `load`
- Produces: `placeRows(sorted)` — the single row/header placement path used by both `load()` and `resort()`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_endpoints.py`:

```python
def test_review_page_has_a_location_sort_mode(client):
    """Location ordering and its group headers ship in the page."""
    html = client.get('/review').data
    assert b'value="location"' in html
    assert b'groupHeader' in html
    assert b'placeRows' in html
    assert b'li.group' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_endpoints.py::test_review_page_has_a_location_sort_mode -v`
Expected: FAIL with `assert b'value="location"' in html`.

- [ ] **Step 3: Write the implementation**

In `templates/review.html`, add the option to the sort select (after `templates/review.html:76`):

```html
    <option value="added">Added</option>
    <option value="location">Location</option>
```

Add to the `SORTS` object, after the `added` comparator (`templates/review.html:145`):

```javascript
  location(a, b){
    // Vocab order, so the blocks always appear fridge → freezer → pantry →
    // counter → other rather than alphabetically or by whatever arrived first.
    const dl = (LOC_ORDER[a.location] ?? 99) - (LOC_ORDER[b.location] ?? 99);
    if (dl) return dl;
    // Unsure first: the point of this order is to open each block on the rows
    // that actually want a decision.
    const du = (isUnsure(a) ? 0 : 1) - (isUnsure(b) ? 0 : 1);
    if (du) return du;
    return SORTS.expiry(a, b);
  },
```

Add above the `SORTS` declaration (`templates/review.html:129`):

```javascript
const LOC_ORDER = {};
LOCATIONS.forEach((l, i) => { LOC_ORDER[l] = i; });
```

Add after `sortItems` (`templates/review.html:151`):

```javascript
function groupHeader(loc, sorted){
  const li = document.createElement('li');
  li.className = 'group';
  const inBlock = sorted.filter(i => i.location === loc);
  const unsure = inBlock.filter(isUnsure).length;
  li.textContent = `${LOC_EMOJI[loc] || "📍"} ${loc} — ${inBlock.length}`
    + (unsure ? ` · ${unsure} unsure` : "");
  return li;
}
function placeRows(sorted){
  // The single placement path, shared by load() and resort(), so headers can
  // never drift out of sync with the rows they label. Headers are rebuilt from
  // scratch each time: a move changes a row's block, and its counts too.
  for (const h of [...list.querySelectorAll('li.group')]) h.remove();
  let current = null;
  for (const it of sorted){
    if (sortMode === "location" && it.location !== current){
      current = it.location;
      list.appendChild(groupHeader(current, sorted));
    }
    const entry = rows.get(keyOf(it));
    if (entry) list.appendChild(entry.li);
  }
}
```

Replace the body of `load()` (`templates/review.html:164-182`) with:

```javascript
async function load(){
  list.innerHTML = "";
  rows.clear();
  let items;
  try { items = await (await fetch('/api/inventory')).json(); }
  catch(e){ empty.hidden = false; empty.textContent = "Couldn't load inventory. Tap ↻ to retry."; return; }
  empty.hidden = items.length > 0;
  const live = new Set();
  const sorted = sortItems(items);
  for (const it of sorted){
    const key = keyOf(it);
    live.add(key);
    rows.set(key, { it, li: row(it, key) });
  }
  placeRows(sorted);
  // Drop selections whose rows no longer exist.
  for (const k of [...selected]) if (!live.has(k)) selected.delete(k);
  renderBulk();
}
```

Replace `resort()` (`templates/review.html:330-337`) with:

```javascript
function resort(){
  // Re-place rows after an edit moved one between groups — otherwise a row you
  // just rescued stays pinned in the expired block and the tap reads as having
  // done nothing. Moves the existing <li> nodes instead of re-fetching, so
  // checkbox selection and the scroll position survive.
  placeRows(sortItems([...rows.values()].map(e => e.it)));
}
```

Replace `rowTarget`'s `run` (`templates/review.html:352-355`) with:

```javascript
    async run(action, params, errLabel){
      const item = await post(SINGLE[action],
        { name: it.name, location: it.location, ...params }, li, errLabel);
      if (!item) return;
      if (action === 'move' || action === 'freeze'){
        // Location is part of the row key, so the row's identity just changed —
        // and in Location order so did its block. Patching in place would leave
        // the rows Map under the stale pre-move key, which is the bug the bulk
        // path already sidesteps by reloading. Take the same path, then flash
        // the row where it landed.
        await load();
        const entry = rows.get(keyOf(item));
        if (entry) flash(entry.li);
        return;
      }
      applyUpdate(it, li, item);
    }
```

Add to the `<style>` block, before its closing `</style>`:

```css
  li.group { display: block; padding: 10px 12px 4px; font-weight: 600;
             opacity: .7; font-size: .85em; text-transform: capitalize;
             border-bottom: none; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_api_endpoints.py -v -k review`
Expected: 5 passed.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2736 passed` (2735 + 1).

- [ ] **Step 5: Commit**

```bash
git add templates/review.html tests/test_api_endpoints.py
git commit -m "$(cat <<'EOF'
feat: group the review list by storage location

A third sort mode blocks rows under location headers carrying a count
and an unsure tally, so a whole zone can be scanned against the physical
shelf. Within a block, unresolved rows sort first — the 180-row pantry
block opens on the handful that want a decision rather than on canned
tomatoes.

load() and resort() now share one placement path, so headers can't drift
out of sync with the rows they label. Single-row moves take the same
full-reload path bulk moves already use: location is part of the row
key, so a move changes the row's identity, and patching in place left
the rows Map under the stale pre-move key.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 7: Mark unresolved locations in `Inventory.md`

**Files:**
- Modify: `lib/inventory.py` (`_location_cell`, `render_inventory_md`)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `InventoryItem.location_source` (Task 2)
- Produces: `lib.inventory._location_cell(location: str, source: Optional[str]) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inventory.py`:

```python
def test_inventory_md_marks_an_unresolved_location(tmp_db, tmp_vault):
    md = inventory.render_inventory_md([
        inventory.InventoryItem(name="psyllium husk", quantity=1,
                                category="other", location="pantry",
                                location_source="default"),
        inventory.InventoryItem(name="kale", quantity=1, category="produce",
                                location="fridge", location_source="category"),
    ])
    assert "| pantry? |" in md
    assert "| fridge |" in md
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_inventory.py::test_inventory_md_marks_an_unresolved_location -v`
Expected: FAIL with `assert '| pantry? |' in md` — the cell currently renders bare `pantry`.

- [ ] **Step 3: Write the implementation**

In `lib/inventory.py`, add beside `_expiry_cell` (after `lib/inventory.py:180`):

```python
def _location_cell(location: str, source: Optional[str]) -> str:
    """Location column text, marked '?' when nothing actually resolved it."""
    if normalize_location_source(source) == "default":
        return f"{location}?"
    return location
```

In `render_inventory_md`, change the location cell (`lib/inventory.py:214`):

```python
            _location_cell(it.location, it.location_source),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_inventory.py -v -k inventory_md`
Expected: passes.

Then the full suite: `.venv/bin/pytest -q`
Expected: `2737 passed` (2736 + 1).

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "$(cat <<'EOF'
docs: mark unresolved locations in the generated Inventory.md view

The Location column already existed; it now carries the same "?" the
review page shows when nothing actually resolved the placement, so the
two views agree about what is known.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 8: Browser coverage

**Files:**
- Create: `tests/e2e/test_location_visibility.py`

**Interfaces:**
- Consumes: the `live_server`, `page`, and `page_errors` fixtures from `tests/e2e/conftest.py`; the seeding helpers pattern from `tests/e2e/test_bulk_inventory.py`

Note: these tests need `requirements-e2e.txt` installed and a downloaded Chromium. They are deselected by default (`pytest.ini` sets `addopts = -m "not e2e"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/e2e/test_location_visibility.py`:

```python
"""End-to-end browser coverage for storage-location visibility on `/review`.

The unit suite only asserts the markup strings ship in the response body, which
a page with a dead handler would also pass. What can actually break here only
breaks in a browser: a group header counting rows it doesn't label, a moved row
staying pinned in its old block, a "?" rendering on a confirmed row.

Isolation: `live_server` serves copies of the vault and DB. The server is
session-scoped and therefore shared, so every test seeds uniquely named items
and asserts only about its own.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import requests

pytestmark = pytest.mark.e2e


def _item(name: str, **kw) -> dict:
    return {
        "name": name,
        "quantity": 1,
        "unit": "each",
        "category": "produce",
        "location": "fridge",
        "purchased": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=5)).isoformat(),
        **kw,
    }


def _seed(server, items: list[dict]) -> None:
    resp = requests.post(
        server.url("/api/inventory/add"),
        json={"items": items, "match_plan": False},
        timeout=30,
    )
    assert resp.status_code in (200, 201), resp.text


def _inventory(server) -> list[dict]:
    resp = requests.get(server.url("/api/inventory"), timeout=30)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _open_review(page, server, sort: str = "expiry") -> None:
    page.goto(server.url("/review"), wait_until="domcontentloaded")
    page.wait_for_selector("#list li", timeout=15_000)
    if sort != "expiry":
        page.select_option("#sortby", sort)
        page.wait_for_timeout(500)


def _row(page, name: str):
    return page.locator("#list li").filter(has=page.locator(".name", has_text=name))


def test_every_row_shows_where_it_is_stored(live_server, page, page_errors):
    """The location leads the subline, and only an unresolved one gets a '?'."""
    _seed(live_server, [
        # `dairy` resolves via a real category rule, so it is an answer.
        _item("E2E Loc Yogurt", category="dairy", location="fridge"),
        # No explicit location and the catch-all category: nothing resolved it.
        {"name": "E2E Loc Mystery", "quantity": 1, "unit": "each",
         "category": "other"},
    ])

    _open_review(page, live_server)

    sure = _row(page, "E2E Loc Yogurt").locator(".sub").inner_text()
    assert "fridge" in sure
    assert "fridge?" not in sure

    unsure = _row(page, "E2E Loc Mystery").locator(".sub").inner_text()
    assert "pantry?" in unsure
    assert page_errors == [], page_errors


def test_location_mode_groups_rows_under_accurate_headers(
    live_server, page, page_errors
):
    """A header's count must match the rows it actually labels."""
    _seed(live_server, [
        _item("E2E Grp Kale", location="fridge"),
        _item("E2E Grp Peas", location="freezer", category="frozen"),
    ])

    _open_review(page, live_server, sort="location")

    headers = page.locator("#list li.group")
    assert headers.count() > 0, "no group headers rendered in Location mode"

    # Every header's count equals the rows between it and the next header.
    items = page.locator("#list li")
    counts: dict[str, int] = {}
    current = None
    for i in range(items.count()):
        el = items.nth(i)
        if "group" in (el.get_attribute("class") or ""):
            current = el.inner_text()
            counts[current] = 0
        elif current is not None:
            counts[current] += 1

    for header, seen in counts.items():
        # Header text is "<glyph> <loc> — <N>" or "... — <N> · <M> unsure".
        stated = int(header.split("—")[1].split("·")[0].strip())
        assert stated == seen, f"{header!r} labels {seen} rows"
    assert page_errors == [], page_errors


def test_a_move_rehomes_the_row_into_its_new_block(live_server, page, page_errors):
    """The row must leave the fridge block and land under freezer."""
    name = "E2E Move Chard"
    _seed(live_server, [_item(name, location="fridge")])

    _open_review(page, live_server, sort="location")
    _row(page, name).locator(".kebab").click()
    page.wait_for_selector("#menu.show", timeout=5_000)
    page.locator("#menu .chips button", has_text="freezer").first.click()
    page.wait_for_timeout(2000)

    rows = [i for i in _inventory(live_server) if i["name"].lower() == name.lower()]
    assert len(rows) == 1, rows
    assert rows[0]["location"] == "freezer"
    # A move is the user asserting the placement.
    assert rows[0]["location_source"] == "manual"

    # And in the DOM it now sits under the freezer header, not the fridge one.
    items = page.locator("#list li")
    current = None
    found_under = None
    for i in range(items.count()):
        el = items.nth(i)
        if "group" in (el.get_attribute("class") or ""):
            current = el.inner_text()
        elif name in el.inner_text():
            found_under = current
    assert found_under and "freezer" in found_under, found_under
    assert page_errors == [], page_errors
```

- [ ] **Step 2: Install the e2e harness and run the tests**

```bash
.venv/bin/pip install -r requirements-e2e.txt
.venv/bin/playwright install chromium
.venv/bin/pytest tests/e2e/test_location_visibility.py -m e2e -v
```

Expected: 8 passed. Unlike the other tasks these are written *after* the behavior (Tasks 5-6 built it), so a green run proves nothing on its own — Step 3 falsifies them.

- [ ] **Step 3: Prove the tests actually fail without the feature**

Temporarily restore the pre-feature template — `fe7cfa1` is this branch's spec commit, made before any template edit — and confirm all three tests fail:

```bash
git checkout fe7cfa1 -- templates/review.html
.venv/bin/pytest tests/e2e/test_location_visibility.py -m e2e -v
```

Expected: 3 failed — no location in the subline, `no group headers rendered in Location mode`, and the moved row not found under a freezer header.

Restore the real template:

```bash
git checkout HEAD -- templates/review.html
git status --short templates/review.html
```

Expected: no output from `git status` — the template is back to the committed version. **Do not proceed until this is clean**, or Step 4 will pass against the wrong file.

- [ ] **Step 4: Run the tests once more to confirm they pass**

Run: `.venv/bin/pytest tests/e2e/test_location_visibility.py -m e2e -v`
Expected: 8 passed.

Then confirm the default suite is unchanged: `.venv/bin/pytest -q`
Expected: `2737 passed` — e2e tests stay deselected, so this task adds none to the default run.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_location_visibility.py
git commit -m "$(cat <<'EOF'
test: drive storage-location visibility in a browser

Covers what only breaks in a browser: a group header counting rows it
doesn't label, a moved row staying pinned in its old block, and a "?"
rendering on a row that actually resolved.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

### Task 9: Documentation, restart, and manual verification

**Files:**
- Modify: `docs/API.md` (the `/api/inventory` payload gains a field)
- Modify: `docs/ARCHITECTURE.md` (the placement router)
- Modify: `CLAUDE.md` (new invariant)

**Interfaces:**
- Consumes: everything above. Produces no code.

- [ ] **Step 1: Document the field and the router**

In `docs/API.md`, find the `/api/inventory` response documentation and add `location_source` to the row shape, described as:

```
`location_source` — how the row's `location` was decided: `manual` (the user
placed it), `item` (a hand-curated `by_item` override matched), `category` (a
`by_category` rule matched a real category), or `default` (nothing matched).
Absent/NULL reads as `default`. Only `default` is rendered as unsure.
```

In `docs/ARCHITECTURE.md`, find the section covering inventory/receipt ingest and add a line noting that `lib/storage_locations.place_item()` is the single router deciding an item's storage location and its provenance, and that `resolve_location()` is a thin wrapper over it.

In `CLAUDE.md`, **append to the end of** the Invariants list. (The plan originally said
"after the `dish_type` entry"; `consume-on-cook` added two invariants after that one, so
appending is now what keeps related entries together.)

```markdown
- **`location_source` is provenance, not address.** `InventoryItem.merge_key()` is
  `(name, unit, location)`; adding `location_source` to it would fragment a row into one
  copy per provenance. A NULL or unrecognised value normalizes to `default`, which renders
  as unsure — the failure direction is always toward being asked again, never toward posing
  as confirmed. Note that `by_category` covers all ten values of `CATEGORIES`, so the bare
  `pantry` fallback in `resolve_location` is unreachable; `place_item` reports a hit on the
  catch-all `other` category as `default`, and that is the only thing making the tier
  reachable. Don't "simplify" that back into a plain category hit.
```

- [ ] **Step 2: Restart the API and regenerate the view**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 3 && curl -s http://localhost:5001/health
```

Expected: a healthy JSON response. Without this the server serves the pre-branch template and every manual check below is meaningless.

Confirm the migration ran against the real DB and classified the expected rows:

```bash
.venv/bin/python -c "
import sqlite3
from lib import inventory_db
inventory_db.connect().close()   # applies the migration
c = sqlite3.connect('data/kitchenos.db')
print(dict(c.execute('select location_source, count(*) from inventory group by location_source')))
"
```

Expected: `{'item': 16, 'category': 199, 'default': 7}` — 222 rows total. The 7 `default` rows are the ones whose category is the catch-all: dog food, dog treats, wet dog food, fiber capsules, magnesium citrate, psyllium husk, and yellow corn tortilla chips.

- [ ] **Step 3: Verify from a phone on the tailnet**

Resolve this machine's address — do not hardcode one:

```bash
tailscale ip -4
```

Open `http://<that-ip>:5001/review` and check:

1. Every row's subline leads with a location and glyph.
2. Exactly the 7 rows above show `pantry?`; nothing else shows a `?`.
3. Switching the sort to **Location** blocks the rows under headers, ordered fridge → freezer → pantry → counter → other.
4. Each header's count matches the rows beneath it; the pantry header reads `🫙 pantry — 180 · 7 unsure`.
5. The pantry block opens on the 7 unsure rows.
6. Moving one of them (⋮ → Move to → `other`) re-homes the row under the `other` header and drops its `?`.
7. `git diff config/storage_locations.json` shows a new `by_item` entry for the item you just moved.

- [ ] **Step 4: Confirm teaching closed the loop**

Re-resolve the item you moved and confirm the table now answers for it:

```bash
.venv/bin/python -c "
from lib.storage_locations import place_item
p = place_item('dog treats')   # or whichever item you moved
print(p)
"
```

Expected: `Placement(location='other', source='item')` — the tier is now `item`, not `default`, so the next receipt files it correctly on the first pass.

- [ ] **Step 5: Commit**

```bash
git add docs/API.md docs/ARCHITECTURE.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: document location provenance and its invariant

Records the location_source field in the API payload, place_item as the
single placement router in the architecture map, and the invariant that
provenance is an attribute of a row rather than part of its address.

Also records why the catch-all category must report `default`: because
by_category covers all ten categories, the bare pantry fallback is
unreachable, so that rule is the only thing making the tier reachable at
all. It reads like a special case and would be easy to "simplify" away.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Bz5G5n1sBxwRa6EvokLzCM
EOF
)"
```

---

## Verification checklist

Before calling this branch done:

- [ ] `.venv/bin/pytest -q` reports `2737 passed` (baseline was 2715; this plan adds 22).
- [ ] `.venv/bin/pytest tests/e2e/test_location_visibility.py -m e2e -v` reports 3 passed.
- [ ] `git status --short config/storage_locations.json` is empty except for entries you taught deliberately during manual verification.
- [ ] The API LaunchAgent has been restarted and `/health` responds.
- [ ] `/review` renders locations, groups by location, and re-homes a moved row — checked in a real browser, not just asserted in markup.
