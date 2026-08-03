# Recipe Schema Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give recipe frontmatter one declared schema, repair the 17 files that drift from it, and leave behind a guard that fails the moment drift returns.

**Architecture:** A pure checker (`lib/recipe_schema.py`) owns the schema and answers "what is wrong with this frontmatter" with no I/O. Three consumers use it: hermetic unit tests over synthetic frontmatter, an e2e corpus audit over the real vault, and `scripts/normalize_recipes.py`, which repairs what the checker reports. All writes go through the existing `lib.frontmatter` line editor — the repo already has one, shared by `backfill_nutrition.py` and the cook-history sync, and a second one would be free to disagree with it.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), pytest, `lib.frontmatter` (line-surgical YAML frontmatter editor), `lib.backup.create_backup`.

## Global Constraints

- **Python 3.11**, always run via `.venv/bin/python`. Never the system interpreter.
- **Line-surgical edits only.** Never round-trip frontmatter through a YAML dumper — it would reformat all 252 files and bury the real change. `lib.frontmatter.rewrite()` is the only writer.
- **`lib.frontmatter` is the only frontmatter editor.** Do not add a second one. It already de-duplicates managed keys (last wins, matching YAML) and supports `remove=`.
- **The vault is not in git.** Every write path must call `lib.backup.create_backup(path)` first; that snapshot is the only recovery route.
- **Unit tests never touch the live vault.** `tests/conftest.py` isolates the DB and storage table autouse; corpus-reading tests belong in `tests/e2e/` and resolve the vault via `tests.e2e._paths.data_root()`, because `vault/` exists only in the main checkout.
- **Servings ranges collapse to the LOW end** (`6-8` → `6`) — user decision, 2026-07-31. Low end means fewer servings means higher per-serving calories, the conservative direction for macros. Note this differs from `nutrition_engine._parse_servings`, which takes the midpoint; Task 6 reconciles the consequence.
- **A `servings` change invalidates stored macros.** `nutrition_*` frontmatter is per-serving, derived as batch ÷ servings. Any file whose `servings` this tool changes must have its nutrition re-derived in the same operation, or the file ships a serving count that disagrees with its own macros.
- Commit convention: `type: short description`, ending with the `Co-Authored-By:` / `Claude-Session:` trailers used by the branch's existing commits.

---

## Background: what is actually wrong

Profiled against the live vault on 2026-08-01, 252 files. **The branch's original premise was wrong in two ways and both corrections are load-bearing** — read this before writing code.

**The non-numeric `servings` values do not crash anything.** `BRANCH-STATUS.md` claims `lib/serving_ledger.py` coerces them "with bare `float()` in five places, so these can throw". Those `float()` calls are all on SQLite rows, not on frontmatter. The frontmatter reader is `lib/week_view.py:135`, and it is wrapped in `except Exception: return 4.0`. Nothing throws. What actually happens is worse, because it is silent:

| `servings` value | `nutrition_engine._parse_servings` | `week_view.recipe_base_servings` | `nutrition_quality.macro_eligible` |
|---|---|---|---|
| `"6-8"` | **7** (midpoint) | **4.0** (silent fallback) | eligible |
| `"4-6 servings (estimated)"` | **5** | **4.0** | eligible |
| `"6-8 as a side dish"` | **7** | **4.0** | eligible |
| `6` | 6 | 6.0 | eligible |

Two subsystems disagree by up to 75% about the same recipe, and the third certifies it as trustworthy enough to rank against macro targets. That is the defect. Write the tests against *that*, not against a phantom `ValueError`.

**Re-running `migrate_recipes.py` would corrupt every one of the 13 legacy-key files.** `rename_nutrition_keys` (`migrate_recipes.py:39`) rewrites `^calories:` → `nutrition_calories:` with no check that the target key already exists. All 13 files are **legacy-first** — verified, every one — so the rename appends a second `nutrition_calories:` *after* the canonical line is already present, and PyYAML takes the **last** duplicate. `Watermelon Feta Salad` would go from `169` kcal/serving to `3058` in one command, silently, and every nutrition surface would consume it. This landmine is armed right now on `main`.

**Two of the branch's "in scope" items are not defects.**

- `enrich_none` is on **18** files, not the 2 the branch profiled. It is real, documented, sticky state written by `scripts/enrich_recipes.py:353` and specified in `docs/OPERATIONS.md:380`. It is optional-by-design, exactly like `short_title`. **Keep it.** This closes the branch's last open question — it resolved by reading code, as predicted.
- The legacy-key fix needs **no value migration**. The branch proposed carrying a legacy value across "when the canonical one is null". Verified against the corpus: there are **zero** such cases — all 13 files have a non-null canonical value. It is a pure delete. Do not write the conditional.

**Key census (252 files).** 30 keys at 100%, and the optional set below. This is the allowlist; it is measured, not guessed.

```
252 (all): banner confidence_notes cook_time cssclasses cuisine date_added dietary
           difficulty dish_type equipment meal_occasion needs_review
           nutrition_calories nutrition_carbs nutrition_fat nutrition_protein
           nutrition_source peak_months prep_time protein recipe_source
           seasonal_ingredients serving_size servings source_channel source_url
           tags title total_time video_title
249: fit_buffer_candidate fit_craving_lane fit_dairy_load fit_effort fit_heart
     fit_needs_review fit_note fit_source fit_steady  ·  249: nutrition_confidence
247: nutrition_coverage nutrition_needs_review  ·  106: nutrition_unmatched
 70: short_title short_title_inferred  ·  18: enrich_none
 13: cook_count make_again_count observed_servings verdict_count  ·  10: last_cooked
 11: servings_inferred servings_needs_review
--- violations ---
 13: calories carbs fat   (legacy nutrition keys)
  1: recipe_url           (Chocolate Peanut Butter Bars.md)
```

**The 17 files to repair:**

- **servings (3):** `Creamy Grape Salad Alternative.md` (`4-6 servings (estimated)` → `4`), `Healthy Blueberry Apple Oatmeal Cake.md` (`6-8` → `6`), `Watermelon Feta Salad.md` (`6-8 as a side dish` → `6`). None currently carries `servings_inferred` / `servings_needs_review`; the normalizer sets both.
- **legacy nutrition keys (13):** `3010 Blueberry Banana Smoothie`, `Borscht Recipe With Meat`, `Charred Cabbage + Sicilian Pesto`, `Cherry Hibiscus Lemonade`, `Chicken Souvlaki Bowl`, `Garlic Parmesan Beans`, `Oven Roasted Chicken`, `Savory Leek, Feta, And Puff Pastry Tart`, `Smoothe Fiber Blend`, `Strawberry Brownies`, `Strawberry Hibiscus Refresher`, `Turkish Eggs (Çılbır)`, `Watermelon Feta Salad`.
- **recipe_url (1):** `Chocolate Peanut Butter Bars.md`. Dropping it discards the creator's own recipe page, which exists nowhere else in the corpus — the backup snapshot is the only recovery. **Never fold it into `source_url`**, which holds the YouTube short.

