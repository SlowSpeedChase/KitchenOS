# Smart Meal Plan Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a goal-directed meal-planning layer on KitchenOS that targets muscle gain + energy + heart health, biases toward user-rated recipes, runs a Wednesday vault-review digest, and supports batch-cook cascades + day-as-menu composition.

**Architecture:** New `lib/planner_engine.py` orchestrates new `meal_scorer.py`, `day_composer.py`, `batch_cascade.py`, `cache.py`, `weekly_digest.py` modules. SQLite cache at `.kitchenos-cache.db` (project root, gitignored) derived from vault markdown. Claude API handles Wednesday digest + one-shot week builder (Mode D); Ollama handles per-slot scoring. Phased rollout: A (core ship), B (structured post-meal feedback), C (heart-health rule activation).

**Tech Stack:** Python 3.11, stdlib sqlite3, `anthropic` SDK (already in project), existing `requests`-based Ollama client, existing markdown-parsing helpers. All commands run via `.venv/bin/python`. Tests use pytest with class-based `TestX` fixtures following existing conventions in `tests/`.

**Source design doc:** `docs/plans/2026-04-19-smart-meal-plan-design.md` — authoritative for all decisions. When this plan and the design conflict, update this plan first.

---

## Phase A: Core System (First Ship)

Phase A is planned in detail. Tasks are TDD, bite-sized (2–5 min), with frequent commits. Every `git commit` message uses `feat:`/`test:`/`docs:`/`chore:` prefix matching existing project convention.

**Phase A prerequisites** (user-driven, not engineering tasks):
- User fills in `Macro Worksheet.md` at vault root
- Claude computes and writes `My Macros.md` (one-time helper, not part of the engineering plan)

---

### Task 1: Add `.kitchenos-cache.db` to gitignore

**Files:**
- Modify: `.gitignore`

**Step 1: Inspect current gitignore**

Run: `cat /Users/chaseeasterling/KitchenOS/.gitignore`

**Step 2: Append cache pattern**

Add these lines at the end:

```
# SQLite cache (derived from vault markdown, disposable)
.kitchenos-cache.db
.kitchenos-cache.db-journal
.kitchenos-cache.db-wal
.kitchenos-cache.db-shm
```

**Step 3: Verify**

Run: `git check-ignore -v .kitchenos-cache.db`
Expected: output confirming the pattern matches.

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore SQLite cache artifacts"
```

---

### Task 2: Create schema migration script (dry-run first)

**Files:**
- Create: `migrate_schema_v2.py`
- Create: `tests/test_migrate_schema_v2.py`

**Step 1: Write the failing test**

```python
# tests/test_migrate_schema_v2.py
"""Tests for Phase A schema migration."""
import tempfile
from pathlib import Path

from migrate_schema_v2 import migrate_recipe_frontmatter


class TestSchemaMigrationV2:
    def test_adds_new_fields_when_absent(self):
        content = """---
recipe_name: Example
cuisine: Italian
---

# Example
"""
        updated = migrate_recipe_frontmatter(content)
        assert "rating: null" in updated
        assert "last_cooked: null" in updated
        assert "times_cooked: 0" in updated
        assert "batch_cook: false" in updated

    def test_does_not_overwrite_existing_fields(self):
        content = """---
recipe_name: Example
rating: 4
times_cooked: 2
last_cooked: 2026-04-15
---

# Example
"""
        updated = migrate_recipe_frontmatter(content)
        assert "rating: 4" in updated
        assert "times_cooked: 2" in updated
        assert "last_cooked: 2026-04-15" in updated

    def test_preserves_body(self):
        content = """---
recipe_name: Example
---

# Example

## Ingredients
- 1 cup flour
"""
        updated = migrate_recipe_frontmatter(content)
        assert "## Ingredients" in updated
        assert "- 1 cup flour" in updated
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_schema_v2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_schema_v2'`.

**Step 3: Write minimal implementation**

```python
# migrate_schema_v2.py
"""One-time migration: add Phase A frontmatter fields to all recipes.

Adds these fields when absent (never overwrites existing values):
  rating: null
  last_cooked: null
  times_cooked: 0
  batch_cook: false

Usage:
  .venv/bin/python migrate_schema_v2.py --dry-run
  .venv/bin/python migrate_schema_v2.py
"""
import argparse
import os
import re
import sys
from pathlib import Path

NEW_FIELDS = [
    ("rating", "null"),
    ("last_cooked", "null"),
    ("times_cooked", "0"),
    ("batch_cook", "false"),
]

VAULT = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS"
)


def migrate_recipe_frontmatter(content: str) -> str:
    """Insert missing Phase A fields into YAML frontmatter."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not match:
        return content  # no frontmatter, leave alone

    fm_text, body = match.group(1), match.group(2)
    existing = {line.split(":", 1)[0].strip() for line in fm_text.splitlines() if ":" in line}

    additions = [f"{k}: {v}" for k, v in NEW_FIELDS if k not in existing]
    if not additions:
        return content

    new_fm = fm_text + "\n" + "\n".join(additions)
    return f"---\n{new_fm}\n---\n{body}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vault", type=Path, default=VAULT)
    args = parser.parse_args()

    recipes_dir = args.vault / "Recipes"
    if not recipes_dir.is_dir():
        print(f"Recipes folder not found at {recipes_dir}", file=sys.stderr)
        sys.exit(1)

    changed = 0
    for md in sorted(recipes_dir.glob("*.md")):
        original = md.read_text(encoding="utf-8")
        updated = migrate_recipe_frontmatter(original)
        if updated != original:
            changed += 1
            action = "WOULD UPDATE" if args.dry_run else "UPDATED"
            print(f"{action}: {md.name}")
            if not args.dry_run:
                md.write_text(updated, encoding="utf-8")

    total = len(list(recipes_dir.glob("*.md")))
    print(f"\n{changed}/{total} recipes {'would be ' if args.dry_run else ''}updated.")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_migrate_schema_v2.py -v`
Expected: PASS.

**Step 5: Dry-run against the real vault**

Run: `.venv/bin/python migrate_schema_v2.py --dry-run`
Expected: `N/207 recipes would be updated.` Review the list — should be close to 207 (every recipe missing the new fields).

**Step 6: Apply migration**

Run: `.venv/bin/python migrate_schema_v2.py`
Expected: same N files updated in the vault.

**Step 7: Commit script**

```bash
git add migrate_schema_v2.py tests/test_migrate_schema_v2.py
git commit -m "feat: schema migration for Phase A frontmatter fields"
```

---

### Task 3: Cache schema + init (TDD)

**Files:**
- Create: `lib/cache.py`
- Create: `tests/test_cache.py`

**Step 1: Write the failing test**

```python
# tests/test_cache.py
"""Tests for the SQLite cache layer."""
import tempfile
from pathlib import Path

from lib.cache import Cache


class TestCacheSchema:
    def test_init_creates_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            cache = Cache(db)
            cache.init_schema()

            tables = cache.raw_query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            names = [r[0] for r in tables]
            assert "recipes" in names
            assert "recipe_notes" in names
            assert "meal_plan_entries" in names
            assert "digests" in names
            assert "schema_version" in names

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            cache = Cache(db)
            cache.init_schema()
            cache.init_schema()  # should not raise
            version = cache.raw_query("SELECT version FROM schema_version")
            assert version[0][0] == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.cache'`.

**Step 3: Write minimal implementation**

```python
# lib/cache.py
"""SQLite cache layer — derived from vault markdown, disposable.

Schema version 1.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS recipes (
  name TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  rating INTEGER,
  cuisine TEXT,
  protein TEXT,
  dish_type TEXT,
  difficulty TEXT,
  meal_occasion TEXT,
  dietary TEXT,
  calories INTEGER,
  protein_g INTEGER,
  carbs_g INTEGER,
  fat_g INTEGER,
  sat_fat_g REAL,
  sodium_mg INTEGER,
  fiber_g REAL,
  sugar_g REAL,
  times_cooked INTEGER DEFAULT 0,
  last_cooked DATE,
  batch_cook INTEGER DEFAULT 0,
  batch_parent TEXT,
  produces TEXT,
  seasonal_ingredients TEXT,
  peak_months TEXT,
  updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating);
CREATE INDEX IF NOT EXISTS idx_recipes_last_cooked ON recipes(last_cooked);
CREATE INDEX IF NOT EXISTS idx_recipes_batch_cook ON recipes(batch_cook);

CREATE TABLE IF NOT EXISTS recipe_notes (
  id INTEGER PRIMARY KEY,
  recipe_name TEXT NOT NULL REFERENCES recipes(name),
  added_date DATE NOT NULL,
  note TEXT NOT NULL,
  source TEXT NOT NULL,
  UNIQUE(recipe_name, added_date, note)
);

CREATE TABLE IF NOT EXISTS meal_plan_entries (
  id INTEGER PRIMARY KEY,
  week TEXT NOT NULL,
  date DATE NOT NULL,
  meal_slot TEXT NOT NULL,
  recipe_name TEXT REFERENCES recipes(name),
  servings INTEGER DEFAULT 1,
  status TEXT,
  UNIQUE(week, date, meal_slot)
);

CREATE INDEX IF NOT EXISTS idx_mpe_week ON meal_plan_entries(week);
CREATE INDEX IF NOT EXISTS idx_mpe_recipe ON meal_plan_entries(recipe_name);

CREATE TABLE IF NOT EXISTS digests (
  week TEXT PRIMARY KEY,
  generated_at DATETIME,
  summary_path TEXT,
  patterns_json TEXT
);
"""


class Cache:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def init_schema(self) -> None:
        self.conn.executescript(_DDL)
        cur = self.conn.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        elif row[0] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Cache schema version mismatch: db={row[0]}, expected={SCHEMA_VERSION}. "
                "Delete .kitchenos-cache.db and rebuild."
            )
        self.conn.commit()

    def raw_query(self, sql: str, params: Iterable[Any] = ()) -> list[tuple]:
        return list(self.conn.execute(sql, params))

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cache.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add lib/cache.py tests/test_cache.py
git commit -m "feat: SQLite cache foundation (schema + init)"
```

---

### Task 4: Cache sync from vault (mtime-based)

**Files:**
- Modify: `lib/cache.py`
- Modify: `tests/test_cache.py`

**Step 1: Add failing tests for `sync_recipes`**

Append to `tests/test_cache.py`:

```python
class TestCacheSync:
    def _make_recipe(self, dir_: Path, name: str, rating: int = None, batch_cook: bool = False):
        fm = [f"recipe_name: {name}"]
        if rating is not None:
            fm.append(f"rating: {rating}")
        fm.append(f"batch_cook: {'true' if batch_cook else 'false'}")
        path = dir_ / f"{name}.md"
        path.write_text("---\n" + "\n".join(fm) + "\n---\n\n# " + name, encoding="utf-8")
        return path

    def test_sync_indexes_all_recipes_on_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            recipes = vault / "Recipes"
            recipes.mkdir()
            self._make_recipe(recipes, "Alpha", rating=4)
            self._make_recipe(recipes, "Beta")

            cache = Cache(vault / "cache.db")
            cache.init_schema()
            cache.sync_recipes(recipes)

            rows = cache.raw_query("SELECT name, rating FROM recipes ORDER BY name")
            assert rows == [("Alpha", 4), ("Beta", None)]

    def test_sync_skips_unchanged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            recipes = vault / "Recipes"
            recipes.mkdir()
            path = self._make_recipe(recipes, "Alpha", rating=3)

            cache = Cache(vault / "cache.db")
            cache.init_schema()
            cache.sync_recipes(recipes)
            first_updated = cache.raw_query(
                "SELECT updated_at FROM recipes WHERE name='Alpha'"
            )[0][0]

            cache.sync_recipes(recipes)  # no file change
            second_updated = cache.raw_query(
                "SELECT updated_at FROM recipes WHERE name='Alpha'"
            )[0][0]
            assert first_updated == second_updated

    def test_sync_removes_deleted_recipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            recipes = vault / "Recipes"
            recipes.mkdir()
            path = self._make_recipe(recipes, "Alpha")

            cache = Cache(vault / "cache.db")
            cache.init_schema()
            cache.sync_recipes(recipes)

            path.unlink()
            cache.sync_recipes(recipes)

            rows = cache.raw_query("SELECT name FROM recipes")
            assert rows == []
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cache.py::TestCacheSync -v`
Expected: FAIL — `AttributeError: 'Cache' object has no attribute 'sync_recipes'`.

**Step 3: Implement `sync_recipes`**

Append to `lib/cache.py`:

```python
import json
import os
from datetime import datetime, timezone

from lib.recipe_parser import parse_recipe_file


def _maybe_json(value):
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps(value)
    return value


_RECIPE_FM_FIELDS = [
    "rating", "cuisine", "protein", "dish_type", "difficulty",
    "meal_occasion", "dietary", "calories", "protein_g", "carbs_g",
    "fat_g", "sat_fat_g", "sodium_mg", "fiber_g", "sugar_g",
    "times_cooked", "last_cooked", "batch_cook", "batch_parent",
    "produces", "seasonal_ingredients", "peak_months",
]


def _upsert_recipe(conn: sqlite3.Connection, name: str, path: Path, fm: dict, mtime: float) -> None:
    values = {
        "name": name,
        "path": str(path),
        "updated_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
    }
    for field in _RECIPE_FM_FIELDS:
        values[field] = _maybe_json(fm.get(field))
    # batch_cook is stored as INT
    bc = fm.get("batch_cook")
    values["batch_cook"] = 1 if bc is True else 0

    cols = list(values.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "name")
    sql = (
        f"INSERT INTO recipes({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(name) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [values[c] for c in cols])


# attach method to Cache class
def _cache_sync_recipes(self: "Cache", recipes_dir: Path) -> int:
    """Reindex recipes in the vault. Skips files whose mtime matches the cache."""
    current_files = {p.stem: p for p in recipes_dir.glob("*.md")}
    cached = dict(self.raw_query("SELECT name, updated_at FROM recipes"))
    changed = 0

    for name, path in current_files.items():
        mtime = path.stat().st_mtime
        iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        if cached.get(name) == iso:
            continue  # unchanged
        parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
        _upsert_recipe(self.conn, name, path, parsed.get("frontmatter", {}), mtime)
        changed += 1

    # remove rows for files that disappeared
    deleted = set(cached.keys()) - set(current_files.keys())
    for name in deleted:
        self.conn.execute("DELETE FROM recipes WHERE name = ?", (name,))
        self.conn.execute("DELETE FROM recipe_notes WHERE recipe_name = ?", (name,))

    self.conn.commit()
    return changed


Cache.sync_recipes = _cache_sync_recipes
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cache.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add lib/cache.py tests/test_cache.py
git commit -m "feat: cache mtime-based recipe sync"
```

---

### Task 5: Cache sync for notes + meal plan entries

**Files:**
- Modify: `lib/cache.py`
- Modify: `tests/test_cache.py`

**Step 1: Add tests for `sync_notes` and `sync_meal_plans`**

