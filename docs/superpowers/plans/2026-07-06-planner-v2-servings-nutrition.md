# Planner v2 — Serving Ledger, Daily Macros, Grocery Scaling, Nutrition Backfill v2, Recipe Detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add serving-level accounting (cook events → servings placed in slots/freezer/trash), daily macro totals on the planner, fractional grocery scaling from cooks, a trustworthy nutrition backfill with a review page, and a recipe detail page.

**Architecture:** Cook events and serving placements live in the existing SQLite DB (`data/kitchenos.db`); the weekly meal-plan Markdown stays a regenerated human-readable view. The Flask server (`api_server.py`) gains ledger CRUD + week-board + review endpoints; `templates/meal_planner.html` gains serving chips, a freezer tray, a trash target, and a daily totals row. The nutrition engine keeps its USDA-first design but reports coverage honestly and learns from human fixes via the existing `food_resolution` cache.

**Tech Stack:** Python 3.11, Flask, SQLite (`lib/inventory_db.py` pattern), vanilla JS + SortableJS (already vendored in `meal_planner.html`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-06-planner-v2-servings-nutrition-design.md`

## Global Constraints

- Repo root: `/Users/chaseeasterling/Dev/KitchenOS`. Run everything from there.
- Python: `.venv/bin/python`, tests: `.venv/bin/pytest` (Python 3.11).
- Tests MUST use the existing fixtures `tmp_db` and `tmp_vault` from `tests/conftest.py` — never touch the real DB/vault.
- `scale` is a float in 0.5 steps, range 0.5–4.0. `servings_produced` and placement `count` are floats.
- Placement invariant: `SUM(placements.count) <= cooks.servings_produced` (per cook). Over-placement is rejected (HTTP 409 / `OverplacementError`).
- Meal slots are exactly: `breakfast`, `lunch`, `snack`, `dinner`. Placement destinations are exactly: `slot`, `freezer`, `trash`.
- Coverage review threshold: 0.8. Per-serving kcal sanity range: [50, 2500].
- Never modify `ops/com.kitchenos.api.plist`, `.env`, or port config.
- The vault Markdown format must stay parseable by `lib/meal_plan_parser.parse_meal_plan` (calendar sync depends on it).
- Commit after every task with a conventional-commits message. Do not push.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `lib/inventory_db.py` | Modify | Add `cooks` + `placements` tables to `_SCHEMA` |
| `lib/serving_ledger.py` | Create | All ledger logic: cook/placement CRUD, invariant, week board, freezer, day totals |
| `lib/week_view.py` | Create | Render a week's Markdown from the ledger (falls back to legacy renderer) |
| `lib/meal_plan_parser.py` | Modify | Fractional `xN` parsing (`x1.5`), float servings |
| `lib/shopping_list_generator.py` | Modify | Float multipliers; source from cooks with link-scan fallback |
| `lib/nutrition_engine.py` | Modify | Coverage, mean confidence, unmatched list, sanity flags |
| `lib/ingredient_text.py` | Create | Pre-match text cleanup (Phase B) + alias table |
| `config/food_aliases.yml` | Create | Ingredient → canonical-food aliases |
| `backfill_nutrition.py` | Modify | Write `nutrition_coverage` / `nutrition_unmatched` |
| `api_server.py` | Modify | Ledger routes, week-board, nutrition-review routes, recipe detail route, extend `/api/recipes/<name>` |
| `templates/meal_planner.html` | Modify | Scale stepper, serving chips, freezer tray, trash, daily totals row |
| `templates/nutrition_review.html` | Create | Review page |
| `templates/recipe_detail.html` | Create | Recipe detail page with live scaling |
| `tests/test_serving_ledger.py` | Create | Ledger unit tests |
| `tests/test_week_view.py` | Create | Markdown view tests |
| `tests/test_api_ledger.py` | Create | Ledger/board API tests |
| `tests/test_shopping_from_cooks.py` | Create | Grocery-from-cooks tests |
| `tests/test_nutrition_coverage.py` | Create | Engine coverage/sanity tests |
| `tests/test_ingredient_text.py` | Create | Cleanup/alias tests |
| `tests/test_nutrition_review_api.py` | Create | Review API tests |
| `tests/test_recipe_detail.py` | Create | Detail route/API tests |

---

### Task 1: Ledger schema + cook/placement CRUD

**Files:**
- Modify: `lib/inventory_db.py` (append to `_SCHEMA`, around line 84)
- Create: `lib/serving_ledger.py`
- Test: `tests/test_serving_ledger.py`

**Interfaces:**
- Consumes: `lib.inventory_db.connect()` (opens DB, applies `_SCHEMA` idempotently).
- Produces (used by Tasks 2–6):
  - `class OverplacementError(ValueError)`
  - `create_cook(recipe: str, week: str, scale: float = 1.0, servings_produced: float | None = None, date: str | None = None, meal: str | None = None, initial_placement_count: float = 1.0, notes: str | None = None) -> dict` — if `servings_produced` is None it must be provided by the caller (raise `ValueError`); when `date`+`meal` given, auto-creates a slot placement of `min(initial_placement_count, servings_produced)`.
  - `get_cook(cook_id: int) -> dict | None` — dict has all columns plus `placements: list[dict]`, `unassigned: float`.
  - `update_cook(cook_id: int, **fields) -> dict` — updatable: `scale`, `servings_produced`, `date`, `meal`, `notes`, `cooked_at`. Raises `OverplacementError` if new `servings_produced` < placed sum.
  - `delete_cook(cook_id: int) -> None` (cascades placements).
  - `add_placement(cook_id: int, destination: str, count: float, date: str | None = None, meal: str | None = None) -> dict` — raises `OverplacementError` / `ValueError` on bad destination or missing date/meal for slots. Merges into an existing placement row with identical (cook_id, destination, date, meal).
  - `update_placement(placement_id: int, **fields) -> dict`, `delete_placement(placement_id: int) -> None`
  - `move_servings(placement_id: int, count: float, destination: str, date: str | None = None, meal: str | None = None) -> dict` — atomically decrement source (delete row if it hits 0), merge into target. Returns `{"from": dict|None, "to": dict}`.
  - `cooks_for_week(week: str) -> list[dict]` (each with placements + unassigned), `freezer_contents() -> list[dict]` (freezer placements joined with cook recipe/week/date), `placements_for_week(week: str) -> list[dict]` (slot placements whose `date` falls in the ISO week).

- [ ] **Step 1: Add tables to the schema**

In `lib/inventory_db.py`, append to the `_SCHEMA` string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS cooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe TEXT NOT NULL,
    week TEXT NOT NULL,
    date TEXT,
    meal TEXT,
    scale REAL NOT NULL DEFAULT 1.0,
    servings_produced REAL NOT NULL,
    cooked_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS placements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cook_id INTEGER NOT NULL REFERENCES cooks(id) ON DELETE CASCADE,
    destination TEXT NOT NULL CHECK (destination IN ('slot','freezer','trash')),
    date TEXT,
    meal TEXT,
    count REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_cooks_week ON cooks(week);
CREATE INDEX IF NOT EXISTS idx_placements_cook ON placements(cook_id);
```

(`connect()` runs `executescript(_SCHEMA)` with `IF NOT EXISTS` on every open, and already sets `PRAGMA foreign_keys = ON`, so the cascade works — no migration entry needed.)

- [ ] **Step 2: Write failing tests**

Create `tests/test_serving_ledger.py`:

```python
"""Serving ledger: cooks produce servings; every serving is placed."""
import pytest

from lib import serving_ledger as sl
from lib.serving_ledger import OverplacementError


def _mk_cook(**over):
    kw = dict(recipe="Chili", week="2026-W28", scale=1.5,
              servings_produced=6.0, date="2026-07-07", meal="dinner")
    kw.update(over)
    return sl.create_cook(**kw)


def test_create_cook_autoplaces_anchor_serving(tmp_db):
    cook = _mk_cook()
    assert cook["recipe"] == "Chili"
    assert cook["servings_produced"] == 6.0
    assert len(cook["placements"]) == 1
    p = cook["placements"][0]
    assert (p["destination"], p["date"], p["meal"], p["count"]) == \
        ("slot", "2026-07-07", "dinner", 1.0)
    assert cook["unassigned"] == 5.0


def test_create_cook_requires_servings_produced(tmp_db):
    with pytest.raises(ValueError):
        sl.create_cook(recipe="Chili", week="2026-W28", servings_produced=None)


def test_overplacement_rejected(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 5.0)
    with pytest.raises(OverplacementError):
        sl.add_placement(cook["id"], "trash", 0.5)


def test_placements_merge_on_same_target(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 1.0)
    sl.add_placement(cook["id"], "freezer", 2.0)
    rows = [p for p in sl.get_cook(cook["id"])["placements"]
            if p["destination"] == "freezer"]
    assert len(rows) == 1 and rows[0]["count"] == 3.0


def test_slot_placement_requires_date_and_meal(tmp_db):
    cook = _mk_cook()
    with pytest.raises(ValueError):
        sl.add_placement(cook["id"], "slot", 1.0)          # no date/meal
    with pytest.raises(ValueError):
        sl.add_placement(cook["id"], "nowhere", 1.0)       # bad destination


def test_move_servings_freezer_to_slot_conserves_count(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 3.0)
    result = sl.move_servings(frozen["id"], 2.0, "slot",
                              date="2026-07-14", meal="lunch")
    assert result["to"]["count"] == 2.0
    c = sl.get_cook(cook["id"])
    total_placed = sum(p["count"] for p in c["placements"])
    assert total_placed == 6.0 - c["unassigned"]
    freezer = [p for p in c["placements"] if p["destination"] == "freezer"]
    assert freezer[0]["count"] == 1.0


def test_move_all_servings_deletes_source_row(tmp_db):
    cook = _mk_cook()
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    sl.move_servings(frozen["id"], 2.0, "trash")
    dests = {p["destination"] for p in sl.get_cook(cook["id"])["placements"]}
    assert "freezer" not in dests and "trash" in dests


def test_shrinking_produced_below_placed_rejected(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 4.0)   # placed now 5.0
    with pytest.raises(OverplacementError):
        sl.update_cook(cook["id"], servings_produced=4.0)


def test_delete_cook_cascades(tmp_db):
    cook = _mk_cook()
    sl.delete_cook(cook["id"])
    assert sl.get_cook(cook["id"]) is None
    assert sl.freezer_contents() == []


def test_freezer_contents_joined_with_cook(tmp_db):
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 2.0)
    fz = sl.freezer_contents()
    assert len(fz) == 1
    assert fz[0]["recipe"] == "Chili" and fz[0]["count"] == 2.0
    assert fz[0]["cook_week"] == "2026-W28"


def test_cooks_for_week_filters(tmp_db):
    _mk_cook()
    _mk_cook(week="2026-W29", date="2026-07-15")
    assert len(sl.cooks_for_week("2026-W28")) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_serving_ledger.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'lib.serving_ledger'`

- [ ] **Step 4: Implement `lib/serving_ledger.py`**

```python
"""Serving ledger: cook events and where their servings went.

A *cook* is one preparation of a recipe at a fractional scale, producing
``servings_produced`` servings. Every serving is accounted for by a
*placement*: a (destination, date, meal, count) row. Destinations:

- ``slot``    eaten at a specific day/meal (date + meal required)
- ``freezer`` banked for later (no date; surfaces in the freezer tray)
- ``trash``   discarded (waste ledger)

Invariant: SUM(placements.count) <= servings_produced. The difference is
"unassigned" and surfaced by the UI. SQLite is authoritative; the weekly
Markdown file is a regenerated view (see lib/week_view.py).
"""
from __future__ import annotations

from typing import Optional

from lib import inventory_db

MEALS = ("breakfast", "lunch", "snack", "dinner")
DESTINATIONS = ("slot", "freezer", "trash")

_COOK_FIELDS = ("scale", "servings_produced", "date", "meal", "notes", "cooked_at")
_EPS = 1e-6


class OverplacementError(ValueError):
    """More servings placed than the cook produced."""


def _row_to_dict(row) -> dict:
    return dict(row)


def _validate_placement(destination: str, date: Optional[str], meal: Optional[str]):
    if destination not in DESTINATIONS:
        raise ValueError(f"destination must be one of {DESTINATIONS}")
    if destination == "slot":
        if not date or not meal:
            raise ValueError("slot placements require date and meal")
        if meal not in MEALS:
            raise ValueError(f"meal must be one of {MEALS}")


def _placed_sum(conn, cook_id: int, exclude_placement: Optional[int] = None) -> float:
    q = "SELECT COALESCE(SUM(count), 0) AS s FROM placements WHERE cook_id = ?"
    args = [cook_id]
    if exclude_placement is not None:
        q += " AND id != ?"
        args.append(exclude_placement)
    return float(conn.execute(q, args).fetchone()["s"])


def _check_capacity(conn, cook_id: int, adding: float,
                    exclude_placement: Optional[int] = None) -> None:
    row = conn.execute(
        "SELECT servings_produced FROM cooks WHERE id = ?", (cook_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"cook {cook_id} not found")
    placed = _placed_sum(conn, cook_id, exclude_placement)
    if placed + adding > float(row["servings_produced"]) + _EPS:
        raise OverplacementError(
            f"cook {cook_id}: placing {adding} exceeds capacity"
            f" ({placed} of {row['servings_produced']} already placed)"
        )


def _merge_or_insert(conn, cook_id: int, destination: str,
                     date: Optional[str], meal: Optional[str], count: float) -> dict:
    existing = conn.execute(
        "SELECT * FROM placements WHERE cook_id = ? AND destination = ?"
        " AND date IS ? AND meal IS ?",
        (cook_id, destination, date, meal),
    ).fetchone()
    if existing:
        new_count = float(existing["count"]) + count
        conn.execute("UPDATE placements SET count = ? WHERE id = ?",
                     (new_count, existing["id"]))
        return {**_row_to_dict(existing), "count": new_count}
    cur = conn.execute(
        "INSERT INTO placements (cook_id, destination, date, meal, count)"
        " VALUES (?, ?, ?, ?, ?)",
        (cook_id, destination, date, meal, count),
    )
    return {"id": cur.lastrowid, "cook_id": cook_id, "destination": destination,
            "date": date, "meal": meal, "count": count}


def create_cook(recipe: str, week: str, scale: float = 1.0,
                servings_produced: Optional[float] = None,
                date: Optional[str] = None, meal: Optional[str] = None,
                initial_placement_count: float = 1.0,
                notes: Optional[str] = None) -> dict:
    if not recipe or not week:
        raise ValueError("recipe and week are required")
    if servings_produced is None or servings_produced <= 0:
        raise ValueError("servings_produced is required and must be > 0")
    if meal is not None and meal not in MEALS:
        raise ValueError(f"meal must be one of {MEALS}")
    conn = inventory_db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO cooks (recipe, week, date, meal, scale,"
                " servings_produced, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (recipe, week, date, meal, float(scale),
                 float(servings_produced), notes),
            )
            cook_id = cur.lastrowid
            if date and meal and initial_placement_count > 0:
                _merge_or_insert(conn, cook_id, "slot", date, meal,
                                 min(float(initial_placement_count),
                                     float(servings_produced)))
        return get_cook(cook_id)
    finally:
        conn.close()


def get_cook(cook_id: int) -> Optional[dict]:
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM cooks WHERE id = ?", (cook_id,)).fetchone()
        if row is None:
            return None
        cook = _row_to_dict(row)
        placements = [
            _row_to_dict(p) for p in conn.execute(
                "SELECT * FROM placements WHERE cook_id = ? ORDER BY id", (cook_id,)
            ).fetchall()
        ]
        cook["placements"] = placements
        cook["unassigned"] = round(
            float(cook["servings_produced"]) - sum(p["count"] for p in placements), 3)
        return cook
    finally:
        conn.close()


def update_cook(cook_id: int, **fields) -> dict:
    bad = set(fields) - set(_COOK_FIELDS)
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    conn = inventory_db.connect()
    try:
        with conn:
            if "servings_produced" in fields:
                new_cap = float(fields["servings_produced"])
                placed = _placed_sum(conn, cook_id)
                if new_cap + _EPS < placed:
                    raise OverplacementError(
                        f"cook {cook_id}: {placed} servings already placed;"
                        f" cannot shrink to {new_cap}")
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE cooks SET {sets} WHERE id = ?",
                         (*fields.values(), cook_id))
    finally:
        conn.close()
    return get_cook(cook_id)


def delete_cook(cook_id: int) -> None:
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM cooks WHERE id = ?", (cook_id,))
    finally:
        conn.close()


def add_placement(cook_id: int, destination: str, count: float,
                  date: Optional[str] = None, meal: Optional[str] = None) -> dict:
    if count <= 0:
        raise ValueError("count must be > 0")
    if destination != "slot":
        date = meal = None
    _validate_placement(destination, date, meal)
    conn = inventory_db.connect()
    try:
        with conn:
            _check_capacity(conn, cook_id, float(count))
            return _merge_or_insert(conn, cook_id, destination, date, meal, float(count))
    finally:
        conn.close()


def update_placement(placement_id: int, **fields) -> dict:
    allowed = {"destination", "date", "meal", "count"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    conn = inventory_db.connect()
    try:
        with conn:
            row = conn.execute("SELECT * FROM placements WHERE id = ?",
                               (placement_id,)).fetchone()
            if row is None:
                raise ValueError(f"placement {placement_id} not found")
            merged = {**_row_to_dict(row), **fields}
            if merged["destination"] != "slot":
                merged["date"] = merged["meal"] = None
            _validate_placement(merged["destination"], merged["date"], merged["meal"])
            if float(merged["count"]) <= 0:
                raise ValueError("count must be > 0")
            _check_capacity(conn, row["cook_id"],
                            float(merged["count"]), exclude_placement=placement_id)
            conn.execute(
                "UPDATE placements SET destination = ?, date = ?, meal = ?,"
                " count = ? WHERE id = ?",
                (merged["destination"], merged["date"], merged["meal"],
                 float(merged["count"]), placement_id))
            return merged
    finally:
        conn.close()


def delete_placement(placement_id: int) -> None:
    conn = inventory_db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM placements WHERE id = ?", (placement_id,))
    finally:
        conn.close()


def move_servings(placement_id: int, count: float, destination: str,
                  date: Optional[str] = None, meal: Optional[str] = None) -> dict:
    """Move ``count`` servings out of a placement into a new destination."""
    if destination != "slot":
        date = meal = None
    _validate_placement(destination, date, meal)
    conn = inventory_db.connect()
    try:
        with conn:
            src = conn.execute("SELECT * FROM placements WHERE id = ?",
                               (placement_id,)).fetchone()
            if src is None:
                raise ValueError(f"placement {placement_id} not found")
            if count <= 0 or count > float(src["count"]) + _EPS:
                raise ValueError(
                    f"cannot move {count} of {src['count']} servings")
            remaining = float(src["count"]) - float(count)
            if remaining <= _EPS:
                conn.execute("DELETE FROM placements WHERE id = ?", (placement_id,))
                src_out = None
            else:
                conn.execute("UPDATE placements SET count = ? WHERE id = ?",
                             (remaining, placement_id))
                src_out = {**_row_to_dict(src), "count": remaining}
            # Total placed is conserved, so no capacity check needed.
            dest = _merge_or_insert(conn, src["cook_id"], destination,
                                    date, meal, float(count))
        return {"from": src_out, "to": dest}
    finally:
        conn.close()


def cooks_for_week(week: str) -> list[dict]:
    conn = inventory_db.connect()
    try:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cooks WHERE week = ? ORDER BY id", (week,)).fetchall()]
    finally:
        conn.close()
    return [get_cook(i) for i in ids]


def freezer_contents() -> list[dict]:
    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT p.id AS placement_id, p.count, c.id AS cook_id, c.recipe,"
            " c.week AS cook_week, c.date AS cook_date, c.created_at"
            " FROM placements p JOIN cooks c ON c.id = p.cook_id"
            " WHERE p.destination = 'freezer' AND p.count > 0"
            " ORDER BY c.created_at",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def placements_for_week(week: str) -> list[dict]:
    """All slot placements whose date falls inside the given ISO week."""
    from lib.meal_plan_parser import get_week_start_date
    from datetime import timedelta
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    start = get_week_start_date(year, week_num)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    conn = inventory_db.connect()
    try:
        marks = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT p.*, c.recipe FROM placements p"
            f" JOIN cooks c ON c.id = p.cook_id"
            f" WHERE p.destination = 'slot' AND p.date IN ({marks})"
            f" ORDER BY p.date, p.id",
            dates,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_serving_ledger.py -v`
Expected: all PASS

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `.venv/bin/pytest -q`
Expected: same pass/fail profile as before this task (note any pre-existing failures in the commit message if present).

- [ ] **Step 7: Commit**

```bash
git add lib/inventory_db.py lib/serving_ledger.py tests/test_serving_ledger.py
git commit -m "feat: serving ledger — cooks and placements with invariant"
```

---

### Task 2: Week board + per-day macro totals

**Files:**
- Modify: `lib/serving_ledger.py` (append)
- Test: `tests/test_serving_ledger.py` (append)

**Interfaces:**
- Consumes: Task 1 functions; `lib.recipe_parser.parse_recipe_file`; `lib.paths.recipes_dir()`.
- Produces (used by Tasks 3, 6, 7):
  - `recipe_macros(recipe_name: str, recipes_dir: Path) -> dict | None` — `{"calories": int, "protein": int, "carbs": int, "fat": int, "coverage": float | None}`; None when the file or `nutrition_calories` is missing.
  - `day_totals(week: str, recipes_dir: Path) -> dict[str, dict]` — keyed by ISO date, values `{"calories": float, "protein": float, "carbs": float, "fat": float, "incomplete": bool}`. `incomplete=True` when any contributing recipe has no macros or coverage < 0.8.
  - `week_board(week: str, recipes_dir: Path) -> dict` — `{"week", "cooks": [...], "freezer": [...], "day_totals": {...}}`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_serving_ledger.py`)

```python
RECIPE_MD = """---
title: Chili
servings: 4
nutrition_calories: 500
nutrition_protein: 30
nutrition_carbs: 40
nutrition_fat: 20
nutrition_coverage: 0.95
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | lb | ground beef |
"""

LOW_COVERAGE_MD = RECIPE_MD.replace("title: Chili", "title: Mystery Soup") \
                           .replace("nutrition_coverage: 0.95",
                                    "nutrition_coverage: 0.4")


def _write_recipe(vault, name, content):
    recipes = vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / f"{name}.md").write_text(content, encoding="utf-8")
    return recipes