`Watermelon Feta Salad.md` appears in two lists; it takes both fixes in one write.

---

## File Structure

| File | Responsibility |
|---|---|
| `lib/recipe_schema.py` (create) | The schema: allowlists, `Violation`, `check_frontmatter()`, `servings_low_end()`. Pure — no I/O, no vault. |
| `tests/test_recipe_schema.py` (create) | Hermetic unit tests of the checker over synthetic frontmatter dicts. |
| `tests/test_migrate_recipes.py` (create) | Pins the `rename_nutrition_keys` duplicate-key hazard and its fix. |
| `migrate_recipes.py:39-64` (modify) | `rename_nutrition_keys` must refuse to rename onto an existing key. |
| `scripts/normalize_recipes.py` (create) | CLI: `--check` / dry-run default / `--apply`. Repairs what the checker reports. |
| `tests/test_normalize_recipes.py` (create) | Unit tests of the repair functions over temp files. |
| `tests/e2e/test_recipe_corpus_schema.py` (create) | Corpus audit: the real vault satisfies the schema. The anti-recurrence guard. |
| `backfill_nutrition.py:210-240` (modify) | `--only NAME` so the 3 servings-changed recipes can be re-derived without a 252-file run. |
| `docs/OPERATIONS.md` (modify) | Runbook entry for the normalizer + the mandatory nutrition re-derive. |
| `CLAUDE.md` (modify) | New invariant: the schema is declared in one place; a `servings` change requires a nutrition re-derive. |
| `docs/plans/INDEX.md` (modify) | Move to Done at closure. |
| `scripts/_analysis/` (delete) | Throwaway profiling scripts; the findings are captured above. |

---

## Task 1: The schema checker

**Files:**
- Create: `lib/recipe_schema.py`
- Test: `tests/test_recipe_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `REQUIRED_KEYS`, `OPTIONAL_KEYS`, `KNOWN_KEYS`, `LEGACY_NUTRITION_KEYS`, `DROPPED_KEYS` (all `frozenset[str]`); `Violation(recipe: str, key: str, code: str, detail: str)` frozen dataclass; `check_frontmatter(recipe: str, fm: dict) -> list[Violation]`; `servings_low_end(value) -> int | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recipe_schema.py`:

```python
"""The schema checker, exercised over synthetic frontmatter.

Hermetic by design: no vault, no DB. The corpus itself is audited by
tests/e2e/test_recipe_corpus_schema.py, which is a statement about the
user's data rather than about this code.
"""
import pytest

from lib.recipe_schema import (
    KNOWN_KEYS,
    LEGACY_NUTRITION_KEYS,
    REQUIRED_KEYS,
    check_frontmatter,
    servings_low_end,
)


def _valid_fm(**overrides):
    """A frontmatter dict that satisfies the schema, before overrides."""
    fm = {k: "x" for k in REQUIRED_KEYS}
    fm["servings"] = 4
    fm.update(overrides)
    return fm


def test_a_conforming_recipe_has_no_violations():
    assert check_frontmatter("Good Recipe", _valid_fm()) == []


def test_optional_keys_are_allowed():
    fm = _valid_fm(short_title="Short", enrich_none=["protein"], last_cooked="2026-07-01")
    assert check_frontmatter("Good Recipe", fm) == []


def test_string_servings_is_a_violation():
    v = check_frontmatter("Ranged", _valid_fm(servings="6-8"))
    assert [x.code for x in v] == ["servings_not_numeric"]
    assert v[0].recipe == "Ranged"
    assert v[0].key == "servings"
    assert "6-8" in v[0].detail


def test_numeric_servings_of_either_type_is_fine():
    assert check_frontmatter("Int", _valid_fm(servings=6)) == []
    assert check_frontmatter("Float", _valid_fm(servings=6.0)) == []


def test_null_servings_is_not_a_schema_violation():
    """A missing serving count is honest; macro_eligible already reports it."""
    assert check_frontmatter("Unknown", _valid_fm(servings=None)) == []


def test_legacy_nutrition_keys_are_violations():
    fm = _valid_fm(calories=3058, carbs=None, fat=None)
    codes = {(x.key, x.code) for x in check_frontmatter("Legacy", fm)}
    assert codes == {
        ("calories", "legacy_nutrition_key"),
        ("carbs", "legacy_nutrition_key"),
        ("fat", "legacy_nutrition_key"),
    }


def test_unknown_key_is_a_violation():
    v = check_frontmatter("Stray", _valid_fm(recipe_url="https://example.com"))
    assert [x.code for x in v] == ["unknown_key"]
    assert v[0].key == "recipe_url"


def test_missing_required_key_is_a_violation():
    fm = _valid_fm()
    del fm["dish_type"]
    v = check_frontmatter("Incomplete", fm)
    assert [(x.key, x.code) for x in v] == [("dish_type", "missing_required_key")]


def test_legacy_keys_are_not_also_reported_as_unknown():
    """One defect, one violation — a legacy key has its own actionable code."""
    v = check_frontmatter("Legacy", _valid_fm(calories=1))
    assert len(v) == 1


def test_violations_are_ordered_deterministically():
    fm = _valid_fm(calories=1, recipe_url="u", servings="6-8")
    first = [(x.key, x.code) for x in check_frontmatter("Multi", fm)]
    second = [(x.key, x.code) for x in check_frontmatter("Multi", dict(fm))]
    assert first == second


def test_legacy_keys_are_not_in_the_allowlist():
    assert not (LEGACY_NUTRITION_KEYS & KNOWN_KEYS)


@pytest.mark.parametrize("raw,expected", [
    ("6-8", 6),
    ("4-6 servings (estimated)", 4),
    ("6-8 as a side dish", 6),
    ("6 to 8", 6),
    ("6–8", 6),          # en dash
    ("Serves 4", 4),
    ("about 2 servings", 2),
    (8, 8),
    (8.0, 8),
    ("8", 8),
])
def test_servings_low_end_takes_the_low_end(raw, expected):
    assert servings_low_end(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "a few", "many servings", 0, -1, True, False])
def test_servings_low_end_returns_none_when_there_is_no_count(raw):
    assert servings_low_end(raw) is None