```python
# append to tests/test_cache.py

class TestCacheNotes:
    def test_sync_notes_extracts_cooked_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            recipes = vault / "Recipes"
            recipes.mkdir()
            (recipes / "Alpha.md").write_text(
                "---\nrecipe_name: Alpha\n---\n\n"
                "## My Notes\n\n"
                "- cooked 2026-04-15 ★★★★☆ — felt energized\n"
                "- cooked 2026-04-02 ★★★☆☆ — too salty\n\n"
                "Free-form text below\n",
                encoding="utf-8",
            )
            cache = Cache(vault / "cache.db")
            cache.init_schema()
            cache.sync_recipes(recipes)
            cache.sync_notes(recipes)

            rows = cache.raw_query(
                "SELECT recipe_name, added_date, note FROM recipe_notes ORDER BY added_date"
            )
            assert rows == [
                ("Alpha", "2026-04-02", "too salty"),
                ("Alpha", "2026-04-15", "felt energized"),
            ]


class TestCacheMealPlans:
    def test_sync_meal_plans_flattens_weekly_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            plans = vault / "Meal Plans"
            plans.mkdir()
            (plans / "2026-W20.md").write_text(
                "# Meal Plan - Week 20\n\n"
                "## Monday (May 18)\n"
                "### Breakfast\n[[Oatmeal]]\n"
                "### Dinner\n[[Chili]] x2\n",
                encoding="utf-8",
            )
            cache = Cache(vault / "cache.db")
            cache.init_schema()
            cache.sync_meal_plans(plans)

            rows = cache.raw_query(
                "SELECT week, meal_slot, recipe_name, servings "
                "FROM meal_plan_entries ORDER BY meal_slot"
            )
            assert rows == [
                ("2026-W20", "breakfast", "Oatmeal", 1),
                ("2026-W20", "dinner", "Chili", 2),
            ]
```

**Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cache.py -v`
Expected: FAIL — `AttributeError` for both methods.

**Step 3: Implement**

Append to `lib/cache.py`:

```python
import re

from lib.meal_plan_parser import parse_meal_plan

_COOKED_LINE = re.compile(
    r"^- cooked (\d{4}-\d{2}-\d{2}) ★+☆* — (.+)$",
    flags=re.UNICODE,
)


def _cache_sync_notes(self: "Cache", recipes_dir: Path) -> int:
    """Extract cooked lines from ## My Notes sections; idempotent via UNIQUE constraint."""
    inserted = 0
    for path in recipes_dir.glob("*.md"):
        name = path.stem
        text = path.read_text(encoding="utf-8")
        notes_section = _extract_section(text, "## My Notes")
        if not notes_section:
            continue
        for line in notes_section.splitlines():
            m = _COOKED_LINE.match(line.strip())
            if not m:
                continue
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO recipe_notes(recipe_name, added_date, note, source) "
                    "VALUES (?, ?, ?, 'user')",
                    (name, m.group(1), m.group(2).strip()),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
    self.conn.commit()
    return inserted


def _extract_section(text: str, header: str) -> str | None:
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.strip() == header:
            capturing = True
            continue
        if capturing and line.startswith("## "):
            break
        if capturing:
            out.append(line)
    return "\n".join(out) if out else None


def _cache_sync_meal_plans(self: "Cache", plans_dir: Path) -> int:
    self.conn.execute("DELETE FROM meal_plan_entries")  # simple rebuild; cheap
    inserted = 0
    for path in plans_dir.glob("*.md"):
        week = path.stem  # e.g. '2026-W20'
        content = path.read_text(encoding="utf-8")
        status = _frontmatter_value(content, "status") or "draft"
        parsed = parse_meal_plan(content)
        # parse_meal_plan returns {day_label: {meal_slot: [MealEntry]}} (per existing module)
        for day_label, slots in parsed.items():
            date_iso = _day_label_to_date(day_label, week)
            for slot, entries in slots.items():
                for entry in entries:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO meal_plan_entries("
                        "week, date, meal_slot, recipe_name, servings, status) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (week, date_iso, slot.lower(), entry.name, entry.servings, status),
                    )
                    inserted += 1
    self.conn.commit()
    return inserted


def _frontmatter_value(text: str, key: str) -> str | None:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        kv = re.match(rf"^{re.escape(key)}:\s*(.*)$", line.strip())
        if kv:
            return kv.group(1).strip() or None
    return None


def _day_label_to_date(day_label: str, week: str) -> str:
    """Convert 'Monday (May 18)' + '2026-W20' to ISO date.
    Uses ISO week calendar — Monday is day 1.
    """
    from datetime import date, timedelta
    year, wk = week.split("-W")
    monday = date.fromisocalendar(int(year), int(wk), 1)
    days = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6}
    for name, offset in days.items():
        if day_label.startswith(name):
            return (monday + timedelta(days=offset)).isoformat()
    raise ValueError(f"Unrecognized day label: {day_label!r}")


Cache.sync_notes = _cache_sync_notes
Cache.sync_meal_plans = _cache_sync_meal_plans
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cache.py -v`
Expected: all pass. If the existing `parse_meal_plan` return shape differs from what's assumed, adjust the loop — check `lib/meal_plan_parser.py` for the authoritative structure before editing.

**Step 5: Commit**

```bash
git add lib/cache.py tests/test_cache.py
git commit -m "feat: cache sync for notes and meal plan entries"
```

---

### Task 6: Add `## Training Days` + `## Heart Health` parsing to macro_targets

**Files:**
- Modify: `lib/macro_targets.py`
- Modify: `lib/nutrition.py` (extend dataclass)
- Modify: `tests/test_macro_targets.py`

**Step 1: Extend `NutritionData` if needed** — check `lib/nutrition.py`. If it's an immutable dataclass, introduce a sibling dataclass `MacroProfile` in `lib/macro_targets.py` instead of mutating existing shapes. Use whichever keeps backward compatibility with `calculate_recipe_nutrition` callers.

```python
# lib/macro_targets.py (replacement)
"""Parser for user macro targets and training profile from My Macros.md."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lib.nutrition import NutritionData
from lib.recipe_parser import parse_recipe_file


@dataclass
class MacroProfile:
    targets: NutritionData
    training_days: dict[str, str] = field(default_factory=dict)  # {"Monday": "lifting", ...}
    heart_health_raw: str = ""  # free-form until Phase C


def load_macro_profile(vault_path: Path) -> MacroProfile | None:
    path = vault_path / "My Macros.md"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    parsed = parse_recipe_file(content)
    fm = parsed["frontmatter"]

    targets = NutritionData(
        calories=int(fm.get("calories", 0) or 0),
        protein=int(fm.get("protein", 0) or 0),
        carbs=int(fm.get("carbs", 0) or 0),
        fat=int(fm.get("fat", 0) or 0),
    )

    body = parsed["body"]
    training_days = _parse_training_days(body)
    heart_health_raw = _extract_section_text(body, "## Heart Health")

    return MacroProfile(
        targets=targets,
        training_days=training_days,
        heart_health_raw=heart_health_raw,
    )


# Backwards compatibility — existing callers of load_macro_targets still work
def load_macro_targets(vault_path: Path) -> NutritionData | None:
    profile = load_macro_profile(vault_path)
    return profile.targets if profile else None


_DAY_LINE = re.compile(r"^-\s*(\w+):\s*(.+)$")


def _parse_training_days(body: str) -> dict[str, str]:
    section = _extract_section_text(body, "## Training Days")
    if not section:
        return {}
    out = {}
    for line in section.splitlines():
        m = _DAY_LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip().lower()
    return out


def _extract_section_text(body: str, header: str) -> str:
    lines = body.splitlines()
    capturing = False
    out: list[str] = []
    for line in lines:
        if line.strip() == header:
            capturing = True
            continue
        if capturing and line.startswith("## "):
            break
        if capturing:
            out.append(line)
    return "\n".join(out).strip()
```

**Step 2: Add tests**

Append to `tests/test_macro_targets.py`:

```python
class TestMacroProfile:
    def _write(self, vault: Path, body_extra: str = ""):
        (vault / "My Macros.md").write_text(f"""---
calories: 2800
protein: 180
carbs: 320
fat: 80
---

# My Daily Macros

{body_extra}
""", encoding="utf-8")

    def test_load_training_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._write(vault, """## Training Days
- Monday: lifting
- Tuesday: cardio
- Wednesday: lifting
- Thursday: rest
""")
            from lib.macro_targets import load_macro_profile
            profile = load_macro_profile(vault)
            assert profile.training_days == {
                "Monday": "lifting",
                "Tuesday": "cardio",
                "Wednesday": "lifting",
                "Thursday": "rest",
            }

    def test_load_heart_health_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._write(vault, """## Heart Health
Watching sodium. Family history of hypertension.
""")
            from lib.macro_targets import load_macro_profile
            profile = load_macro_profile(vault)
            assert "sodium" in profile.heart_health_raw.lower()

    def test_backwards_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._write(vault)
            from lib.macro_targets import load_macro_targets
            targets = load_macro_targets(vault)
            assert targets.calories == 2800
```

**Step 3: Run all macro_targets tests**

Run: `.venv/bin/python -m pytest tests/test_macro_targets.py -v`
Expected: all pass (old test still works, new ones pass).

**Step 4: Commit**

```bash
git add lib/macro_targets.py tests/test_macro_targets.py
git commit -m "feat: parse Training Days and Heart Health sections from My Macros.md"
```

---

### Task 7: Meal plan frontmatter — `status`, `locked_at`, `intent`

**Files:**
- Modify: `lib/meal_plan_parser.py`
- Modify: `templates/meal_plan_template.py`
- Modify: `generate_meal_plan.py` (emit new fields)
- Modify: `tests/test_meal_plan_parser.py`

**Step 1: Add failing tests**

Append to `tests/test_meal_plan_parser.py`:

```python
class TestMealPlanStatus:
    def test_parses_status_frontmatter(self):
        from lib.meal_plan_parser import parse_meal_plan_frontmatter
        content = """---
status: draft
intent: heavy lifting
---
# Meal Plan
"""
        fm = parse_meal_plan_frontmatter(content)
        assert fm["status"] == "draft"
        assert fm["intent"] == "heavy lifting"

    def test_defaults_status_to_draft_when_missing(self):
        from lib.meal_plan_parser import parse_meal_plan_frontmatter
        fm = parse_meal_plan_frontmatter("# Meal Plan")
        assert fm["status"] == "draft"
```

**Step 2: Run — expect fail.**

**Step 3: Implement `parse_meal_plan_frontmatter`** in `lib/meal_plan_parser.py`:

```python
def parse_meal_plan_frontmatter(content: str) -> dict:
    """Return {status, locked_at, intent} with 'draft' default."""
    import re
    defaults = {"status": "draft", "locked_at": None, "intent": None}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not m:
        return defaults
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line.strip())
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip()
            if val == "null" or val == "":
                val = None
            if key in defaults:
                defaults[key] = val
    return defaults
```

**Step 4: Update `templates/meal_plan_template.py`** to emit a frontmatter block above the existing content:

```python
# Prepend this to the generated markdown
FRONTMATTER_TEMPLATE = """---
status: draft
locked_at: null
intent: null
---

"""
```

Apply by wrapping wherever `generate_meal_plan_markdown` returns its string.

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py tests/test_meal_plan_template.py -v`
Expected: all pass. Adjust existing tests if they compare raw markdown without accounting for frontmatter.

**Step 6: Commit**

```bash
git add lib/meal_plan_parser.py templates/meal_plan_template.py tests/test_meal_plan_parser.py
git commit -m "feat: meal plan frontmatter (status, locked_at, intent)"
```

---

### Task 8: Extract cooked lines from recipe notes (reusable parser)

**Files:**
- Modify: `lib/recipe_parser.py`
- Modify: `tests/test_recipe_parser.py` (create if absent)

**Step 1: Add test**

```python
# tests/test_recipe_parser.py
from lib.recipe_parser import extract_cooked_lines


class TestCookedLines:
    def test_extracts_stars_and_reason(self):
        md = """## My Notes

- cooked 2026-04-15 ★★★★☆ — felt energized
- cooked 2026-04-02 ★★★☆☆ — too salty
"""
        lines = extract_cooked_lines(md)
        assert lines == [
            {"date": "2026-04-15", "stars": 4, "reason": "felt energized"},
            {"date": "2026-04-02", "stars": 3, "reason": "too salty"},
        ]

    def test_handles_5_stars_no_empty(self):
        md = "- cooked 2026-04-20 ★★★★★ — crown jewel"
        lines = extract_cooked_lines(md)
        assert lines[0]["stars"] == 5

    def test_ignores_malformed(self):
        md = "- cooked 2026-04-20 no stars — nothing"
        assert extract_cooked_lines(md) == []
```

**Step 2: Run — expect fail.**

**Step 3: Implement** in `lib/recipe_parser.py`:

```python
_COOKED_RE = re.compile(
    r"^- cooked (\d{4}-\d{2}-\d{2}) (★+)(☆*) — (.+)$",
    re.UNICODE,
)


def extract_cooked_lines(text: str) -> list[dict]:
    """Extract all '- cooked DATE ★★★☆☆ — reason' lines from any markdown."""
    out = []
    for line in text.splitlines():
        m = _COOKED_RE.match(line.strip())
        if not m:
            continue
        out.append({
            "date": m.group(1),
            "stars": len(m.group(2)),
            "reason": m.group(4).strip(),
        })
    return out
```

**Step 4: Run tests.** Expected pass.

**Step 5: Commit**

```bash
git add lib/recipe_parser.py tests/test_recipe_parser.py
git commit -m "feat: extract structured cooked-line entries from recipe notes"
```

---

### Task 9: Scoring weights config

**Files:**
- Create: `config/scoring_weights.json`
- Create: `lib/scoring_weights.py`
- Create: `tests/test_scoring_weights.py`

**Step 1: Write the config file**

```json
{
  "macro_fit_max": 40,
  "rating": {"5": 15, "4": 8, "3": 0, "2": -5, "1": -10},
  "rotation": {
    "max_penalty": -20,
    "full_penalty_days": 7,
    "recovery_days": 14
  },
  "seasonality_bonus": 5,
  "training_day_bonus": 10,
  "batch_coherence_bonus": 30,
  "heart_health_phase_a": 0,
  "day_fit_bonus_max": 20,
  "top_k_per_slot": 5,
  "macro_tolerance_pct": 15
}
```

**Step 2: Add test**

```python
# tests/test_scoring_weights.py
from lib.scoring_weights import load_weights


class TestWeights:
    def test_load_default(self):
        w = load_weights()
        assert w["top_k_per_slot"] == 5
        assert w["rating"]["5"] == 15
        assert w["rotation"]["max_penalty"] == -20
```

**Step 3: Run — fail.**

**Step 4: Implement**

```python
# lib/scoring_weights.py
"""Loader for tunable scorer weights."""
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "config" / "scoring_weights.json"


def load_weights(path: Path | None = None) -> dict:
    target = path or _DEFAULT_PATH
    return json.loads(target.read_text(encoding="utf-8"))
```

**Step 5: Run tests.** Pass.

**Step 6: Commit**

```bash
git add config/scoring_weights.json lib/scoring_weights.py tests/test_scoring_weights.py
git commit -m "feat: tunable scoring weights config"
```

---

### Task 10: Meal scorer — macro_fit component

**Files:**
- Create: `lib/meal_scorer.py`
- Create: `tests/test_meal_scorer.py`

**Step 1: Write test**

```python
# tests/test_meal_scorer.py
import pytest

from lib.nutrition import NutritionData
from lib.meal_scorer import score_macro_fit