def test_day_totals_sum_placed_servings(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Chili", RECIPE_MD)
    cook = _mk_cook()                                  # anchor: 1 serving Jul 7 dinner
    sl.add_placement(cook["id"], "slot", 2.0, date="2026-07-07", meal="dinner")
    sl.add_placement(cook["id"], "slot", 1.0, date="2026-07-08", meal="lunch")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["calories"] == 1500    # 3 servings x 500
    assert totals["2026-07-07"]["incomplete"] is False
    assert totals["2026-07-08"]["protein"] == 30


def test_day_totals_flags_low_coverage(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Mystery Soup", LOW_COVERAGE_MD)
    sl.create_cook(recipe="Mystery Soup", week="2026-W28", scale=1.0,
                   servings_produced=4.0, date="2026-07-07", meal="dinner")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["incomplete"] is True


def test_day_totals_flags_missing_recipe(tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    sl.create_cook(recipe="Ghost Recipe", week="2026-W28", scale=1.0,
                   servings_produced=2.0, date="2026-07-07", meal="dinner")
    totals = sl.day_totals("2026-W28", recipes)
    assert totals["2026-07-07"]["incomplete"] is True
    assert totals["2026-07-07"]["calories"] == 0


def test_week_board_shape(tmp_db, tmp_vault):
    recipes = _write_recipe(tmp_vault, "Chili", RECIPE_MD)
    cook = _mk_cook()
    sl.add_placement(cook["id"], "freezer", 2.0)
    board = sl.week_board("2026-W28", recipes)
    assert board["week"] == "2026-W28"
    assert len(board["cooks"]) == 1
    assert board["cooks"][0]["unassigned"] == 3.0
    assert len(board["freezer"]) == 1
    assert "2026-07-07" in board["day_totals"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_serving_ledger.py -v -k "day_totals or week_board"`
Expected: FAIL with `AttributeError: module 'lib.serving_ledger' has no attribute 'day_totals'`

- [ ] **Step 3: Implement** (append to `lib/serving_ledger.py`)

```python
COVERAGE_REVIEW_THRESHOLD = 0.8


def recipe_macros(recipe_name: str, recipes_dir) -> Optional[dict]:
    """Per-serving macros + coverage from a recipe's frontmatter, or None."""
    from lib.recipe_parser import parse_recipe_file
    path = recipes_dir / f"{recipe_name}.md"
    if not path.exists():
        return None
    fm = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
    if fm.get("nutrition_calories") is None:
        return None
    coverage = fm.get("nutrition_coverage")
    return {
        "calories": int(fm.get("nutrition_calories") or 0),
        "protein": int(fm.get("nutrition_protein") or 0),
        "carbs": int(fm.get("nutrition_carbs") or 0),
        "fat": int(fm.get("nutrition_fat") or 0),
        "coverage": float(coverage) if coverage is not None else None,
    }


def day_totals(week: str, recipes_dir) -> dict:
    totals: dict = {}
    macro_cache: dict = {}
    for p in placements_for_week(week):
        day = totals.setdefault(p["date"], {
            "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
            "incomplete": False,
        })
        name = p["recipe"]
        if name not in macro_cache:
            macro_cache[name] = recipe_macros(name, recipes_dir)
        macros = macro_cache[name]
        if macros is None:
            day["incomplete"] = True
            continue
        if macros["coverage"] is not None and \
                macros["coverage"] < COVERAGE_REVIEW_THRESHOLD:
            day["incomplete"] = True
        for k in ("calories", "protein", "carbs", "fat"):
            day[k] += macros[k] * float(p["count"])
    return totals


def week_board(week: str, recipes_dir) -> dict:
    return {
        "week": week,
        "cooks": cooks_for_week(week),
        "freezer": freezer_contents(),
        "day_totals": day_totals(week, recipes_dir),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_serving_ledger.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add lib/serving_ledger.py tests/test_serving_ledger.py
git commit -m "feat: week board and per-day macro totals from placements"
```

---

### Task 3: Fractional multipliers in parser/renderer + ledger→Markdown week view

**Files:**
- Modify: `lib/meal_plan_parser.py:12-23` (`MealEntry`), `:53-58` (regex), `:224-233` (`fmt_meal`)
- Modify: `lib/shopping_list_generator.py:51-54` (link regex → float), `:91-111` (`multiply_ingredients` float)
- Create: `lib/week_view.py`
- Test: `tests/test_week_view.py`, plus additions to existing `tests/test_meal_plan_parser.py` if present (check first: `ls tests | grep meal_plan`)

**Interfaces:**
- Consumes: `serving_ledger.cooks_for_week`, `placements_for_week`; `meal_plan_parser.get_week_start_date`, `rebuild_meal_plan_markdown`.
- Produces:
  - `MealEntry.servings: float` (was int) — downstream display code must tolerate floats.
  - Parser regex accepts `x1.5`: `r'\[\[(Meal:\s*)?([^\]]+)\]\]\s*(?:x([\d.]+))?'` in BOTH `lib/meal_plan_parser.py:53` and `lib/shopping_list_generator.py:51`; `float(mult)` instead of `int(mult)`.
  - `fmt_mult(x: float) -> str` in `meal_plan_parser` — `2.0 → "2"`, `1.5 → "1.5"`; `fmt_meal` emits `xN` whenever `servings != 1`.
  - `week_view.render_week_markdown(week: str, recipes_dir) -> str` — full weekly Markdown from the ledger: anchor cooks as `[[Recipe]] x<scale>`, non-anchor slot placements as `[[Recipe]] (leftover x<count>)` lines, a `> Freezer: N · Trash: N · Unassigned: N` summary line under each anchored slot, plus per-day totals under `### Notes`.
  - `week_view.write_week_markdown(week: str) -> None` — renders and writes `Meal Plans/<week>.md` ONLY when the ledger has cooks or placements for that week; otherwise leaves the file alone (legacy weeks untouched).

- [ ] **Step 1: Write failing tests**

Create `tests/test_week_view.py`:

```python
from lib import serving_ledger as sl
from lib import week_view
from lib.meal_plan_parser import parse_meal_plan, fmt_mult


def test_fmt_mult():
    assert fmt_mult(2.0) == "2"
    assert fmt_mult(1.5) == "1.5"
    assert fmt_mult(1.0) == "1"


def test_parser_accepts_fractional_multiplier():
    section = "## Monday (Jul 6)\n### Dinner\n[[Chili]] x1.5\n### Notes\n"
    days = parse_meal_plan(section, 2026, 28)
    assert days[0]["dinner"].servings == 1.5


def test_render_week_markdown_anchor_and_leftover(tmp_db, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    cook = sl.create_cook(recipe="Chili", week="2026-W28", scale=1.5,
                          servings_produced=6.0,
                          date="2026-07-07", meal="dinner")
    sl.add_placement(cook["id"], "slot", 1.0, date="2026-07-08", meal="lunch")
    sl.add_placement(cook["id"], "freezer", 2.0)
    md = week_view.render_week_markdown("2026-W28", recipes)
    assert "[[Chili]] x1.5" in md                      # anchor, Tuesday dinner
    assert "[[Chili]] (leftover x1)" in md             # Wednesday lunch
    assert "Freezer: 2" in md
    # Round-trips through the legacy parser (calendar sync depends on this)
    days = parse_meal_plan(md, 2026, 28)
    assert days[1]["dinner"].name == "Chili"           # Tue = index 1


def test_write_week_markdown_skips_ledgerless_weeks(tmp_db, tmp_vault):
    plans = tmp_vault / "Meal Plans"
    plans.mkdir(parents=True)
    legacy = plans / "2026-W20.md"
    legacy.write_text("# hand-made\n", encoding="utf-8")
    week_view.write_week_markdown("2026-W20")
    assert legacy.read_text(encoding="utf-8") == "# hand-made\n"
```

Note: `2026-07-06` is the Monday of ISO week 2026-W28; the anchor date `2026-07-07` is Tuesday.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_week_view.py -v`
Expected: FAIL (`No module named 'lib.week_view'`, `ImportError: cannot import name 'fmt_mult'`)

- [ ] **Step 3: Modify `lib/meal_plan_parser.py`**

1. `MealEntry.servings: float = 1.0` (line 21).
2. Line 53 regex: `r'\[\[(Meal:\s*)?([^\]]+)\]\]\s*(?:x([\d.]+))?'`; line 57: `servings = float(link_match.group(3)) if link_match.group(3) else 1.0`.
3. Add near the top (after imports):

```python
def fmt_mult(x: float) -> str:
    """Format a multiplier: whole numbers without a decimal point."""
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:g}"
```

4. In `fmt_meal` (line 224): replace the `if servings > 1` block with:

```python
        if float(servings) != 1:
            return f"{link} x{fmt_mult(servings)}"
        return link
```

- [ ] **Step 4: Modify `lib/shopping_list_generator.py`**

1. Line 51: same regex change (`x([\d.]+)`); line 54: `servings = float(mult) if mult else 1.0`. Update `extract_recipe_links` return-type comment to `(recipe_name, multiplier: float)`.
2. `multiply_ingredients(ingredients: list[dict], multiplier: float)` — body unchanged (`amount * multiplier` already works for floats; the `if multiplier == 1` guard still short-circuits).

- [ ] **Step 5: Implement `lib/week_view.py`**

```python
"""Render a week's meal-plan Markdown from the serving ledger.

The ledger (SQLite) is authoritative; this module regenerates the weekly
Markdown as a human-readable Obsidian view after every ledger mutation.
Weeks with no ledger rows are left alone so legacy hand-edited plans and
the link-scan shopping fallback keep working.
"""
from __future__ import annotations

from datetime import timedelta

from lib import paths, serving_ledger
from lib.meal_plan_parser import get_week_start_date, fmt_mult

MEALS = ("breakfast", "lunch", "snack", "dinner")
MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch",
               "snack": "Snack", "dinner": "Dinner"}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")


def _slot_lines(date_iso: str, meal: str, cooks: list[dict]) -> list[str]:
    lines: list[str] = []
    for cook in cooks:
        if cook["date"] == date_iso and cook["meal"] == meal:
            lines.append(f"[[{cook['recipe']}]] x{fmt_mult(cook['scale'])}")
            frozen = sum(p["count"] for p in cook["placements"]
                         if p["destination"] == "freezer")
            trashed = sum(p["count"] for p in cook["placements"]
                          if p["destination"] == "trash")
            summary = []
            if frozen:
                summary.append(f"Freezer: {fmt_mult(frozen)}")
            if trashed:
                summary.append(f"Trash: {fmt_mult(trashed)}")
            if cook["unassigned"] > 0:
                summary.append(f"Unassigned: {fmt_mult(cook['unassigned'])}")
            if summary:
                lines.append("> " + " · ".join(summary))
    for cook in cooks:
        for p in cook["placements"]:
            if (p["destination"] == "slot" and p["date"] == date_iso
                    and p["meal"] == meal
                    and not (cook["date"] == date_iso and cook["meal"] == meal)):
                lines.append(
                    f"[[{cook['recipe']}]] (leftover x{fmt_mult(p['count'])})")
    return lines


def render_week_markdown(week: str, recipes_dir) -> str:
    year, week_num = int(week[:4]), int(week.split("-W")[1])
    start = get_week_start_date(year, week_num)
    cooks = serving_ledger.cooks_for_week(week)
    # Leftovers from other weeks placed into this week's days:
    extra = serving_ledger.placements_for_week(week)
    known_ids = {c["id"] for c in cooks}
    foreign_cook_ids = {p["cook_id"] for p in extra
                        if p["cook_id"] not in known_ids}
    cooks += [serving_ledger.get_cook(cid) for cid in sorted(foreign_cook_ids)]
    totals = serving_ledger.day_totals(week, recipes_dir)

    def fmt_date(d):
        return d.strftime("%b %-d")

    end = start + timedelta(days=6)
    lines = [
        f"# Meal Plan - Week {week_num:02d}"
        f" ({fmt_date(start)} - {fmt_date(end)}, {year})",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week}",
        "```",
        "",
    ]
    for i, day_name in enumerate(DAY_NAMES):
        d = start + timedelta(days=i)
        date_iso = d.isoformat()
        lines.append(f"## {day_name} ({fmt_date(d)})")
        for meal in MEALS:
            lines.append(f"### {MEAL_LABELS[meal]}")
            lines.extend(_slot_lines(date_iso, meal, cooks))
        lines.append("### Notes")
        t = totals.get(date_iso)
        if t and any(t[k] for k in ("calories", "protein", "carbs", "fat")):
            flag = " ⚠" if t["incomplete"] else ""
            lines.append(
                f"Totals: {round(t['calories'])} kcal ·"
                f" {round(t['protein'])}p / {round(t['carbs'])}c /"
                f" {round(t['fat'])}f{flag}")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def write_week_markdown(week: str) -> None:
    """Regenerate the week's Markdown, only if the ledger owns that week."""
    cooks = serving_ledger.cooks_for_week(week)
    placements = serving_ledger.placements_for_week(week)
    if not cooks and not placements:
        return
    plans_dir = paths.meal_plans_dir()
    plans_dir.mkdir(parents=True, exist_ok=True)
    content = render_week_markdown(week, paths.recipes_dir())
    (plans_dir / f"{week}.md").write_text(content, encoding="utf-8")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_week_view.py -v`
Expected: all PASS

- [ ] **Step 7: Full suite** — the float change can ripple (e.g. tests asserting `servings == 1`).

Run: `.venv/bin/pytest -q`
Expected: PASS. Fix any test that asserts int servings by comparing to `1.0`/`1.5` (equality with ints still holds for whole floats, so most should pass untouched). `templates/*` python generators that render `x{servings}` must go through `fmt_mult` — grep: `grep -rn "x{.*servings" lib/ templates/*.py` and fix hits.

- [ ] **Step 8: Commit**

```bash
git add lib/meal_plan_parser.py lib/shopping_list_generator.py lib/week_view.py tests/test_week_view.py
git commit -m "feat: fractional multipliers + ledger-rendered weekly markdown view"
```

---

### Task 4: Ledger + week-board API routes

**Files:**
- Modify: `api_server.py` (add routes after `/api/meal-plan` PUT, i.e. after line 921)
- Test: `tests/test_api_ledger.py` (follow the client-fixture pattern in `tests/test_api_endpoints.py` — read it first and reuse its Flask test-client fixture)

**Interfaces:**
- Consumes: `serving_ledger` (Tasks 1–2), `week_view.write_week_markdown` (Task 3).
- Produces (consumed by the frontend, Tasks 6–7):
  - `GET /api/week-board/<week>` → `serving_ledger.week_board(...)` JSON.
  - `POST /api/cooks` body `{recipe, week, scale?, servings_produced, date?, meal?, initial_placement_count?}` → 201 + cook JSON.
  - `PATCH /api/cooks/<int:cook_id>` body = updatable fields → cook JSON. `DELETE /api/cooks/<int:cook_id>` → `{"status":"deleted"}`.
  - `POST /api/placements` body `{cook_id, destination, count, date?, meal?}` → placement JSON.
  - `PATCH /api/placements/<int:pid>`, `DELETE /api/placements/<int:pid>`.
  - `POST /api/placements/<int:pid>/move` body `{count, destination, date?, meal?}` → `{"from":..., "to":...}`.
  - All: 409 on `OverplacementError`, 400 on `ValueError`, 404 on missing ids. Every mutating route ends with `week_view.write_week_markdown(week)` for each affected week (a placement's week comes from its cook; a slot date outside the cook's week affects that date's week too — compute with `_iso_week_of(date_str)` helper below).

- [ ] **Step 1: Write failing tests**

Create `tests/test_api_ledger.py` (adjust the client fixture to match `tests/test_api_endpoints.py` — same import/app pattern):

```python
import json


def _create_cook(client, **over):
    body = dict(recipe="Chili", week="2026-W28", scale=1.5,
                servings_produced=6.0, date="2026-07-07", meal="dinner")
    body.update(over)
    return client.post("/api/cooks", json=body)


def test_create_and_board(client, tmp_db, tmp_vault):
    resp = _create_cook(client)
    assert resp.status_code == 201
    cook = resp.get_json()
    assert cook["unassigned"] == 5.0

    board = client.get("/api/week-board/2026-W28").get_json()
    assert len(board["cooks"]) == 1
    assert board["week"] == "2026-W28"


def test_overplacement_returns_409(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 99})
    assert resp.status_code == 409


def test_bad_destination_returns_400(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    resp = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "compost", "count": 1})
    assert resp.status_code == 400


def test_move_endpoint(client, tmp_db, tmp_vault):
    cook = _create_cook(client).get_json()
    frozen = client.post("/api/placements", json={
        "cook_id": cook["id"], "destination": "freezer", "count": 3}).get_json()
    resp = client.post(f"/api/placements/{frozen['id']}/move", json={
        "count": 2, "destination": "slot",
        "date": "2026-07-14", "meal": "lunch"})
    assert resp.status_code == 200
    assert resp.get_json()["to"]["count"] == 2.0


def test_mutations_regenerate_markdown(client, tmp_db, tmp_vault):
    _create_cook(client)
    plan = tmp_vault / "Meal Plans" / "2026-W28.md"
    assert plan.exists()
    assert "[[Chili]] x1.5" in plan.read_text(encoding="utf-8")


def test_week_board_invalid_week_400(client, tmp_db, tmp_vault):
    assert client.get("/api/week-board/garbage").status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_api_ledger.py -v`
Expected: FAIL with 404s (routes don't exist)

- [ ] **Step 3: Implement routes in `api_server.py`**

Insert after the `/api/meal-plan` PUT handler (after line 921):

```python
# --- Serving ledger -----------------------------------------------------------

def _ledger_error(fn):
    """Map ledger exceptions to HTTP codes; regenerate affected week views."""
    from functools import wraps
    from lib.serving_ledger import OverplacementError

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OverplacementError as e:
            return jsonify({"error": str(e)}), 409
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return wrapper


def _iso_week_of(date_str):
    from datetime import date as _date
    y, w, _ = _date.fromisoformat(date_str).isocalendar()
    return f"{y}-W{w:02d}"


def _regen_weeks(*weeks):
    from lib import week_view
    for wk in {w for w in weeks if w}:
        try:
            week_view.write_week_markdown(wk)
        except Exception as e:
            print(f"Warning: week view regen failed for {wk}: {e}", file=sys.stderr)


@app.route('/api/week-board/<week>', methods=['GET'])
@require_token
def api_week_board(week):
    from lib import serving_ledger
    if not re.match(r'^\d{4}-W\d{2}$', week):
        return jsonify({"error": "Invalid week format. Expected YYYY-WNN"}), 400
    return jsonify(serving_ledger.week_board(week, RECIPES_PATH))


@app.route('/api/cooks', methods=['POST'])
@require_token
@_ledger_error
def api_cook_create():
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    cook = serving_ledger.create_cook(
        recipe=data.get('recipe'), week=data.get('week'),
        scale=float(data.get('scale', 1.0)),
        servings_produced=data.get('servings_produced'),
        date=data.get('date'), meal=data.get('meal'),
        initial_placement_count=float(data.get('initial_placement_count', 1.0)),
        notes=data.get('notes'))
    _regen_weeks(cook["week"])
    return jsonify(cook), 201


@app.route('/api/cooks/<int:cook_id>', methods=['PATCH'])
@require_token
@_ledger_error
def api_cook_update(cook_id):
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    before = serving_ledger.get_cook(cook_id)
    if before is None:
        return jsonify({"error": "cook not found"}), 404
    cook = serving_ledger.update_cook(cook_id, **data)
    _regen_weeks(before["week"], cook["week"])
    return jsonify(cook)


@app.route('/api/cooks/<int:cook_id>', methods=['DELETE'])
@require_token
def api_cook_delete(cook_id):
    from lib import serving_ledger
    cook = serving_ledger.get_cook(cook_id)
    if cook is None:
        return jsonify({"error": "cook not found"}), 404
    affected = [cook["week"]] + [_iso_week_of(p["date"])
                                 for p in cook["placements"] if p.get("date")]
    serving_ledger.delete_cook(cook_id)
    _regen_weeks(*affected)
    return jsonify({"status": "deleted"})


@app.route('/api/placements', methods=['POST'])
@require_token
@_ledger_error
def api_placement_create():
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    p = serving_ledger.add_placement(
        cook_id=int(data.get('cook_id', 0)),
        destination=data.get('destination'),
        count=float(data.get('count', 0)),
        date=data.get('date'), meal=data.get('meal'))
    cook = serving_ledger.get_cook(p["cook_id"])
    _regen_weeks(cook["week"], _iso_week_of(p["date"]) if p.get("date") else None)
    return jsonify(p), 201


@app.route('/api/placements/<int:pid>', methods=['PATCH'])
@require_token
@_ledger_error
def api_placement_update(pid):
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    p = serving_ledger.update_placement(pid, **data)
    cook = serving_ledger.get_cook(p["cook_id"])
    _regen_weeks(cook["week"], _iso_week_of(p["date"]) if p.get("date") else None)
    return jsonify(p)


@app.route('/api/placements/<int:pid>', methods=['DELETE'])
@require_token
def api_placement_delete(pid):
    from lib import serving_ledger, inventory_db
    conn = inventory_db.connect()
    try:
        row = conn.execute("SELECT * FROM placements WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return jsonify({"error": "placement not found"}), 404
    cook = serving_ledger.get_cook(row["cook_id"])
    serving_ledger.delete_placement(pid)
    _regen_weeks(cook["week"],
                 _iso_week_of(row["date"]) if row["date"] else None)
    return jsonify({"status": "deleted"})


@app.route('/api/placements/<int:pid>/move', methods=['POST'])
@require_token
@_ledger_error
def api_placement_move(pid):
    from lib import serving_ledger
    data = request.get_json(force=True, silent=True) or {}
    result = serving_ledger.move_servings(
        pid, count=float(data.get('count', 0)),
        destination=data.get('destination'),
        date=data.get('date'), meal=data.get('meal'))
    cook = serving_ledger.get_cook(result["to"]["cook_id"])
    weeks = [cook["week"]]
    for part in (result.get("from"), result.get("to")):
        if part and part.get("date"):
            weeks.append(_iso_week_of(part["date"]))
    _regen_weeks(*weeks)
    return jsonify(result)
```

`RECIPES_PATH` already exists as a module constant in `api_server.py` (grep to confirm the exact name; it's used by the recipe endpoints). If it's named differently, use that name.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_ledger.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_api_ledger.py
git commit -m "feat: ledger + week-board API routes with 409 invariant handling"
```

---

### Task 5: Grocery list from cooks (fractional), link-scan fallback

**Files:**
- Modify: `lib/shopping_list_generator.py` (`generate_shopping_list`, ~line 240)
- Test: `tests/test_shopping_from_cooks.py`

**Interfaces:**
- Consumes: `serving_ledger.cooks_for_week`, `placements_for_week`; existing `load_recipe_ingredients`, `multiply_ingredients`, `aggregate_ingredients`, `compute_lines`.
- Produces: `generate_shopping_list(week, pantry=None)` — same return contract as today, plus `"source": "ledger" | "links"` key. Ledger path is used when the week has any cooks OR slot placements; the list is built ONLY from cooks anchored to that week (`ingredients × scale`) — freezer-sourced and leftover placements contribute nothing.

- [ ] **Step 1: Write failing tests**

Create `tests/test_shopping_from_cooks.py`:

```python
from pathlib import Path

import lib.shopping_list_generator as slg
from lib import serving_ledger as sl

RECIPE_MD = """---
title: Chili
servings: 4
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | dried beans |
| 1 | lb | ground beef |
"""


def _setup_vault(tmp_vault, monkeypatch):
    recipes = tmp_vault / "Recipes"
    plans = tmp_vault / "Meal Plans"
    recipes.mkdir(parents=True)
    plans.mkdir(parents=True)
    (recipes / "Chili.md").write_text(RECIPE_MD, encoding="utf-8")
    # Module constants are captured at import time — repoint them.
    monkeypatch.setattr(slg, "RECIPES_PATH", recipes)
    monkeypatch.setattr(slg, "MEAL_PLANS_PATH", plans)
    return recipes, plans


def test_ledger_week_scales_fractionally(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W28.md").write_text("# plan\n", encoding="utf-8")
    sl.create_cook(recipe="Chili", week="2026-W28", scale=1.5,
                   servings_produced=6.0, date="2026-07-07", meal="dinner")
    result = slg.generate_shopping_list("2026-W28")
    assert result["success"] is True
    assert result["source"] == "ledger"
    assert any("3 cup" in i and "dried beans" in i for i in result["items"])


def test_freezer_only_week_produces_empty_list(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W29.md").write_text("# plan\n", encoding="utf-8")
    cook = sl.create_cook(recipe="Chili", week="2026-W28", scale=1.0,
                          servings_produced=4.0,
                          date="2026-07-07", meal="dinner")
    frozen = sl.add_placement(cook["id"], "freezer", 2.0)
    sl.move_servings(frozen["id"], 2.0, "slot", date="2026-07-14", meal="dinner")
    result = slg.generate_shopping_list("2026-W29")
    assert result["success"] is True
    assert result["source"] == "ledger"
    assert result["items"] == []


def test_legacy_week_falls_back_to_link_scan(tmp_db, tmp_vault, monkeypatch):
    _, plans = _setup_vault(tmp_vault, monkeypatch)
    (plans / "2026-W20.md").write_text(
        "## Monday (May 11)\n### Dinner\n[[Chili]] x2\n", encoding="utf-8")
    result = slg.generate_shopping_list("2026-W20")
    assert result["success"] is True
    assert result["source"] == "links"
    assert any("4 cup" in i for i in result["items"])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_shopping_from_cooks.py -v`
Expected: FAIL (`KeyError: 'source'` or wrong quantities)

- [ ] **Step 3: Implement**

In `lib/shopping_list_generator.py`, replace `generate_shopping_list` (line 240) with:

```python
def _build_from_recipe_multipliers(pairs: list[tuple[str, float]],
                                   pantry: Optional[list[dict]] = None) -> dict:
    """Shared assembly: (recipe, multiplier) pairs → aggregated list dict."""
    all_ingredients = []
    loaded_recipes = []
    warnings = []
    for name, mult in pairs:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(multiply_ingredients(ingredients, mult))
            loaded_recipes.append(name)
    if not all_ingredients:
        return {"success": True, "items": [], "lines": [],
                "recipes": loaded_recipes, "warnings": warnings}
    aggregated = aggregate_ingredients(all_ingredients)
    lines = compute_lines(aggregated, pantry=pantry)
    if pantry is None:
        formatted = [line["display"] for line in lines]
    else:
        formatted = []
        for line in lines:
            tb = line.get("to_buy")
            if tb is None:
                continue
            formatted.append(format_ingredient(
                {"amount": tb.get("amount", ""), "unit": tb.get("unit", ""),
                 "item": line["item"]}))
    return {"success": True, "items": sorted(formatted), "lines": lines,
            "recipes": loaded_recipes, "warnings": warnings}


def generate_shopping_list(week: str, pantry: Optional[list[dict]] = None) -> dict:
    """Generate shopping list from a week — ledger cooks first, links fallback.

    The ledger path activates when the week has any cooks or slot placements.
    Only cooks anchored to the week contribute (ingredients × scale); meals
    eaten from the freezer add nothing.
    """
    from lib import serving_ledger

    cooks = serving_ledger.cooks_for_week(week)
    placements = serving_ledger.placements_for_week(week)
    if cooks or placements:
        pairs = [(c["recipe"], float(c["scale"])) for c in cooks]
        result = _build_from_recipe_multipliers(pairs, pantry=pantry)
        result["source"] = "ledger"
        return result

    try:
        meal_plan_path = parse_week_string(week)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    result = generate_shopping_list_from_path(meal_plan_path, pantry=pantry)
    result["source"] = "links"
    return result
```

Keep `generate_shopping_list_from_path` unchanged (the CLI `--plan custom.md` path still uses it directly). Note the ledger path returns `success: True` with empty items for a freezer-only week — the API caller at `api_server.py:564` treats `success` as the gate, so verify it handles empty `items` gracefully (it writes an empty checklist; that is correct behavior now).

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/bin/pytest tests/test_shopping_from_cooks.py tests/test_shopping_list*.py -v` (glob may differ — run `ls tests | grep -i shop` and include whatever exists)
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add lib/shopping_list_generator.py tests/test_shopping_from_cooks.py
git commit -m "feat: grocery list computed from cook events with link-scan fallback"
```

---

### Task 6: Planner UI — cooks, scale stepper, serving chips, freezer tray, trash

**Files:**
- Modify: `templates/meal_planner.html`
  - State block (~line 1224): add `weekBoard = null`
  - `init()` (~1244): load week board alongside meal plan
  - `buildGrid()` (~1365): unchanged here (totals row is Task 7)
  - `createGridCard` (~1532) / grid `onAdd` (~1475): cook-based cards
  - New: freezer tray panel + trash drop target + chip drag wiring
- Test: manual (no JS test rig in repo) — verification checklist below. Backend behavior is already covered by Task 4 tests.

**Interfaces:**
- Consumes: `GET /api/week-board/<week>`, `POST /api/cooks`, `PATCH/DELETE /api/cooks/<id>`, `POST /api/placements`, `POST /api/placements/<id>/move`, `DELETE /api/placements/<id>` (Task 4); `allRecipes[i].servings` (confirm `/api/recipes` includes `servings`; if not, extend that endpoint to include the frontmatter `servings` field — small server change, test in `tests/test_api_ledger.py`).
- Produces: DOM/UX contract used by Task 7 — grid cards carry `data-cook-id`; chips carry `data-cook-id`, `data-placement-id`, `data-count`.

**Implementation notes (follow these exactly):**

1. **Data flow switch.** On load, `loadMealPlan(week)` stays (it renders legacy weeks), then `loadWeekBoard(week)` fetches the board; if the board has cooks, clear the grid cards and render from the board instead (board wins). All mutations go through the ledger API; `saveMealPlan()`/`debounceSave()` are NOT called for board-backed weeks (the server regenerates Markdown itself). Gate with `const boardMode = weekBoard && (weekBoard.cooks.length > 0);`. First drop on a legacy week converts it: create the cook via API, then reload the board (the server rewrites the Markdown from the ledger; pre-existing legacy links for that week are imported first — see note 6).

2. **Drop = create cook** — in the grid `onAdd` handler (line 1475), replace the recipe-card branch:

```javascript
if (item.classList.contains('recipe-card')) {
    const name = item.dataset.name;
    const recipe = allRecipes.find(r => r.name === name);
    const baseServings = (recipe && recipe.servings) ? recipe.servings : 4;
    item.remove();  // placeholder; board re-render replaces it
    createCook(name, cell.dataset.day, cell.dataset.meal, 1.0, baseServings);
}

async function createCook(name, day, meal, scale, baseServings) {
    try {
        const resp = await fetch('/api/cooks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                recipe: name, week: currentWeek, scale: scale,
                servings_produced: baseServings * scale,
                date: dayDates[day], meal: meal,
                initial_placement_count: 1
            })
        });
        if (!resp.ok) { showToast((await resp.json()).error, 'error'); return; }
        await loadWeekBoard(currentWeek);
    } catch (err) { showToast('Failed to create cook', 'error'); }
}
```

3. **Cook card render** — `createCookCard(cook)` replaces `createGridCard` for board mode. Same visual shell (name link, image, remove button) plus:
   - Scale stepper: `− 1.5× +` buttons; `−`/`+` PATCH `/api/cooks/<id>` with `scale ± 0.5` (clamp 0.5–4.0) AND `servings_produced` recomputed as `baseServings × newScale` where `baseServings = cook.servings_produced / cook.scale`. On 409 (already placed more), show the error toast.
   - Serving chips row: for each slot placement AT this cell, a chip `🍽×N`; plus one "unassigned" chip `+N` when `cook.unassigned > 0`. Chips are SortableJS draggables in a shared group `'servings'`.
   - Remove button DELETEs the cook (confirm dialog: "Delete this cook and all its servings?").
   - Keep the 🍳 cooked button; it now PATCHes `cooked_at` (ISO now) on the cook AND calls the existing `/api/cook` consume endpoint with `{recipe, servings: cook.scale}`.

4. **Chip drag targets.** Register three kinds of Sortable containers in group `'servings'`:
   - Every `.grid-cell` (accept chip → `POST /api/placements/<id>/move` with the cell's `date`/`meal`; an "unassigned" chip instead does `POST /api/placements` with `{cook_id, destination:'slot', date, meal, count:1}`).
   - `#freezer-tray` panel (→ move/place with `destination:'freezer'`).
   - `#trash-target` (→ move/place with `destination:'trash'`).
   After every successful call, `loadWeekBoard(currentWeek)` re-renders (simple + correct beats optimistic DOM surgery on an iPad).
   Chips move ONE serving per drag (count: 1). Fractional remainders (< 1) render as a chip labeled `+0.5` and move their exact count.

5. **Freezer tray.** A third sidebar tab ("Freezer") next to Recipes/Meals listing `weekBoard.freezer`: each entry a chip-card with recipe name, `×count`, and age (`Math.round((Date.now() - Date.parse(created_at))/86400000)`d). Draggable into grid cells (→ `/api/placements/<id>/move` with `count: 1`, slot destination). The tray also accepts chips (freeze a serving).

6. **Legacy import on first board mutation.** Before `createCook` on a week whose board is empty BUT whose Markdown has `[[links]]`: call a new endpoint `POST /api/week-board/<week>/import-legacy` (add in api_server.py) that walks `parse_meal_plan` output and creates one cook per filled slot (`scale = entry.servings`, `servings_produced = recipe frontmatter servings × scale` — fall back to 4, `initial_placement_count = recipe servings × scale`, i.e. all servings assumed eaten at that slot), then proceed. Add a pytest for this endpoint in `tests/test_api_ledger.py`: a week file with `[[Chili]] x2` imports as one cook with scale 2.0.

7. **Trash target placement**: a fixed-position drop zone (`#trash-target`, 🗑 icon) bottom-right of the grid area, visible only while a chip drag is in progress (`onStart`/`onEnd` toggles a `body.dragging-serving` class; CSS shows/hides).

- [ ] **Step 1: Implement note 6's import-legacy endpoint + test (TDD: test first, red, implement, green)**
- [ ] **Step 2: Implement the JS/CSS per notes 1–5, 7**
- [ ] **Step 3: Manual verification (server + browser)**

Run: `cd /Users/chaseeasterling/Dev/KitchenOS && PORT=5010 KITCHENOS_VAULT=/tmp/kv-test KITCHENOS_DB=/tmp/kv-test.db .venv/bin/python api_server.py` (copy 2–3 real recipe files into `/tmp/kv-test/Recipes/` first). Open `http://localhost:5010/meal-planner`:
  - Drop a recipe on Tuesday dinner → card appears with `1×` stepper and unassigned chips.
  - Step scale to 1.5 → servings recompute; chips update.
  - Drag a chip to Wednesday lunch → leftover appears there; drag one to Freezer tab; drag one to trash.
  - Reload the page → identical state (server round-trip).
  - `cat "/tmp/kv-test/Meal Plans/"*.md` → anchor link `x1.5`, leftover line, freezer/trash summary present.
- [ ] **Step 4: Commit**

```bash
git add templates/meal_planner.html api_server.py tests/test_api_ledger.py
git commit -m "feat: planner serving chips, scale stepper, freezer tray, trash target"
```

---

### Task 7: Daily macro totals row in the grid

**Files:**
- Modify: `templates/meal_planner.html` — `buildGrid()` (after the `MEALS.forEach` loop, line 1394), plus a `renderDayTotals()` called from `loadWeekBoard`; CSS for `.totals-cell`.
- Test: manual (backend `day_totals` covered in Task 2).

**Interfaces:**
- Consumes: `weekBoard.day_totals` (Task 2 shape) and `dayDates` map (existing).

- [ ] **Step 1: Add the totals row to `buildGrid()`** (after line 1394):

```javascript
            // Daily totals row (populated by renderDayTotals)
            DAYS.forEach(day => {
                const cell = document.createElement('div');
                cell.className = 'totals-cell';
                cell.dataset.day = day;
                cell.innerHTML = '<span class="totals-empty">—</span>';
                grid.appendChild(cell);
            });
```

Update the grid CSS: the grid template gains one auto row (find the `grid-template-rows` / `repeat(7, ...)` rule near line 398 and append an `auto` row).

- [ ] **Step 2: Render totals**

```javascript
        function renderDayTotals() {
            const totals = (weekBoard && weekBoard.day_totals) || {};
            DAYS.forEach(day => {
                const cell = document.querySelector(`.totals-cell[data-day="${day}"]`);
                if (!cell) return;
                const t = totals[dayDates[day]];
                if (!t || (!t.calories && !t.protein && !t.carbs && !t.fat)) {
                    cell.innerHTML = '<span class="totals-empty">—</span>';
                    return;
                }
                const warn = t.incomplete
                    ? ' <span class="totals-warn" title="Some recipes have missing or low-confidence nutrition data">⚠</span>'
                    : '';
                cell.innerHTML =
                    `<div class="totals-kcal">${Math.round(t.calories)} kcal${warn}</div>` +
                    `<div class="totals-macros">${Math.round(t.protein)}p · ${Math.round(t.carbs)}c · ${Math.round(t.fat)}f</div>`;
            });
        }
```

Call `renderDayTotals()` at the end of `loadWeekBoard()` and after every board re-render.

- [ ] **Step 3: Manual verification** — with the Task 6 test server: place 2 chips of a recipe with known macros on one day; the day's cell shows `2 × per-serving` values; place a recipe with no nutrition frontmatter → ⚠ appears.
- [ ] **Step 4: Commit**

```bash
git add templates/meal_planner.html
git commit -m "feat: daily calorie/macro totals row with data-quality warning"
```

---

### Task 8: Nutrition engine — coverage, mean confidence, unmatched, sanity flags

**Files:**
- Modify: `lib/nutrition_engine.py` (`RecipeNutritionResult` ~line 57, rollup ~lines 311–354)
- Modify: `backfill_nutrition.py` (`_MANAGED_KEYS` line 34, `write_nutrition_to_file` line 101)
- Test: `tests/test_nutrition_coverage.py`

**Interfaces:**
- Consumes: existing engine internals (no resolver changes here).
- Produces:
  - `RecipeNutritionResult` gains: `coverage: float` (resolved lines / countable lines), `unmatched: list[str]` (item names of unresolved lines), `sanity_flags: list[str]` (`"kcal_out_of_range"`, `"dominant_line"`).
  - Confidence semantics change: `confidence` = mean of RESOLVED lines' confidences (0.0 when nothing resolved). `needs_review` = `servings_inferred or coverage < 0.8 or sanity_flags or confidence < REVIEW_CONFIDENCE`.
  - Frontmatter (via backfill): `nutrition_coverage: <float>`, `nutrition_unmatched: "<name>; <name>"` (semicolon-joined quoted scalar; omitted when empty and REMOVED if previously present — add both keys to `_MANAGED_KEYS`).
  - Lines with unit `"to taste"` are excluded from the coverage denominator (they are legitimately negligible).

- [ ] **Step 1: Write failing tests**

Create `tests/test_nutrition_coverage.py`. Mock resolution the way `tests/test_food_db.py` / existing engine tests do (read those first and reuse their stub pattern for `food_db.usda_search` / `usda_food_detail`). Core cases:

```python
"""Coverage/sanity semantics of calculate_recipe_nutrition.

Stub _resolve_food/_resolve_grams (monkeypatch) so no network is touched.
"""
import lib.nutrition_engine as ne
from lib import units


def _stub_resolvers(monkeypatch, resolves: dict):
    """resolves: item -> (per100g dict | None). None = unresolved."""
    def fake_resolve_food(item, *, use_cache, resolution_provider):
        per = resolves.get(item)
        if per is None:
            return None, 0.0, "unresolved"
        rec = {"source": "usda", "source_id": "1", "description": item,
               "per_100g": per, "portions": [], "density_g_per_ml": None}
        return rec, 0.8, "match"
    def fake_resolve_grams(amount, unit, item, record, *, use_cache, portion_provider):
        return units.GramResult(100.0, "direct", 1.0, False, note="")
    monkeypatch.setattr(ne, "_resolve_food", fake_resolve_food)
    monkeypatch.setattr(ne, "_resolve_grams", fake_resolve_grams)


PER = {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 5.0}


def test_full_coverage(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "beef": PER})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "beef", "amount": "1", "unit": "lb"}], 2)
    assert r.coverage == 1.0
    assert r.unmatched == []
    assert r.confidence == 0.8            # mean, not min
    assert r.needs_review is False


def test_one_unresolved_line_lowers_coverage_not_confidence(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "unicorn dust": None})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "unicorn dust", "amount": "1", "unit": "tsp"}], 2)
    assert r.coverage == 0.5
    assert r.unmatched == ["unicorn dust"]
    assert r.confidence == 0.8            # unresolved line excluded from mean
    assert r.needs_review is True         # coverage < 0.8


def test_to_taste_excluded_from_denominator(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "salt": None})
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "salt", "amount": "1", "unit": "to taste"}], 2)
    assert r.coverage == 1.0


def test_kcal_sanity_flag(monkeypatch, tmp_db):
    huge = {"calories": 9000.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    _stub_resolvers(monkeypatch, {"lard": huge})
    r = ne.calculate_recipe_nutrition(
        [{"item": "lard", "amount": "1", "unit": "cup"}], 1)
    assert "kcal_out_of_range" in r.sanity_flags
    assert r.needs_review is True


def test_dominant_line_flag(monkeypatch, tmp_db):
    _stub_resolvers(monkeypatch, {"beans": PER, "beef": PER})
    def fake_grams(amount, unit, item, record, *, use_cache, portion_provider):
        g = 1000.0 if item == "beef" else 50.0
        return units.GramResult(g, "direct", 1.0, False, note="")
    monkeypatch.setattr(ne, "_resolve_grams", fake_grams)
    r = ne.calculate_recipe_nutrition(
        [{"item": "beans", "amount": "1", "unit": "cup"},
         {"item": "beef", "amount": "1", "unit": "lb"}], 4)
    assert "dominant_line" in r.sanity_flags
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_nutrition_coverage.py -v`
Expected: FAIL (`TypeError: __init__ got unexpected keyword 'coverage'` / attribute errors)

- [ ] **Step 3: Implement in `lib/nutrition_engine.py`**

1. Add constants below `REVIEW_CONFIDENCE`:

```python
COVERAGE_REVIEW_THRESHOLD = 0.8
KCAL_SANITY_RANGE = (50, 2500)          # per serving
DOMINANT_LINE_FRACTION = 0.5            # one line > 50% of recipe grams
```

2. Extend the dataclass:

```python
    coverage: float = 1.0
    unmatched: list = field(default_factory=list)
    sanity_flags: list = field(default_factory=list)
```

3. In `calculate_recipe_nutrition`, track alongside the existing loop:
   - `countable = 0`, `resolved_count = 0`, `resolved_confs = []`, `unmatched = []`, `grams_list = []`.
   - Per line: `is_negligible = (unit or "").strip().lower() == "to taste"`; if not negligible → `countable += 1`. On the unresolved-food branch: `unmatched.append(item)` (only when not negligible). On the resolved-with-grams branch: `resolved_count += 1` (when not negligible), `resolved_confs.append(line_conf)`, `grams_list.append(gr.grams)`. On the resolved-food-but-unresolved-grams branch: also `unmatched.append(item)` when not negligible.
4. Replace the rollup lines 337–343 with:

```python
    source = next(iter(sources)) if len(sources) == 1 else "mixed"
    coverage = round(resolved_count / countable, 2) if countable else 0.0
    confidence = round(sum(resolved_confs) / len(resolved_confs), 2) \
        if resolved_confs else 0.0

    sanity_flags: list[str] = []
    lo, hi = KCAL_SANITY_RANGE
    if not (lo <= per_serving.calories <= hi):
        sanity_flags.append("kcal_out_of_range")
    total_grams = sum(grams_list)
    if total_grams and max(grams_list) / total_grams > DOMINANT_LINE_FRACTION \
            and len(grams_list) > 1:
        sanity_flags.append("dominant_line")

    needs_review = (
        servings_inferred
        or coverage < COVERAGE_REVIEW_THRESHOLD
        or bool(sanity_flags)
        or confidence < REVIEW_CONFIDENCE
    )
```

and pass `coverage=coverage, unmatched=unmatched, sanity_flags=sanity_flags, confidence=confidence` into the result. (Delete the old `recipe_conf = min(...)` line; `confidences` list can stay for the audit trail.)

5. In `backfill_nutrition.py`: add `"nutrition_coverage", "nutrition_unmatched"` to `_MANAGED_KEYS`; in `write_nutrition_to_file` add:

```python
    updates["nutrition_coverage"] = result.coverage
    if result.unmatched:
        joined = "; ".join(result.unmatched)
        updates["nutrition_unmatched"] = f'"{joined}"'
```

For the removal case (previously written, now empty): after building `updates`, if `not result.unmatched`, post-process `new_fm` to drop any `nutrition_unmatched:` line (simplest: `new_fm = "\n".join(l for l in new_fm.split("\n") if not l.startswith("nutrition_unmatched:")) `— apply before the trailing-newline check, only when `not result.unmatched`).

- [ ] **Step 4: Run tests + existing engine/backfill tests**

Run: `.venv/bin/pytest tests/test_nutrition_coverage.py tests/test_backfill_nutrition.py tests/test_nutrition*.py -v` (include whatever `ls tests | grep nutrition` shows)
Expected: new tests PASS; fix any existing test asserting `min()` confidence semantics to the new mean/coverage semantics (that behavior change is the point of this task — update the assertions, don't preserve `min()`).

- [ ] **Step 5: Commit**

```bash
git add lib/nutrition_engine.py backfill_nutrition.py tests/test_nutrition_coverage.py
git commit -m "feat: nutrition coverage, mean confidence, unmatched list, sanity flags"
```

---

### Task 9: Pre-match ingredient text cleanup + alias table

**Files:**
- Create: `lib/ingredient_text.py`, `config/food_aliases.yml`
- Modify: `lib/nutrition_engine.py:110` (`_resolve_food` — clean before normalize)
- Test: `tests/test_ingredient_text.py`

**Interfaces:**
- Consumes: nothing new (pure text).
- Produces:
  - `clean_for_matching(item: str) -> str` — strips `(...)` parentheticals, `*(inferred)*` markers, prep phrases, doubled words, excess whitespace.
  - `apply_aliases(item: str) -> str` — exact-match (case-insensitive, post-clean) lookup in `config/food_aliases.yml`; returns the canonical name or the input.
  - `_resolve_food` calls `norm = units._normalize_item(apply_aliases(clean_for_matching(item)))` — cache keys change for affected items, which simply re-resolves them once.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ingredient_text.py`:

```python
from lib.ingredient_text import clean_for_matching, apply_aliases


def test_strips_parentheticals():
    assert clean_for_matching(
        "blanched almond flour (spooned and leveled)") == "blanched almond flour"


def test_strips_inferred_marker():
    assert clean_for_matching("olive oil *(inferred)*") == "olive oil"


def test_strips_prep_phrases():
    assert clean_for_matching("extra-virgin olive oil, plus more for serving") \
        == "extra-virgin olive oil"
    assert clean_for_matching("fresh cilantro, finely chopped") == "fresh cilantro"


def test_collapses_doubled_words():
    assert clean_for_matching("garlic garlic cloves") == "garlic cloves"


def test_alias_lookup():
    assert apply_aliases("evoo") == "olive oil"


def test_alias_passthrough():
    assert apply_aliases("ground beef") == "ground beef"
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ingredient_text.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Implement `lib/ingredient_text.py`**

```python
"""Pre-match ingredient text cleanup ("Phase B") + alias table.

USDA descriptions are terse ("Oil, olive, salad or cooking"); recipe lines
are chatty ("extra-virgin olive oil (plus more for serving)"). Stripping the
chat before word-overlap matching is the cheapest accuracy win available.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "food_aliases.yml"

# Trailing prep/serving phrases introduced by a comma.
_PREP_TAIL = re.compile(
    r",\s*(plus more[^,]*|finely [a-z]+|coarsely [a-z]+|roughly [a-z]+"
    r"|thinly [a-z]+|chopped|minced|diced|sliced|grated|shredded|melted"
    r"|softened|divided|to serve|for serving|for garnish|optional"
    r"|at room temperature)\b.*$",
    re.IGNORECASE,
)


def clean_for_matching(item: str) -> str:
    text = item or ""
    text = re.sub(r"\*\(inferred\)\*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^)]*\)", " ", text)          # parentheticals
    text = _PREP_TAIL.sub("", text)
    # collapse immediately doubled words ("garlic garlic cloves")
    text = re.sub(r"\b(\w+)( \1\b)+", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,.*")


@lru_cache(maxsize=1)
def _aliases() -> dict:
    if not _ALIASES_PATH.exists():
        return {}
    data = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in data.items()}


def apply_aliases(item: str) -> str:
    return _aliases().get((item or "").lower(), item)
```

Create `config/food_aliases.yml` (seed set; grows via review-page fixes and hand edits):

```yaml
# ingredient text (lowercase) -> canonical food name for USDA matching
evoo: olive oil
extra-virgin olive oil: olive oil
scallions: green onions
cilantro leaves: cilantro
kosher salt: salt
flaky sea salt: salt
neutral oil: canola oil
```

Wire into `lib/nutrition_engine.py` `_resolve_food` (line 110):

```python
    from lib.ingredient_text import clean_for_matching, apply_aliases
    norm = units._normalize_item(apply_aliases(clean_for_matching(item)))
```

(Import at module top instead if the engine has no circular-import risk — it doesn't; prefer top-level.)

- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_ingredient_text.py tests/test_nutrition_coverage.py -v` → PASS. Check `yaml` is already a dependency (`grep -i yaml requirements.txt` — `pyyaml` is used by recipe parsing; if truly absent add `pyyaml` to `requirements.txt`).

- [ ] **Step 5: Commit**

```bash
git add lib/ingredient_text.py config/food_aliases.yml lib/nutrition_engine.py tests/test_ingredient_text.py
git commit -m "feat: pre-match ingredient text cleanup and alias table"
```

---

### Task 10: Nutrition review API

**Files:**
- Modify: `api_server.py` (add after the `/api/nutrition/<week>` route, line 1804)
- Test: `tests/test_nutrition_review_api.py`

**Interfaces:**
- Consumes: `calculate_recipe_nutrition` (Task 8 result shape), `backfill_nutrition.write_nutrition_to_file`, `extract_ingredients`, `inventory_db.put_food_resolution/put_food_cache`, `food_db.usda_search/usda_food_detail`, `ingredient_text` (Task 9).
- Produces (consumed by the review page, Task 11):
  - `GET /api/nutrition-review/recipes` → `[{name, coverage, confidence, calories, needs_review, unmatched: [..], flags: [..]}]` sorted worst-first (coverage asc, then confidence asc). Reads frontmatter only (fast).
  - `GET /api/nutrition-review/recipe/<name>` → recomputes live: `{name, servings, result: {per_serving, coverage, confidence, unmatched, sanity_flags}, lines: [{item, amount, unit, grams, grams_method, food_source, food_description, confidence, needs_review, candidates: [{source_id, description}]}]}`. Candidates fetched via `food_db.usda_search` ONLY for lines with `needs_review` or `confidence < 0.8` (limit 5).
  - `POST /api/nutrition-review/resolve` body `{item, source_id, recipe?}` → pins the match: `usda_food_detail(source_id)` → `put_food_cache` + `put_food_resolution(norm, "usda", source_id, 1.0, "human")`; when `recipe` given, recompute + `write_nutrition_to_file` for it; returns `{status, recipe_result?}`. Also `{item, negligible: true}` marks the item resolved-as-zero: `put_food_resolution(norm, "none", "0", 1.0, "human-negligible")` — and `_resolve_food` must learn to honor resolver `"human-negligible"` by returning a zero-macro record (add that check right after the cache lookup, with a test).
  - `POST /api/nutrition-review/recompute` body `{recipe}` → rerun backfill for one file, return new summary.

- [ ] **Step 1: Write failing tests** (stub network: monkeypatch `lib.food_db.usda_search`/`usda_food_detail` as in `tests/test_food_db.py`; use `tmp_vault` with 2 recipe files — one with `nutrition_coverage: 0.4` + `nutrition_unmatched`, one clean; use the Flask client fixture)

Create `tests/test_nutrition_review_api.py` (adapt the `client` fixture import from `tests/test_api_endpoints.py`; the USDA stub mirrors `tests/test_food_db.py`'s record shape — read both first and adjust the stub class if the real `FoodRecord` differs):

```python
"""Nutrition review API: ranked queue, candidates, human match pinning."""
import pytest

from lib import inventory_db

WEAK_MD = """---
title: Mystery Soup
servings: 4
source_url: "https://example.com/soup"
nutrition_calories: 100
nutrition_protein: 5
nutrition_carbs: 10
nutrition_fat: 2
nutrition_coverage: 0.4
nutrition_unmatched: "unicorn dust"
needs_review: true
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | cup | dried beans |
| 1 | tsp | unicorn dust |
"""

STRONG_MD = WEAK_MD.replace("title: Mystery Soup", "title: Solid Stew") \
                   .replace("nutrition_coverage: 0.4", "nutrition_coverage: 1.0") \
                   .replace('nutrition_unmatched: "unicorn dust"\n', "") \
                   .replace("needs_review: true\n", "")


class _Rec:
    def __init__(self, source_id, description):
        self.source_id = source_id
        self.description = description
        self.per_100g = _Per()
        self.portions = []
        self.density_g_per_ml = None


class _Per:
    def to_dict(self):
        return {"calories": 100.0, "protein": 5.0, "carbs": 10.0, "fat": 2.0}


@pytest.fixture
def review_vault(tmp_db, tmp_vault, monkeypatch):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True)
    (recipes / "Mystery Soup.md").write_text(WEAK_MD, encoding="utf-8")
    (recipes / "Solid Stew.md").write_text(STRONG_MD, encoding="utf-8")
    import lib.food_db as food_db
    monkeypatch.setattr(food_db, "usda_search",
                        lambda q: [_Rec("111", "Beans, dry"),
                                   _Rec("222", "Dust, unicorn")])
    monkeypatch.setattr(food_db, "usda_food_detail",
                        lambda fid: _Rec(fid, "Dust, unicorn"))
    return recipes


def test_review_list_ranked_worst_first(client, review_vault):
    resp = client.get("/api/nutrition-review/recipes")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert rows[0]["name"] == "Mystery Soup"
    assert rows[0]["coverage"] == 0.4
    assert "unicorn dust" in rows[0]["unmatched"]


def test_recipe_detail_includes_candidates_for_weak_lines(client, review_vault):
    resp = client.get("/api/nutrition-review/recipe/Mystery Soup")
    assert resp.status_code == 200
    data = resp.get_json()
    weak = [l for l in data["lines"] if l["needs_review"]
            or l["confidence"] < 0.8]
    assert weak and len(weak[0]["candidates"]) >= 1
    assert weak[0]["candidates"][0]["source_id"]


def test_resolve_pins_match_and_recomputes(client, review_vault):
    resp = client.post("/api/nutrition-review/resolve", json={
        "item": "unicorn dust", "source_id": "222", "recipe": "Mystery Soup"})
    assert resp.status_code == 200
    row = inventory_db.get_food_resolution("unicorn dust")
    assert row and row["resolver"] == "human"
    md = (review_vault / "Mystery Soup.md").read_text(encoding="utf-8")
    assert "nutrition_coverage: 1.0" in md


def test_resolve_negligible(client, review_vault):
    resp = client.post("/api/nutrition-review/resolve", json={
        "item": "unicorn dust", "negligible": True, "recipe": "Mystery Soup"})
    assert resp.status_code == 200
    row = inventory_db.get_food_resolution("unicorn dust")
    assert row and row["resolver"] == "human-negligible"
```

Note: `get_food_resolution` keys are normalized via `units._normalize_item` — the resolve endpoint must store under the same normalized key the engine looks up (`units._normalize_item(apply_aliases(clean_for_matching(item)))`); if the literal-key assertions above fail on normalization, assert via the normalized key instead.

- [ ] **Step 2: Run to verify failure** — 404s.

- [ ] **Step 3: Implement the three routes + the `human-negligible` branch in `_resolve_food`**

In `lib/nutrition_engine.py` `_resolve_food`, replace the existing cache-check block (lines 115–120) with:

```python
    if use_cache:
        res = inventory_db.get_food_resolution(norm)
        if res and res.get("resolver") == "human-negligible":
            record = {"query_norm": norm, "source": "none", "source_id": "0",
                      "description": "negligible (human)", "per_100g":
                      {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                      "portions": [], "density_g_per_ml": None}
            return record, 1.0, "human-negligible"
        if res and res.get("resolver") != "llm-portion":
            cached = inventory_db.get_food_cache(norm, res["source"])
            if cached:
                return cached, res["confidence"], "cache"
```

Routes (after line 1804 of `api_server.py`) — follow the shapes in the Interfaces block; reuse `parse_recipe_file`, `backfill_nutrition.extract_ingredients` (import the module — it has no side effects beyond `load_dotenv`), `calculate_recipe_nutrition(...)` with default providers, and `RECIPES_PATH.glob("*.md")` for the list endpoint. The list endpoint must skip non-recipe files the same way `collect_all_recipes` does (dot-prefixed).

- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_nutrition_review_api.py -v` → PASS.
- [ ] **Step 5: Commit**

```bash
git add api_server.py lib/nutrition_engine.py tests/test_nutrition_review_api.py
git commit -m "feat: nutrition review API — ranked queue, candidates, human match pinning"
```

---

### Task 11: Nutrition review page

**Files:**
- Create: `templates/nutrition_review.html`
- Modify: `api_server.py` — add `GET /nutrition-review` serving the template (same `open(...).read()` pattern as `/system-health`, line 1814); add a "Review" link in the meal planner header nav.
- Test: route smoke test appended to `tests/test_nutrition_review_api.py` (`GET /nutrition-review` → 200, contains `id="review-list"`); rest manual.

**Page contract (single-file HTML+JS, same style as `system_health.html`):**
- Loads `/api/nutrition-review/recipes` into a table: Recipe · Coverage (bar) · Confidence · kcal/serving · flags. Sorted worst-first; a recipe row click loads `/api/nutrition-review/recipe/<name>` into an expandable panel.
- The panel lists ingredient lines: item, grams, matched food description, confidence. Weak lines render a `<select>` of candidates + "Negligible" + "Search…" (free-text re-query via the same endpoint with `?q=` — add that param to the detail route: when present, return candidates for that query string only).
- Choosing a candidate → `POST /api/nutrition-review/resolve {item, source_id, recipe}` → panel re-renders with the returned updated result; toast shows new coverage.
- Header: count of recipes below 0.8 coverage + a "Re-run backfill for all flagged" button → sequential `POST /api/nutrition-review/recompute` per flagged recipe with a progress counter (client-side loop, no new bulk endpoint).

- [ ] **Step 1: Smoke test first** (route 200 + marker div), run red.
- [ ] **Step 2: Implement page + route + nav link.**
- [ ] **Step 3: Manual verification** — with the dev server + a copied real vault (`cp -r` a few recipes): open `/nutrition-review`, fix one bad match end-to-end, confirm the recipe file's frontmatter updated (`grep nutrition_ "<vault>/Recipes/<name>.md"`) and `food_resolution` has a `human` row (`sqlite3 <db> "select * from food_resolution where resolver like 'human%'"`).
- [ ] **Step 4: Commit**

```bash
git add templates/nutrition_review.html api_server.py templates/meal_planner.html tests/test_nutrition_review_api.py
git commit -m "feat: nutrition review page — fix matches, teach the resolver"
```

---

### Task 12: Recipe detail page with live scaling

**Files:**
- Modify: `api_server.py` — extend `GET /api/recipes/<name>` (line 469) to include `ingredients` (parsed table), `instructions_html` or raw body sections, and all `nutrition_*` + `servings` frontmatter; add `GET /recipe/<name>` page route.
- Create: `templates/recipe_detail.html`
- Test: `tests/test_recipe_detail.py`

**Interfaces:**
- Consumes: `parse_recipe_file`, `parse_ingredient_table`, existing recipe-listing helpers in `api_server.py` (read the current `/api/recipes/<name>` handler first and extend, don't replace).
- Produces:
  - `GET /api/recipes/<name>` additionally returns: `servings: int`, `ingredients: [{amount, unit, item}]`, `body_markdown: str` (full body), `nutrition: {calories, protein, carbs, fat, coverage, confidence, source} | null`, `image: str | null`, `source_url: str | null`.
  - `GET /recipe/<name>` → 200 HTML (404 page for unknown recipe).
  - Page JS: scale selector (0.5–4.0 step 0.5) recomputes displayed ingredient amounts client-side using the same fraction-friendly formatting (amounts are decimals post-clean; multiply and round to 2 dp, trim zeros); macro table shows per-serving values with coverage/confidence footer and the ⚠ badge when `coverage < 0.8`; buttons: "Add to this week" (`POST /api/cooks` with `week = current ISO week`, no date/meal — an unanchored cook the planner shows as unassigned; simplest correct v1) and "Open in Obsidian" (`obsidian://open?vault=KitchenOS&file=Recipes/<name>`).
  - Sidebar recipe cards in `meal_planner.html` get a small "ⓘ" link to `/recipe/<name>`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_recipe_detail.py` (client fixture as in `tests/test_api_endpoints.py`):

```python
"""Recipe detail: extended API payload + page route."""

RECIPE_MD = """---
title: Chili
servings: 4
source_url: "https://example.com/chili"
nutrition_calories: 500
nutrition_protein: 30
nutrition_carbs: 40
nutrition_fat: 20
nutrition_coverage: 0.95
nutrition_confidence: 0.8
nutrition_source: "usda"
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | cup | dried beans |
| 1 | lb | ground beef |

## Instructions

1. Cook it.
"""


def _write(tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "Chili.md").write_text(RECIPE_MD, encoding="utf-8")


def test_api_recipe_includes_ingredients_and_nutrition(client, tmp_vault):
    _write(tmp_vault)
    resp = client.get("/api/recipes/Chili")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["servings"] == 4
    assert len(data["ingredients"]) == 2
    assert data["ingredients"][0]["item"] == "dried beans"
    assert "## Ingredients" in data["body_markdown"]
    assert data["nutrition"]["calories"] == 500
    assert data["nutrition"]["coverage"] == 0.95


def test_api_recipe_nutrition_null_when_absent(client, tmp_vault):
    recipes = tmp_vault / "Recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    bare = RECIPE_MD.split("nutrition_calories")[0] + "---\n\n## Ingredients\n"
    (recipes / "Bare.md").write_text(bare, encoding="utf-8")
    data = client.get("/api/recipes/Bare").get_json()
    assert data["nutrition"] is None


def test_recipe_page_renders(client, tmp_vault):
    _write(tmp_vault)
    resp = client.get("/recipe/Chili")
    assert resp.status_code == 200
    assert 'id="scale-select"' in resp.get_data(as_text=True)


def test_recipe_page_404(client, tmp_vault):
    _write(tmp_vault)
    assert client.get("/recipe/Nope").status_code == 404
```

(If the existing `/api/recipes/<name>` handler caches recipe listings, remember it may need the cache invalidated in tests — check how `tests/test_api_recipes_ingredient.py` handles `_recipe_cache` and mirror it.)

- [ ] **Step 2: Run red.** — `.venv/bin/pytest tests/test_recipe_detail.py -v`
- [ ] **Step 3: Implement** — extend the API handler; add the page route (`open('templates/recipe_detail.html').read()` pattern); build the template fetching `/api/recipes/<name>` on load using the URL path segment.
- [ ] **Step 4: Run green + full suite.** — `.venv/bin/pytest -q`
- [ ] **Step 5: Commit**

```bash
git add api_server.py templates/recipe_detail.html templates/meal_planner.html tests/test_recipe_detail.py
git commit -m "feat: recipe detail page with live ingredient scaling"
```

---

### Task 13: End-to-end verification + backfill run

**Files:** none new (verification only; small fixes as found)

- [ ] **Step 1: Full test suite** — `.venv/bin/pytest -q` → PASS.
- [ ] **Step 2: Drive the real flow** (dev server on a COPY of the vault + a scratch DB — never the live ones):

```bash
cp -r "$(cd /Users/chaseeasterling/Dev/KitchenOS && .venv/bin/python -c 'from lib import paths; print(paths.vault_root())')" /tmp/kv-verify
cd /Users/chaseeasterling/Dev/KitchenOS
PORT=5010 KITCHENOS_VAULT=/tmp/kv-verify KITCHENOS_DB=/tmp/kv-verify.db .venv/bin/python api_server.py
```

Walk the spec's verification section: drop recipe at 1.5× → place servings across two days + freezer + trash → totals row updates with ⚠ where coverage is low → shopping list shows 1.5× quantities and nothing for the freezer meal → `/nutrition-review` fix-one-match flow → `/recipe/<name>` scaling. Confirm the regenerated `Meal Plans/<week>.md` parses in Obsidian-compatible form (open the file; run `.venv/bin/python sync_calendar.py --dry-run` → no errors).

- [ ] **Step 3: Dry-run the improved backfill on the real vault (read-only):**

```bash
.venv/bin/python backfill_nutrition.py --dry-run --force --limit 20
```
Expected: audit lines show coverage; the known 20,883 kcal recipe shows `kcal_out_of_range`. Report results to the user — the real `--force` run over all 233 recipes is the user's call (it rewrites frontmatter vault-wide).

- [ ] **Step 4: Commit any fixes; stop.** Use superpowers:verification-before-completion before claiming done, then superpowers:finishing-a-development-branch.

---

## Self-Review Notes

- Spec §1 → Tasks 1–4; §2 → Tasks 6–7; §3 → Task 5; §4 → Tasks 8–11; §5 → Task 12; spec "Verification" → Task 13. Backlog items (cooking mode, meal-bundle chips, waste analytics) intentionally absent.
- Coverage is line-count based (not gram-weighted): unresolved lines have unknown grams, so gram-weighting is impossible for exactly the lines that matter; the spec's "count by line" fallback becomes the rule. `nutrition_coverage` frontmatter + review threshold 0.8 match the spec.
- Type consistency: `scale`/`servings_produced`/`count` are floats everywhere (ledger, API, JS, parser `MealEntry.servings`, `multiply_ingredients`).
- Known risk: `meal_planner.html` is a 100 KB single file — Tasks 6–7 are the least mechanical; the manual checklists there are the acceptance gate.