def test_servings_low_end_differs_from_the_nutrition_engine_midpoint():
    """Pins the deliberate divergence, so changing one side is a conscious act."""
    from lib.nutrition_engine import _parse_servings
    assert servings_low_end("6-8") == 6
    assert _parse_servings("6-8") == 7
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/recipe-schema-normalize
../../.venv/bin/python -m pytest tests/test_recipe_schema.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'lib.recipe_schema'`.

- [ ] **Step 3: Write the implementation**

Create `lib/recipe_schema.py`:

```python
"""The one declaration of what a recipe's frontmatter may contain.

Recipe files are written by six different producers — the extractor, the
nutrition backfill, the fit backfill, the enricher, the short-title backfill and
the cook-history sync — and nothing ever stated what the union of their output
was allowed to look like. Drift accumulated silently: 13 files carried a legacy
nutrition key beside the canonical one, 3 carried a servings *range* that three
subsystems each read differently, and 1 carried a one-off key.

This module is pure: it takes an already-parsed frontmatter dict and reports
what is wrong with it. It performs no I/O, so it is equally usable from a
hermetic unit test, from an audit of the real vault, and from the normalizer
that repairs what it reports.

The allowlists below are *measured* against the 252-file corpus, not designed.
Adding a key to a recipe template means adding it here in the same commit —
that is the point of the guard, not an inconvenience it imposes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Present on every one of the 252 files. A recipe missing one is malformed.
REQUIRED_KEYS = frozenset({
    "banner", "confidence_notes", "cook_time", "cssclasses", "cuisine",
    "date_added", "dietary", "difficulty", "dish_type", "equipment",
    "meal_occasion", "needs_review", "nutrition_calories", "nutrition_carbs",
    "nutrition_fat", "nutrition_protein", "nutrition_source", "peak_months",
    "prep_time", "protein", "recipe_source", "seasonal_ingredients",
    "serving_size", "servings", "source_channel", "source_url", "tags",
    "title", "total_time", "video_title",
})

#: Written by a specific producer for a subset of recipes. All optional by
#: design — see docs/OPERATIONS.md and CLAUDE.md for who writes each.
OPTIONAL_KEYS = frozenset({
    # backfill_fit.py — inference, always flagged
    "fit_buffer_candidate", "fit_craving_lane", "fit_dairy_load", "fit_effort",
    "fit_heart", "fit_needs_review", "fit_note", "fit_source", "fit_steady",
    # backfill_nutrition.py
    "nutrition_confidence", "nutrition_coverage", "nutrition_needs_review",
    "nutrition_unmatched",
    # scripts/backfill_short_titles.py
    "short_title", "short_title_inferred",
    # scripts/enrich_recipes.py — sticky "this field has no value" record
    "enrich_none",
    # lib/cook_history.py sync
    "cook_count", "last_cooked", "make_again_count", "observed_servings",
    "verdict_count",
    # scripts/backfill_servings.py and this module's normalizer
    "servings_inferred", "servings_needs_review",
})

KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS

#: Pre-``nutrition_*`` names. The canonical keys are FDC-sourced and per-serving;
#: these survivors are whole-recipe totals from an earlier era and disagree by up
#: to 18x. They are deleted, never migrated — every file carrying one already has
#: a non-null canonical value (verified across the corpus, 2026-08-01).
LEGACY_NUTRITION_KEYS = frozenset({"calories", "carbs", "fat"})

#: Keys removed outright by user decision (2026-07-31). ``recipe_url`` held the
#: creator's own recipe page on exactly one file; it is *not* a duplicate of
#: ``source_url``, which holds that file's YouTube short.
DROPPED_KEYS = frozenset({"recipe_url"})


@dataclass(frozen=True)
class Violation:
    """One thing wrong with one recipe's frontmatter."""

    recipe: str
    key: str
    code: str
    detail: str


def check_frontmatter(recipe: str, fm: dict) -> list[Violation]:
    """Report every way ``fm`` departs from the schema, in a stable order.

    Order is (missing required, then by key name) so two runs over the same
    input produce identical output — the audit diffs its own results.
    """
    out: list[Violation] = []

    for key in sorted(REQUIRED_KEYS - set(fm)):
        out.append(Violation(
            recipe, key, "missing_required_key",
            f"every recipe carries {key!r}; this one does not",
        ))

    for key in sorted(fm):
        if key in LEGACY_NUTRITION_KEYS:
            out.append(Violation(
                recipe, key, "legacy_nutrition_key",
                f"{key!r} is superseded by 'nutrition_{key}' and disagrees with it",
            ))
        elif key not in KNOWN_KEYS:
            out.append(Violation(
                recipe, key, "unknown_key",
                f"{key!r} is not in the declared schema",
            ))

    servings = fm.get("servings")
    if servings is not None and not isinstance(servings, (int, float)):
        out.append(Violation(
            recipe, "servings", "servings_not_numeric",
            f"servings={servings!r} is read as 4.0 by week_view and as a "
            f"different number by nutrition_engine",
        ))

    return out


def servings_low_end(value) -> int | None:
    """Coerce a frontmatter ``servings`` value to its LOW end, or ``None``.

    User decision, 2026-07-31: a range collapses to its low end, because fewer
    servings means higher per-serving calories — the conservative direction for
    a macro target. This deliberately differs from
    ``nutrition_engine._parse_servings``, which takes the midpoint; the
    divergence is pinned by a test so changing either side is a conscious act.

    Returns ``None`` when nothing numeric is present, so the caller can leave
    the value alone rather than invent one.
    """
    if isinstance(value, bool):  # bool is an int subclass — not a serving count
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 1 else None
    if not isinstance(value, str):
        return None

    # A range first, so "4-6" yields 4 rather than the bare first integer rule
    # below happening to agree. Handles hyphen, en/em dash, and "to".
    rng = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", value)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo >= 1 and hi >= lo:
            return lo

    single = re.search(r"\d+", value)
    if single:
        n = int(single.group())
        if n >= 1:
            return n
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
../../.venv/bin/python -m pytest tests/test_recipe_schema.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Lint**

```bash
../../.venv/bin/python -m ruff check lib/recipe_schema.py tests/test_recipe_schema.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add lib/recipe_schema.py tests/test_recipe_schema.py
git commit -m "$(cat <<'EOF'
feat: declare the recipe frontmatter schema in one place

A pure checker over an already-parsed frontmatter dict. The allowlists are
measured against the 252-file corpus rather than designed, so the guard
describes what the six producers actually write.

servings_low_end takes the low end of a range per the user's decision, and
a test pins its deliberate divergence from nutrition_engine's midpoint.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 2: Disarm the `migrate_recipes.py` landmine

`rename_nutrition_keys` would corrupt all 13 legacy-key files today. Fix this **before** the normalizer, so the two tools can never race to a worse state.

**Files:**
- Modify: `migrate_recipes.py:39-64`
- Test: `tests/test_migrate_recipes.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `rename_nutrition_keys(content: str) -> tuple[str, list[str]]` — unchanged signature, new refusal behaviour.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_recipes.py`:

```python
"""rename_nutrition_keys must never create a duplicate YAML key.

All 13 files carrying a legacy nutrition key are legacy-*first*, and PyYAML
takes the last duplicate. Renaming 'calories: 3058' onto a file that already
has 'nutrition_calories: 169' therefore replaces a per-serving value with a
whole-recipe total, silently, in every nutrition surface.
"""
import yaml

from migrate_recipes import rename_nutrition_keys

LEGACY_FIRST = """---
title: Watermelon Feta Salad
calories: 3058
nutrition_calories: 169
---

# Watermelon Feta Salad
"""

NO_TWIN = """---
title: Old Recipe
calories: 420
---

# Old Recipe
"""


