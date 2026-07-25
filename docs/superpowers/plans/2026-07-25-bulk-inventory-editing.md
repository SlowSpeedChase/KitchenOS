# Bulk Inventory Editing Implementation Plan

> **STATUS — all 6 tasks implemented; branch is at `review` (2026-07-25).** The
> per-step checkboxes below were not back-ticked; `BRANCH-STATUS.md` is the
> authoritative tracker and records the outcome of each stage. Three steps were
> executed differently than written — Task 6 Steps 2, 3 and 4 — and the reasons are
> in that file's "Deviations from the plan" section. Most relevant here: Task 5's
> claim that the repo has **no JS test harness is wrong** (`tests/e2e/` is a
> Playwright harness), so Task 6's manual phone script became
> `tests/e2e/test_bulk_inventory.py` instead of a one-time hand check.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the `/review` page apply one action (remove, extend, set-expiry, set-category, move, freeze) to many selected inventory items in a single server write, and fix the `(name, location)` vs `(name, unit, location)` addressing mismatch on the bulk path.

**Architecture:** Extract the mutation logic in `lib/inventory.py` out of its read/write wrappers into pure in-memory `_apply_*` helpers. A new `bulk_apply()` does one `read_inventory()` → resolve refs by `merge_key()` → dispatch to an `_apply_*` helper → one `write_inventory()`. The existing single-item functions become thin wrappers over the same helpers, so there is one source of truth for merge semantics. A new `POST /api/inventory/bulk` route exposes it, and `templates/review.html` grows checkboxes plus a sticky selection bar that mirrors a row's own controls.

**Tech Stack:** Python 3.11 (run everything via `.venv/bin/python`), Flask, SQLite via `lib/inventory_db.py`, pytest, vanilla JS + CSS in a single Jinja-free template.

**Design doc:** `docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md`

## Global Constraints

- **Python 3.11 via `.venv/bin/python`.** Never call bare `python`/`pytest`; use `.venv/bin/python -m pytest`.
- **`data/kitchenos.db` is the single source of truth** for inventory. `Inventory.md` and `Cook Now.md` are generated read-only views rewritten inside `write_inventory()`. Never add a parallel source of truth.
- **All DB access goes through `lib/inventory_db.py`.** Never open `sqlite3` directly.
- **Tests must use the `tmp_vault` + `tmp_db` fixtures** (`tests/conftest.py`) for anything that reads or writes inventory.
- **Existing single-item routes keep their current signatures and semantics.** `remove_item` still deletes every `(name, location)` match; `set_expiry` / `set_category` / `extend_expiry` / `move_item` still update only the first. Their tests pin this. The addressing fix applies to the bulk path only.
- **The uniqueness key is `(name, unit, location)`**, lowercased and stripped — exactly what `InventoryItem.merge_key()` (`lib/inventory.py:46`) returns.
- **`InventoryItem` is a plain dataclass, so `==` compares by value.** Never use `list.remove(item)` on it; remove by identity (`is`). Task 1 adds `_drop()` for this.
- **New bulk action names are the wire vocabulary and must match exactly:** `remove`, `extend`, `set-expiry`, `set-category`, `move`, `freeze` (hyphens, not underscores).
- **After editing anything under `lib/`, `templates/`, or `prompts/`, the `com.kitchenos.api` LaunchAgent serves stale code until reloaded.** Manual verification steps must be preceded by a reload (see Task 6).
- **Commit message convention:** `type: short description` + the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer, per `CLAUDE.md`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `lib/inventory.py` | Inventory model, mutators, persistence | Modify — add `_drop`, `_match_by_name`, six `_apply_*` helpers, `bulk_apply`, `BULK_ACTIONS`; rewrite six single-item functions as wrappers |
| `api_server.py` | HTTP surface | Modify — add `_serialize_item` (extracted from `_item_response`) and `POST /api/inventory/bulk` |
| `templates/review.html` | The `/review` page | Modify — checkboxes, Select All, `#bulkbar`, generalized `openMenu`, array-based undo |
| `tests/test_inventory.py` | Unit tests for the inventory module | Modify — new classes for the helpers and `bulk_apply` |
| `tests/test_api_endpoints.py` | Route contract tests | Modify — new tests for `/api/inventory/bulk` |
| `docs/API.md` | Endpoint reference | Modify — document the bulk route |
| `BRANCH-STATUS.md` | GitOps branch tracking | Modify — tick stages as they complete |

`lib/inventory.py` is 538 lines and will grow by roughly 140. That is within the range the codebase already uses for this module; do **not** split it.

---

### Task 1: Pure mutators

Extract the in-memory mutation logic so both the bulk path and the single-item path can share it. Nothing calls these yet — this task is pure foundation, tested directly.