class TestMacroFit:
    def test_zero_progress_high_gap(self):
        """Recipe that makes big progress on empty day = high score."""
        targets = NutritionData(calories=2500, protein=180, carbs=300, fat=80)
        day_so_far = NutritionData(calories=0, protein=0, carbs=0, fat=0)
        recipe = NutritionData(calories=700, protein=45, carbs=80, fat=20)
        score = score_macro_fit(recipe, day_so_far, targets, max_score=40)
        assert 20 <= score <= 40

    def test_overshoot_penalized(self):
        """Recipe that pushes every macro way past target = low score."""
        targets = NutritionData(calories=2500, protein=180, carbs=300, fat=80)
        day_so_far = NutritionData(calories=2400, protein=170, carbs=290, fat=75)
        recipe = NutritionData(calories=1500, protein=90, carbs=160, fat=40)
        score = score_macro_fit(recipe, day_so_far, targets, max_score=40)
        assert score <= 10

    def test_null_recipe_macros_returns_zero(self):
        """Recipes missing nutrition data score neutral (no bonus, no penalty)."""
        targets = NutritionData(calories=2500, protein=180, carbs=300, fat=80)
        day_so_far = NutritionData(calories=0, protein=0, carbs=0, fat=0)
        recipe = NutritionData(calories=0, protein=0, carbs=0, fat=0)
        assert score_macro_fit(recipe, day_so_far, targets, max_score=40) == 0
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# lib/meal_scorer.py
"""Meal candidate scoring.

Pure functions; no I/O. Each component is independently testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from lib.nutrition import NutritionData


def score_macro_fit(
    recipe: NutritionData,
    day_so_far: NutritionData,
    targets: NutritionData,
    max_score: int = 40,
) -> float:
    """Return 0..max_score based on how well this recipe moves the day toward targets.

    If recipe has no nutrition (all zeros), returns 0 (neutral).
    """
    if not any([recipe.calories, recipe.protein, recipe.carbs, recipe.fat]):
        return 0.0

    # For each macro, measure the fraction of remaining-gap that this recipe closes,
    # with a penalty for overshoot.
    components = []
    for attr in ("calories", "protein", "carbs", "fat"):
        target = getattr(targets, attr)
        have = getattr(day_so_far, attr)
        add = getattr(recipe, attr)
        if target == 0:
            continue
        remaining = target - have
        if add == 0:
            components.append(0.0)
            continue
        if remaining <= 0:
            # day already at or over target: any add is overshoot
            components.append(-1.0 * min(1.0, add / target))
            continue
        progress = min(add, remaining) / remaining
        overshoot = max(0.0, (have + add - target) / target)
        components.append(progress - overshoot)

    if not components:
        return 0.0
    avg = sum(components) / len(components)
    raw = max(-1.0, min(1.0, avg))  # clamp to [-1, 1]
    # map to [0, max_score]: -1 -> 0, 0 -> max/2, 1 -> max
    return round((raw + 1) / 2 * max_score, 2)
```

**Step 4: Run tests.** Pass.

**Step 5: Commit**

```bash
git add lib/meal_scorer.py tests/test_meal_scorer.py
git commit -m "feat: meal scorer macro_fit component"
```

---

### Task 11: Meal scorer — rating component

**Files:**
- Modify: `lib/meal_scorer.py`
- Modify: `tests/test_meal_scorer.py`

**Step 1: Test**

```python
class TestRating:
    def test_five_star_max_bonus(self):
        from lib.meal_scorer import score_rating
        weights = {"5": 15, "4": 8, "3": 0, "2": -5, "1": -10}
        assert score_rating(5, weights) == 15

    def test_unrated_neutral(self):
        from lib.meal_scorer import score_rating
        assert score_rating(None, {"5": 15, "4": 8, "3": 0, "2": -5, "1": -10}) == 0

    def test_one_star_penalty(self):
        from lib.meal_scorer import score_rating
        assert score_rating(1, {"1": -10}) == -10
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# append to lib/meal_scorer.py
def score_rating(rating: int | None, weights: dict[str, int]) -> int:
    if rating is None:
        return 0
    return weights.get(str(rating), 0)
```

**Step 4: Run.** Pass.

**Step 5: Commit**

```bash
git add lib/meal_scorer.py tests/test_meal_scorer.py
git commit -m "feat: meal scorer rating component"
```

---

### Task 12: Meal scorer — rotation component

**Files:** same.

**Step 1: Test**

```python
class TestRotation:
    def test_cooked_yesterday_max_penalty(self):
        from lib.meal_scorer import score_rotation
        today = date(2026, 4, 19)
        cfg = {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14}
        assert score_rotation(date(2026, 4, 18), today, cfg) == -20

    def test_cooked_14_days_ago_zero(self):
        from lib.meal_scorer import score_rotation
        today = date(2026, 4, 19)
        cfg = {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14}
        assert score_rotation(date(2026, 4, 5), today, cfg) == 0

    def test_cooked_10_days_ago_linear(self):
        from lib.meal_scorer import score_rotation
        today = date(2026, 4, 19)
        cfg = {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14}
        # 10 days ago: between 7 (full penalty) and 14 (zero), 3/7 of recovery done
        # penalty should be 4/7 of -20 ~= -11.4, round to -11
        assert score_rotation(date(2026, 4, 9), today, cfg) == -11

    def test_never_cooked_zero(self):
        from lib.meal_scorer import score_rotation
        cfg = {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14}
        assert score_rotation(None, date(2026, 4, 19), cfg) == 0
```

**Step 2: Implement**

```python
# append to lib/meal_scorer.py
from datetime import date as _date

def score_rotation(
    last_cooked: _date | None,
    today: _date,
    cfg: dict[str, int],
) -> int:
    if last_cooked is None:
        return 0
    days_ago = (today - last_cooked).days
    if days_ago <= cfg["full_penalty_days"]:
        return cfg["max_penalty"]
    if days_ago >= cfg["recovery_days"]:
        return 0
    # linear interpolation between full_penalty_days (max penalty) and recovery_days (0)
    span = cfg["recovery_days"] - cfg["full_penalty_days"]
    progress = (days_ago - cfg["full_penalty_days"]) / span
    return round(cfg["max_penalty"] * (1 - progress))
```

**Step 3: Run.** Pass.

**Step 4: Commit**

```bash
git add lib/meal_scorer.py tests/test_meal_scorer.py
git commit -m "feat: meal scorer rotation component"
```

---

### Task 13: Meal scorer — seasonality, training-day, batch-coherence components

Each of these is structurally similar to the above. Follow the same TDD cycle per component. One commit per component.

**Seasonality:** bonus when current month is in `peak_months`.

```python
def score_seasonality(peak_months: list[int] | None, today: _date, bonus: int) -> int:
    if not peak_months:
        return 0
    return bonus if today.month in peak_months else 0
```

**Training-day:** bonus when the date is a lifting day and recipe is high-protein (≥30g) OR high-carb (≥50g).

```python
def score_training_day(
    recipe: NutritionData,
    training_day_kind: str | None,  # 'lifting', 'cardio', 'rest', None
    bonus: int,
) -> int:
    if training_day_kind != "lifting":
        return 0
    if recipe.protein >= 30 or recipe.carbs >= 50:
        return bonus
    return 0
```

**Batch-coherence:** bonus when the recipe's `batch_parent` is scheduled earlier in the same week with servings remaining.

```python
def score_batch_coherence(
    recipe_batch_parent: str | None,
    week_plan: list[dict],      # list of {date, meal_slot, recipe_name, servings}
    cache,                       # Cache — to look up parent's batch_servings
    bonus: int,
) -> int:
    if not recipe_batch_parent:
        return 0
    parent_rows = [e for e in week_plan if e["recipe_name"] == recipe_batch_parent]
    if not parent_rows:
        return 0
    # Check servings remaining: parent.batch_servings - sum(children servings already placed)
    # (Phase A: assume any parent placement gives full bonus; refine later if needed)
    return bonus
```

Write tests for each, covering: happy path, absent signal, and edge cases (empty week_plan, recipe with no batch_parent).

Commit each component separately (`test: ...` / `feat: ...` cadence).

---

### Task 14: Meal scorer — hard filters + integration `score_candidate`

**Files:** same.

**Step 1: Test**

```python
class TestScoreCandidate:
    def test_returns_breakdown_and_total(self):
        from lib.meal_scorer import score_candidate

        recipe = {
            "name": "Chili",
            "rating": 4,
            "meal_occasion": ["weeknight-dinner"],
            "dietary": ["gluten-free"],
            "last_cooked": None,
            "peak_months": [10, 11, 12],
            "batch_parent": None,
            "nutrition": NutritionData(calories=650, protein=40, carbs=70, fat=18),
        }
        slot = {
            "date": date(2026, 4, 19),
            "meal_slot": "dinner",
            "training_day_kind": "lifting",
        }
        plan_state = {
            "day_so_far": NutritionData(0, 0, 0, 0),
            "week_entries": [],
            "user_dietary_exclusions": [],
        }
        targets = NutritionData(calories=2500, protein=180, carbs=300, fat=80)
        weights = {
            "macro_fit_max": 40,
            "rating": {"4": 8},
            "rotation": {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14},
            "seasonality_bonus": 5,
            "training_day_bonus": 10,
            "batch_coherence_bonus": 30,
            "heart_health_phase_a": 0,
        }
        result = score_candidate(recipe, slot, plan_state, targets, weights)
        assert "total" in result
        assert "components" in result
        assert result["components"]["rating"] == 8
        assert result["components"]["training_day"] == 10

    def test_hard_filter_wrong_meal_occasion(self):
        from lib.meal_scorer import score_candidate
        recipe = {
            "name": "Donut",
            "meal_occasion": ["dessert"],
            "dietary": [],
            "last_cooked": None,
            "peak_months": [],
            "batch_parent": None,
            "rating": None,
            "nutrition": NutritionData(200, 2, 30, 10),
        }
        slot = {"date": date(2026, 4, 19), "meal_slot": "breakfast", "training_day_kind": None}
        plan_state = {"day_so_far": NutritionData(0, 0, 0, 0), "week_entries": [], "user_dietary_exclusions": []}
        targets = NutritionData(2500, 180, 300, 80)
        weights = {"rating": {}, "rotation": {"max_penalty": -20, "full_penalty_days": 7, "recovery_days": 14}}
        result = score_candidate(recipe, slot, plan_state, targets, weights)
        assert result["filtered"] is True
        assert "meal_occasion" in result["filter_reason"]
```

**Step 2: Implement `score_candidate`**

```python
# append to lib/meal_scorer.py
def score_candidate(recipe, slot, plan_state, targets, weights):
    # hard filters
    slot_kind = slot["meal_slot"]
    if recipe.get("meal_occasion") and not _matches_slot(recipe["meal_occasion"], slot_kind):
        return {"filtered": True, "filter_reason": f"meal_occasion != {slot_kind}"}
    if any(d in plan_state["user_dietary_exclusions"] for d in recipe.get("dietary", [])):
        return {"filtered": True, "filter_reason": "dietary conflict"}
    # rotation filter — already in week?
    already = {e["recipe_name"] for e in plan_state["week_entries"]}
    if recipe["name"] in already and not recipe.get("batch_parent"):
        return {"filtered": True, "filter_reason": "already in week"}

    components = {
        "macro_fit": score_macro_fit(
            recipe["nutrition"], plan_state["day_so_far"], targets,
            max_score=weights.get("macro_fit_max", 40),
        ),
        "rating": score_rating(recipe.get("rating"), weights.get("rating", {})),
        "rotation": score_rotation(
            recipe.get("last_cooked"), slot["date"], weights.get("rotation", {}),
        ),
        "seasonality": score_seasonality(
            recipe.get("peak_months"), slot["date"], weights.get("seasonality_bonus", 0),
        ),
        "training_day": score_training_day(
            recipe["nutrition"], slot.get("training_day_kind"),
            weights.get("training_day_bonus", 0),
        ),
        "batch_coherence": score_batch_coherence(
            recipe.get("batch_parent"), plan_state["week_entries"],
            None, weights.get("batch_coherence_bonus", 0),
        ),
        "heart_health": weights.get("heart_health_phase_a", 0),
    }
    total = sum(components.values())
    return {"filtered": False, "total": total, "components": components}


_SLOT_OCCASION_MAP = {
    "breakfast": {"breakfast", "grab-and-go-breakfast"},
    "lunch": {"lunch", "weeknight-dinner", "meal-prep"},
    "snack": {"snack"},
    "dinner": {"weeknight-dinner", "dinner", "meal-prep"},
}

def _matches_slot(occasions: list[str], slot_kind: str) -> bool:
    allowed = _SLOT_OCCASION_MAP.get(slot_kind, set())
    return any(o in allowed for o in occasions)
```

**Step 3: Run tests.** Pass.

**Step 4: Commit**

```bash
git add lib/meal_scorer.py tests/test_meal_scorer.py
git commit -m "feat: meal scorer hard filters + score_candidate integration"
```

---

### Task 15: Day composer — combination enumeration + day_fit_bonus

**Files:**
- Create: `lib/day_composer.py`
- Create: `tests/test_day_composer.py`

**Step 1: Test** (covers: enumerate 5^4, pick highest total, day_fit_bonus rewards hitting targets)

```python
# tests/test_day_composer.py
from datetime import date
from lib.nutrition import NutritionData
from lib.day_composer import compose_day


class TestComposeDay:
    def _candidates(self):
        # 5 candidates per slot, differing only in calories
        def gen(prefix, base_cal):
            return [
                {"name": f"{prefix}{i}", "nutrition": NutritionData(base_cal + i * 50, 20, 30, 10),
                 "total": 30 - i, "filtered": False}
                for i in range(5)
            ]
        return {
            "breakfast": gen("B", 400),
            "lunch": gen("L", 500),
            "snack": gen("S", 150),
            "dinner": gen("D", 600),
        }

    def test_returns_top_combination(self):
        targets = NutritionData(2500, 180, 300, 80)
        weights = {"day_fit_bonus_max": 20, "macro_tolerance_pct": 15}
        result = compose_day(self._candidates(), targets, "lifting", weights)
        assert result["status"] == "auto"
        assert set(result["meals"].keys()) == {"breakfast", "lunch", "snack", "dinner"}
        assert "score" in result
        assert "day_fit_bonus" in result
        assert "top_alternatives" in result

    def test_surfaces_top3_when_no_combination_meets_tolerance(self):
        # Use tiny candidates with low calories so no combo hits 2500 ± 15%
        tiny_candidates = {
            slot: [{"name": f"{slot}-{i}", "nutrition": NutritionData(100, 5, 10, 2),
                    "total": 5 - i, "filtered": False} for i in range(5)]
            for slot in ("breakfast", "lunch", "snack", "dinner")
        }
        targets = NutritionData(2500, 180, 300, 80)
        weights = {"day_fit_bonus_max": 20, "macro_tolerance_pct": 15}
        result = compose_day(tiny_candidates, targets, "lifting", weights)
        assert result["status"] == "needs_user_pick"
        assert len(result["top_alternatives"]) == 3
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# lib/day_composer.py
"""Day-level meal composition — picks a B/L/S/D combination that hits daily macros."""
from __future__ import annotations

from itertools import product
from typing import Any

from lib.nutrition import NutritionData


def compose_day(
    candidates: dict[str, list[dict]],   # {slot_name: [scored candidate dict]}
    targets: NutritionData,
    training_day_kind: str | None,
    weights: dict,
) -> dict:
    """Return the best combination + day_fit_bonus, plus the top 3 alternatives.

    When no combination hits macros within tolerance, status='needs_user_pick'.
    """
    slot_order = ["breakfast", "lunch", "snack", "dinner"]
    slots = [candidates.get(s, []) for s in slot_order]
    if any(len(s) == 0 for s in slots):
        return {"status": "insufficient_candidates", "meals": {}, "top_alternatives": []}

    scored = []
    for combo in product(*slots):
        day_macros = _sum_macros([c["nutrition"] for c in combo])
        fit = _day_fit_bonus(day_macros, targets, training_day_kind, weights["day_fit_bonus_max"])
        total = sum(c["total"] for c in combo) + fit
        within = _within_tolerance(day_macros, targets, weights["macro_tolerance_pct"])
        scored.append({
            "meals": {slot_order[i]: combo[i] for i in range(4)},
            "day_macros": day_macros,
            "day_fit_bonus": fit,
            "score": total,
            "within_tolerance": within,
        })
    scored.sort(key=lambda r: r["score"], reverse=True)

    best = scored[0]
    alternatives = scored[1:4]
    if not any(s["within_tolerance"] for s in scored[:3]):
        return {
            "status": "needs_user_pick",
            "meals": best["meals"],
            "score": best["score"],
            "day_fit_bonus": best["day_fit_bonus"],
            "top_alternatives": alternatives,
        }
    return {
        "status": "auto",
        "meals": best["meals"],
        "score": best["score"],
        "day_fit_bonus": best["day_fit_bonus"],
        "top_alternatives": alternatives,
    }


def _sum_macros(macros: list[NutritionData]) -> NutritionData:
    return NutritionData(
        calories=sum(m.calories for m in macros),
        protein=sum(m.protein for m in macros),
        carbs=sum(m.carbs for m in macros),
        fat=sum(m.fat for m in macros),
    )


def _within_tolerance(day: NutritionData, target: NutritionData, pct: float) -> bool:
    for attr in ("calories", "protein", "carbs", "fat"):
        t = getattr(target, attr)
        if t == 0:
            continue
        diff_pct = abs(getattr(day, attr) - t) / t * 100
        if diff_pct > pct:
            return False
    return True


def _day_fit_bonus(day: NutritionData, target: NutritionData, kind: str | None, max_bonus: int) -> float:
    # base: proximity to calorie target (penalty for >20% off)
    if target.calories == 0:
        return 0.0
    cal_dist = abs(day.calories - target.calories) / target.calories
    base = max(0.0, 1.0 - (cal_dist / 0.2))  # 0% off -> 1.0, 20% off -> 0.0
    # training day bonus: lifting days reward high-carb share
    if kind == "lifting" and day.carbs / max(1, day.calories / 4) > 0.55:
        base = min(1.0, base + 0.1)
    elif kind == "rest" and day.calories <= target.calories * 0.95:
        base = min(1.0, base + 0.05)
    return round(base * max_bonus, 2)
```

**Step 4: Run.** Pass.

**Step 5: Commit**

```bash
git add lib/day_composer.py tests/test_day_composer.py
git commit -m "feat: day composer — B/L/S/D combination optimizer"
```

---

### Task 16: Batch cascade — placement suggestions + shopping list suppression

**Files:**
- Create: `lib/batch_cascade.py`
- Create: `tests/test_batch_cascade.py`
- Modify: `lib/shopping_list_generator.py`

**Step 1: Tests for batch cascade**

```python
# tests/test_batch_cascade.py
from lib.batch_cascade import suggest_children, suppress_batch_ingredients


class TestBatchCascade:
    def test_suggest_children_returns_children_in_order(self):
        parent = {
            "name": "Carnitas Batch Cook",
            "batch_cook": True,
            "batch_children": ["Carnitas Tacos", "Carnitas Bowl", "Carnitas Quesadilla"],
            "batch_servings": 12,
        }
        all_recipes = {
            "Carnitas Tacos": {"name": "Carnitas Tacos", "rating": 4, "servings": 3},
            "Carnitas Bowl": {"name": "Carnitas Bowl", "rating": 5, "servings": 3},
            "Carnitas Quesadilla": {"name": "Carnitas Quesadilla", "rating": 3, "servings": 3},
        }
        suggestions = suggest_children(parent, all_recipes, max_children=3)
        # Highest-rated first
        assert [s["name"] for s in suggestions] == [
            "Carnitas Bowl", "Carnitas Tacos", "Carnitas Quesadilla"
        ]

    def test_suppress_batch_ingredients_removes_fuzzy_match(self):
        parent = {"name": "Carnitas Batch Cook", "produces": ["shredded carnitas meat"]}
        child_ingredients = [
            {"amount": "3", "unit": "cups", "item": "shredded carnitas"},
            {"amount": "6", "unit": "", "item": "corn tortillas"},
        ]
        suppressed = suppress_batch_ingredients(child_ingredients, [parent])
        assert len(suppressed) == 1
        assert suppressed[0]["item"] == "corn tortillas"
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# lib/batch_cascade.py
"""Batch-cook cascade helpers: child placement suggestions + ingredient suppression."""
from __future__ import annotations

from lib.normalizer import normalize_field  # existing project helper


def suggest_children(
    parent: dict,
    all_recipes: dict[str, dict],
    max_children: int = 3,
) -> list[dict]:
    """Return ranked child recipes to place alongside a batch parent."""
    names = parent.get("batch_children") or []
    children = [all_recipes[n] for n in names if n in all_recipes]
    # Rank by rating desc (None rating = 0)
    children.sort(key=lambda r: (r.get("rating") or 0), reverse=True)
    return children[:max_children]


def suppress_batch_ingredients(
    child_ingredients: list[dict],
    parents_in_week: list[dict],
) -> list[dict]:
    """Remove child ingredients that match any parent's `produces` entries (fuzzy)."""
    produced = []
    for p in parents_in_week:
        for item in p.get("produces") or []:
            produced.append(_normalize(item))
    if not produced:
        return child_ingredients
    kept = []
    for ing in child_ingredients:
        if _matches_any(_normalize(ing.get("item", "")), produced):
            continue
        kept.append(ing)
    return kept