def _fm(content: str) -> dict:
    return yaml.safe_load(content.split("---")[1])


def test_rename_refuses_when_the_canonical_key_already_exists():
    out, changes = rename_nutrition_keys(LEGACY_FIRST)
    assert out == LEGACY_FIRST
    assert changes == []


def test_the_canonical_value_survives_a_migration_attempt():
    """The regression this guards: 169 kcal/serving must not become 3058."""
    out, _ = rename_nutrition_keys(LEGACY_FIRST)
    assert _fm(out)["nutrition_calories"] == 169


def test_no_duplicate_key_is_ever_emitted():
    out, _ = rename_nutrition_keys(LEGACY_FIRST)
    keys = [ln.split(":")[0] for ln in out.split("---")[1].strip().splitlines()]
    assert len(keys) == len(set(keys))


def test_rename_still_works_when_there_is_no_canonical_twin():
    out, changes = rename_nutrition_keys(NO_TWIN)
    assert "nutrition_calories: 420" in out
    assert "calories: 420" not in out.replace("nutrition_calories: 420", "")
    assert changes == ["Renamed 'calories' to 'nutrition_calories'"]


def test_rename_is_idempotent():
    once, _ = rename_nutrition_keys(NO_TWIN)
    twice, changes = rename_nutrition_keys(once)
    assert twice == once
    assert changes == []


def test_a_partial_collision_renames_only_the_safe_key():
    content = """---
title: Mixed
calories: 3058
nutrition_calories: 169
fat: 12
---

# Mixed
"""
    out, changes = rename_nutrition_keys(content)
    assert changes == ["Renamed 'fat' to 'nutrition_fat'"]
    assert _fm(out)["nutrition_calories"] == 169
    assert _fm(out)["nutrition_fat"] == 12
    assert "calories: 3058" in out  # left for the normalizer to delete
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
../../.venv/bin/python -m pytest tests/test_migrate_recipes.py -q
```

Expected: FAIL. `test_rename_refuses_when_the_canonical_key_already_exists`, `test_the_canonical_value_survives_a_migration_attempt`, `test_no_duplicate_key_is_ever_emitted` and `test_a_partial_collision_renames_only_the_safe_key` all fail — the current code renames unconditionally and `nutrition_calories` reads back as `3058`.

- [ ] **Step 3: Write the implementation**

In `migrate_recipes.py`, replace the body of the `for old_key, new_key` loop inside `rename_nutrition_keys` (currently lines 55-60):

```python
    for old_key, new_key in NUTRITION_KEY_RENAMES.items():
        # Anchored to start-of-line so 'nutrition_calories:' is not matched by 'calories:'
        pattern = rf'(?m)^(\s*){re.escape(old_key)}:'
        if not re.search(pattern, new_frontmatter):
            continue

        # Refuse to rename onto a key that already exists. All 13 files in the
        # corpus carrying a legacy key are legacy-FIRST, and PyYAML takes the
        # last duplicate — so renaming here would append a second
        # 'nutrition_calories:' below the canonical one and silently replace a
        # per-serving value (169) with a whole-recipe total (3058). Deleting the
        # legacy key is scripts/normalize_recipes.py's job, not a rename's.
        canonical = rf'(?m)^\s*{re.escape(new_key)}:'
        if re.search(canonical, new_frontmatter):
            continue

        new_frontmatter = re.sub(pattern, rf'\g<1>{new_key}:', new_frontmatter)
        changes.append(f"Renamed '{old_key}' to '{new_key}'")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
../../.venv/bin/python -m pytest tests/test_migrate_recipes.py -q
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
../../.venv/bin/python -m ruff check migrate_recipes.py tests/test_migrate_recipes.py
git add migrate_recipes.py tests/test_migrate_recipes.py
git commit -m "$(cat <<'EOF'
fix: never rename a nutrition key onto one that already exists

All 13 files carrying a legacy nutrition key are legacy-first, and PyYAML
takes the last duplicate — so re-running this migration would have replaced
every canonical per-serving value with a whole-recipe total. Watermelon Feta
Salad would have gone from 169 kcal/serving to 3058 in one command.

Deleting the legacy key belongs to the normalizer; a rename's only safe move
on a collision is to decline.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 3: The normalizer's repair functions

Pure-ish repair over file *content*, unit-tested against temp files. The CLI wrapper is Task 4, so the logic is testable without argument parsing.

**Files:**
- Create: `scripts/normalize_recipes.py`
- Test: `tests/test_normalize_recipes.py`

**Interfaces:**
- Consumes: `lib.recipe_schema.{check_frontmatter, servings_low_end, LEGACY_NUTRITION_KEYS, DROPPED_KEYS}`; `lib.frontmatter.{split_frontmatter, rewrite}`; `lib.recipe_parser.parse_recipe_file`.
- Produces: `normalize_content(recipe: str, content: str) -> tuple[str, list[str]]` returning `(new_content, changes)`; `normalize_file(path: Path, apply: bool) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalize_recipes.py`:

```python
"""Repairs, exercised over temp files — never the real vault."""
import yaml

from scripts.normalize_recipes import normalize_content, normalize_file

RANGED = """---
title: Watermelon Feta Salad
servings: 6-8 as a side dish
calories: 3058
carbs: null
fat: null
nutrition_calories: 169
nutrition_carbs: 12
nutrition_fat: 9
---

# Watermelon Feta Salad

Body stays untouched.
"""

CLEAN = """---
title: Fine Recipe
servings: 4
nutrition_calories: 200
---

# Fine Recipe
"""


def _fm(content: str) -> dict:
    return yaml.safe_load(content.split("---")[1])


def test_a_servings_range_becomes_its_low_end():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    assert _fm(out)["servings"] == 6


def test_a_repaired_servings_is_flagged_as_inferred():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert fm["servings_inferred"] is True
    assert fm["servings_needs_review"] is True


def test_legacy_nutrition_keys_are_deleted():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert "calories" not in fm
    assert "carbs" not in fm
    assert "fat" not in fm


def test_the_canonical_nutrition_values_are_untouched():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    fm = _fm(out)
    assert fm["nutrition_calories"] == 169
    assert fm["nutrition_carbs"] == 12
    assert fm["nutrition_fat"] == 9


def test_a_dropped_key_is_removed():
    content = CLEAN.replace("servings: 4", 'servings: 4\nrecipe_url: "https://example.com"')
    out, changes = normalize_content("Chocolate Peanut Butter Bars", content)
    assert "recipe_url" not in _fm(out)
    assert any("recipe_url" in c for c in changes)


def test_the_body_is_never_touched():
    out, _ = normalize_content("Watermelon Feta Salad", RANGED)
    assert out.split("---", 2)[2] == RANGED.split("---", 2)[2]


def test_a_conforming_file_is_returned_byte_identical():
    out, changes = normalize_content("Fine Recipe", CLEAN)
    assert out == CLEAN
    assert changes == []


def test_normalization_is_idempotent():
    once, _ = normalize_content("Watermelon Feta Salad", RANGED)
    twice, changes = normalize_content("Watermelon Feta Salad", once)
    assert twice == once
    assert changes == []


def test_changes_name_every_repair():
    _, changes = normalize_content("Watermelon Feta Salad", RANGED)
    joined = " ".join(changes)
    assert "servings" in joined
    assert "calories" in joined


def test_a_file_with_no_frontmatter_is_left_alone():
    content = "# Just a body\n\nNo frontmatter here.\n"
    out, changes = normalize_content("Bare", content)
    assert out == content
    assert changes == []


def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "Watermelon Feta Salad.md"
    p.write_text(RANGED, encoding="utf-8")
    changes = normalize_file(p, apply=False)
    assert changes                       # it reports what it would do
    assert p.read_text(encoding="utf-8") == RANGED   # but changes nothing


def test_apply_writes_and_backs_up(tmp_path):
    p = tmp_path / "Watermelon Feta Salad.md"
    p.write_text(RANGED, encoding="utf-8")
    normalize_file(p, apply=True)
    assert _fm(p.read_text(encoding="utf-8"))["servings"] == 6
    backups = list((tmp_path / ".history").glob("*"))
    assert backups, "the vault is not in git — a backup is the only recovery path"


def test_apply_on_a_clean_file_writes_nothing(tmp_path):
    p = tmp_path / "Fine Recipe.md"
    p.write_text(CLEAN, encoding="utf-8")
    before = p.stat().st_mtime_ns
    assert normalize_file(p, apply=True) == []
    assert p.stat().st_mtime_ns == before
    assert not (tmp_path / ".history").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
../../.venv/bin/python -m pytest tests/test_normalize_recipes.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'scripts.normalize_recipes'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/normalize_recipes.py`. (Task 4 adds `main()`; this step is the logic only.)

