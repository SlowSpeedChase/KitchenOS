# KitchenOS Security and Data-Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the privileged Claude web bridge, contain all request-derived Markdown paths, and make inventory plus receipt persistence atomic under retries and concurrent writers.

**Architecture:** Flask pages retain the existing stale-code banner but stop registering or rendering the Claude bridge. A focused path-validation module owns canonical Markdown and ISO-week checks. SQLite owns additive merges and receipt idempotency inside `BEGIN IMMEDIATE` transactions; whole-inventory mutations use one connection from read through replace, and derived Markdown views refresh only after commit.

**Tech Stack:** Python 3, Flask, SQLite WAL, pytest, existing KitchenOS inventory/receipt modules.

**Spec:** `docs/superpowers/specs/2026-08-23-security-data-integrity-design.md`

## Global Constraints

- The Claude bridge is structurally disabled: no feature flag, no registered send/notes routes, and no injected UI.
- `lib/claude_send.py` and `lib/claude_notes.py` remain as dormant, unit-tested modules.
- Flask request values are already URL-decoded once; path validation must not call `unquote` again.
- Inventory identity remains case-insensitive `(name, unit, location)`.
- Existing merge rules remain: quantities sum, explicit purchase date wins, non-`other` category wins, existing notes are preserved, strongest location source wins, recipe names union in order, and earliest expiry wins.
- Duplicate `source_id` is a successful no-op; every other SQLite integrity error rolls back and propagates.
- Database state commits before derived `Inventory.md`/Cook Now view refresh; a derived-view failure never causes a client retry to duplicate data.
- Tests use temporary vaults and databases only; never write the production vault or database.
- Do not copy or commit the dirty main checkout's retry-cap/dead-letter changes.
- Do not alter Apple/search/auth behavior owned by `ios27-new-siri`; review shared `api_server.py` hunks at rebase.

---

### Task 1: Hard-disable the Claude web bridge

**Files:**
- Rename: `tests/test_claude_bar.py` → `tests/test_page_chrome.py`
- Modify: `tests/test_page_chrome.py`
- Modify: `tests/test_api_endpoints.py`
- Modify: `tests/test_claude_send.py`
- Modify: `api_server.py:157-230,307-313,828-3860,3301-3362`

**Interfaces:**
- Consumes: existing `_inject_after_body(html: str, snippet: str) -> str` and `_stale_banner_html() -> str`.
- Produces: `_serve_page(template_filename: str, extra_replacements: list[tuple[str, str]] | None = None) -> str`; `/api/claude-send` and `/api/claude-notes` are absent.

- [ ] **Step 1: Replace route/widget expectations with failing shutdown tests**

Keep the `_inject_after_body` and stale-banner tests in the renamed file, delete assertions for `_claude_bar_html`, and add:

```python
PAGES = ['/', '/review', '/system-health', '/nutrition-review',
         '/meal-planner', '/receipt-paste']

@pytest.mark.parametrize('path', PAGES)
def test_page_has_no_claude_bridge(client, path):
    response = client.get(path)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="ko-claude-bar"' not in body
    assert '/api/claude-send' not in body
    assert '/api/claude-notes' not in body

@pytest.mark.parametrize("method,path", [
    ("get", "/api/claude-notes"),
    ("post", "/api/claude-notes"),
    ("post", "/api/claude-send"),
])
def test_claude_bridge_routes_are_absent(client, method, path):
    response = getattr(client, method)(path, json={"notes": "x", "text": "x"})
    assert response.status_code == 404
```

Replace `TestSendRoute` in `tests/test_claude_send.py` with a test that monkeypatches `claude_send.send_text`, posts to the absent route, and asserts the mock was not called. Replace the notes endpoint tests in `tests/test_api_endpoints.py` with a sentinel `Claude Notes.md`, GET/POST 404 assertions, and a byte-for-byte unchanged sentinel assertion.

- [ ] **Step 2: Run shutdown tests and verify RED**

Run:

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_page_chrome.py tests/test_api_endpoints.py tests/test_claude_send.py -q
```

Expected: failures show pages still contain `ko-claude-bar` and the three routes still return 200/400 rather than 404.

- [ ] **Step 3: Remove bridge wiring while preserving stale-page chrome**

In `api_server.py`:

1. Delete `_CLAUDE_BAR_TEMPLATE` and `_claude_bar_html`.
2. Keep `_inject_after_body` because the stale-code banner still needs global injection.
3. Replace `_serve_page_with_claude_bar` with:

```python
def _serve_page(template_filename: str, extra_replacements=None) -> str:
    """Read a template, apply replacements, and inject global safety chrome."""
    html = open(f"templates/{template_filename}").read()
    for old, new in (extra_replacements or []):
        html = html.replace(old, new)
    return _inject_after_body(html, _stale_banner_html())