**Files:**
- Modify: `lib/inventory.py` (insert after `_match`, currently `lib/inventory.py:421-425`)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `InventoryItem`, `normalize_category`, `normalize_location`, `_match` — all already in `lib/inventory.py`.
- Produces, all doing **no I/O**:
  - `_drop(items: list[InventoryItem], victim: InventoryItem) -> None`
  - `_match_by_name(items: list[InventoryItem], name: str, location: Optional[str]) -> list[InventoryItem]`
  - `_apply_remove(items, matches) -> list[InventoryItem]`
  - `_apply_extend(items, matches, days: int, today: Optional[date] = None) -> list[InventoryItem]`
  - `_apply_set_expiry(items, matches, expires: Optional[str]) -> list[InventoryItem]`
  - `_apply_set_category(items, matches, category: str) -> list[InventoryItem]`
  - `_apply_move(items, matches, to_location: str) -> list[InventoryItem]`
  - `_apply_freeze(items, matches) -> list[InventoryItem]`

  Every `_apply_*` takes the full item list plus the already-matched rows, mutates `items` in place, and returns the affected rows (the removed rows for `_apply_remove`, the resulting destination rows for the others).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inventory.py`:

```python
class TestPureMutators:
    """The _apply_* helpers mutate in memory and do no I/O."""

    def _items(self):
        return [
            InventoryItem(name="Bread", quantity=1, unit="loaf",
                          category="bakery", location="pantry"),
            InventoryItem(name="Bread", quantity=2, unit="loaf",
                          category="bakery", location="counter"),
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", location="fridge",
                          expires="2026-09-15"),
        ]

    def test_drop_removes_by_identity_not_value(self):
        from lib.inventory import _drop
        a = InventoryItem(name="Egg", quantity=1, unit="ct", location="fridge")
        b = InventoryItem(name="Egg", quantity=1, unit="ct", location="fridge")
        items = [a, b]
        assert a == b  # dataclass equality is by value
        _drop(items, b)
        assert len(items) == 1
        assert items[0] is a

    def test_match_by_name_returns_every_match(self):
        from lib.inventory import _match_by_name
        items = self._items()
        assert len(_match_by_name(items, "Bread", None)) == 2
        assert len(_match_by_name(items, "bread", "counter")) == 1
        assert _match_by_name(items, "Nope", None) == []

    def test_apply_remove_drops_all_matches_and_returns_them(self):
        from lib.inventory import _apply_remove
        items = self._items()
        removed = _apply_remove(items, [items[0], items[2]])
        assert len(items) == 1
        assert items[0].name == "Bread" and items[0].location == "counter"
        assert [r.name for r in removed] == ["Bread", "Milk"]

    def test_apply_extend_sets_expiry_from_today(self):
        from datetime import date
        from lib.inventory import _apply_extend
        items = self._items()
        out = _apply_extend(items, items[:2], 7, today=date(2026, 7, 25))
        assert [i.expires for i in out] == ["2026-08-01", "2026-08-01"]
        assert items[2].expires == "2026-09-15"  # untouched row keeps its own

    def test_apply_set_expiry_sets_and_clears(self):
        from lib.inventory import _apply_set_expiry
        items = self._items()
        _apply_set_expiry(items, [items[0]], "2026-09-09")
        assert items[0].expires == "2026-09-09"
        _apply_set_expiry(items, [items[2]], None)
        assert items[2].expires is None

    def test_apply_set_category_normalizes(self):
        from lib.inventory import _apply_set_category
        items = self._items()
        _apply_set_category(items, items[:2], "Produce")
        assert [i.category for i in items[:2]] == ["produce", "produce"]
        _apply_set_category(items, [items[2]], "widgets")
        assert items[2].category == "other"

    def test_apply_move_changes_location(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[2]], "Freezer")
        assert out[0].location == "freezer"
        assert len(items) == 3

    def test_apply_move_merges_two_selected_rows_into_one_destination(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[0], items[1]], "freezer")
        assert len(items) == 2          # the two Bread rows collapsed into one
        assert len(out) == 1            # and the result is reported once
        assert out[0].quantity == 3.0
        assert out[0].location == "freezer"

    def test_apply_move_to_same_location_is_a_noop(self):
        from lib.inventory import _apply_move
        items = self._items()
        out = _apply_move(items, [items[0]], "pantry")
        assert out == [items[0]]
        assert len(items) == 3

    def test_apply_freeze_moves_sets_category_and_clears_expiry(self):
        from lib.inventory import _apply_freeze
        items = self._items()
        out = _apply_freeze(items, [items[2]])
        assert out[0].location == "freezer"
        assert out[0].category == "frozen"
        assert out[0].expires is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestPureMutators -v`
Expected: FAIL — `ImportError: cannot import name '_drop' from 'lib.inventory'`

- [ ] **Step 3: Implement the helpers**

Insert into `lib/inventory.py` immediately after `_match` (after line 425, before `def set_expiry`):

```python
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
    """Set every matched row's expiry to today + ``days``."""
    new_expires = ((today or date.today()) + timedelta(days=days)).isoformat()
    for it in matches:
        it.expires = new_expires
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestPureMutators -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Run the whole inventory suite for regressions**

Run: `.venv/bin/python -m pytest tests/test_inventory.py -q`
Expected: PASS — no failures (nothing calls the new helpers yet)

- [ ] **Step 6: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "refactor: extract pure inventory mutators with no I/O

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `bulk_apply`

One read, one dispatch, one write — addressing rows by the real `(name, unit, location)` key.