```python
#!/usr/bin/env python3
"""Repair recipe frontmatter that drifts from the declared schema.

Reads what is wrong from lib.recipe_schema and fixes the three repairable
classes: a non-numeric ``servings``, a surviving legacy nutrition key, and a
key the user decided to drop. Anything else the checker reports is surfaced and
left alone — a normalizer that invents values is worse than the drift.

Writes are line-surgical, through lib.frontmatter, for two reasons: a YAML
round-trip would reformat all 252 files and bury the real change, and
lib.frontmatter is already the shared editor used by backfill_nutrition.py and
the cook-history sync, so this tool cannot drift from them.

IMPORTANT: changing ``servings`` invalidates the file's stored per-serving
macros, which were derived as batch / servings. Re-derive them afterwards:

    .venv/bin/python backfill_nutrition.py --force --only "<Recipe Name>"

Usage:
    python scripts/normalize_recipes.py            # dry run (default)
    python scripts/normalize_recipes.py --apply
    python scripts/normalize_recipes.py --check    # exit 1 if the corpus drifts
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import frontmatter, paths
from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file
from lib.recipe_schema import (
    DROPPED_KEYS,
    LEGACY_NUTRITION_KEYS,
    check_frontmatter,
    servings_low_end,
)

# Keys this tool rewrites in place. Passing them as `managed` to
# frontmatter.rewrite also de-duplicates them, which is free insurance against
# a file that already carries two.
_MANAGED_KEYS = {"servings", "servings_inferred", "servings_needs_review"}


def normalize_content(recipe: str, content: str) -> tuple[str, list[str]]:
    """Return ``(new_content, changes)``. ``changes`` is empty when conforming."""
    fm_text, rest = frontmatter.split_frontmatter(content)
    if fm_text is None:
        return content, []

    fm = parse_recipe_file(content)["frontmatter"]
    violations = check_frontmatter(recipe, fm)
    if not violations:
        return content, []

    updates: dict = {}
    remove: set[str] = set()
    changes: list[str] = []

    for v in violations:
        if v.code == "servings_not_numeric":
            low = servings_low_end(fm.get("servings"))
            if low is None:
                # Nothing numeric to recover; leave it rather than invent one.
                changes.append(f"SKIPPED servings={fm.get('servings')!r} (no number in it)")
                continue
            updates["servings"] = low
            updates["servings_inferred"] = "true"
            updates["servings_needs_review"] = "true"
            changes.append(f"servings {fm['servings']!r} -> {low} (low end, flagged for review)")

        elif v.code == "legacy_nutrition_key":
            remove.add(v.key)
            changes.append(f"dropped legacy {v.key!r} (superseded by 'nutrition_{v.key}')")

        elif v.code == "unknown_key" and v.key in DROPPED_KEYS:
            remove.add(v.key)
            changes.append(f"dropped {v.key!r} (user decision, 2026-07-31)")

        else:
            # Reported, deliberately not repaired.
            changes.append(f"UNREPAIRED {v.code}: {v.detail}")

    if not updates and not remove:
        return content, changes

    managed = _MANAGED_KEYS | LEGACY_NUTRITION_KEYS | DROPPED_KEYS
    new_fm = frontmatter.rewrite(fm_text, updates, managed, remove=remove)
    return f"---{new_fm}---{rest}", changes


def normalize_file(path: Path, apply: bool) -> list[str]:
    """Normalize one recipe file. Returns the changes made (or that would be)."""
    content = path.read_text(encoding="utf-8")
    new_content, changes = normalize_content(path.stem, content)

    if apply and new_content != content:
        create_backup(path)
        path.write_text(new_content, encoding="utf-8")

    return changes


def audit(recipes_dir: Path) -> list:
    """Every violation across the corpus, for --check."""
    out = []
    for p in sorted(recipes_dir.glob("*.md")):
        fm = parse_recipe_file(p.read_text(encoding="utf-8"))["frontmatter"]
        out.extend(check_frontmatter(p.stem, fm))
    return out
```

Add `tests/__init__.py`-style import support if `scripts/` is not a package: create an empty `scripts/__init__.py` **only if** `../../.venv/bin/python -c "import scripts.normalize_recipes"` fails from the repo root.

- [ ] **Step 4: Run the test to verify it passes**

```bash
../../.venv/bin/python -m pytest tests/test_normalize_recipes.py -q
```

Expected: all 13 tests PASS. If `test_apply_writes_and_backs_up` fails on the backup location, check `lib/backup.py:28` — it writes to `<parent>/.history/`, which is `tmp_path/.history` here.

- [ ] **Step 5: Commit**

```bash
../../.venv/bin/python -m ruff check scripts/normalize_recipes.py tests/test_normalize_recipes.py
git add scripts/normalize_recipes.py tests/test_normalize_recipes.py
git commit -m "$(cat <<'EOF'
feat: repair recipe frontmatter drift through the shared editor

Fixes the three repairable classes — a non-numeric servings, a surviving
legacy nutrition key, a dropped key — and reports anything else rather than
inventing a value. Writes go through lib.frontmatter so this tool cannot
drift from backfill_nutrition or the cook-history sync.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 4: The normalizer CLI

**Files:**
- Modify: `scripts/normalize_recipes.py` (append `main()`)
- Test: `tests/test_normalize_recipes.py` (append)

**Interfaces:**
- Consumes: `normalize_file`, `audit` from Task 3.
- Produces: `main() -> int` — exit code 0 clean / 1 on drift under `--check`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_normalize_recipes.py`:

```python
def test_check_exits_nonzero_when_the_corpus_drifts(tmp_path, monkeypatch, capsys):
    from scripts import normalize_recipes

    (tmp_path / "Recipes").mkdir()
    (tmp_path / "Recipes" / "Ranged.md").write_text(RANGED, encoding="utf-8")
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    assert normalize_recipes.main() == 1
    assert "servings_not_numeric" in capsys.readouterr().out


def test_check_exits_zero_on_a_conforming_corpus(tmp_path, monkeypatch):
    from scripts import normalize_recipes

    (tmp_path / "Recipes").mkdir()
    (tmp_path / "Recipes" / "Fine Recipe.md").write_text(CLEAN, encoding="utf-8")
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["normalize_recipes.py", "--check"])

    assert normalize_recipes.main() == 0
```

Add `import sys` to the test file's imports.

- [ ] **Step 2: Run the test to verify it fails**

```bash
../../.venv/bin/python -m pytest tests/test_normalize_recipes.py -q -k check
```

Expected: FAIL — `AttributeError: module 'scripts.normalize_recipes' has no attribute 'main'`.

- [ ] **Step 3: Write the implementation**

Append to `scripts/normalize_recipes.py`:

```python
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 if any exists; never writes")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()

    if args.check:
        violations = audit(recipes_dir)
        for v in violations:
            print(f"  {v.recipe[:46]:48} {v.code:22} {v.detail}")
        print(f"\n{len(violations)} violation(s) across {len(list(recipes_dir.glob('*.md')))} recipes")
        return 1 if violations else 0

    if not args.apply:
        print("DRY RUN — no files will be modified (pass --apply to write)\n")

    touched = servings_changed = 0
    for p in sorted(recipes_dir.glob("*.md")):
        changes = normalize_file(p, apply=args.apply)
        if not changes:
            continue
        touched += 1
        if any(c.startswith("servings ") for c in changes):
            servings_changed += 1
        print(f"{p.stem}")
        for c in changes:
            print(f"    {c}")

    print(f"\n{'Modified' if args.apply else 'Would modify'}: {touched} file(s)")
    if servings_changed:
        print(
            f"\n{servings_changed} file(s) had servings changed — their stored\n"
            f"per-serving macros were derived from the OLD count and are now stale.\n"
            f"Re-derive them:  .venv/bin/python backfill_nutrition.py --force --only \"<name>\""
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
../../.venv/bin/python -m pytest tests/test_normalize_recipes.py -q
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
../../.venv/bin/python -m ruff check scripts/normalize_recipes.py tests/test_normalize_recipes.py
git add scripts/normalize_recipes.py tests/test_normalize_recipes.py
git commit -m "$(cat <<'EOF'
feat: normalize_recipes CLI with dry-run default and --check

--check is the drift gate: it prints every violation and exits 1, so the
corpus guard can run from an audit as well as from the test suite. The
apply path names the files whose servings changed, because their stored
macros are stale until backfill_nutrition re-derives them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 5: `backfill_nutrition.py --only`

Needed to re-derive exactly the 3 recipes whose `servings` changes, without a 252-file `--force` run.

**Files:**
- Modify: `backfill_nutrition.py:210-245`
- Test: `tests/test_backfill_nutrition.py` (append)

**Interfaces:**
- Produces: `--only NAME` CLI flag, repeatable, matching on recipe stem.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backfill_nutrition.py`:

```python
def test_only_selects_named_recipes(tmp_path):
    """--only narrows the candidate list to the named stems."""
    from backfill_nutrition import select_only

    class P:
        def __init__(self, stem):
            self.stem = stem

    cands = [P("Alpha"), P("Beta"), P("Gamma")]
    assert [p.stem for p in select_only(cands, ["Beta"])] == ["Beta"]
    assert [p.stem for p in select_only(cands, ["Beta", "Alpha"])] == ["Alpha", "Beta"]
    assert [p.stem for p in select_only(cands, [])] == ["Alpha", "Beta", "Gamma"]


def test_only_raises_on_an_unknown_name(tmp_path):
    from backfill_nutrition import select_only

    class P:
        def __init__(self, stem):
            self.stem = stem

    with pytest.raises(SystemExit) as e:
        select_only([P("Alpha")], ["Nope"])
    assert "Nope" in str(e.value)
```

Ensure `import pytest` is present in that test file.

- [ ] **Step 2: Run the test to verify it fails**

```bash
../../.venv/bin/python -m pytest tests/test_backfill_nutrition.py -q -k only
```

Expected: FAIL — `ImportError: cannot import name 'select_only'`.

- [ ] **Step 3: Write the implementation**

Add to `backfill_nutrition.py`, above `main()`:

```python
def select_only(candidates, names):
    """Narrow ``candidates`` to the recipes named in ``names``.

    A name that matches nothing is an error, not a silent no-op: the caller
    asked for a specific recipe to be re-derived, and quietly doing zero work
    would look identical to success.
    """
    if not names:
        return candidates
    by_stem = {p.stem: p for p in candidates}
    missing = [n for n in names if n not in by_stem]
    if missing:
        raise SystemExit(f"--only: no such recipe(s) in the candidate set: {', '.join(missing)}")
    return [by_stem[n] for n in sorted(names)]
```

In `main()`, add the argument beside `--limit`:

```python
    parser.add_argument(
        "--only", action="append", default=[], metavar="NAME",
        help="only this recipe (by filename stem); repeatable",
    )
```

and apply it immediately after `candidates = collect_recipes_needing_backfill(...)`:

```python
    candidates = select_only(candidates, args.only)

    if args.limit:
        candidates = candidates[: args.limit]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
../../.venv/bin/python -m pytest tests/test_backfill_nutrition.py -q
```

Expected: PASS, with no regression in the existing tests in that file.

- [ ] **Step 5: Commit**

```bash
../../.venv/bin/python -m ruff check backfill_nutrition.py tests/test_backfill_nutrition.py
git add backfill_nutrition.py tests/test_backfill_nutrition.py
git commit -m "$(cat <<'EOF'
feat: backfill_nutrition --only, to re-derive named recipes

A servings correction invalidates exactly the files it touched. --limit
takes the first N, which cannot express that; --only names them. An
unmatched name exits rather than silently doing nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 6: Run it on the corpus

The first step that touches real data. Everything before this is reversible by `git checkout`; this is not.

- [ ] **Step 1: Confirm the corpus drift matches this plan**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/recipe-schema-normalize
../../.venv/bin/python scripts/normalize_recipes.py --check
```