def _normalize(text: str) -> str:
    return text.lower().strip()


def _matches_any(needle: str, haystack: list[str]) -> bool:
    # Conservative fuzzy: any haystack token is a substring of needle (or vice versa)
    for item in haystack:
        if item in needle or needle in item:
            return True
        # overlap by shared word of length >= 5
        needle_words = set(needle.split())
        item_words = set(item.split())
        shared = {w for w in needle_words & item_words if len(w) >= 5}
        if shared:
            return True
    return False
```

**Step 4: Update `lib/shopping_list_generator.py`** — in `generate_shopping_list`, after collecting recipes for a week, before aggregation:

```python
from lib.batch_cascade import suppress_batch_ingredients

# ... inside the function, for each week:
parents_in_week = [r for r in recipes if r.get("batch_cook")]
for child in recipes:
    if child.get("batch_parent") and any(p["name"] == child["batch_parent"] for p in parents_in_week):
        child["ingredients"] = suppress_batch_ingredients(child["ingredients"], parents_in_week)
```

And at the end of `shopping_list.py` (CLI), after writing the list successfully, add a step to transition that week's meal plan `status` to `locked` + set `locked_at`. Implement this as a new helper in `lib/meal_plan_parser.py`:

```python
def lock_meal_plan(path: Path) -> None:
    """Set status: locked and locked_at: <now ISO> in frontmatter."""
    from datetime import datetime, timezone
    content = path.read_text(encoding="utf-8")
    now = datetime.now(tz=timezone.utc).isoformat()
    content = _upsert_frontmatter_value(content, "status", "locked")
    content = _upsert_frontmatter_value(content, "locked_at", now)
    path.write_text(content, encoding="utf-8")


def _upsert_frontmatter_value(content: str, key: str, value: str) -> str:
    import re
    if re.match(r"^---", content):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        fm_lines = m.group(1).splitlines()
        body = m.group(2)
        set_existing = False
        new_fm_lines = []
        for line in fm_lines:
            kv = re.match(rf"^{re.escape(key)}:\s*", line)
            if kv:
                new_fm_lines.append(f"{key}: {value}")
                set_existing = True
            else:
                new_fm_lines.append(line)
        if not set_existing:
            new_fm_lines.append(f"{key}: {value}")
        return "---\n" + "\n".join(new_fm_lines) + "\n---\n" + body
    return f"---\n{key}: {value}\n---\n{content}"
```

Write a quick test for `lock_meal_plan` in `tests/test_meal_plan_parser.py` — assert status flips from `draft` to `locked` and `locked_at` is ISO-formatted.

**Step 5: Run all touched tests.** Pass.

**Step 6: Commit**

```bash
git add lib/batch_cascade.py lib/shopping_list_generator.py lib/meal_plan_parser.py \
        tests/test_batch_cascade.py tests/test_meal_plan_parser.py
git commit -m "feat: batch-cook cascade + shopping list lock/suppress"
```

---

### Task 17: Planner engine — Mode C (weekday auto-fill)

**Files:**
- Create: `lib/planner_engine.py`
- Create: `tests/test_planner_engine.py`

**Step 1: Test**

```python
# tests/test_planner_engine.py
from unittest.mock import MagicMock
from datetime import date

from lib.nutrition import NutritionData
from lib.planner_engine import plan_weekday_fills


class TestPlanWeekdayFills:
    def test_fills_empty_monday_through_friday(self):
        cache = MagicMock()
        cache.raw_query.return_value = []  # no prior meal plan entries
        # Fake: 10 candidate recipes, all fit any slot
        cache.list_candidates.return_value = _fake_candidates()
        profile = _fake_profile()
        targets = NutritionData(2500, 180, 300, 80)
        week = "2026-W20"

        result = plan_weekday_fills(week, cache, profile, targets)
        assert set(result.keys()) == {"monday", "tuesday", "wednesday", "thursday", "friday"}
        for day in result.values():
            assert set(day["meals"].keys()) == {"breakfast", "lunch", "snack", "dinner"}

    def test_skips_saturday_sunday(self):
        cache = MagicMock()
        cache.raw_query.return_value = []
        cache.list_candidates.return_value = _fake_candidates()
        profile = _fake_profile()
        targets = NutritionData(2500, 180, 300, 80)
        result = plan_weekday_fills("2026-W20", cache, profile, targets)
        assert "saturday" not in result
        assert "sunday" not in result

    def test_respects_existing_filled_slot(self):
        cache = MagicMock()
        cache.raw_query.return_value = [
            ("2026-W20", "2026-05-18", "breakfast", "Oatmeal", 1, "draft"),
        ]
        cache.list_candidates.return_value = _fake_candidates()
        profile = _fake_profile()
        targets = NutritionData(2500, 180, 300, 80)
        result = plan_weekday_fills("2026-W20", cache, profile, targets)
        # Monday breakfast should still be Oatmeal
        assert result["monday"]["meals"]["breakfast"]["name"] == "Oatmeal"


def _fake_candidates():
    return [
        {"name": f"R{i}", "rating": 3, "meal_occasion": ["weeknight-dinner", "breakfast", "lunch", "snack"],
         "dietary": [], "last_cooked": None, "peak_months": [], "batch_parent": None,
         "nutrition": NutritionData(500, 30, 60, 15)}
        for i in range(10)
    ]


def _fake_profile():
    class FakeProfile:
        training_days = {"Monday": "lifting", "Wednesday": "lifting", "Friday": "lifting"}
    return FakeProfile()
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# lib/planner_engine.py
"""Orchestrator for Mode C (weekday auto-fill) and Mode D (one-shot builder)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from lib.day_composer import compose_day
from lib.meal_scorer import score_candidate
from lib.scoring_weights import load_weights

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def plan_weekday_fills(week: str, cache, profile, targets) -> dict:
    """Fill Mon–Fri of `week` using day composer. Respects existing entries."""
    weights = load_weights()
    year, wk = week.split("-W")
    monday = date.fromisocalendar(int(year), int(wk), 1)

    existing = _load_existing_entries(cache, week)  # {date_iso: {slot: name}}
    all_candidates = cache.list_candidates()

    out = {}
    day_so_far_running = None  # reset per day
    for idx, day_name in enumerate(WEEKDAYS):
        d = monday + timedelta(days=idx)
        kind = profile.training_days.get(day_name.capitalize())
        existing_day = existing.get(d.isoformat(), {})

        slot_candidates = {}
        from lib.nutrition import NutritionData
        day_so_far = NutritionData(0, 0, 0, 0)
        # for each slot, build candidate list
        for slot in ("breakfast", "lunch", "snack", "dinner"):
            if slot in existing_day:
                # keep the existing; don't re-score
                slot_candidates[slot] = [_fixed_candidate(existing_day[slot], cache)]
                continue
            ctx = {"date": d, "meal_slot": slot, "training_day_kind": kind}
            state = {
                "day_so_far": day_so_far,
                "week_entries": _entries_flat(existing, week),
                "user_dietary_exclusions": [],
            }
            scored = []
            for recipe in all_candidates:
                r = score_candidate(recipe, ctx, state, targets, weights)
                if r.get("filtered"):
                    continue
                scored.append({**recipe, **r})
            scored.sort(key=lambda r: r["total"], reverse=True)
            slot_candidates[slot] = scored[:weights["top_k_per_slot"]]

        composed = compose_day(slot_candidates, targets, kind, weights)
        out[day_name] = composed
    return out


def _load_existing_entries(cache, week: str) -> dict:
    rows = cache.raw_query(
        "SELECT date, meal_slot, recipe_name FROM meal_plan_entries WHERE week = ?",
        (week,),
    )
    out: dict[str, dict[str, str]] = {}
    for date_iso, slot, name in rows:
        out.setdefault(date_iso, {})[slot] = name
    return out


def _entries_flat(existing, week) -> list[dict]:
    flat = []
    for date_iso, slots in existing.items():
        for slot, name in slots.items():
            flat.append({"date": date_iso, "meal_slot": slot, "recipe_name": name, "servings": 1})
    return flat


def _fixed_candidate(recipe_name: str, cache) -> dict:
    row = cache.raw_query(
        "SELECT name, rating, calories, protein_g, carbs_g, fat_g FROM recipes WHERE name = ?",
        (recipe_name,),
    )
    if not row:
        return {"name": recipe_name, "total": 0, "filtered": False, "nutrition": None}
    n = row[0]
    from lib.nutrition import NutritionData
    return {
        "name": n[0],
        "total": 0,
        "filtered": False,
        "nutrition": NutritionData(calories=n[2] or 0, protein=n[3] or 0, carbs=n[4] or 0, fat=n[5] or 0),
    }
```

Also add `Cache.list_candidates()` method — returns list of recipe dicts for the scorer. Extend `lib/cache.py`:

```python
def _cache_list_candidates(self: "Cache") -> list[dict]:
    """Return all recipes as dicts suited for the scorer."""
    rows = self.raw_query(
        "SELECT name, rating, meal_occasion, dietary, last_cooked, peak_months, "
        "batch_parent, calories, protein_g, carbs_g, fat_g FROM recipes"
    )
    out = []
    for r in rows:
        import json
        from lib.nutrition import NutritionData
        from datetime import date as _d
        out.append({
            "name": r[0],
            "rating": r[1],
            "meal_occasion": json.loads(r[2]) if r[2] else [],
            "dietary": json.loads(r[3]) if r[3] else [],
            "last_cooked": _d.fromisoformat(r[4]) if r[4] else None,
            "peak_months": json.loads(r[5]) if r[5] else [],
            "batch_parent": r[6],
            "nutrition": NutritionData(
                calories=r[7] or 0, protein=r[8] or 0, carbs=r[9] or 0, fat=r[10] or 0,
            ),
        })
    return out


Cache.list_candidates = _cache_list_candidates
```

**Step 4: Run tests.** Pass.

**Step 5: Commit**

```bash
git add lib/planner_engine.py lib/cache.py tests/test_planner_engine.py
git commit -m "feat: planner engine — Mode C weekday auto-fill"
```

---

### Task 18: Claude prompt for Mode D (one-shot week builder)

**Files:**
- Create: `prompts/week_builder.py`
- Create: `tests/test_week_builder_prompt.py`

**Step 1: Test the prompt shape** (not Claude's output — just the prompt string construction):

```python
# tests/test_week_builder_prompt.py
from lib.nutrition import NutritionData
from prompts.week_builder import build_week_builder_prompt


class TestWeekBuilderPrompt:
    def test_includes_intent_and_targets_and_recipes(self):
        targets = NutritionData(2800, 200, 300, 80)
        profile = type("P", (), {
            "training_days": {"Monday": "lifting", "Wednesday": "lifting", "Friday": "lifting"},
            "heart_health_raw": "Watching sodium.",
        })
        last_4_weeks = [{"week": "2026-W18", "entries": []}]
        candidates = [{"name": "Chili", "rating": 4, "nutrition": NutritionData(650, 40, 70, 18),
                       "cuisine": "American", "meal_occasion": ["weeknight-dinner"]}]
        batch_recipes = []
        intent = "heavy lifting, batch cook Sunday"
        prompt = build_week_builder_prompt(
            week="2026-W20", intent=intent, targets=targets, profile=profile,
            last_4_weeks=last_4_weeks, candidates=candidates, batch_recipes=batch_recipes,
        )
        assert "2026-W20" in prompt
        assert "heavy lifting" in prompt
        assert "2800" in prompt
        assert "Chili" in prompt
        assert "Watching sodium" in prompt
        assert "lifting" in prompt
```

**Step 2: Run — fail.**

**Step 3: Implement**

```python
# prompts/week_builder.py
"""Claude prompt template for the one-shot week builder (Mode D)."""
import json


SYSTEM_PROMPT = """You are a meal plan assistant for KitchenOS. You build weekly \
meal plans optimized for the user's macro targets, training schedule, and heart-health \
considerations. Respond ONLY with valid JSON matching the schema below.