**Files:**
- Modify: `lib/inventory.py` (append after `_apply_freeze` from Task 1)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: every `_apply_*` helper from Task 1, plus `read_inventory` / `write_inventory`.
- Produces:
  - `BULK_ACTIONS: tuple[str, ...]` = `("remove", "extend", "set-expiry", "set-category", "move", "freeze")`
  - `bulk_apply(action: str, refs: list[dict], **params) -> dict` returning
    `{"applied": int, "items": list[InventoryItem], "removed": list[InventoryItem], "not_found": list[dict]}`.
    `items` is empty for `remove`; `removed` is empty for everything else. Both keys are always present so the client never branches on absence.
    Raises `ValueError` on an unknown action, a ref missing `name`/`unit`/`location`, or a missing/invalid action parameter. Task 4 turns that into a 400.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inventory.py`:

```python
class TestBulkApply:
    def _seed(self):
        add_items([
            InventoryItem(name="Kale", quantity=1, unit="bunch",
                          category="produce", location="fridge",
                          expires="2026-07-26"),
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", location="fridge",
                          expires="2026-07-28"),
            InventoryItem(name="Rice", quantity=2, unit="lb",
                          category="pantry", location="pantry"),
        ])

    def _ref(self, name, unit, location):
        return {"name": name, "unit": unit, "location": location}

    def test_bulk_remove_removes_all_and_returns_rows(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Milk", "gal", "fridge"),
        ])
        assert out["applied"] == 2
        assert out["items"] == []
        assert sorted(r.name for r in out["removed"]) == ["Kale", "Milk"]
        assert [i.name for i in read_inventory()] == ["Rice"]

    def test_bulk_extend_sets_all_expiries_in_one_write(self, tmp_vault, tmp_db):
        from datetime import date
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("extend", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Rice", "lb", "pantry"),
        ], days=7, today=date(2026, 7, 25))
        assert out["applied"] == 2
        assert out["removed"] == []
        assert {i.expires for i in out["items"]} == {"2026-08-01"}
        stored = {i.name: i.expires for i in read_inventory()}
        assert stored["Kale"] == "2026-08-01"
        assert stored["Rice"] == "2026-08-01"
        assert stored["Milk"] == "2026-07-28"  # unselected row untouched

    def test_bulk_set_expiry_clears(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        bulk_apply("set-expiry", [self._ref("Kale", "bunch", "fridge")],
                   expires=None)
        assert {i.name: i.expires for i in read_inventory()}["Kale"] is None

    def test_bulk_set_category_normalizes(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        bulk_apply("set-category", [self._ref("Rice", "lb", "pantry")],
                   category="Produce")
        assert {i.name: i.category for i in read_inventory()}["Rice"] == "produce"

    def test_bulk_move_merges_two_selected_rows_into_one_destination(
        self, tmp_vault, tmp_db
    ):
        from lib.inventory import bulk_apply
        add_items([
            InventoryItem(name="Peas", quantity=1, unit="bag", location="fridge"),
            InventoryItem(name="Peas", quantity=2, unit="bag", location="pantry"),
        ])
        out = bulk_apply("move", [
            self._ref("Peas", "bag", "fridge"),
            self._ref("Peas", "bag", "pantry"),
        ], to_location="freezer")
        assert out["applied"] == 2
        assert len(out["items"]) == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3.0
        assert items[0].location == "freezer"

    def test_bulk_freeze_sets_category_and_clears_expiry(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("freeze", [self._ref("Kale", "bunch", "fridge")])
        assert out["items"][0].location == "freezer"
        assert out["items"][0].category == "frozen"
        assert out["items"][0].expires is None

    def test_unit_is_part_of_the_address(self, tmp_vault, tmp_db):
        """The whole point of the fix: same name, different unit, different row."""
        from lib.inventory import bulk_apply
        add_items([
            InventoryItem(name="Flour", quantity=1, unit="lb", location="pantry"),
            InventoryItem(name="Flour", quantity=1, unit="bag", location="pantry"),
        ])
        out = bulk_apply("remove", [self._ref("Flour", "lb", "pantry")])
        assert out["applied"] == 1
        remaining = read_inventory()
        assert len(remaining) == 1
        assert remaining[0].unit == "bag"

    def test_partial_not_found_still_applies_the_rest(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [
            self._ref("Kale", "bunch", "fridge"),
            self._ref("Ghost", "ct", "fridge"),
        ])
        assert out["applied"] == 1
        assert out["not_found"] == [self._ref("Ghost", "ct", "fridge")]
        assert len(read_inventory()) == 2

    def test_all_refs_missing_writes_nothing(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [self._ref("Ghost", "ct", "fridge")])
        assert out["applied"] == 0
        assert len(out["not_found"]) == 1
        assert len(read_inventory()) == 3

    def test_matching_is_case_insensitive(self, tmp_vault, tmp_db):
        from lib.inventory import bulk_apply
        self._seed()
        out = bulk_apply("remove", [self._ref("KALE", "Bunch", "Fridge")])
        assert out["applied"] == 1

    def test_unknown_action_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="unknown action"):
            bulk_apply("explode", [self._ref("Kale", "bunch", "fridge")])

    def test_ref_missing_unit_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="unit"):
            bulk_apply("remove", [{"name": "Kale", "location": "fridge"}])

    def test_ref_missing_location_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="location"):
            bulk_apply("remove", [{"name": "Kale", "unit": "bunch"}])

    def test_missing_action_parameter_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="to_location"):
            bulk_apply("move", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="category"):
            bulk_apply("set-category", [self._ref("Kale", "bunch", "fridge")])
        with pytest.raises(ValueError, match="expires"):
            bulk_apply("set-expiry", [self._ref("Kale", "bunch", "fridge")])

    def test_missing_parameter_raises_even_when_nothing_matches(
        self, tmp_vault, tmp_db
    ):
        """Validation is about the request, not about what happens to match."""
        import pytest
        from lib.inventory import bulk_apply
        self._seed()
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Ghost", "ct", "fridge")])

    def test_non_integer_days_raises(self, tmp_vault, tmp_db):
        import pytest
        from lib.inventory import bulk_apply
        with pytest.raises(ValueError, match="days"):
            bulk_apply("extend", [self._ref("Kale", "bunch", "fridge")],
                       days="soon")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestBulkApply -v`
Expected: FAIL — `ImportError: cannot import name 'bulk_apply' from 'lib.inventory'`

- [ ] **Step 3: Implement `bulk_apply`**

Append to `lib/inventory.py`, after `_apply_freeze`:

```python
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
            updated = _apply_move(items, matches, to_location)
        elif action == "freeze":
            updated = _apply_freeze(items, matches)

        write_inventory(items)

    return {
        "applied": len(matches),
        "items": updated,
        "removed": removed,
        "not_found": not_found,
    }
```

Note the ordering: action → refs → action parameters are all validated **before** `read_inventory()`. A malformed body must fail the same way whether or not its refs happen to match anything.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestBulkApply -v`
Expected: PASS — 16 passed

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "feat: add bulk_apply, one write for many inventory edits

Addresses rows by the real (name, unit, location) key instead of
(name, location), which the single-item functions handle inconsistently.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Single-item functions become thin wrappers

One source of truth for merge semantics. Every existing test must stay green — their behavior is the contract.