Expected: exit 1, 17 files, exactly 41 violations — 3 × `servings_not_numeric`, 39 × `legacy_nutrition_key` (13 files × `calories`/`carbs`/`fat`), 1 × `unknown_key` (`recipe_url` on `Chocolate Peanut Butter Bars`). **If the counts differ, stop and re-read the corpus — the vault has changed since this plan was written.**

- [ ] **Step 2: Review the dry run in full**

```bash
../../.venv/bin/python scripts/normalize_recipes.py | tee /tmp/normalize-dryrun.txt
```

Read every line. Confirm: `Watermelon Feta Salad` takes both a servings fix and a legacy-key delete; no `UNREPAIRED` or `SKIPPED` lines appear.

- [ ] **Step 3: Apply**

```bash
../../.venv/bin/python scripts/normalize_recipes.py --apply
```

Expected: `Modified: 17 file(s)`, followed by the stale-macro warning naming 3 files.

- [ ] **Step 4: Verify idempotency and a clean corpus**

```bash
../../.venv/bin/python scripts/normalize_recipes.py --apply    # second run
../../.venv/bin/python scripts/normalize_recipes.py --check
```

Expected: the second apply reports `Modified: 0 file(s)`; `--check` exits 0 with `0 violation(s)`.

- [ ] **Step 5: Re-derive the stale macros**

```bash
../../.venv/bin/python backfill_nutrition.py --force \
  --only "Creamy Grape Salad Alternative" \
  --only "Healthy Blueberry Apple Oatmeal Cake" \
  --only "Watermelon Feta Salad"
```

Expected: 3 recipes processed. Their per-serving calories should rise (servings fell from the midpoint to the low end): `4-6`→4 is +25% over the previous midpoint of 5, and both `6-8`→6 are +17% over 7.

- [ ] **Step 6: Confirm the three subsystems now agree**

```bash
../../.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, '.')
from lib import paths
from lib.recipe_parser import parse_recipe_file
from lib.nutrition_engine import _parse_servings
from lib.nutrition_quality import macro_eligible
for name in ["Creamy Grape Salad Alternative", "Healthy Blueberry Apple Oatmeal Cake", "Watermelon Feta Salad"]:
    fm = parse_recipe_file((paths.recipes_dir() / f"{name}.md").read_text())["frontmatter"]
    s = fm["servings"]
    wv = float(s) if s else 4.0
    print(f"{name[:42]:44} servings={s!r:6} engine={_parse_servings(s):3} week_view={wv:5} eligible={macro_eligible(fm)[0]}")
PY
```

Expected: for each recipe `servings`, `engine` and `week_view` are the **same** number.

- [ ] **Step 7: Commit (no vault files — the vault is not in git)**

```bash
git status --short   # expect: nothing from vault/; only .gitignored paths changed
git commit --allow-empty -m "$(cat <<'EOF'
chore: normalize the recipe corpus

17 files repaired: 3 servings ranges collapsed to their low end and flagged
for review, 39 legacy nutrition keys deleted across 13 files, 1 recipe_url
dropped. Nutrition re-derived for the 3 recipes whose servings changed, so
their stored per-serving macros match the count they now declare.

Verified: --check reports 0 violations, a second apply is a no-op, and
nutrition_engine and week_view agree on all three repaired recipes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 7: The anti-recurrence guard

The deliverable that makes this branch worth more than a one-off cleanup.

**Files:**
- Create: `tests/e2e/test_recipe_corpus_schema.py`

**Interfaces:**
- Consumes: `lib.recipe_schema.check_frontmatter`; `tests.e2e._paths.data_root`.

- [ ] **Step 1: Write the test**

Create `tests/e2e/test_recipe_corpus_schema.py`:

```python
"""The real corpus satisfies the declared schema.

An audit of the user's data, not of code behaviour — which is why it lives
beside test_live_state.py rather than in the hermetic unit suite. The schema
checker itself is tested over synthetic frontmatter in
tests/test_recipe_schema.py; this asks whether the vault currently conforms.

Failing here means a producer started writing a key nobody declared, or drift
came back. The fix is either to add the key to lib/recipe_schema.OPTIONAL_KEYS
(if it is legitimate) or to run scripts/normalize_recipes.py --apply.
"""
from __future__ import annotations

import collections
from pathlib import Path

import pytest

from lib.recipe_parser import parse_recipe_file
from lib.recipe_schema import check_frontmatter
from tests.e2e._paths import data_root

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
RECIPES = data_root(REPO) / "vault" / "KitchenOS" / "Recipes"


def _violations():
    out = []
    for p in sorted(RECIPES.glob("*.md")):
        fm = parse_recipe_file(p.read_text(encoding="utf-8"))["frontmatter"]
        out.extend(check_frontmatter(p.stem, fm))
    return out


@pytest.mark.skipif(not RECIPES.exists(), reason="vault not present on this machine")
def test_the_corpus_has_no_schema_violations():
    violations = _violations()
    if violations:
        by_code = collections.Counter(v.code for v in violations)
        detail = "\n".join(f"  {v.recipe}: {v.code} ({v.key})" for v in violations[:20])
        pytest.fail(
            f"{len(violations)} schema violation(s) across the corpus: {dict(by_code)}\n"
            f"{detail}\n"
            f"Fix: .venv/bin/python scripts/normalize_recipes.py --check"
        )


@pytest.mark.skipif(not RECIPES.exists(), reason="vault not present on this machine")
def test_no_recipe_declares_a_non_numeric_servings():
    """Called out separately: three subsystems each read a range differently."""
    bad = [v for v in _violations() if v.code == "servings_not_numeric"]
    assert bad == [], f"{len(bad)} recipe(s) with a non-numeric servings: {[v.recipe for v in bad]}"
```

- [ ] **Step 2: Run it**

```bash
../../.venv/bin/python -m pytest tests/e2e/test_recipe_corpus_schema.py -q
```

Expected: 2 PASS (Task 6 already cleaned the corpus). If it fails, the vault drifted between Task 6 and now — re-run the normalizer rather than editing the test.

- [ ] **Step 3: Prove the guard actually catches drift**

A guard that has never failed is not known to work. Temporarily reintroduce drift into one file, confirm the test fails, then restore it:

```bash
../../.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, '.')
from lib import paths
p = paths.recipes_dir() / "Watermelon Feta Salad.md"
t = p.read_text(encoding="utf-8")
p.write_text(t.replace("servings: 6", "servings: 6-8", 1), encoding="utf-8")
print("drift injected")
PY
../../.venv/bin/python -m pytest tests/e2e/test_recipe_corpus_schema.py -q   # expect FAIL
../../.venv/bin/python scripts/normalize_recipes.py --apply
../../.venv/bin/python -m pytest tests/e2e/test_recipe_corpus_schema.py -q   # expect PASS
```

Expected: FAIL naming `Watermelon Feta Salad` and `servings_not_numeric`, then PASS after the repair. If the second `--apply` changed servings, re-run the Task 6 Step 5 backfill for that one recipe.

- [ ] **Step 4: Commit**

```bash
../../.venv/bin/python -m ruff check tests/e2e/test_recipe_corpus_schema.py
git add tests/e2e/test_recipe_corpus_schema.py
git commit -m "$(cat <<'EOF'
test: fail when the recipe corpus drifts from the declared schema