Schema:
{
  "days": {
    "monday": {"breakfast": "Recipe Name" | null, "lunch": ..., "snack": ..., "dinner": ...},
    "tuesday": {...},
    ...,
    "sunday": {...}
  },
  "rationale": {
    "monday": "short reason why this day works",
    ...
  }
}

Rules:
- Every recipe name MUST appear in the provided candidate list. Do not invent recipes.
- Hit daily calorie target within ±15%. Prefer recipes with higher ratings.
- On lifting days, prioritize high-protein and higher-carb combinations.
- On rest days, balance macros; reduce calories ~5%.
- Avoid repeating any recipe within the week unless it's a batch-cook child.
- If a batch-cook parent is placed, prefer its children in later slots that week.
"""


def build_week_builder_prompt(
    week: str, intent: str, targets, profile,
    last_4_weeks, candidates, batch_recipes,
) -> str:
    intent_str = intent or "(no specific intent)"
    training_days = ", ".join(f"{d}:{k}" for d, k in profile.training_days.items()) or "(none)"
    recent_used = []
    for w in last_4_weeks:
        for e in w.get("entries", []):
            recent_used.append(e.get("recipe_name"))
    recent_used = [n for n in recent_used if n]

    recipe_summary = [
        {
            "name": r["name"],
            "rating": r.get("rating"),
            "cuisine": r.get("cuisine"),
            "meal_occasion": r.get("meal_occasion", []),
            "calories": r["nutrition"].calories,
            "protein_g": r["nutrition"].protein,
            "carbs_g": r["nutrition"].carbs,
            "fat_g": r["nutrition"].fat,
        }
        for r in candidates
    ]
    batch_summary = [{"name": b["name"], "children": b.get("batch_children", [])} for b in batch_recipes]

    return f"""Week: {week}
Intent: {intent_str}

Daily targets: calories={targets.calories}, protein={targets.protein}g, \
carbs={targets.carbs}g, fat={targets.fat}g
Training days: {training_days}
Heart health notes: {profile.heart_health_raw or "(none)"}

Recently used recipes (avoid unless rating >= 4):
{json.dumps(recent_used, indent=2)}

Batch-cook parents available:
{json.dumps(batch_summary, indent=2)}

Candidate recipes:
{json.dumps(recipe_summary, indent=2)}

Return the plan JSON now.
"""
```

**Step 4: Run tests.** Pass.

**Step 5: Commit**

```bash
git add prompts/week_builder.py tests/test_week_builder_prompt.py
git commit -m "feat: Claude prompt template for Mode D week builder"
```

---

### Task 19: Mode D CLI entry — `plan_week.py`

**Files:**
- Create: `plan_week.py`
- Modify: `lib/planner_engine.py` — add `build_full_week`

**Step 1: Test `build_full_week` with Claude mocked**

```python
# append to tests/test_planner_engine.py
from unittest.mock import patch

class TestBuildFullWeek:
    def test_calls_claude_and_parses_json(self):
        fake_response = '{"days": {"monday": {"breakfast": "Oatmeal", "lunch": "Chili", ' \
                        '"snack": "Apple", "dinner": "Salmon"}, "tuesday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}, "wednesday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}, "thursday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}, "friday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}, "saturday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}, "sunday": {"breakfast": null, ' \
                        '"lunch": null, "snack": null, "dinner": null}}, "rationale": {}}'
        cache = MagicMock()
        cache.list_candidates.return_value = [
            {"name": "Oatmeal", "rating": 3, "nutrition": NutritionData(300, 12, 50, 6),
             "meal_occasion": ["breakfast"], "cuisine": "American"},
            {"name": "Chili", "rating": 4, "nutrition": NutritionData(650, 40, 70, 18),
             "meal_occasion": ["weeknight-dinner"], "cuisine": "American"},
            {"name": "Apple", "rating": 3, "nutrition": NutritionData(100, 0, 25, 0),
             "meal_occasion": ["snack"], "cuisine": "n/a"},
            {"name": "Salmon", "rating": 5, "nutrition": NutritionData(500, 45, 10, 25),
             "meal_occasion": ["weeknight-dinner"], "cuisine": "American"},
        ]
        cache.raw_query.return_value = []  # no history
        profile = _fake_profile()
        profile.heart_health_raw = ""
        targets = NutritionData(2500, 180, 300, 80)

        with patch("lib.planner_engine._call_claude", return_value=fake_response):
            from lib.planner_engine import build_full_week
            result = build_full_week("2026-W20", "", cache, profile, targets)

        assert result["days"]["monday"]["breakfast"] == "Oatmeal"
        assert result["days"]["monday"]["dinner"] == "Salmon"
```

**Step 2: Implement `build_full_week`**

Append to `lib/planner_engine.py`:

```python
import json
import os


def build_full_week(week: str, intent: str, cache, profile, targets, model: str = "claude-opus-4-7"):
    from prompts.week_builder import SYSTEM_PROMPT, build_week_builder_prompt
    candidates = cache.list_candidates()
    batch_recipes = [r for r in candidates if r.get("batch_cook")]
    last_4_weeks = _last_n_weeks(cache, week, n=4)

    user_prompt = build_week_builder_prompt(
        week=week, intent=intent, targets=targets, profile=profile,
        last_4_weeks=last_4_weeks, candidates=candidates, batch_recipes=batch_recipes,
    )
    response = _call_claude(SYSTEM_PROMPT, user_prompt, model=model)
    plan = json.loads(response)
    _validate_plan(plan, candidates)
    return plan


def _call_claude(system: str, user: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=model,
        system=system,
        max_tokens=4096,
        messages=[{"role": "user", "content": user}],
    )
    # The model may wrap JSON in fences; strip if needed
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0]
    return text


def _validate_plan(plan: dict, candidates: list[dict]) -> None:
    valid_names = {r["name"] for r in candidates}
    days = plan.get("days", {})
    for day, slots in days.items():
        for slot, name in slots.items():
            if name and name not in valid_names:
                raise ValueError(f"Plan references unknown recipe: {name} on {day}/{slot}")


def _last_n_weeks(cache, this_week: str, n: int = 4) -> list[dict]:
    from datetime import date, timedelta
    year, wk = this_week.split("-W")
    base = date.fromisocalendar(int(year), int(wk), 1)
    results = []
    for i in range(1, n + 1):
        prior = base - timedelta(weeks=i)
        prior_week = f"{prior.isocalendar()[0]}-W{prior.isocalendar()[1]:02d}"
        entries = cache.raw_query(
            "SELECT date, meal_slot, recipe_name FROM meal_plan_entries WHERE week = ?",
            (prior_week,),
        )
        results.append({
            "week": prior_week,
            "entries": [{"date": e[0], "meal_slot": e[1], "recipe_name": e[2]} for e in entries],
        })
    return results
```

**Step 3: Write `plan_week.py` CLI**

```python
# plan_week.py
"""Mode D — one-shot full-week builder CLI.

Usage:
  .venv/bin/python plan_week.py --week 2026-W20 --intent "heavy lifting week"
  .venv/bin/python plan_week.py --week 2026-W20 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.cache import Cache
from lib.macro_targets import load_macro_profile
from lib.planner_engine import build_full_week

VAULT = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS"
)
CACHE_DB = Path(__file__).resolve().parent / ".kitchenos-cache.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True, help="ISO week, e.g. 2026-W20")
    ap.add_argument("--intent", default="", help="optional intent string")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    profile = load_macro_profile(VAULT)
    if profile is None:
        print("My Macros.md not found. Run the macros setup first.", file=sys.stderr)
        sys.exit(1)

    cache = Cache(CACHE_DB)
    cache.init_schema()
    cache.sync_recipes(VAULT / "Recipes")
    cache.sync_meal_plans(VAULT / "Meal Plans")

    plan = build_full_week(args.week, args.intent, cache, profile, profile.targets)
    if args.dry_run:
        import json
        print(json.dumps(plan, indent=2))
        return

    _write_plan_to_markdown(args.week, plan, VAULT / "Meal Plans")
    print(f"Wrote plan to Meal Plans/{args.week}.md")


def _write_plan_to_markdown(week: str, plan: dict, plans_dir: Path) -> None:
    """Overwrite / merge plan into the meal plan file, keeping frontmatter + existing."""
    path = plans_dir / f"{week}.md"
    # Build markdown body per day/slot
    # ... see templates/meal_plan_template.py for day labels
    from templates.meal_plan_template import generate_meal_plan_markdown
    # Generate a fresh template, then inject recipe links per plan["days"]
    import re
    md = generate_meal_plan_markdown(week)
    for day_name, slots in plan["days"].items():
        label = day_name.capitalize()
        for slot, recipe in slots.items():
            if recipe is None:
                continue
            slot_header = f"### {slot.capitalize()}"
            day_block_pat = rf"(## {label}.*?{re.escape(slot_header)}\n)([^\n#]*)"
            md = re.sub(
                day_block_pat,
                lambda m: m.group(1) + f"[[{recipe}]]\n",
                md, count=1, flags=re.DOTALL,
            )
    path.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests** (unit-level — CLI is exercised end-to-end in Task 25).

```bash
.venv/bin/python -m pytest tests/test_planner_engine.py -v
```

**Step 5: Commit**

```bash
git add plan_week.py lib/planner_engine.py tests/test_planner_engine.py
git commit -m "feat: Mode D CLI + build_full_week via Claude API"
```

---

### Task 20: Weekly digest — prompt + generator

**Files:**
- Create: `prompts/weekly_digest.py`
- Create: `templates/vault_review_template.py`
- Create: `lib/weekly_digest.py`
- Create: `tests/test_weekly_digest.py`

**Step 1: Write `weekly_digest` prompt template**

```python
# prompts/weekly_digest.py
"""Claude prompt for the Wednesday vault review digest."""

SYSTEM_PROMPT = """You are a nutrition and meal-planning assistant. Analyze the user's past week \
of meals, ratings, and notes and produce a concise weekly digest in markdown with these sections:

# Vault Review — Week {week}

## Last week at a glance
(Adherence table: calories/protein/carbs/fat per day, target vs. actual. Then 2-3 sentences of summary.)

## What worked
(High ratings, positive notes. Pull themes — cuisines, prep time, ingredients.)

## What didn't
(Skipped meals, low ratings, notes mentioning friction.)

## Patterns spotted
(Only include if at least 8 weeks of history exist. Otherwise write 'Insufficient history'.)

## Proposed next week
(A pre-filled plan for the next unlocked week as a JSON block. Same schema as Mode D.)

## Suggested swaps
(For slots already filled in the upcoming plan, suggest higher-rated alternatives.)

Be concise. Target 400-800 words total. Use data; avoid generic advice."""


def build_digest_prompt(
    week: str, last_week_entries, notes_last_7, rating_changes,
    adherence, upcoming_plan, candidates, history_weeks_count: int,
) -> str:
    import json
    return f"""Week reviewed: {week}
History available: {history_weeks_count} weeks

Last week's meals:
{json.dumps(last_week_entries, indent=2)}

Notes added in last 7 days:
{json.dumps(notes_last_7, indent=2)}

Rating changes in last 7 days:
{json.dumps(rating_changes, indent=2)}

Adherence vs. targets per day:
{json.dumps(adherence, indent=2)}

Upcoming plan (next unlocked week):
{json.dumps(upcoming_plan, indent=2)}

Candidates (top 30 by rating + recent 14d):
{json.dumps(candidates[:40], indent=2)}

Produce the digest markdown now."""
```

**Step 2: Write `weekly_digest` core**