**Files:**
- Modify: `lib/inventory.py:349-366` (`remove_item`), `:390-418` (`extend_expiry`), `:428-449` (`set_expiry`), `:452-472` (`set_category`), `:475-522` (`move_item`), `:525-538` (`freeze_item`)
- Test: `tests/test_inventory.py` (existing classes `TestRemove`, `TestExtendExpiry`, `TestSetExpiry`, `TestSetCategory`, `TestMoveItem`, `TestFreezeItem` — do not change them)

**Interfaces:**
- Consumes: `_match_by_name` and every `_apply_*` helper from Task 1.
- Produces: the same six public signatures and return types as before. `update_quantity` is **not** touched — it has no bulk counterpart.

- [ ] **Step 1: Pin the current behavior**

Run: `.venv/bin/python -m pytest tests/test_inventory.py -q`
Expected: PASS. This is the baseline — the same command must pass identically at Step 4.

- [ ] **Step 2: Rewrite the six functions**

Replace `remove_item` (`lib/inventory.py:349-366`) with:

```python
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
```

Replace `extend_expiry` (`lib/inventory.py:390-418`) with:

```python
def extend_expiry(
    name: str,
    days: int,
    location: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[InventoryItem]:
    """Set the first ``(name, location)`` match's expiry to today + ``days``.

    Works on no-expiry items. Returns the updated item, or None if nothing
    matched.
    """
    items = read_inventory()
    matches = _match_by_name(items, name, location)[:1]
    if not matches:
        return None
    updated = _apply_extend(items, matches, days, today=today)
    write_inventory(items)
    return updated[0]
```

Replace `set_expiry` (`lib/inventory.py:428-449`) with:

```python
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
```

Replace `set_category` (`lib/inventory.py:452-472`) with:

```python
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
```

Replace `move_item` (`lib/inventory.py:475-522`) with:

```python
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
    # Already there: return without a write, so a no-op move doesn't churn the
    # DB and regenerate Inventory.md / Cook Now.md for nothing.
    if matches[0].location == normalize_location(to_location):
        return matches[0]
    result = _apply_move(items, matches, to_location)
    write_inventory(items)
    return result[0]
```

Replace `freeze_item` (`lib/inventory.py:525-538`) with:

```python
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
```

- [ ] **Step 3: Delete the now-dead `_match` callers check**

`_match` is still used by `_match_by_name`. Confirm nothing else references the old inline loops.

Run: `grep -n "target_loc" lib/inventory.py`
Expected: hits only inside `_match`, `_match_by_name`, `remove_item`… — specifically, **no** occurrences left in `extend_expiry`, `set_expiry`, `set_category`, `move_item`, or `freeze_item`. `update_quantity` still has its own loop and that is correct.

- [ ] **Step 4: Run the full inventory suite**

Run: `.venv/bin/python -m pytest tests/test_inventory.py -q`
Expected: PASS — identical count to the Step 1 baseline, zero failures.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 1405+ passed, no regressions. Other modules (MCP tools, receipt ingest) call these functions.

- [ ] **Step 6: Commit**