Lives beside test_live_state.py because it audits the user's data rather
than code behaviour, and resolves the vault through _paths.data_root so it
runs from a worktree. Verified by injecting drift and watching it fail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

---

## Task 8: Docs and closure

**Files:**
- Modify: `docs/OPERATIONS.md`, `CLAUDE.md`, `docs/plans/INDEX.md`, `BRANCH-STATUS.md`
- Delete: `scripts/_analysis/`

- [ ] **Step 1: Add the runbook entry**

In `docs/OPERATIONS.md`, beside the other maintenance scripts:

```markdown
### Normalize recipe frontmatter

`scripts/normalize_recipes.py` repairs frontmatter that drifts from the schema
declared in `lib/recipe_schema.py`: a non-numeric `servings` (collapsed to the
**low end** of a range and flagged `servings_inferred` + `servings_needs_review`),
a surviving legacy `calories`/`carbs`/`fat` key (deleted — `nutrition_*` is the
FDC-sourced authority), and `recipe_url` (dropped, user decision 2026-07-31).

```bash
.venv/bin/python scripts/normalize_recipes.py            # dry run (default)
.venv/bin/python scripts/normalize_recipes.py --check    # exit 1 on drift
.venv/bin/python scripts/normalize_recipes.py --apply    # write (backs up first)
```

**A `servings` change leaves the file's macros stale** — `nutrition_*` is
per-serving, derived as batch ÷ servings. The apply run names the affected
recipes; re-derive them:

```bash
.venv/bin/python backfill_nutrition.py --force --only "<Recipe Name>"
```

`tests/e2e/test_recipe_corpus_schema.py` fails if the corpus drifts again.
```

- [ ] **Step 2: Add the invariant**

Append to the invariants list in `CLAUDE.md`:

```markdown
- **Recipe frontmatter has one declared schema, and `servings` is a number.** `lib/recipe_schema.py` holds the measured allowlists (30 required keys, the optional set each producer writes) and is the only description of what a recipe file may contain — a new frontmatter key means editing that file in the same commit, which is what `tests/e2e/test_recipe_corpus_schema.py` enforces. The reason it matters is that a *string* `servings` is read three different ways with no error anywhere: `nutrition_engine._parse_servings` takes a range's **midpoint** (`"6-8"` → 7), `week_view.recipe_base_servings` does a bare `float()` inside `except Exception: return 4.0` so it silently becomes **4.0**, and `nutrition_quality.macro_eligible` only checks for `None`, so it certifies the recipe as trustworthy while the two disagree by 75%. `scripts/normalize_recipes.py` collapses ranges to the **low end** (fewer servings → higher per-serving calories, the conservative direction for a macro target) — deliberately *not* the engine's midpoint, a divergence pinned by a test. Because `nutrition_*` is per-serving, **changing `servings` invalidates the stored macros**: re-derive with `backfill_nutrition.py --force --only "<name>"` or the file ships a serving count that contradicts its own numbers. Legacy `calories`/`carbs`/`fat` are deleted rather than migrated — all 13 files carrying one were legacy-*first*, and since PyYAML takes the last duplicate, `migrate_recipes.rename_nutrition_keys` would have renamed a whole-recipe total on top of the canonical per-serving value (169 → 3058 kcal on one recipe); it now refuses to rename onto an existing key.
```

- [ ] **Step 3: Delete the throwaway analysis scripts**

```bash
git rm -r scripts/_analysis
```

- [ ] **Step 4: Full test suite + lint**

```bash
../../.venv/bin/python -m pytest tests/ -q -x --ignore=tests/e2e
../../.venv/bin/python -m pytest tests/e2e -q
../../.venv/bin/python -m ruff check .
```

Expected: unit suite green with ~30 more tests than `main`'s 3433; e2e green at 124+; ruff clean. **Record the actual numbers** — do not claim them from this plan.

- [ ] **Step 5: Update `BRANCH-STATUS.md`**

Check off every Dev / Testing / Docs box, set `Current Stage: review`, and correct the Findings section: the `serving_ledger` "can throw" claim is wrong (record the real three-way divergence), `enrich_none` is on 18 files and is kept, and there were zero legacy-value carry-across cases.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: runbook, invariant and branch status for the schema normalizer

Records the real defect the branch was built on — a string servings is read
as the midpoint by nutrition_engine, as 4.0 by week_view, and as fine by
macro_eligible — rather than the crash the original findings predicted.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018gpxgqgAZLCn9nWax5thKg
EOF
)"
```

- [ ] **Step 7: Review, then close out**

Use `superpowers:requesting-code-review`, address feedback, then `superpowers:finishing-a-development-branch` for the merge + closure ritual (archive summary in `docs/completed/`, move the row to Done in `docs/plans/INDEX.md`, remove the worktree, confirm no `BRANCH-STATUS.md` in the main root).

---

## Self-Review

**Spec coverage.** Every in-scope item from `BRANCH-STATUS.md` maps to a task: non-numeric servings → Tasks 1/3/6; legacy nutrition keys → Tasks 1/3/6, with the migration hazard it warned about disarmed in Task 2; stray `recipe_url` → Tasks 1/3/6; the corpus-wide drift test → Tasks 1 and 7; the normalizer script (`--dry-run` default, backup, idempotent) → Tasks 3/4, with idempotency pinned by both a unit test and a live second run. The branch's last open question (`enrich_none`) is answered in Background and resolved as "keep" in Task 1's `OPTIONAL_KEYS`. Out-of-scope items (two nutrition sections, missing body nutrition, quoted vs bare scalars, time-string formats) stay out — none is touched.

**Additions beyond the original scope, and why.** Task 2 exists because the hazard is armed on `main` right now and the normalizer would otherwise be racing it. Task 5 exists because Task 6 cannot honestly complete without it — a servings correction that leaves stale macros just moves the inconsistency instead of fixing it.

**Placeholder scan.** No TBDs; every code step carries complete code; every command carries its expected output. The one conditional instruction (create `scripts/__init__.py` only if the import fails) states its exact test.

**Type consistency.** `check_frontmatter(recipe, fm) -> list[Violation]` and `servings_low_end(value) -> int | None` are used with those signatures in Tasks 3, 4 and 7. `Violation` fields (`recipe`, `key`, `code`, `detail`) are read consistently. Violation codes — `missing_required_key`, `legacy_nutrition_key`, `unknown_key`, `servings_not_numeric` — are spelled identically in the checker, its tests, the normalizer's dispatch, and the corpus guard. `normalize_content` / `normalize_file` / `audit` / `select_only` signatures match every call site.

**Known risk.** Task 6 is the only irreversible step. Its guard is `lib.backup.create_backup` per file plus the Step 1 count check, which halts if the corpus no longer matches this plan.