```python
# lib/weekly_digest.py
"""Digest generation logic.

Reads cache → builds Claude prompt → writes Vault Review/YYYY-W##.md →
logs to digests table.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from lib.cache import Cache
from lib.macro_targets import load_macro_profile
from prompts.weekly_digest import SYSTEM_PROMPT, build_digest_prompt
from lib.planner_engine import _call_claude


def run_digest(vault: Path, cache_db: Path, this_week: str | None = None) -> Path:
    profile = load_macro_profile(vault)
    if profile is None:
        raise RuntimeError("My Macros.md not found — cannot run digest")

    cache = Cache(cache_db)
    cache.init_schema()
    cache.sync_recipes(vault / "Recipes")
    cache.sync_notes(vault / "Recipes")
    cache.sync_meal_plans(vault / "Meal Plans")

    if this_week is None:
        today = date.today()
        last_mon = today - timedelta(days=today.weekday() + 7)
        this_week = f"{last_mon.isocalendar()[0]}-W{last_mon.isocalendar()[1]:02d}"

    last_week_entries = cache.raw_query(
        "SELECT date, meal_slot, recipe_name, servings FROM meal_plan_entries WHERE week = ?",
        (this_week,),
    )
    notes_last_7 = cache.raw_query(
        "SELECT recipe_name, added_date, note FROM recipe_notes "
        "WHERE added_date >= date('now', '-7 days') ORDER BY added_date DESC"
    )
    rating_changes = cache.raw_query(
        "SELECT name, rating, updated_at FROM recipes "
        "WHERE updated_at >= datetime('now', '-7 days') AND rating IS NOT NULL"
    )

    adherence = _compute_adherence(cache, this_week, profile.targets)

    upcoming_week = _next_unlocked_week(cache)
    upcoming_plan = cache.raw_query(
        "SELECT date, meal_slot, recipe_name FROM meal_plan_entries WHERE week = ?",
        (upcoming_week,),
    ) if upcoming_week else []

    candidates = cache.raw_query(
        "SELECT name, rating, cuisine, meal_occasion, calories, protein_g, carbs_g, fat_g "
        "FROM recipes WHERE rating IS NOT NULL ORDER BY rating DESC LIMIT 30"
    )
    history_count = _history_weeks_count(cache)

    user_prompt = build_digest_prompt(
        week=this_week,
        last_week_entries=[dict(zip(["date", "slot", "recipe", "servings"], r)) for r in last_week_entries],
        notes_last_7=[dict(zip(["recipe", "date", "note"], r)) for r in notes_last_7],
        rating_changes=[dict(zip(["recipe", "rating", "updated_at"], r)) for r in rating_changes],
        adherence=adherence,
        upcoming_plan=[dict(zip(["date", "slot", "recipe"], r)) for r in upcoming_plan],
        candidates=[dict(zip(
            ["name", "rating", "cuisine", "meal_occasion", "calories",
             "protein_g", "carbs_g", "fat_g"], r,
        )) for r in candidates],
        history_weeks_count=history_count,
    )
    markdown = _call_claude(SYSTEM_PROMPT, user_prompt, model="claude-opus-4-7")
    if markdown.startswith("```"):
        markdown = markdown.split("\n", 1)[1].rsplit("```", 1)[0]

    reviews_dir = vault / "Vault Review"
    reviews_dir.mkdir(exist_ok=True)
    out_path = reviews_dir / f"{this_week}.md"
    out_path.write_text(markdown, encoding="utf-8")

    from datetime import datetime, timezone
    cache.conn.execute(
        "INSERT OR REPLACE INTO digests(week, generated_at, summary_path) VALUES (?, ?, ?)",
        (this_week, datetime.now(tz=timezone.utc).isoformat(), str(out_path)),
    )
    cache.conn.commit()
    return out_path


def _compute_adherence(cache, week: str, targets) -> list[dict]:
    # Phase A assumption: planned == cooked
    rows = cache.raw_query(
        "SELECT mpe.date, mpe.recipe_name, r.calories, r.protein_g, r.carbs_g, r.fat_g "
        "FROM meal_plan_entries mpe LEFT JOIN recipes r ON r.name = mpe.recipe_name "
        "WHERE mpe.week = ? ORDER BY mpe.date",
        (week,),
    )
    per_day: dict[str, dict] = {}
    for d, name, cal, pro, carb, fat in rows:
        if d not in per_day:
            per_day[d] = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        per_day[d]["calories"] += cal or 0
        per_day[d]["protein"] += pro or 0
        per_day[d]["carbs"] += carb or 0
        per_day[d]["fat"] += fat or 0
    return [
        {
            "date": d,
            "calories_pct": round(m["calories"] / targets.calories * 100) if targets.calories else 0,
            "protein_pct": round(m["protein"] / targets.protein * 100) if targets.protein else 0,
            "carbs_pct": round(m["carbs"] / targets.carbs * 100) if targets.carbs else 0,
            "fat_pct": round(m["fat"] / targets.fat * 100) if targets.fat else 0,
            "calories": m["calories"], "protein": m["protein"],
            "carbs": m["carbs"], "fat": m["fat"],
        }
        for d, m in sorted(per_day.items())
    ]


def _next_unlocked_week(cache) -> str | None:
    rows = cache.raw_query(
        "SELECT DISTINCT week FROM meal_plan_entries WHERE status = 'draft' ORDER BY week LIMIT 1"
    )
    return rows[0][0] if rows else None


def _history_weeks_count(cache) -> int:
    rows = cache.raw_query("SELECT COUNT(DISTINCT week) FROM meal_plan_entries")
    return rows[0][0] if rows else 0
```

**Step 3: Test with Claude mocked**

```python
# tests/test_weekly_digest.py
import tempfile
from pathlib import Path
from unittest.mock import patch

from lib.cache import Cache
from lib.weekly_digest import run_digest


class TestRunDigest:
    def test_writes_vault_review_file(self, tmp_path):
        vault = tmp_path
        (vault / "Recipes").mkdir()
        (vault / "Meal Plans").mkdir()
        (vault / "My Macros.md").write_text("""---
calories: 2500
protein: 180
carbs: 300
fat: 80
---

# My Daily Macros

## Training Days
- Monday: lifting
""", encoding="utf-8")
        db = tmp_path / "cache.db"
        fake_md = "# Vault Review — Week 2026-W19\n\n## Last week at a glance\nGreat week."
        with patch("lib.weekly_digest._call_claude", return_value=fake_md):
            out = run_digest(vault, db, this_week="2026-W19")
        assert out.exists()
        assert "Vault Review" in str(out)
        assert "Great week" in out.read_text()
```

**Step 4: Run.** Pass.

**Step 5: Commit**

```bash
git add prompts/weekly_digest.py lib/weekly_digest.py tests/test_weekly_digest.py
git commit -m "feat: weekly digest — Claude-driven vault review"
```

---

### Task 21: `weekly_digest.py` CLI + LaunchAgent plist

**Files:**
- Create: `weekly_digest.py` (CLI entry)
- Create: `com.kitchenos.weekly-digest.plist`

**Step 1: CLI script**

```python
# weekly_digest.py
"""Entry point for weekly vault review digest.

Triggered by com.kitchenos.weekly-digest.plist every Wednesday at 6am.
Also runs Mode C weekday auto-fill after the digest completes.
"""
from pathlib import Path

from lib.weekly_digest import run_digest
from lib.cache import Cache
from lib.macro_targets import load_macro_profile
from lib.planner_engine import plan_weekday_fills

VAULT = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS"
)
CACHE_DB = Path(__file__).resolve().parent / ".kitchenos-cache.db"


def main():
    out = run_digest(VAULT, CACHE_DB)
    print(f"Digest written: {out}")

    cache = Cache(CACHE_DB)
    cache.init_schema()
    cache.sync_recipes(VAULT / "Recipes")
    cache.sync_meal_plans(VAULT / "Meal Plans")
    profile = load_macro_profile(VAULT)
    if profile is None:
        return

    # Find the nearest unlocked week and auto-fill Mon-Fri
    rows = cache.raw_query(
        "SELECT DISTINCT week FROM meal_plan_entries WHERE status = 'draft' ORDER BY week LIMIT 1"
    )
    if not rows:
        return
    week = rows[0][0]
    result = plan_weekday_fills(week, cache, profile, profile.targets)
    _write_weekday_fills(VAULT, week, result)


def _write_weekday_fills(vault: Path, week: str, result: dict) -> None:
    import re
    path = vault / "Meal Plans" / f"{week}.md"
    if not path.exists():
        return
    md = path.read_text(encoding="utf-8")
    for day_name, composed in result.items():
        label = day_name.capitalize()
        for slot, cand in composed.get("meals", {}).items():
            recipe_name = cand.get("name")
            if not recipe_name:
                continue
            # only fill empty slots
            slot_header = f"### {slot.capitalize()}"
            day_block_pat = rf"(## {label}.*?{re.escape(slot_header)}\n)(\n|$)"
            md = re.sub(day_block_pat, lambda m: m.group(1) + f"[[{recipe_name}]]\n", md, count=1, flags=re.DOTALL)
    path.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
```

**Step 2: LaunchAgent plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kitchenos.weekly-digest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/chaseeasterling/KitchenOS/.venv/bin/python</string>
        <string>/Users/chaseeasterling/KitchenOS/weekly_digest.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>3</integer>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/chaseeasterling/KitchenOS/weekly_digest.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/chaseeasterling/KitchenOS/weekly_digest.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**Step 3: Smoke test the CLI manually** (after `My Macros.md` exists):

```bash
.venv/bin/python weekly_digest.py
```

Expected: `Digest written: .../Vault Review/YYYY-W##.md` and no exception.

**Step 4: Install LaunchAgent**

```bash
cp com.kitchenos.weekly-digest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.weekly-digest.plist
launchctl list | grep kitchenos.weekly-digest
```

**Step 5: Commit**

```bash
git add weekly_digest.py com.kitchenos.weekly-digest.plist
git commit -m "feat: weekly digest CLI + Wednesday 6am LaunchAgent"
```

---

### Task 22: API endpoints for planner

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_api_endpoints.py` (or `test_api_server.py` — use whichever the project uses for new endpoints)

Add:

- `POST /api/plan-next-week` — body: `{week, intent}` — runs Mode D, writes to vault, returns plan JSON.
- `POST /api/score-candidates` — body: `{week, date, meal_slot}` — returns top-K candidates with breakdowns for UI.
- `GET /api/digest-preview?week=YYYY-W##` — returns the digest markdown (or 404 if not yet generated).
- `PATCH /api/recipe-rating` — body: `{recipe_name, rating}` — updates frontmatter, re-indexes cache entry.

For each endpoint, TDD: mock the cache / Claude, assert JSON shape.

**Commit one endpoint at a time** with message like `feat: POST /api/plan-next-week for Mode D`.

---

### Task 23: Meal planner UI updates — day-score panel, rating stars, Build Week button

**Files:**
- Modify: `templates/meal_planner.html`

Three UI additions — each its own commit.

**23a — Day-score panel:** sticky panel in the day columns showing running totals (calories, protein, carbs, fat, sat fat, sodium, fiber, added sugar). Color-coded: green if within ±10% of target, yellow if within ±20%, red otherwise. Heart-health metrics shown in a secondary row (Phase A is informational; no color coding yet).

**23b — Rating stars:** tap to set rating (1–5) inline on each recipe card in the sidebar. Sends `PATCH /api/recipe-rating`. Optimistic update; roll back on error.

**23c — "Build Full Week" button:** header button opens a modal with an intent text field. On submit, calls `POST /api/plan-next-week`. Shows a progress spinner; refreshes the board when complete.

Test each UI change by opening `http://localhost:5001/meal-planner` in a browser — KitchenOS doesn't currently have frontend tests, so document manual test steps in the commit message.

**Commit once per sub-change.**

---

### Task 24: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

Add sections documenting:

- New Key Functions table entries for every new module (`lib/cache.py`, `lib/meal_scorer.py`, `lib/day_composer.py`, `lib/batch_cascade.py`, `lib/planner_engine.py`, `lib/weekly_digest.py`).
- New architecture subsection for the planner engine + cache.
- New commands section: `plan_week.py`, `weekly_digest.py`, install steps for the new LaunchAgent.
- New config note for `config/scoring_weights.json`.
- Updates to AI Configuration: note that Claude is used for Mode D and the Wednesday digest, Ollama still used for scoring assists.

**Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for smart meal plan engine"
```

---

### Task 25: End-to-end verification

**Step 1: Ensure `My Macros.md` exists** (user step; skip if already done).

**Step 2: Delete + rebuild cache** to verify a clean boot:

```bash
rm -f .kitchenos-cache.db
.venv/bin/python -c "from pathlib import Path; from lib.cache import Cache; c = Cache(Path('.kitchenos-cache.db')); c.init_schema(); c.sync_recipes(Path('/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes')); print('synced')"
```

**Step 3: Run Mode D for a future week (dry-run first):**

```bash
.venv/bin/python plan_week.py --week 2026-W22 --intent "heavy lifting, batch-cook Sunday" --dry-run
```

Inspect the JSON; verify recipe names are all real, no duplicates, day macros within ±15% of targets.

**Step 4: Run for real:**

```bash
.venv/bin/python plan_week.py --week 2026-W22 --intent "heavy lifting, batch-cook Sunday"
```

Open `Meal Plans/2026-W22.md` in Obsidian — verify 7 days filled, frontmatter has `status: draft`.

**Step 5: Run the weekly digest manually:**

```bash
.venv/bin/python weekly_digest.py
```

Verify `Vault Review/YYYY-W##.md` exists with 5 sections.

**Step 6: Commit any end-to-end fixes discovered.** No code commit if everything passes.

**Step 7: Add a smoke-test script for future verification:**

```bash
# scripts/smoke_test_planner.sh
#!/usr/bin/env bash
set -euo pipefail
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python -m pytest tests/test_cache.py tests/test_meal_scorer.py tests/test_day_composer.py tests/test_planner_engine.py tests/test_weekly_digest.py -v
.venv/bin/python plan_week.py --week "$(date -v+2w +%G-W%V)" --intent "smoke test" --dry-run >/dev/null
echo "Smoke tests passed."
```

```bash
chmod +x scripts/smoke_test_planner.sh
git add scripts/smoke_test_planner.sh
git commit -m "chore: smoke-test script for planner engine"
```

---

## Phase A.5: Kitchen Inventory

Phase A.5 sits between Phase A (core planner) and Phase B (cook-logging + receipt OCR). It leverages Phase A's cache + scorer with additive changes only — no refactors required. Same TDD cadence as Phase A.

### Task 26: `inventory` SQLite table + cache integration

**Files:**
- Modify: `lib/cache.py` — add table DDL
- Modify: `tests/test_cache.py`

**Step 1: Add DDL to `_DDL` string in `lib/cache.py`**

```sql
CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY,
  item TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT NOT NULL,
  category TEXT NOT NULL,
  added_date DATE NOT NULL,
  expires_date DATE,
  notes TEXT,
  updated_at DATETIME,
  UNIQUE(item, unit, category)
);

CREATE INDEX IF NOT EXISTS idx_inventory_item ON inventory(item);
CREATE INDEX IF NOT EXISTS idx_inventory_expires ON inventory(expires_date);
```

**Step 2: Extend schema test**

Add to `TestCacheSchema`:

```python
def test_init_creates_inventory_table(self):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        cache = Cache(db)
        cache.init_schema()
        tables = cache.raw_query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        assert any(r[0] == "inventory" for r in tables)
```

**Step 3: Run tests.** All pass.

**Step 4: Commit**

```bash
git add lib/cache.py tests/test_cache.py
git commit -m "feat: inventory SQLite table in cache schema"
```

---

### Task 27: `lib/inventory.py` — parser + normalizer + round-trip

**Files:**
- Create: `lib/inventory.py`
- Create: `templates/inventory_template.py`
- Create: `tests/test_inventory.py`

**Step 1: Tests covering normalization + markdown↔struct round-trip**