```bash
git add lib/inventory.py
git commit -m "refactor: single-item inventory mutators reuse the pure helpers

freeze_item collapses from three write cycles to one. Public signatures
and legacy (name, location) addressing are unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `POST /api/inventory/bulk`

**Files:**
- Modify: `api_server.py:2278-2287` (extract `_serialize_item` from `_item_response`), and append the new route after `api_inventory_freeze` (currently ends at `api_server.py:2353`)
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: `lib.inventory.bulk_apply` (Task 2), `lib.expiry.expiry_status`.
- Produces:
  - `_serialize_item(item) -> dict` in `api_server.py` — an `InventoryItem` as a dict plus a computed `expiry_status`.
  - `POST /api/inventory/bulk`, ungated like its `/api/inventory/*` siblings. Body `{action, refs, days?, expires?, category?, to_location?}`. Responds `200 {status: "applied", applied, items, removed, not_found}` or `400 {error}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_endpoints.py`:

```python
def _bulk_seed(client, name, unit, location, category="produce"):
    client.post('/api/inventory/add', json={'items': [
        {'name': name, 'quantity': 1, 'unit': unit,
         'category': category, 'location': location}]})


def _bulk_cleanup(client, name, location):
    client.post('/api/inventory/remove', json={'name': name, 'location': location})


def test_inventory_bulk_requires_action(client):
    response = client.post('/api/inventory/bulk',
                           json={'refs': [{'name': 'X', 'unit': 'ct',
                                           'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'action' in response.get_json()['error'].lower()


def test_inventory_bulk_requires_non_empty_refs(client):
    response = client.post('/api/inventory/bulk',
                           json={'action': 'remove', 'refs': []})
    assert response.status_code == 400
    assert 'refs' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_unknown_action(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'detonate',
        'refs': [{'name': 'X', 'unit': 'ct', 'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'unknown action' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_ref_missing_unit(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'X', 'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'unit' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_ref_missing_location(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'X', 'unit': 'ct'}]})
    assert response.status_code == 400
    assert 'location' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_missing_action_param(client):
    _bulk_seed(client, 'BulkParamKale', 'bunch', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend',
        'refs': [{'name': 'BulkParamKale', 'unit': 'bunch',
                  'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'days' in response.get_json()['error'].lower()
    _bulk_cleanup(client, 'BulkParamKale', 'fridge')


def test_inventory_bulk_extend_applies_to_all(client):
    _bulk_seed(client, 'BulkKale', 'bunch', 'fridge')
    _bulk_seed(client, 'BulkRice', 'lb', 'pantry', category='pantry')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend', 'days': 7,
        'refs': [
            {'name': 'BulkKale', 'unit': 'bunch', 'location': 'fridge'},
            {'name': 'BulkRice', 'unit': 'lb', 'location': 'pantry'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'applied'
    assert body['applied'] == 2
    assert body['removed'] == []
    assert body['not_found'] == []
    assert len(body['items']) == 2
    for item in body['items']:
        assert item['expires']
        assert 'expiry_status' in item      # same shape as the single routes
    _bulk_cleanup(client, 'BulkKale', 'fridge')
    _bulk_cleanup(client, 'BulkRice', 'pantry')


def test_inventory_bulk_remove_returns_rows_for_undo(client):
    _bulk_seed(client, 'BulkGone', 'ct', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'BulkGone', 'unit': 'ct', 'location': 'fridge'}]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 1
    assert body['items'] == []
    assert body['removed'][0]['name'] == 'BulkGone'
    assert body['removed'][0]['quantity'] == 1
    assert body['removed'][0]['unit'] == 'ct'


def test_inventory_bulk_partial_not_found_is_not_a_404(client):
    _bulk_seed(client, 'BulkHalf', 'ct', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend', 'days': 3,
        'refs': [
            {'name': 'BulkHalf', 'unit': 'ct', 'location': 'fridge'},
            {'name': 'BulkGhostZzz', 'unit': 'ct', 'location': 'fridge'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 1
    assert len(body['not_found']) == 1
    assert body['not_found'][0]['name'] == 'BulkGhostZzz'
    _bulk_cleanup(client, 'BulkHalf', 'fridge')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k bulk -v`
Expected: FAIL — 404 responses (route does not exist), so the `assert response.status_code == 400` / `== 200` lines fail.

- [ ] **Step 3: Extract the serializer**

Replace `_item_response` (`api_server.py:2278-2287`) with:

```python
def _serialize_item(item):
    """An InventoryItem as a dict plus its computed expiry_status."""
    from lib.expiry import expiry_status

    d = item.to_dict()
    d["expiry_status"] = expiry_status(d.get("expires"))
    return d


def _item_response(item, status):
    """Serialize an InventoryItem with computed expiry_status, or 404 if None."""
    if item is None:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": status, "item": _serialize_item(item)})
```

- [ ] **Step 4: Add the route**

Append to `api_server.py` immediately after `api_inventory_freeze`:

```python
@app.route('/api/inventory/bulk', methods=['POST'])
def api_inventory_bulk():
    """Apply one action to many items in a single write.

    Body: {action, refs, days?, expires?, category?, to_location?} where
    `action` is one of remove | extend | set-expiry | set-category | move |
    freeze, and each ref is {name, unit, location} — the real uniqueness key,
    all three fields required. Ungated, like the sibling /api/inventory/* routes.

    Refs matching nothing come back in `not_found` instead of 404-ing the call:
    the client's list can be stale, and one dead ref must not discard the rest
    of the edits.
    """
    from lib.inventory import bulk_apply

    data = request.get_json(force=True, silent=True) or {}
    if not data.get('action'):
        return jsonify({"error": "'action' is required"}), 400
    refs = data.get('refs')
    if not isinstance(refs, list) or not refs:
        return jsonify({"error": "'refs' must be a non-empty list"}), 400

    params = {k: data[k] for k in ('days', 'expires', 'category', 'to_location')
              if k in data}
    try:
        result = bulk_apply(data['action'], refs, **params)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "applied",
        "applied": result["applied"],
        "items": [_serialize_item(i) for i in result["items"]],
        "removed": [_serialize_item(i) for i in result["removed"]],
        "not_found": result["not_found"],
    })
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k bulk -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Run the full API suites**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py tests/test_api_server.py -q`
Expected: PASS — no regressions from the `_item_response` refactor.

- [ ] **Step 7: Commit**

```bash
git add api_server.py tests/test_api_endpoints.py
git commit -m "feat: add POST /api/inventory/bulk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Selection UI on `/review`

**Files:**
- Modify: `templates/review.html`
- Test: `tests/test_api_endpoints.py` (the served-page assertions — there is no JS test harness in this repo, so the browser behavior is covered by the manual script in Task 6)

**Interfaces:**
- Consumes: `POST /api/inventory/bulk` (Task 4), the existing `/api/inventory`, `/api/inventory/add`, and the four single-item routes.
- Produces: no server interface. Internally, `openMenu(target, anchor)` now takes a **target object** instead of `(it, li)`:
  ```
  { location, category, expires,            // null when the target is a heterogeneous selection
    run(action, params, errLabel) -> Promise }
  ```
  built by either `rowTarget(it, li)` or `bulkTarget()`.

Key decisions baked in below:
- Selection lives in a `Set` of **merge keys**, not DOM positions, so it survives a re-render.
- `move` and `freeze` change a row's key (location changes, and rows can merge away), so after a bulk move/freeze the page clears the selection and reloads rather than patching stale keys. `extend` / `set-expiry` / `set-category` patch in place.
- `lastRemoved` becomes an **array**, so one undo path serves both the single-row and bulk removes.

- [ ] **Step 1: Add the bulk-bar markup and styles**

In `templates/review.html`, replace the `<header>` block (lines 57-60) with:

```html
<header>
  <input type="checkbox" id="selall" aria-label="Select all items">
  <h1>Inventory Review</h1>
  <button id="refresh" aria-label="Refresh">↻</button>
</header>
```

Immediately after `<div id="menu"></div>` (line 64), add:

```html
<div id="bulkbar" hidden>
  <button id="bulkclear" aria-label="Clear selection">✕</button>
  <span id="bulkcount"></span>
  <span class="actions">
    <button class="rm" id="bulkrm">Remove</button>
    <button data-bd="3">+3d</button><button data-bd="7">+7d</button>
    <button class="kebab" id="bulkkebab" aria-label="More actions">⋮</button>
  </span>
</div>
```

In the `<style>` block, append before the closing `</style>` (line 54):

```css
  li input[type=checkbox], header input[type=checkbox] {
    width: 22px; height: 22px; flex: none; accent-color: #4a90d9; margin: 0; }
  #bulkbar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 15;
             display: flex; align-items: center; gap: 10px;
             padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
             background: Canvas; border-top: 1px solid #8886;
             box-shadow: 0 -4px 16px #0003; }
  #bulkbar[hidden] { display: none; }
  #bulkcount { flex: 1; font-weight: 600; }
  #bulkbar .err { flex-basis: 100%; }
  body.has-bulk #toast { bottom: 88px; }
```

- [ ] **Step 2: Add selection state and key helpers**

In the `<script>` block, replace the state declarations (lines 73-78) with:

```js
const list = document.getElementById('list');
const empty = document.getElementById('empty');
const toast = document.getElementById('toast');
const menu = document.getElementById('menu');
const bulkbar = document.getElementById('bulkbar');
const selall = document.getElementById('selall');
let lastRemoved = null, toastTimer = null;
let menuTarget = null;
const selected = new Set();   // merge keys, so selection survives a re-render
const rows = new Map();       // merge key -> { it, li }

function keyOf(it){
  // Mirrors InventoryItem.merge_key(). The separator below is a NUL *escape*
  // (six characters), not a literal NUL byte — so a name containing the
  // separator can't collide with a different (name, unit, location) triple.
  return [it.name, it.unit, it.location]
    .map(s => (s || "").toLowerCase().trim()).join("\u0000");
}
function refOf(it){
  return { name: it.name, unit: it.unit, location: it.location };
}
function selectedEntries(){
  return [...selected].map(k => rows.get(k)).filter(Boolean);
}
```

- [ ] **Step 3: Render checkboxes and keep the bar in sync**

Replace `load()` (lines 100-107) and `row()` (lines 108-123) with:

```js
async function load(){
  list.innerHTML = "";
  rows.clear();
  let items;
  try { items = await (await fetch('/api/inventory')).json(); }
  catch(e){ empty.hidden = false; empty.textContent = "Couldn't load inventory. Tap ↻ to retry."; return; }
  empty.hidden = items.length > 0;
  const live = new Set();
  for (const it of sortItems(items)){
    const key = keyOf(it);
    live.add(key);
    const li = row(it, key);
    rows.set(key, { it, li });
    list.appendChild(li);
  }
  // Drop selections whose rows no longer exist.
  for (const k of [...selected]) if (!live.has(k)) selected.delete(k);
  renderBulk();
}
function row(it, key){
  const li = document.createElement('li');
  li.innerHTML =
    `<input type="checkbox" class="pick" aria-label="Select item">` +
    `<span class="emoji">${EMOJI[it.category] || "📦"}</span>` +
    `<span class="meta"><div class="name"></div><div class="sub">${subline(it)}</div></span>` +
    `<span class="actions">` +
    `<button class="rm">Remove</button>` +
    `<button data-d="3">+3d</button><button data-d="7">+7d</button>` +
    `<button class="kebab" aria-label="More actions">⋮</button></span>`;
  li.querySelector('.name').textContent = it.name;
  const pick = li.querySelector('.pick');
  pick.checked = selected.has(key);
  pick.onchange = () => {
    if (pick.checked) selected.add(key); else selected.delete(key);
    renderBulk();
  };
  li.querySelector('.rm').onclick = () => remove(it, li);
  li.querySelectorAll('button[data-d]').forEach(b =>
    b.onclick = () => extend(it, li, parseInt(b.dataset.d, 10)));
  li.querySelector('.kebab').onclick = (e) =>
    openMenu(rowTarget(it, li), e.currentTarget);
  return li;
}
function renderBulk(){
  const n = selected.size;
  bulkbar.hidden = n === 0;
  document.body.classList.toggle('has-bulk', n > 0);
  document.getElementById('bulkcount').textContent =
    n + " selected";
  selall.checked = n > 0 && n === rows.size;
  selall.indeterminate = n > 0 && n < rows.size;
  const e = bulkbar.querySelector('.err'); if (e && n === 0) e.remove();
}
```

- [ ] **Step 4: Wire Select All, clear, and the bulk request path**

Add after `renderBulk()`:

```js
selall.onchange = () => {
  selected.clear();
  if (selall.checked) for (const k of rows.keys()) selected.add(k);
  for (const { li } of rows.values())
    li.querySelector('.pick').checked = selall.checked;
  renderBulk();
};
document.getElementById('bulkclear').onclick = () => {
  selected.clear();
  for (const { li } of rows.values()) li.querySelector('.pick').checked = false;
  renderBulk();
};
function bulkError(msg){
  let e = bulkbar.querySelector('.err');
  if (!e){ e = document.createElement('div'); e.className = 'err';
           bulkbar.appendChild(e); }
  e.textContent = msg;
}
async function runBulk(action, params, errLabel){
  const entries = selectedEntries();
  if (!entries.length) return;
  let body;
  try {
    const r = await fetch('/api/inventory/bulk', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ action, refs: entries.map(e => refOf(e.it)), ...params }) });
    if (!r.ok){ bulkError(`Couldn't ${errLabel} — tap ↻`); return; }
    body = await r.json();
  } catch(e){ bulkError("Network error — tap ↻"); return; }

  const e = bulkbar.querySelector('.err'); if (e) e.remove();

  if (action === 'remove'){
    lastRemoved = body.removed;
    for (const item of body.removed){
      const entry = rows.get(keyOf(item));
      if (entry){ entry.li.remove(); rows.delete(keyOf(item)); }
    }
    selected.clear();
    showToast(`Removed ${body.removed.length} item${body.removed.length === 1 ? "" : "s"}`);
    renderBulk();
  } else if (action === 'move' || action === 'freeze'){
    // Both change a row's location — and therefore its key — and can merge two
    // rows into one. Patching by the old key would leave the selection stale.
    selected.clear();
    await load();
  } else {
    for (const item of body.items){
      const entry = rows.get(keyOf(item));
      if (entry) applyUpdate(entry.it, entry.li, item);
    }
    renderBulk();
  }
  if (body.not_found && body.not_found.length) await load();
}
document.getElementById('bulkrm').onclick = () => runBulk('remove', {}, "remove");
bulkbar.querySelectorAll('button[data-bd]').forEach(b =>
  b.onclick = () => runBulk('extend', { days: parseInt(b.dataset.bd, 10) }, "extend"));
document.getElementById('bulkkebab').onclick = (e) =>
  openMenu(bulkTarget(), e.currentTarget);
```

- [ ] **Step 5: Generalize the menu over a target**

Replace `closeMenu`, `menuAction`, and `openMenu` (lines 168-248) with:

```js
function rowTarget(it, li){
  const SINGLE = { 'set-expiry': '/api/inventory/set-expiry',
                   'set-category': '/api/inventory/set-category',
                   'move': '/api/inventory/move',
                   'freeze': '/api/inventory/freeze' };
  return {
    id: keyOf(it),
    location: it.location, category: it.category, expires: it.expires,
    async run(action, params, errLabel){
      applyUpdate(it, li, await post(SINGLE[action],
        { name: it.name, location: it.location, ...params }, li, errLabel));
    }
  };
}
function bulkTarget(){
  // A heterogeneous selection has no single current value, so every location
  // and category chip is offered rather than skipping "the current one".
  return {
    id: '__bulk__',
    location: null, category: null, expires: null,
    async run(action, params, errLabel){ await runBulk(action, params, errLabel); }
  };
}
function closeMenu(){
  menu.classList.remove('show'); menuTarget = null;
}
function menuAction(label, fn, cls){
  const b = document.createElement('button');
  b.className = 'mi' + (cls ? ' ' + cls : '');
  b.textContent = label;
  b.onclick = async () => { const t = menuTarget; closeMenu(); await fn(t); };
  return b;
}
function openMenu(target, anchor){
  // Re-tapping the *same* trigger closes; tapping a different one re-opens
  // against the new target. Targets are freshly built each call, so compare
  // their ids, not the objects.
  if (menuTarget && menuTarget.id === target.id &&
      menu.classList.contains('show')){ closeMenu(); return; }
  menuTarget = target;
  menu.innerHTML = '';

  // Set expiration date — native picker
  const dl = document.createElement('div'); dl.className = 'sub-label';
  dl.textContent = 'Expiration'; menu.appendChild(dl);
  const dp = document.createElement('input'); dp.type = 'date';
  if (target.expires) dp.value = target.expires;
  dp.onchange = async () => {
    if (!dp.value) return;
    const t = menuTarget; closeMenu();
    await t.run('set-expiry', { expires: dp.value }, "set date");
  };
  menu.appendChild(dp);
  menu.appendChild(menuAction('🚫 Remove expiration', (t) =>
    t.run('set-expiry', { expires: null }, "clear expiry")));
  menu.appendChild(menuAction('🧊 Mark as frozen', (t) =>
    t.run('freeze', {}, "freeze")));

  menu.appendChild(document.createElement('hr'));

  // Move to…
  const ml = document.createElement('div'); ml.className = 'sub-label';
  ml.textContent = 'Move to'; menu.appendChild(ml);
  const mc = document.createElement('div'); mc.className = 'chips';
  for (const loc of LOCATIONS){
    if (loc === target.location) continue;
    const b = document.createElement('button');
    b.textContent = loc;
    b.onclick = async () => {
      const t = menuTarget; closeMenu();
      await t.run('move', { to_location: loc }, "move");
    };
    mc.appendChild(b);
  }
  menu.appendChild(mc);

  // Category…
  const cl = document.createElement('div'); cl.className = 'sub-label';
  cl.textContent = 'Category'; menu.appendChild(cl);
  const cc = document.createElement('div'); cc.className = 'chips';
  for (const cat of CATEGORIES){
    if (cat === target.category) continue;
    const b = document.createElement('button');
    b.textContent = (EMOJI[cat] || "📦") + " " + cat;
    b.onclick = async () => {
      const t = menuTarget; closeMenu();
      await t.run('set-category', { category: cat }, "set category");
    };
    cc.appendChild(b);
  }
  menu.appendChild(cc);

  // Position anchored to the trigger, clamped to viewport.
  menu.classList.add('show');
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
  left = Math.max(8, left);
  let top = r.bottom + 4;
  if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
}
```

- [ ] **Step 6: Make undo restore an array**

Replace `remove()` (lines 130-138) with:

```js
async function remove(it, li){
  try {
    const r = await fetch('/api/inventory/remove', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name: it.name, location: it.location }) });
    if (!r.ok){ rowError(li, "Couldn't remove — tap ↻"); return; }
    lastRemoved = [it];
    selected.delete(keyOf(it)); rows.delete(keyOf(it));
    li.remove(); showToast(`Removed ${it.name}`);
    renderBulk();
  } catch(e){ rowError(li, "Network error — tap ↻"); }
}
```

Replace the undo handler (lines 261-271) with:

```js
document.getElementById('undo').onclick = async () => {
  if (!lastRemoved || !lastRemoved.length) return;
  const items = lastRemoved; lastRemoved = null; toast.classList.remove('show');
  await fetch('/api/inventory/add', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ items: items.map(it => ({
      name: it.name, quantity: it.quantity, unit: it.unit, category: it.category,
      location: it.location, purchased: it.purchased, expires: it.expires,
      for_recipe: it.for_recipe, source: it.source, notes: it.notes })) }) });
  load();
};
```

Also update the toast timeout (line 259) — it currently clears `lastRemoved` to `null`, which stays correct with an array, so no change is needed there. Verify it reads:

```js
  toastTimer = setTimeout(() => { toast.classList.remove('show'); lastRemoved = null; }, 5000);
```

- [ ] **Step 7: Verify the click-outside handler still covers the bulk kebab**

The document click handler closes the menu on any click that is neither inside
the menu nor on a `.kebab`. It needs no edit — but only because `#bulkkebab`
carries `class="kebab"`. Confirm that, or a tap on the bulk kebab will close the
menu in the same gesture that opens it.

Run: `/usr/bin/grep -n 'id="bulkkebab"' templates/review.html`
Expected: the matched line contains `class="kebab"`.

Then confirm the handler itself is untouched:

Run: `/usr/bin/grep -n "classList.contains('kebab')" templates/review.html`
Expected: exactly one match, inside the `document.addEventListener('click', …)` block.

- [ ] **Step 8: Add page-content tests**

Append to `tests/test_api_endpoints.py`:

```python
def test_review_page_has_bulk_selection_ui(client):
    """The bulk bar, select-all, and per-row checkbox ship in the page."""
    response = client.get('/review')
    assert response.status_code == 200
    html = response.data
    assert b'id="bulkbar"' in html
    assert b'id="selall"' in html
    assert b'class="pick"' in html
    assert b'/api/inventory/bulk' in html
```

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -q`
Expected: PASS — including the two `/review` tests.

- [ ] **Step 10: Commit**

```bash
git add templates/review.html tests/test_api_endpoints.py
git commit -m "feat: bulk select and edit on the inventory review page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Verify against the running server, then document

**Files:**
- Modify: `docs/API.md`, `BRANCH-STATUS.md`, `docs/plans/INDEX.md`

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 1405 baseline + ~35 new tests, zero failures. Record the exact number; it goes in the closeout note.

- [ ] **Step 2: Reload the API LaunchAgent**

`lib/` and `templates/` both changed, and `com.kitchenos.api` holds them in memory — without this the server serves the old page and 404s the new route.

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
curl -s http://localhost:5001/health
```
Expected: a healthy JSON response.

- [ ] **Step 3: Manual verification from a phone on the tailnet**

Open `http://chases-mac-mini.taila69703.ts.net:5001/review` (or whatever `KITCHENOS_API_BASE` resolves to) and confirm:

1. **Bulk extend** — select 3 items, tap `+7d`. All three sublines advance to the same date in one refresh, with no page reload.
2. **Bulk move with merge** — put two same-name/same-unit rows in different locations, select both, `⋮ → Move to → freezer`. The list reloads showing **one** row with the summed quantity.
3. **Bulk remove + undo** — note `select count(*) from inventory` first, select 5, Remove, then tap Undo on the toast. All five come back with their original quantity, unit, category, location, and expiry, and the count returns to its starting value:
   ```bash
   .venv/bin/python -c "from lib import inventory_db; print(len(inventory_db.fetch_inventory_rows()))"
   ```
4. **Heterogeneous selection** — select items in two different categories, open `⋮`. Every category chip is offered (none skipped), because the selection has no single current value.
5. **Select All** — the header checkbox selects every row; unchecking one row puts it in the indeterminate state.

- [ ] **Step 4: Document the endpoint**

In `docs/API.md`, find the `/api/inventory/freeze` entry and add after it:

```markdown
### POST /api/inventory/bulk

Apply one action to many items in a single read-modify-write. Ungated.

**Body:** `{action, refs, days?, expires?, category?, to_location?}`

- `action` — one of `remove`, `extend`, `set-expiry`, `set-category`, `move`, `freeze`
- `refs` — non-empty list of `{name, unit, location}`. All three fields are
  required: this route addresses rows by the real `(name, unit, location)`
  uniqueness key, unlike the single-item routes which match on
  `(name, location)` and can therefore hit the wrong row when a name repeats
  across units.
- Action parameters: `days` (extend), `expires` (set-expiry, nullable),
  `category` (set-category), `to_location` (move). `remove` and `freeze` take none.

**Response 200:** `{status: "applied", applied, items, removed, not_found}`

- `applied` — how many refs matched a row
- `items` — the resulting rows (empty for `remove`), each in the same shape as
  the single-item routes' `item`, including the computed `expiry_status`
- `removed` — the full pre-delete rows (empty except for `remove`), suitable for
  replaying into `/api/inventory/add` as an undo
- `not_found` — refs that matched nothing. These do **not** fail the call; a
  stale client list must not discard the edits that did land.

**Response 400:** unknown/missing action, empty `refs`, a ref missing `name`,
`unit`, or `location`, or a missing action parameter.

A `move` may merge rows: colliding `(name, unit)` at the destination sum their
quantities, and two *selected* rows moving to the same destination merge into
each other, so `items` can be shorter than `applied`.
```

- [ ] **Step 5: Tick BRANCH-STATUS.md through its stages**

Mark planning/dev/testing/docs complete with the evidence gathered above (test counts from Step 1, manual results from Step 3), and set `Current Stage: review`.

- [ ] **Step 6: Commit**

```bash
git add docs/API.md BRANCH-STATUS.md
git commit -m "docs: document POST /api/inventory/bulk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Request review**

Use `superpowers:requesting-code-review`. Then, on approval, `superpowers:finishing-a-development-branch` for the merge + closure ritual: archive `docs/completed/2026-07-25-bulk-inventory-editing.md`, move the design doc to **Done** in `docs/plans/INDEX.md`, remove the worktree, and confirm no `BRANCH-STATUS.md` is left in the repo root.

---

## Out of Scope

Carried over from the design doc — do not build these here:

- Giving `InventoryItem` a stable `id` (needs a migration; `write_inventory` delete-and-reinserts so DB ids churn).
- Migrating the single-item routes to `(name, unit, location)` addressing.
- The concurrent-writer lost-update TODO at `lib/inventory.py:308`. `bulk_apply` narrows the window from N writes to 1 but does not close it; the real fix is `INSERT … ON CONFLICT` in one transaction.
- Bulk quantity edit — every other row action generalizes to a selection, setting one quantity across heterogeneous items does not.