```

4. Replace every `_serve_page_with_claude_bar(` call with `_serve_page(` and update `_stale_banner_html`'s docstring to name `_serve_page`.
5. Delete all three Claude route functions/decorators at `/api/claude-notes` and `/api/claude-send`; do not delete the two `lib/` modules.

- [ ] **Step 4: Run shutdown tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit the disabled bridge**

```bash
git add api_server.py tests/test_page_chrome.py tests/test_api_endpoints.py tests/test_claude_send.py
git commit -m "fix(security): disable Claude web bridge"
```

---

### Task 2: Contain recipe and shopping-list paths

**Files:**
- Create: `lib/safe_paths.py`
- Create: `tests/test_safe_paths.py`
- Modify: `tests/test_api_server.py`
- Modify: `tests/test_api_endpoints.py`
- Modify: `tests/test_shopping_list_generator.py`
- Modify: `api_server.py:991-1077,1158-1244,2767-2791`
- Modify: `lib/shopping_list_generator.py:369-387`

**Interfaces:**
- Produces: `contained_markdown(root: Path, value: str) -> Path`, `parse_iso_week(value: str) -> str`, and `shopping_list_path(root: Path, week: str) -> Path`.
- Consumers: Flask recipe/shopping handlers and `lib.shopping_list_generator.parse_shopping_list_file`.

- [ ] **Step 1: Write failing unit tests for containment and canonical ISO weeks**

Create `tests/test_safe_paths.py`:

```python
from pathlib import Path
import pytest

from lib.safe_paths import contained_markdown, parse_iso_week, shopping_list_path

def test_contained_markdown_accepts_nested_markdown(tmp_path):
    assert contained_markdown(tmp_path, "Dinner/Stew.md") == (tmp_path / "Dinner/Stew.md").resolve()

@pytest.mark.parametrize("value", ["../outside.md", "/tmp/outside.md", "x.txt", "bad\x00.md"])
def test_contained_markdown_rejects_escape_and_wrong_types(tmp_path, value):
    with pytest.raises(ValueError):
        contained_markdown(tmp_path, value)

def test_contained_markdown_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        contained_markdown(tmp_path, "link/escape.md")

@pytest.mark.parametrize("value", ["2026-W00", "2026-W54", "2026-W1", "../outside", "x2026-W01"])
def test_parse_iso_week_rejects_noncanonical_or_impossible_weeks(value):
    with pytest.raises(ValueError):
        parse_iso_week(value)

def test_parse_iso_week_returns_canonical_week():
    assert parse_iso_week("2026-W35") == "2026-W35"

def test_shopping_list_path_is_constructed_from_validated_week(tmp_path):
    assert shopping_list_path(tmp_path, "2026-W35") == (tmp_path / "2026-W35.md").resolve()
```

- [ ] **Step 2: Add failing route-level sentinel tests**

Add tests that patch `OBSIDIAN_RECIPES_PATH`/`SHOPPING_LISTS_PATH` to a temporary root, create `outside.md` beside it, call:

```python
client.get("/refresh?file=../outside.md")
client.get("/reprocess?file=..%2Foutside.md")
client.post("/generate-shopping-list", json={"week": "../outside"})
client.post("/send-to-reminders", json={"week": "../outside"})
client.post("/api/shopping-list/preview", json={"week": "2026-W54"})
client.post("/api/shopping-list/confirm", json={"week": "../outside", "items_to_buy": []})
```

Assert every response is 400, `outside.md` remains byte-identical, and the patched Reminders function is never called.

- [ ] **Step 3: Run path tests and verify RED**

Run:

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_safe_paths.py tests/test_api_server.py \
  tests/test_api_endpoints.py tests/test_shopping_list_generator.py -q
```

Expected: import failure for `lib.safe_paths` first; after the module exists, current traversal handlers fail the sentinel expectations.

- [ ] **Step 4: Implement the path authority**

Create `lib/safe_paths.py` exactly around these rules:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
import re

_ISO_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")

def contained_markdown(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid Markdown filename")
    relative = Path(value)
    if relative.is_absolute() or relative.suffix.lower() != ".md":
        raise ValueError("invalid Markdown filename")
    resolved_root = Path(root).resolve()
    candidate = (resolved_root / relative).resolve(strict=False)
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("Markdown path escapes its configured directory")
    return candidate

def parse_iso_week(value: str) -> str:
    match = _ISO_WEEK.fullmatch(value or "")
    if match is None:
        raise ValueError("week required (YYYY-WNN)")
    year, week = map(int, match.groups())
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError("week required (YYYY-WNN)") from exc
    return f"{year:04d}-W{week:02d}"

def shopping_list_path(root: Path, week: str) -> Path:
    return contained_markdown(root, f"{parse_iso_week(week)}.md")
```

Do not import or call `urllib.parse.unquote` anywhere in this module or in `/refresh` and `/reprocess`.

- [ ] **Step 5: Route every request-derived path through the authority**

For `/refresh` and `/reprocess`, validate before `exists`, backup, subprocess, or file read:

```python
try:
    filepath = contained_markdown(OBSIDIAN_RECIPES_PATH, filename)
except ValueError as exc:
    return error_page(f"Error: {exc}"), 400
filename = filepath.name
```

For all four shopping handlers, canonicalize with `parse_iso_week` in a `try/except ValueError` and use `shopping_list_path(SHOPPING_LISTS_PATH, week)` instead of joining request text. Change `parse_shopping_list_file` to the same helper so every non-Flask caller is safe too.

- [ ] **Step 6: Run focused path tests and verify GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 7: Commit path containment**

```bash
git add lib/safe_paths.py api_server.py lib/shopping_list_generator.py \
  tests/test_safe_paths.py tests/test_api_server.py tests/test_api_endpoints.py \
  tests/test_shopping_list_generator.py
git commit -m "fix(security): contain vault request paths"
```

---

### Task 3: Replace additive inventory rewrites with transactional merges

**Files:**
- Modify: `lib/inventory_db.py:250-410`
- Modify: `lib/inventory.py:290-320,421-480`
- Modify: `tests/test_inventory_db.py`
- Modify: `tests/test_inventory.py`

**Interfaces:**
- Produces: `write_transaction(conn: sqlite3.Connection | None = None)`, `merge_inventory_rows(rows: list[dict], conn: sqlite3.Connection | None = None) -> dict`, and `refresh_inventory_views() -> None`.
- Preserves: `inventory.add_items(new_items: list[InventoryItem]) -> dict` response contract.

- [ ] **Step 1: Write failing merge and controlled-concurrency tests**

Add a lower-level merge test covering every compatibility field and this deterministic concurrency test:

```python
def test_concurrent_adds_preserve_both_updates(tmp_vault, tmp_db, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import lib.inventory as inventory

    real_read = inventory.read_inventory
    barrier = threading.Barrier(2)

    def synchronized_read():
        rows = real_read()
        barrier.wait(timeout=5)
        return rows

    monkeypatch.setattr(inventory, "read_inventory", synchronized_read)
    item = lambda: inventory.InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: inventory.add_items([item()]), range(2)))

    [milk] = real_read()
    assert milk.quantity == 2
```

The compatibility test must assert summed quantity, new explicit purchase date, preserved existing notes, upgraded category, strongest location source, ordered/deduplicated `for_recipe`, and earliest expiry.

- [ ] **Step 2: Run inventory tests and verify RED**

Run:

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_inventory_db.py tests/test_inventory.py -q
```

Expected: the controlled concurrent add leaves quantity `1`, not `2`.

- [ ] **Step 3: Add an owned-or-borrowed SQLite write transaction**

In `lib/inventory_db.py`, add a context manager with this ownership contract:

```python
@contextmanager
def write_transaction(conn=None):
    if conn is not None:
        yield conn
        return
    owned = connect()
    try:
        owned.execute("BEGIN IMMEDIATE")
        yield owned
        owned.commit()
    except Exception:
        owned.rollback()
        raise
    finally:
        owned.close()
```

Borrowed connections are already inside the caller's transaction; this helper must neither commit nor close them.

- [ ] **Step 4: Implement `merge_inventory_rows` with one UPSERT transaction**

Import `date` from `datetime`. For each normalized row, query whether the key exists (for `added`/`merged` counts and safe `for_recipe` union). When the key is new and `purchased` is unset, assign `row["purchased"] = date.today().isoformat()`; when the key exists, leave an unset incoming date as `None` so the UPSERT preserves the stored date. Then execute one `INSERT ... ON CONFLICT(name, unit, location) DO UPDATE` whose assignments are:

```sql
quantity = inventory.quantity + excluded.quantity,
purchased = COALESCE(NULLIF(excluded.purchased, ''), inventory.purchased),
category = CASE WHEN excluded.category <> 'other' THEN excluded.category ELSE inventory.category END,
notes = CASE WHEN inventory.notes = '' AND excluded.notes <> '' THEN excluded.notes ELSE inventory.notes END,
for_recipe = excluded.for_recipe,
expires = CASE
  WHEN inventory.expires IS NULL THEN excluded.expires
  WHEN excluded.expires IS NULL THEN inventory.expires
  ELSE MIN(inventory.expires, excluded.expires)
END,
location_source = CASE
  WHEN CASE excluded.location_source WHEN 'manual' THEN 3 WHEN 'item' THEN 2 WHEN 'category' THEN 1 ELSE 0 END
     > CASE inventory.location_source WHEN 'manual' THEN 3 WHEN 'item' THEN 2 WHEN 'category' THEN 1 ELSE 0 END
  THEN excluded.location_source ELSE inventory.location_source
END
```

Before the UPSERT, set `row["for_recipe"]` to the existing plus incoming ordered union. Return `{"added": added, "merged": merged, "total": SELECT COUNT(*)}` from inside the transaction.

- [ ] **Step 5: Separate persistence from derived-view refresh and switch `add_items`**

Move the two guarded view blocks from `write_inventory` into `refresh_inventory_views()`. Keep `write_inventory(items)` as full replacement plus refresh for explicit callers. Change `add_items` to:

```python
def add_items(new_items: list[InventoryItem]) -> dict:
    for item in new_items:
        if item.expires is None:
            item.expires = compute_expires(item.purchased, item.name, item.category)
        item.location_source = normalize_location_source(item.location_source)
    result = inventory_db.merge_inventory_rows([item.to_dict() for item in new_items])
    refresh_inventory_views()
    return result
```

Import `inventory_db` inside the function or module consistently with the existing circular-import guard.

- [ ] **Step 6: Run inventory tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass, including the controlled concurrent add.

- [ ] **Step 7: Commit additive inventory transactions**

```bash
git add lib/inventory_db.py lib/inventory.py tests/test_inventory_db.py tests/test_inventory.py
git commit -m "fix(inventory): merge additions transactionally"
```

---

### Task 4: Serialize whole-inventory read/modify/write operations

**Files:**
- Modify: `lib/inventory_db.py`
- Modify: `lib/inventory.py`
- Modify: `lib/pantry.py`
- Modify: `tests/test_inventory_db.py`
- Modify: `tests/test_inventory.py`
- Modify: `tests/test_pantry.py`

**Interfaces:**
- Produces: `mutate_inventory_rows(mutator: Callable[[list[dict]], tuple[list[dict], T, bool]]) -> tuple[T, bool]` and `mutate_inventory(mutator: Callable[[list[InventoryItem]], tuple[T, bool]]) -> T`.
- Consumes: Task 3 `write_transaction` and `refresh_inventory_views`.

- [ ] **Step 1: Write a failing serialized-replacement regression test**

Use two threads and events: thread A enters a whole-inventory mutation and pauses after its transaction-protected read; thread B calls `add_items`. Assert B cannot finish until A is released, then assert A's edit and B's new row both survive. Expose a private test hook only through the mutator callback—do not add sleeps to production code.

```python
entered = threading.Event()
release = threading.Event()

def mutate(rows):
    entered.set()
    assert release.wait(5)
    rows[0]["quantity"] = 2
    return rows, None, True
```

The test calls `inventory_db.mutate_inventory_rows(mutate)` in thread A and `add_items([new_row])` in thread B.

- [ ] **Step 2: Run the new regression and verify RED**

Run the new test by node ID. Expected: `inventory_db.mutate_inventory_rows` is absent.

- [ ] **Step 3: Implement same-connection mutation primitives**

Add connection-aware private fetch/replace helpers and:

```python
def mutate_inventory_rows(mutator):
    with write_transaction() as conn:
        rows = _fetch_inventory_rows(conn)
        replacement, result, changed = mutator(rows)
        if changed:
            _replace_inventory_rows(conn, replacement)
        return result, changed
```

`_replace_inventory_rows` executes DELETE plus INSERTs but never commits. Public `replace_inventory_rows(rows)` wraps it in `write_transaction()`.

In `lib/inventory.py`, add row↔`InventoryItem` conversion through the same normalization used by `read_inventory`, then:

```python
def mutate_inventory(mutator):
    def apply(rows):
        items = [_item_from_row(row) for row in rows]
        result, changed = mutator(items)
        return [item.to_dict() for item in items], result, changed
    (result, changed) = inventory_db.mutate_inventory_rows(apply)
    if changed:
        refresh_inventory_views()
    return result
```

- [ ] **Step 4: Move every full-set mutation inside the transaction**

Refactor these functions so their existing list-edit logic runs inside a `mutate_inventory` callback and no longer performs `read_inventory()` followed later by `write_inventory()`:

- `seed_pantry_staples`
- `prune_expired`
- `remove_item`
- `update_quantity`
- `extend_expiry`
- `bulk_apply`
- `set_expiry`
- `set_category`
- `move_item`
- `freeze_item`

Preserve return values with `(result, changed)` from each callback. Preserve `_teach_location` ordering after the database commit. When no row matches, return the existing false/`None`/empty result with `changed=False`; the database and derived views remain untouched. A mutation that edits or removes a row returns `changed=True`.

Rewrite `pantry.save_pantry(items)` so `new_by_key` is prepared before the transaction and its reconciliation callback receives the current `InventoryItem` snapshot. It must not call `read_inventory` or `write_inventory` itself.

- [ ] **Step 5: Run inventory and pantry suites and verify GREEN**

Run:

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_inventory_db.py tests/test_inventory.py tests/test_pantry.py -q
```

Expected: all tests pass, including the lock-order regression.

- [ ] **Step 6: Commit serialized full-set mutations**

```bash
git add lib/inventory_db.py lib/inventory.py lib/pantry.py \
  tests/test_inventory_db.py tests/test_inventory.py tests/test_pantry.py
git commit -m "fix(inventory): serialize reconciliation writes"
```

---

### Task 5: Commit receipts and inventory atomically

**Files:**
- Modify: `lib/inventory_db.py:272-323`
- Modify: `lib/receipt_ingest.py:53-119`
- Modify: `api_server.py:2940-3058`
- Modify: `tests/test_inventory_db.py`
- Modify: `tests/test_receipt_ingest.py`
- Modify: `tests/test_api_server.py`

**Interfaces:**
- Produces: `record_trip_with_inventory(trip: dict, purchases: list[dict], inventory_rows: list[dict]) -> tuple[int | None, dict | None]`.
- Consumes: Task 3 `write_transaction` and `merge_inventory_rows(..., conn=conn)`.

- [ ] **Step 1: Write failing rollback and replay regressions**

Add to `tests/test_receipt_ingest.py`:

```python
def test_ingest_failure_rolls_back_trip_purchases_and_inventory(
        tmp_vault, tmp_db, alias_tmp, monkeypatch):
    from lib import inventory_db as idb
    real_merge = idb.merge_inventory_rows
    monkeypatch.setattr(idb, "merge_inventory_rows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt", source_id="photo-x")
    conn = idb.connect()
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0
    conn.close()

    monkeypatch.setattr(idb, "merge_inventory_rows", real_merge)
    assert ri.ingest_parsed(dict(PARSED_OK), source="photo_receipt",
                            source_id="photo-x")["status"] == "ingested"
```

Add an API regression that posts the same optional-trip payload twice and asserts one trip, one purchase row, and unchanged inventory quantity after the second response.

- [ ] **Step 2: Run receipt/API regressions and verify RED**

Run:

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_inventory_db.py tests/test_receipt_ingest.py tests/test_api_server.py -q
```

Expected: rollback test leaves a trip behind, and replay doubles inventory.

- [ ] **Step 3: Extract connection-aware trip insert helpers**

Split `record_trip` into private `_insert_trip(conn, trip) -> int | None` and `_insert_purchases(conn, trip_id, purchases) -> None`. Keep public `record_trip` behavior by wrapping both in `write_transaction()`.

Duplicate handling remains only:

```python
except sqlite3.IntegrityError as exc:
    if "trips.source_id" in str(exc):
        return None
    raise
```

- [ ] **Step 4: Implement the combined receipt transaction**

```python
def record_trip_with_inventory(trip, purchases, inventory_rows):
    with write_transaction() as conn:
        trip_id = _insert_trip(conn, trip)
        if trip_id is None:
            return None, None
        _insert_purchases(conn, trip_id, purchases)
        result = merge_inventory_rows(inventory_rows, conn=conn)
        return trip_id, result
```

The borrowed `merge_inventory_rows` must not commit or close the connection.

- [ ] **Step 5: Route both receipt entry points through the combined operation**

In `receipt_ingest.ingest_parsed`, fully prepare `stock` first. For valid receipts call `record_trip_with_inventory`; return `skipped` on `trip_id is None`, otherwise refresh views after commit and return `ingested`. Keep invalid/needs-review receipts on `record_trip` with no stock rows.

In `/api/inventory/add`, build `purchases` before writing. When `trip_payload` exists, call `record_trip_with_inventory` instead of `add_items` plus `record_trip`; refresh views only after a nonduplicate commit. On duplicate, return `{"status": "ok", "added": 0, "merged": 0, "total": len(read_inventory())}`. Without a trip, retain `add_items(parsed)`.

- [ ] **Step 6: Run receipt/API regressions and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass; forced failure leaves every table empty and retry succeeds once.

- [ ] **Step 7: Commit atomic receipt ingestion**

```bash
git add lib/inventory_db.py lib/receipt_ingest.py api_server.py \
  tests/test_inventory_db.py tests/test_receipt_ingest.py tests/test_api_server.py
git commit -m "fix(receipts): commit ledger and stock atomically"
```

---

### Task 6: Update contracts and verify the complete branch

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CLAUDE.md`
- Modify: `BRANCH-STATUS.md`
- Modify: `docs/plans/INDEX.md`

**Interfaces:**
- Consumes: all prior task behavior.
- Produces: current route count/contracts, transaction invariants, and verification evidence.

- [ ] **Step 1: Update documentation from source, not remembered counts**

Remove Claude bridge routes/UI from API and architecture docs. Document:

- request paths are decoded once by Flask and then contained beneath their configured root;
- shopping-list weeks are real canonical ISO weeks;
- additive inventory writes use transactional key merges;
- receipt source-ID dedupe, purchases, and inventory commit together;
- full-set reconciliations lock before reading.

Recompute route counts with:

```bash
rg -o "@app\.route\([^)]*" api_server.py | wc -l
rg -o "@app\.route\(['\"][^'\"]+" api_server.py \
  | sed -E "s/^@app\.route\(['\"]//" | sort -u | wc -l
```

Write the measured numbers into `docs/API.md`; do not assume the predicted count.

- [ ] **Step 2: Run focused security and persistence suites**

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest \
  tests/test_page_chrome.py tests/test_claude_send.py tests/test_api_endpoints.py \
  tests/test_safe_paths.py tests/test_api_server.py tests/test_shopping_list_generator.py \
  tests/test_inventory_db.py tests/test_inventory.py tests/test_pantry.py \
  tests/test_receipt_ingest.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run the default Python suite**

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest -q
```

Expected: zero failures; compare warning and deselection counts to the clean baseline `4086 passed, 1 skipped, 133 deselected, 9 warnings`.

- [ ] **Step 4: Run the E2E suite**

```bash
/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest -m e2e -q -rxX
```

Expected: no hard failures; record skips, xfails, and xpasses verbatim in `BRANCH-STATUS.md`.

- [ ] **Step 5: Check diff quality and shared-branch overlap**

```bash
git diff --check main...HEAD
git diff --name-only main...ios27-new-siri
git diff --name-only main...HEAD
git status --short
```

Inspect the `api_server.py` hunks against `ios27-new-siri`; record any semantic overlap in `BRANCH-STATUS.md` before review.

- [ ] **Step 6: Update branch tracking and commit documentation**

Mark completed planning/dev/testing/docs items only when their evidence exists. Keep LaunchAgent restart unchecked until merge because production must continue serving main during branch work.

```bash
git add docs/API.md docs/ARCHITECTURE.md CLAUDE.md BRANCH-STATUS.md docs/plans/INDEX.md
git commit -m "docs(security): document atomic persistence"
```

- [ ] **Step 7: Request final code review**

Use `superpowers:requesting-code-review` over `main...HEAD`. Address every load-bearing finding, rerun the affected focused suite, then rerun the default suite before declaring the branch ready.