```python
# tests/test_inventory.py
import tempfile
from datetime import date
from pathlib import Path

from lib.inventory import (
    normalize_item, normalize_unit, parse_inventory_md,
    write_inventory_md, default_expiry,
)


class TestNormalize:
    def test_normalize_item_lowercases_and_singularizes(self):
        assert normalize_item("Yellow Onions") == "yellow onion"
        assert normalize_item("EGGS") == "egg"
        assert normalize_item("  tomatoes  ") == "tomato"

    def test_normalize_unit_aliases(self):
        assert normalize_unit("lbs") == "lb"
        assert normalize_unit("Pounds") == "lb"
        assert normalize_unit("bottles") == "bottle"
        assert normalize_unit("boxes") == "box"
        assert normalize_unit("") == "each"


class TestDefaultExpiry:
    def test_produce_default(self):
        assert default_expiry("produce", date(2026, 4, 19)) == date(2026, 4, 26)

    def test_fridge_default(self):
        assert default_expiry("fridge", date(2026, 4, 19)) == date(2026, 5, 3)

    def test_freezer_default(self):
        assert default_expiry("freezer", date(2026, 4, 19)) == date(2026, 7, 18)

    def test_pantry_default_none(self):
        assert default_expiry("pantry", date(2026, 4, 19)) is None


class TestRoundTrip:
    def test_parse_basic_markdown(self):
        md = """# Kitchen Inventory

## Pantry
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|
| olive oil | 1 | bottle | 2026-03-15 |  |  |

## Fridge
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|
| chicken breast | 2 | lb | 2026-04-18 | 2026-04-22 |  |
"""
        items = parse_inventory_md(md)
        assert len(items) == 2
        assert items[0]["item"] == "olive oil"
        assert items[0]["category"] == "pantry"
        assert items[1]["qty"] == 2.0
        assert items[1]["unit"] == "lb"
        assert items[1]["expires_date"] == "2026-04-22"

    def test_write_and_reparse_is_lossless(self):
        items = [
            {"item": "olive oil", "qty": 1, "unit": "bottle",
             "category": "pantry", "added_date": "2026-03-15",
             "expires_date": None, "notes": ""},
            {"item": "chicken breast", "qty": 2.0, "unit": "lb",
             "category": "fridge", "added_date": "2026-04-18",
             "expires_date": "2026-04-22", "notes": ""},
        ]
        md = write_inventory_md(items)
        reparsed = parse_inventory_md(md)
        assert len(reparsed) == 2
        assert reparsed[0]["item"] == "olive oil"
        assert reparsed[1]["expires_date"] == "2026-04-22"
```

**Step 2: Run — fail.**

**Step 3: Implement `lib/inventory.py`**

```python
# lib/inventory.py
"""Kitchen inventory: Inventory.md ↔ SQLite round-trip + normalization."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

CATEGORIES = ("pantry", "fridge", "freezer", "produce")

_UNIT_ALIASES = {
    "": "each",
    "ea": "each",
    "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ounce": "oz", "ounces": "oz",
    "bottles": "bottle",
    "boxes": "box",
    "cans": "can",
    "cups": "cup",
    "bags": "bag",
    "jars": "jar",
    "packages": "package", "pkg": "package",
}


def normalize_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    return _UNIT_ALIASES.get(u, u or "each")


def normalize_item(name: str) -> str:
    n = (name or "").strip().lower()
    # Naive singularization: only strip trailing 's' when it's not clearly plural-of-collective.
    # Keep 'pasta', 'rice' alone; drop 'onions' → 'onion', 'tomatoes' → 'tomato', 'eggs' → 'egg'.
    if n.endswith("oes"):
        return n[:-2]         # tomatoes → tomato
    if n.endswith("ies"):
        return n[:-3] + "y"   # berries → berry
    if n.endswith("s") and not n.endswith("ss"):
        # Leave uncountables alone
        uncountables = {"rice", "pasta", "molasses", "hummus"}
        if n not in uncountables:
            return n[:-1]
    return n


_EXPIRY_DAYS = {
    "pantry": None,
    "fridge": 14,
    "freezer": 90,
    "produce": 7,
}


def default_expiry(category: str, added: date) -> date | None:
    days = _EXPIRY_DAYS.get(category)
    return added + timedelta(days=days) if days else None


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def parse_inventory_md(md: str) -> list[dict[str, Any]]:
    """Parse Inventory.md into a list of item dicts. Normalizes item name + unit."""
    items: list[dict[str, Any]] = []
    current_category: str | None = None
    in_table = False

    for raw in md.splitlines():
        line = raw.rstrip()
        header = re.match(r"^##\s+(\w+)", line)
        if header:
            cat = header.group(1).lower()
            current_category = cat if cat in CATEGORIES else None
            in_table = False
            continue

        if current_category is None:
            continue

        row = _TABLE_ROW_RE.match(line)
        if not row:
            continue
        cells = [c.strip() for c in row.group(1).split("|")]
        # Skip header + separator rows
        if cells and set(cells[0].replace("-", "").strip()) <= {""}:
            in_table = True
            continue
        if cells[0].lower() == "item":
            continue
        if len(cells) < 5:
            continue

        item_name, qty_str, unit, added, *rest = cells
        expires = rest[0] if len(rest) >= 1 else ""
        notes = rest[1] if len(rest) >= 2 else ""
        try:
            qty = float(qty_str.replace(",", "."))
        except ValueError:
            continue
        items.append({
            "item": normalize_item(item_name),
            "qty": qty,
            "unit": normalize_unit(unit),
            "category": current_category,
            "added_date": added.strip() or date.today().isoformat(),
            "expires_date": expires.strip() or None,
            "notes": notes.strip(),
        })
    return items


def write_inventory_md(items: list[dict[str, Any]]) -> str:
    """Serialize items back to Inventory.md format, grouped by category."""
    from datetime import datetime
    sections = {c: [] for c in CATEGORIES}
    for it in items:
        sections[it.get("category", "pantry")].append(it)

    lines = [
        "# Kitchen Inventory",
        f"Last updated: {datetime.now().date().isoformat()}",
        "",
    ]
    for cat in CATEGORIES:
        lines.append(f"## {cat.capitalize()}")
        lines.append("| Item | Qty | Unit | Added | Expires | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for it in sorted(sections[cat], key=lambda r: r["item"]):
            expires = it.get("expires_date") or ""
            notes = it.get("notes") or ""
            qty = it["qty"]
            qty_str = f"{int(qty)}" if qty == int(qty) else f"{qty}"
            lines.append(
                f"| {it['item']} | {qty_str} | {it['unit']} | "
                f"{it['added_date']} | {expires} | {notes} |"
            )
        lines.append("")
    return "\n".join(lines)


def sync_from_markdown(vault: Path, cache) -> int:
    """Read Inventory.md → write to cache.inventory table. Returns row count."""
    path = vault / "Inventory.md"
    if not path.exists():
        return 0
    items = parse_inventory_md(path.read_text(encoding="utf-8"))
    cache.conn.execute("DELETE FROM inventory")
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc).isoformat()
    for it in items:
        cache.conn.execute(
            "INSERT OR REPLACE INTO inventory("
            "item, qty, unit, category, added_date, expires_date, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (it["item"], it["qty"], it["unit"], it["category"],
             it["added_date"], it["expires_date"], it["notes"], now),
        )
    cache.conn.commit()
    return len(items)


def sync_to_markdown(vault: Path, cache) -> Path:
    """Read cache.inventory → rewrite Inventory.md."""
    rows = cache.raw_query(
        "SELECT item, qty, unit, category, added_date, expires_date, notes FROM inventory"
    )
    items = [
        {"item": r[0], "qty": r[1], "unit": r[2], "category": r[3],
         "added_date": r[4], "expires_date": r[5], "notes": r[6] or ""}
        for r in rows
    ]
    path = vault / "Inventory.md"
    path.write_text(write_inventory_md(items), encoding="utf-8")
    return path
```

**Step 4: Template skeleton**

```python
# templates/inventory_template.py
"""Initial Inventory.md template."""
from datetime import date


def generate_inventory_markdown() -> str:
    today = date.today().isoformat()
    return f"""# Kitchen Inventory
Last updated: {today}

## Pantry
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|

## Fridge
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|

## Freezer
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|

## Produce
| Item | Qty | Unit | Added | Expires | Notes |
|---|---|---|---|---|---|
"""
```

**Step 5: Run tests.** Pass.

**Step 6: Commit**

```bash
git add lib/inventory.py templates/inventory_template.py tests/test_inventory.py
git commit -m "feat: inventory parser + normalizer + round-trip"
```

---

### Task 28: Inventory CRUD API endpoints

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_api_endpoints.py`

Add four endpoints. TDD one at a time, one commit per endpoint.

**`GET /api/inventory`** — returns full inventory JSON grouped by category.

```python
@app.route("/api/inventory", methods=["GET"])
def api_inventory_list():
    cache = _get_cache()
    rows = cache.raw_query(
        "SELECT id, item, qty, unit, category, added_date, expires_date, notes "
        "FROM inventory ORDER BY category, item"
    )
    out: dict[str, list] = {c: [] for c in ("pantry", "fridge", "freezer", "produce")}
    for r in rows:
        out[r[4]].append({
            "id": r[0], "item": r[1], "qty": r[2], "unit": r[3],
            "category": r[4], "added_date": r[5], "expires_date": r[6],
            "notes": r[7] or "",
        })
    return jsonify(out)
```

**`POST /api/inventory`** — body `{items: [{item, qty, unit, category, added_date?, expires_date?, notes?}, ...]}`. Normalizes, applies default expiry when missing, writes to SQLite, rewrites `Inventory.md`.

**`PATCH /api/inventory/<id>`** — body with any of `qty`, `unit`, `expires_date`, `notes`. Updates row, rewrites Inventory.md.

**`DELETE /api/inventory/<id>`** — removes row, rewrites Inventory.md.

For each endpoint: write a Flask test that exercises it against a tempdir vault, asserts the response JSON AND the Inventory.md file contents.

**Commit each separately:** `feat: GET /api/inventory`, `feat: POST /api/inventory`, etc.

---

### Task 29: MCP tool `inventory_add` — conversational bulk load

**Files:**
- Create: `prompts/inventory_parse.py`
- Modify: `lib/mcp_tools.py`
- Modify: `mcp_server.py` (register tool)
- Create: `tests/test_mcp_inventory.py`

**Step 1: Write the Claude prompt**

```python
# prompts/inventory_parse.py
"""Claude prompt template: convert natural-language inventory description to structured rows."""

SYSTEM_PROMPT = """Extract kitchen inventory items from the user's natural-language description.

Return ONLY valid JSON, matching this schema:

{
  "items": [
    {
      "item": "chicken breast",
      "qty": 2,
      "unit": "lb",
      "category": "fridge",
      "notes": ""
    },
    ...
  ]
}

Rules:
- item names: lowercase, singular
- category: one of 'pantry', 'fridge', 'freezer', 'produce'
- unit: prefer 'each', 'lb', 'oz', 'cup', 'bottle', 'box', 'can', 'bag', 'jar', 'package'
- If the user didn't specify a category, infer from the item (meat/dairy→fridge, flour/pasta→pantry, lettuce/onion→produce, ice cream→freezer)
- If quantity isn't stated, use 1
- Never invent items the user didn't mention
"""


def build_parse_prompt(free_text: str) -> str:
    return f"User inventory description:\n\n{free_text}\n\nReturn the JSON now."
```

**Step 2: Implement `inventory_add` tool**

```python
# in lib/mcp_tools.py
def inventory_add(free_text: str) -> dict:
    """Parse free-text into inventory items via Claude, then POST to /api/inventory."""
    import json, os
    import anthropic

    from prompts.inventory_parse import SYSTEM_PROMPT, build_parse_prompt

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-opus-4-7",
        system=SYSTEM_PROMPT,
        max_tokens=2048,
        messages=[{"role": "user", "content": build_parse_prompt(free_text)}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(text)

    # POST to API
    import requests
    r = requests.post(
        "http://localhost:5001/api/inventory",
        json={"items": parsed["items"]},
        timeout=30,
    )
    r.raise_for_status()
    return {"added": len(parsed["items"]), "result": r.json()}
```

**Step 3: Register in `mcp_server.py`** — follow existing pattern for other MCP tools; add to the tool manifest.

**Step 4: Also add `inventory_check(item_name: str)` and `inventory_expiring(days: int = 7)`** as simple wrappers over `GET /api/inventory` with client-side filtering.

**Step 5: Tests** — mock Claude + requests, assert tool returns the expected structure.

**Step 6: Commit**

```bash
git add prompts/inventory_parse.py lib/mcp_tools.py mcp_server.py tests/test_mcp_inventory.py
git commit -m "feat: MCP inventory_add/check/expiring tools"
```

---

### Task 30: Scoring components — `inventory_match` + `expiring_boost`

**Files:**
- Modify: `config/scoring_weights.json` — add keys
- Modify: `lib/meal_scorer.py` — add functions + integrate into `score_candidate`
- Modify: `tests/test_meal_scorer.py`

**Step 1: Add weights**

```json
"inventory_match_max": 25,
"expiring_boost_max": 15,
"expiring_window_days": 3
```

**Step 2: Tests**

```python
class TestInventoryMatch:
    def test_full_match_max_score(self):
        from lib.meal_scorer import score_inventory_match
        recipe_ingredients = [
            {"item": "chicken breast"}, {"item": "onion"}, {"item": "garlic"},
        ]
        inventory = {"chicken breast", "onion", "garlic"}
        staples = set()
        assert score_inventory_match(recipe_ingredients, inventory, staples, max_score=25) == 25

    def test_staples_count_as_match(self):
        from lib.meal_scorer import score_inventory_match
        recipe_ingredients = [{"item": "chicken breast"}, {"item": "salt"}]
        inventory = {"chicken breast"}
        staples = {"salt"}
        assert score_inventory_match(recipe_ingredients, inventory, staples, max_score=25) == 25

    def test_partial_match_proportional(self):
        from lib.meal_scorer import score_inventory_match
        recipe_ingredients = [
            {"item": "chicken breast"}, {"item": "onion"},
            {"item": "bell pepper"}, {"item": "rice"},
        ]
        inventory = {"chicken breast", "onion"}
        staples = set()
        # 2/4 = 50% → 12.5 → round to 13 (or 12 depending on rounding; either OK in test)
        score = score_inventory_match(recipe_ingredients, inventory, staples, max_score=25)
        assert 10 <= score <= 14

    def test_empty_inventory_zero(self):
        from lib.meal_scorer import score_inventory_match
        recipe_ingredients = [{"item": "chicken breast"}, {"item": "onion"}]
        assert score_inventory_match(recipe_ingredients, set(), set(), max_score=25) == 0


class TestExpiringBoost:
    def test_expiring_within_window_boosts(self):
        from datetime import date
        from lib.meal_scorer import score_expiring_boost
        recipe_ingredients = [{"item": "spinach"}]
        expiring = {"spinach": date(2026, 4, 21)}  # 2 days from today (2026-04-19)
        today = date(2026, 4, 19)
        assert score_expiring_boost(recipe_ingredients, expiring, today, window_days=3, max_score=15) == 15

    def test_outside_window_zero(self):
        from datetime import date
        from lib.meal_scorer import score_expiring_boost
        expiring = {"spinach": date(2026, 4, 28)}
        today = date(2026, 4, 19)
        assert score_expiring_boost([{"item": "spinach"}], expiring, today, window_days=3, max_score=15) == 0
```

**Step 3: Implement**

```python
# append to lib/meal_scorer.py
def score_inventory_match(
    recipe_ingredients: list[dict],
    inventory_items: set[str],
    staples: set[str],
    max_score: int = 25,
) -> int:
    """Fraction of recipe ingredients present in inventory or staples → bonus."""
    if not recipe_ingredients:
        return 0
    from lib.inventory import normalize_item
    normalized_ing = [normalize_item(i.get("item", "")) for i in recipe_ingredients]
    available = inventory_items | staples
    matches = sum(1 for item in normalized_ing if item in available or _fuzzy_in(item, available))
    fraction = matches / len(normalized_ing)
    return round(fraction * max_score)


def _fuzzy_in(needle: str, haystack: set[str]) -> bool:
    for item in haystack:
        if item in needle or needle in item:
            return True
    return False


def score_expiring_boost(
    recipe_ingredients: list[dict],
    expiring_map: dict,  # {item_name: expires_date}
    today,
    window_days: int = 3,
    max_score: int = 15,
) -> int:
    if not expiring_map:
        return 0
    from datetime import timedelta
    from lib.inventory import normalize_item
    deadline = today + timedelta(days=window_days)
    normalized_ing = {normalize_item(i.get("item", "")) for i in recipe_ingredients}
    for item, exp in expiring_map.items():
        if exp <= deadline and (item in normalized_ing or _fuzzy_in(item, normalized_ing)):
            return max_score
    return 0
```

**Step 4: Integrate into `score_candidate`** — add components dict entries for `inventory_match` and `expiring_boost`. Update existing `TestScoreCandidate` tests to pass the new `inventory_snapshot` + `expiring_map` via `plan_state`.

**Step 5: Run all scorer tests.** Pass.

**Step 6: Commit**

```bash
git add config/scoring_weights.json lib/meal_scorer.py tests/test_meal_scorer.py
git commit -m "feat: scorer — inventory_match + expiring_boost components"
```

---

### Task 31: Shopping list conservative dedup

**Files:**
- Modify: `lib/shopping_list_generator.py`
- Modify: `tests/test_shopping_list.py` (or create if absent)

**Step 1: Tests**

```python
class TestShoppingListInventoryDedup:
    def test_skips_when_inventory_covers_2x(self):
        from lib.shopping_list_generator import dedup_against_inventory
        required = [{"item": "chicken breast", "qty": 2.0, "unit": "lb"}]
        inventory = {("chicken breast", "lb"): 5.0}
        result = dedup_against_inventory(required, inventory)
        assert result[0]["skipped"] is True
        assert "in inventory" in result[0]["annotation"]

    def test_buys_when_inventory_is_1x_only(self):
        from lib.shopping_list_generator import dedup_against_inventory
        required = [{"item": "chicken breast", "qty": 2.0, "unit": "lb"}]
        inventory = {("chicken breast", "lb"): 2.0}  # exactly 1x
        result = dedup_against_inventory(required, inventory)
        assert result[0]["skipped"] is False

    def test_buys_when_units_differ(self):
        from lib.shopping_list_generator import dedup_against_inventory
        required = [{"item": "onion", "qty": 1, "unit": "cup"}]
        inventory = {("onion", "each"): 10.0}  # units don't match; shop anyway
        result = dedup_against_inventory(required, inventory)
        assert result[0]["skipped"] is False
```

**Step 2: Implement**

```python
# add to lib/shopping_list_generator.py
def dedup_against_inventory(
    required: list[dict],  # [{item, qty, unit}, ...]
    inventory: dict,       # {(normalized_item, unit): qty}
) -> list[dict]:
    """Mark required ingredients as skipped when inventory covers ≥ 2× and units match."""
    out = []
    for r in required:
        key = (r["item"], r["unit"])
        stocked = inventory.get(key, 0.0)
        if stocked >= r["qty"] * 2:
            out.append({**r, "skipped": True, "annotation": "(in inventory)"})
        else:
            out.append({**r, "skipped": False, "annotation": ""})
    return out
```

**Step 3: Wire into `generate_shopping_list`** — build the `inventory` dict from cache, call `dedup_against_inventory` after aggregation. Pass skipped items through to the template; existing template rendering adds them as `- [x] ~~item~~ (in inventory)`.

**Step 4: Update `templates/shopping_list_template.py`** to render skipped items differently.

**Step 5: Run tests.** Pass.

**Step 6: Commit**

```bash
git add lib/shopping_list_generator.py templates/shopping_list_template.py tests/test_shopping_list.py
git commit -m "feat: shopping list conservative 2× inventory dedup"
```

---

### Task 32: "✓ I shopped" button → confirm endpoint

**Files:**
- Modify: `api_server.py` — `POST /api/shopping-list/confirm`
- Modify: `templates/shopping_list_template.py` — button
- Modify: `scripts/kitchenos-uri-handler/` (existing URI handler, likely needs a new action)

**Step 1: Test the endpoint**

```python
class TestShoppingListConfirm:
    def test_checked_items_become_inventory(self, tmp_path):
        # set up tempdir vault with a shopping list file containing checked items
        (tmp_path / "Shopping Lists").mkdir()
        (tmp_path / "Shopping Lists" / "2026-W20.md").write_text("""# Shopping List - W20

- [x] chicken breast 2 lb
- [x] onion 3 each
- [ ] celery 1 bunch
""", encoding="utf-8")
        # POST to /api/shopping-list/confirm with {file: "2026-W20"}
        # assert chicken and onion landed in inventory; celery did not
```

**Step 2: Implement**

```python
# in api_server.py
@app.route("/api/shopping-list/confirm", methods=["POST"])
def api_shopping_list_confirm():
    from lib.inventory import default_expiry, sync_to_markdown
    from datetime import date

    payload = request.get_json(silent=True) or {}
    week = payload.get("week") or payload.get("file")
    if not week:
        return jsonify({"error": "week required"}), 400
    path = VAULT / "Shopping Lists" / f"{week}.md"
    if not path.exists():
        return jsonify({"error": "shopping list not found"}), 404

    content = path.read_text(encoding="utf-8")
    checked = _extract_checked_items(content)  # helper parses `- [x] item qty unit`
    cache = _get_cache()
    today = date.today()
    added = 0
    for it in checked:
        category = _infer_category(it["item"])
        exp = default_expiry(category, today)
        cache.conn.execute(
            "INSERT OR REPLACE INTO inventory("
            "item, qty, unit, category, added_date, expires_date, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (it["item"], it["qty"], it["unit"], category,
             today.isoformat(), exp.isoformat() if exp else None, ""),
        )
        added += 1
    cache.conn.commit()
    sync_to_markdown(VAULT, cache)
    return jsonify({"added": added})


def _infer_category(item: str) -> str:
    # Small rules table; conservative default to pantry
    fridge_hints = ("chicken", "beef", "pork", "fish", "dairy", "milk", "yogurt", "cheese", "eggs", "butter")
    produce_hints = ("onion", "garlic", "pepper", "tomato", "lettuce", "spinach", "kale", "broccoli", "carrot", "apple", "lemon", "lime", "banana")
    freezer_hints = ("frozen", "ice cream")
    lower = item.lower()
    if any(h in lower for h in freezer_hints):
        return "freezer"
    if any(h in lower for h in produce_hints):
        return "produce"
    if any(h in lower for h in fridge_hints):
        return "fridge"
    return "pantry"
```

**Step 3: Add button to shopping list template**

```markdown
\`\`\`button
name ✓ I shopped
type link
action kitchenos://confirm-shopping-list?week={{week}}
\`\`\`
```

Add a `confirm-shopping-list` action to `scripts/kitchenos-uri-handler/` that POSTs to the endpoint.

**Step 4: Manual verification** — run the shopping list generator, check a few items in Obsidian, tap the button, verify inventory updates.

**Step 5: Commit**

```bash
git add api_server.py templates/shopping_list_template.py scripts/kitchenos-uri-handler tests/test_api_endpoints.py
git commit -m "feat: I-shopped button flows checked items into inventory"
```

---

### Task 33: Inventory view in meal planner UI

**Files:**
- Modify: `templates/meal_planner.html`

Add a sidebar panel showing current inventory grouped by category. Highlight items expiring in ≤3 days in amber; ≤1 day in red. Sortable, searchable.

Calls `GET /api/inventory` on load; refreshes when `POST /api/inventory` fires anywhere (via existing event bus or explicit refresh on planner state change).

No unit tests (UI); document manual test steps in commit.

```bash
git add templates/meal_planner.html
git commit -m "feat: inventory sidebar panel in meal planner UI"
```

---

### Task 34: Wednesday digest — "Expiring soon" section + inventory adherence

**Files:**
- Modify: `lib/weekly_digest.py`
- Modify: `prompts/weekly_digest.py`

Add to the digest prompt input:
- List of items expiring in ≤7 days
- Last week's shopping list: how many items were deduped against inventory vs. bought fresh

Update system prompt to include:

```
## Expiring soon
(If any inventory items expire within 7 days: list them and suggest next-week slots that would use them. If nothing expiring, write 'Nothing critical.')

## Inventory usage last week
(Count of planned ingredients that were in inventory vs. bought. If >50% bought fresh when stock existed, flag it.)
```

Update `lib/weekly_digest.py` to query `inventory` table for `expires_date <= date('now', '+7 days')` and include in prompt context.

Add a test that mocks Claude and asserts the expiring list reaches the prompt.

```bash
git add lib/weekly_digest.py prompts/weekly_digest.py tests/test_weekly_digest.py
git commit -m "feat: digest — expiring-soon section + inventory adherence"
```

---

### Task 35: Phase A.5 end-to-end verification

**Step 1: Seed inventory via MCP tool**

From a Claude session with the KitchenOS MCP server loaded, use `inventory_add` with a realistic description. Verify `Inventory.md` is populated.

**Step 2: Dry-run Mode D with and without inventory present**

```bash
.venv/bin/python plan_week.py --week 2026-W24 --dry-run > /tmp/with_inventory.json
mv Inventory.md /tmp/Inventory.md.bak   # temporarily remove
.venv/bin/python plan_week.py --week 2026-W24 --dry-run > /tmp/without_inventory.json
mv /tmp/Inventory.md.bak Inventory.md   # restore
diff /tmp/without_inventory.json /tmp/with_inventory.json
```

Expected: different recipe selections, with the inventory run favoring recipes using stocked items.

**Step 3: Generate a shopping list for a week and verify dedup annotations**

```bash
.venv/bin/python shopping_list.py --week 2026-W24
```

Open the resulting Shopping Lists file; confirm at least one line is rendered as `- [x] ~~item~~ (in inventory)`.

**Step 4: Commit smoke-test update**

Extend `scripts/smoke_test_planner.sh` to also run `.venv/bin/python -m pytest tests/test_inventory.py tests/test_mcp_inventory.py`.

```bash
git add scripts/smoke_test_planner.sh
git commit -m "chore: add inventory tests to smoke-test script"
```

---

## Phase B: Structured Feedback Loop (outline)

Activated after Phase A has 2+ weeks of real use. High-level tasks (to be expanded into a separate plan when triggered):

1. **iOS Shortcut: "I cooked [recipe]"** — prompts for stars (1–5) + optional 1-liner. Appends `- cooked YYYY-MM-DD ★★★★☆ — reason` to the recipe file's `## My Notes` section via an existing POST endpoint.
2. **New API endpoint** `POST /api/recipes/<name>/log-cook` — body `{date, stars, reason}` — writes the structured line + updates cache.
3. **New `recipe_cook_log` SQLite table** — one row per cook (richer than the current note-extraction approach).
4. **Rolling rating recomputation** — `rating` frontmatter becomes weighted average of last 3 cooks (3×/2×/1× weighting of newest to oldest). Applied on every cook-log write.
5. **Digest adherence uses cook-log** — instead of assuming planned == cooked, the digest reads actual cook logs for the past 7 days.
6. **Meal planner UI: cook-log button on each scheduled meal card** — one-tap to open the shortcut.
7. **Inventory depletion on cook-log** — after cook-log writes, fuzzy-match recipe ingredients against `inventory` table; build a decrement preview; user confirms → quantities reduced (rows with `qty ≤ 0` removed). Implement as `POST /api/inventory/deplete-from-recipe` with `{recipe_name, servings, confirm: bool}`.
8. **Receipt OCR** — iOS Shortcut: photograph receipt → `POST /api/inventory/from-receipt` (multipart image) → server calls Claude Vision API with `prompts/receipt_parse.py` prompt → returns parsed items → Shortcut shows preview → user confirms → items posted to `POST /api/inventory`. Build the prompt carefully to handle price lines, discount lines, and blurry photos gracefully.

Phase B gate: two full weeks of shortcut-logged cooks; digest accurately reports planned-vs-cooked; at least one successful receipt OCR import end-to-end; at least one cook depletion round-trip verified by inventory diff.

---

## Phase C: Heart-Health Rule Activation (outline)

Activated by user filling in structured rules in `## Heart Health` section of `My Macros.md`:

```markdown
## Heart Health
sat_fat_max_g: 15
sodium_max_mg: 2000
fiber_min_g: 30
added_sugar_max_g: 25
fish_min_per_week: 2
```

High-level tasks:

1. **Parse rules** in `lib/macro_targets.py` — detect structured `key: value` lines inside `## Heart Health`.
2. **New scoring component** `score_heart_health(recipe, day_so_far, rules)` in `lib/meal_scorer.py`. Weight configurable (up to -30 in `config/scoring_weights.json`).
3. **Day composer reject** day combinations that exceed hard-cap sums (sat fat, sodium, added sugar).
4. **Fish-per-week tracking** — weekly plan evaluated for ≥2 `protein: fish` recipes. Day composer favors fish on at least two days of the week.
5. **Digest adherence section** adds heart-health targets alongside macro targets.
6. **UI day-score panel** gains color-coding for heart-health metrics once rules are active.

Phase C gate: user has medical or informed guidance. Not time-bound.

---

## Notes for the implementing engineer

- **Always activate `.venv`.** Commands in this plan use `.venv/bin/python` explicitly. If you chain into a shell and forget, tests will fail with missing `anthropic` / `requests`.
- **Tests are class-based** (`class TestX:` with method `test_*`) — follow existing conventions in `tests/`.
- **The existing `parse_meal_plan` helper** returns a structure specific to the current `MealEntry` tuple. Verify its exact return shape before Task 5 — if it's `{day_label: {meal_slot: [MealEntry]}}`, the code in this plan is correct. If it's different, adjust the loop in `_cache_sync_meal_plans` accordingly.
- **The cache is disposable.** If you break it in development, `rm .kitchenos-cache.db && python -c "from lib.cache import Cache; ..."` rebuilds it.
- **`anthropic` SDK usage** — the project is on the Anthropic Python SDK. Use the `anthropic.Anthropic(api_key=...)` client pattern shown in Task 19. Model ID for Opus 4.7: `claude-opus-4-7`. If rate limits hit, add exponential backoff in `_call_claude`.
- **User's `Macro Worksheet.md`** — the user fills this in; Claude computes and writes `My Macros.md` as a one-time pre-work step. Engineers should not block on it.
- **Commit cadence** — this plan has ~40 commits in Phase A. Each one should be small, green, and leave the tree in a shippable state.

---

## Open questions flagged in the design doc

These are left for resolution during implementation:

1. Top-K per slot (5) — tune up to 7 if Mode C quality suffers.
2. Weeks of history in Mode D context (4) — tune to 6 if rotation feels stale.
3. Mode D retry on macro-tolerance failure — retry once with a feedback prompt that includes the previous output + the gap, then surface the gap if still failing.
4. Cache `schema_version` bump procedure — hard delete + rebuild on mismatch; no in-place migrations (the cache is disposable).

---

## Plan complete.

Saved to `docs/plans/2026-04-19-smart-meal-plan-implementation.md`.

Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — open a new session in a worktree with `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
