# Cook Now Meal-Type Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Cook Now be filtered by meal type, so reviewing "what could I cook right now?" can exclude the 47 dessert recipes.

**Architecture:** Repair `dish_type` across all 239 recipes with a one-off Claude Batches pass into a 13-value controlled vocabulary (dry-run diff, then apply with backups), delete the `"biscuit" → "dessert"` normalizer rule that caused the corruption, then serve a new `/cook-now` page whose 6 chip groups filter a single payload client-side.

**Tech Stack:** Python 3.11, Flask (`api_server.py`), `anthropic` SDK (Batches API + structured outputs), pytest, Playwright for the browser test.

## Global Constraints

- **Always run Python via `.venv/bin/python`** — never bare `python`.
- **Vault paths come from `lib/paths.py` helpers only** (`recipes_dir()`, `vault_root()`). Never hardcode a vault path.
- **Editing `lib/`, `templates/`, or `prompts/` requires a LaunchAgent restart** or the server serves stale code:
  `launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist && launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist`
- **A new browsable page must be registered in `SECTIONS`** (`lib/web_dashboard.py`) and propagated via `scripts/generate_web_dashboard.py` + `scripts/sync_safari_bookmarks.py --apply`. The Safari sync quits and relaunches Safari — pre-authorized, do it without asking.
- **Recipe file overwrites call `backup.create_backup()` first** (see `backfill_fit.py:63-68`).
- **Commit message trailer:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Model:** `claude-opus-5`. It thinks by default and `max_tokens` bounds thinking + text together — keep `max_tokens=2000` even for one-field output.
- Work happens in the worktree `.worktrees/cook-now-meal-type-filter` on branch `cook-now-meal-type-filter`.

## File Structure

| File | Responsibility |
|---|---|
| `lib/normalizer.py` (modify) | Add `VALID_DISH_TYPES`; delete the `biscuit → dessert` rule |
| `scripts/reclassify_dish_type.py` (create) | One-off repair: batch classify, diff report, `--apply` writes |
| `lib/cook_now.py` (modify) | `DISH_TYPE_GROUPS`, `group_for()`; emit `dish_type` + `group` per recipe |
| `api_server.py` (modify) | `GET /api/cook-now`, `GET /cook-now` |
| `templates/cook_now.html` (create) | Chip UI, client-side filtering, localStorage |
| `lib/web_dashboard.py` (modify) | `SECTIONS` entry for `/cook-now` |
| `tests/test_normalizer_dish_type.py` (create) | Vocabulary + biscuit-rule tests |
| `tests/test_reclassify_dish_type.py` (create) | Diff/apply logic, no network |
| `tests/test_cook_now.py` (modify) | Group mapping, fallback, note unchanged |
| `tests/test_api_cook_now.py` (create) | Endpoint contract |
| `tests/e2e/test_cook_now_filter.py` (create) | Chips in a real browser |

---

### Task 1: Controlled vocabulary and the biscuit rule

**Files:**
- Modify: `lib/normalizer.py` (add `VALID_DISH_TYPES` near `VALID_MEAL_OCCASIONS` ~line 221; delete `"biscuit": "dessert",` at line 196)
- Test: `tests/test_normalizer_dish_type.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalizer.VALID_DISH_TYPES: set[str]` — the 13 canonical dish types. Tasks 2 and 4 both import it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalizer_dish_type.py`:

```python
"""The dish_type controlled vocabulary, and the biscuit rule that corrupted it."""

from lib import normalizer


def test_vocabulary_is_exactly_the_map_targets():
    """VALID_DISH_TYPES must describe DISH_TYPE_MAP, not compete with it.

    If a new variant is mapped to a brand-new target, this fails loudly rather
    than letting a value exist that no UI chip group knows about.
    """
    assert set(normalizer.DISH_TYPE_MAP.values()) == normalizer.VALID_DISH_TYPES


def test_vocabulary_has_thirteen_values():
    assert len(normalizer.VALID_DISH_TYPES) == 13


def test_biscuit_no_longer_maps_to_dessert():
    """'biscuit' -> 'dessert' filed savory biscuits as desserts.

    Left in place, it re-corrupts the data on the next extraction, so the
    one-off repair would silently rot.
    """
    assert "biscuit" not in normalizer.DISH_TYPE_MAP


def test_savory_biscuit_is_not_normalized_to_dessert():
    assert normalizer.normalize_field("dish_type", "biscuit") != "dessert"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_normalizer_dish_type.py -v
```

Expected: FAIL — `AttributeError: module 'lib.normalizer' has no attribute 'VALID_DISH_TYPES'`.

- [ ] **Step 3: Add the vocabulary**

In `lib/normalizer.py`, immediately after the `VALID_MEAL_OCCASIONS` set (~line 235), add:

```python
# The canonical dish_type values — exactly the right-hand side of DISH_TYPE_MAP.
# Kept as a named set because scripts/reclassify_dish_type.py constrains the LLM
# to these values via a JSON-schema enum, and lib/cook_now.py maps every one of
# them to a UI chip group. A target that exists in the map but not here would be
# a dish type no chip can show.
VALID_DISH_TYPES = set(DISH_TYPE_MAP.values())
```

- [ ] **Step 4: Delete the biscuit rule**

In `lib/normalizer.py`, in the "More dessert variants" block (~line 196), delete this line:

```python
    "biscuit": "dessert",
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_normalizer_dish_type.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run the full normalizer suite for regressions**

```bash
.venv/bin/python -m pytest tests/ -k normalizer -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add lib/normalizer.py tests/test_normalizer_dish_type.py
git commit -m "$(cat <<'EOF'
fix: drop the biscuit->dessert rule, name the dish_type vocabulary

"biscuit" -> "dessert" filed savory biscuits as desserts (Butter Biscuits is
the live example). Left in place it would re-corrupt any recipe extracted
after the one-off repair, so the repair had a built-in expiry date.

VALID_DISH_TYPES is derived from DISH_TYPE_MAP's targets so the vocabulary
can't drift from the normalizer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The reclassification script

**Files:**
- Create: `scripts/reclassify_dish_type.py`
- Test: `tests/test_reclassify_dish_type.py`

**Interfaces:**
- Consumes: `normalizer.VALID_DISH_TYPES` (Task 1).
- Produces:
  - `build_prompt(recipe: dict) -> str`
  - `diff(recipes: list[dict], results: dict[str, str]) -> dict` returning `{"change": [(name, old, new)], "keep": [(name, dt)], "unresolved": [(name, dt)]}` — `results` is keyed by `custom_id` (`"r0"`, `"r1"`, …, positional against `recipes`).
  - `apply_changes(changes: list[tuple[str, str, str]]) -> tuple[int, list[str]]` returning `(written_count, skipped_names)`.
  - `classify(recipes, client) -> dict[str, str]` — network; not unit-tested.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reclassify_dish_type.py`:

```python
"""Diff and apply logic for the one-off dish_type repair. No network."""

import pytest

from lib import paths
from scripts import reclassify_dish_type as rc


RECIPES = [
    {"name": "Butter Biscuits", "dish_type": "dessert",
     "ingredient_items": ["flour", "butter", "buttermilk"]},
    {"name": "Chili Garlic Noodles", "dish_type": "main",
     "ingredient_items": ["noodles", "chili crisp", "garlic"]},
    {"name": "Green Shakshuka", "dish_type": "Shakshuka",
     "ingredient_items": ["eggs", "spinach", "feta"]},
]


class TestDiff:
    def test_splits_change_keep_and_unresolved(self):
        results = {"r0": "bread", "r1": "main"}  # r2 missing -> unresolved
        out = rc.diff(RECIPES, results)
        assert out["change"] == [("Butter Biscuits", "dessert", "bread")]
        assert out["keep"] == [("Chili Garlic Noodles", "main")]
        assert out["unresolved"] == [("Green Shakshuka", "Shakshuka")]

    def test_every_recipe_lands_in_exactly_one_bucket(self):
        """A silently dropped recipe would read as 'nothing to do'."""
        results = {"r0": "bread"}
        out = rc.diff(RECIPES, results)
        total = len(out["change"]) + len(out["keep"]) + len(out["unresolved"])
        assert total == len(RECIPES)

    def test_results_are_keyed_by_custom_id_not_order(self):
        """Batch results come back in arbitrary order — position must not matter."""
        forward = rc.diff(RECIPES, {"r0": "bread", "r1": "main", "r2": "main"})
        shuffled = rc.diff(RECIPES, {"r2": "main", "r1": "main", "r0": "bread"})
        assert forward == shuffled

    def test_unknown_custom_id_is_ignored(self):
        out = rc.diff(RECIPES, {"r99": "dessert"})
        assert out["change"] == []
        assert len(out["unresolved"]) == 3


class TestApplyChanges:
    def test_writes_frontmatter_and_backs_up(self, tmp_vault):
        recipes_dir = paths.recipes_dir()
        recipes_dir.mkdir(parents=True, exist_ok=True)
        path = recipes_dir / "Butter Biscuits.md"
        path.write_text(
            "---\ntitle: Butter Biscuits\ndish_type: dessert\n---\n\n## Ingredients\n- flour\n",
            encoding="utf-8",
        )

        written, skipped = rc.apply_changes([("Butter Biscuits", "dessert", "bread")])

        assert written == 1 and skipped == []
        assert "dish_type: bread" in path.read_text(encoding="utf-8")
        assert list((recipes_dir / ".history").glob("Butter Biscuits*")), "no backup written"

    def test_leaves_other_frontmatter_untouched(self, tmp_vault):
        recipes_dir = paths.recipes_dir()
        recipes_dir.mkdir(parents=True, exist_ok=True)
        path = recipes_dir / "Butter Biscuits.md"
        path.write_text(
            "---\ntitle: Butter Biscuits\ndish_type: dessert\ncuisine: American\n---\n\nbody\n",
            encoding="utf-8",
        )

        rc.apply_changes([("Butter Biscuits", "dessert", "bread")])

        text = path.read_text(encoding="utf-8")
        assert "cuisine: American" in text
        assert "title: Butter Biscuits" in text
        assert "body" in text

    def test_missing_file_is_reported_not_crashed(self, tmp_vault):
        paths.recipes_dir().mkdir(parents=True, exist_ok=True)
        written, skipped = rc.apply_changes([("Nonexistent Recipe", "main", "side")])
        assert written == 0
        assert skipped == ["Nonexistent Recipe"]


class TestPrompt:
    def test_prompt_carries_name_ingredients_and_current_value(self):
        prompt = rc.build_prompt(RECIPES[0])
        assert "Butter Biscuits" in prompt
        assert "buttermilk" in prompt
        assert "dessert" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_reclassify_dish_type.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reclassify_dish_type'`.

- [ ] **Step 3: Create the script**

Create `scripts/reclassify_dish_type.py`:

```python
"""One-off repair: reclassify every recipe's dish_type with Claude.

Why this exists: dish_type is the field the Cook Now meal-type filter reads, and
it drifted. Twelve recipes carry one-off values ("Dinner", "Tostada",
"biscuits"), and the dessert bucket is contaminated because normalizer.py used
to map "biscuit" -> "dessert". A hand-written mapping of the visible strays
would not have caught Butter Biscuits, which looks perfectly well-formed.

Dry-run by default: prints a CHANGE / KEEP / UNRESOLVED report and writes
nothing. --apply writes dish_type into recipe frontmatter, backing each file up
into .history/ first.

    .venv/bin/python scripts/reclassify_dish_type.py            # report only
    .venv/bin/python scripts/reclassify_dish_type.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import frontmatter, paths  # noqa: E402
from lib.backup import create_backup  # noqa: E402
from lib.normalizer import VALID_DISH_TYPES  # noqa: E402
from lib.recipe_index import get_recipe_index  # noqa: E402

CLAUDE_MODEL = "claude-opus-5"

# Structured output: the model physically cannot answer outside the vocabulary,
# so there is no validation branch here that could drift from normalizer.py.
DISH_TYPE_SCHEMA = {
    "type": "object",
    "properties": {"dish_type": {"type": "string", "enum": sorted(VALID_DISH_TYPES)}},
    "required": ["dish_type"],
    "additionalProperties": False,
}


def build_prompt(recipe: dict) -> str:
    """One classification prompt. Current value is included as a hint, not an answer."""
    ingredients = ", ".join(recipe.get("ingredient_items") or []) or "(none listed)"
    return (
        "Classify this recipe into exactly one dish type.\n\n"
        f"Recipe name: {recipe['name']}\n"
        f"Ingredients: {ingredients}\n"
        f"Currently filed as: {recipe.get('dish_type') or '(unset)'}\n\n"
        "The current value may be wrong — judge from the name and ingredients. "
        "A savory baked good is bread or breakfast, not dessert."
    )


def classify(recipes: list[dict], client) -> dict[str, str]:
    """Batch-classify every recipe. Returns {custom_id: dish_type} for successes."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    batch = client.messages.batches.create(requests=[
        Request(
            # custom_id is alphanumerics/underscores/dashes only, so it cannot be
            # the recipe name — this library has "Arayes 🥙" and "Hardee's Biscuits".
            custom_id=f"r{i}",
            params=MessageCreateParamsNonStreaming(
                model=CLAUDE_MODEL,
                # Opus 5 thinks by default and max_tokens bounds thinking + text
                # together, so a one-field answer still needs real headroom.
                max_tokens=2000,
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": DISH_TYPE_SCHEMA}},
                messages=[{"role": "user", "content": build_prompt(r)}],
            ),
        )
        for i, r in enumerate(recipes)
    ])
    print(f"Batch {batch.id} submitted ({len(recipes)} recipes). Waiting…")

    while True:
        status = client.messages.batches.retrieve(batch.id)
        if status.processing_status == "ended":
            break
        print(f"  {status.processing_status}: "
              f"{status.request_counts.processing} processing")
        time.sleep(30)

    results: dict[str, str] = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type != "succeeded":
            continue
        text = next((b.text for b in result.result.message.content
                     if getattr(b, "type", None) == "text"), "")
        try:
            results[result.custom_id] = json.loads(text)["dish_type"]
        except (json.JSONDecodeError, KeyError):
            continue  # falls through to UNRESOLVED
    return results


def diff(recipes: list[dict], results: dict[str, str]) -> dict:
    """Split recipes into change / keep / unresolved.

    Keyed by custom_id, never by position — batch results arrive in arbitrary
    order. Every recipe lands in exactly one bucket; a silently dropped recipe
    would read as "nothing to do".
    """
    change, keep, unresolved = [], [], []
    for i, recipe in enumerate(recipes):
        current = recipe.get("dish_type")
        new = results.get(f"r{i}")
        if new is None:
            unresolved.append((recipe["name"], current))
        elif new != current:
            change.append((recipe["name"], current, new))
        else:
            keep.append((recipe["name"], current))
    return {"change": change, "keep": keep, "unresolved": unresolved}


def apply_changes(changes: list[tuple[str, str, str]]) -> tuple[int, list[str]]:
    """Write new dish_type values into frontmatter. Returns (written, skipped)."""
    written, skipped = 0, []
    for name, _old, new in changes:
        path = paths.recipes_dir() / f"{name}.md"
        if not path.exists():
            skipped.append(name)
            continue
        content = path.read_text(encoding="utf-8")
        # managed_keys scoped to dish_type so no other frontmatter field moves.
        updated = frontmatter.apply(content, {"dish_type": new}, ("dish_type",))
        if updated is None:
            skipped.append(name)
            continue
        create_backup(path)
        path.write_text(updated, encoding="utf-8")
        written += 1
    return written, skipped


def _report(result: dict) -> None:
    print(f"\n  CHANGE     {len(result['change'])}")
    for name, old, new in result["change"]:
        print(f"    {name[:44]:46} {str(old):18} -> {new}")
    print(f"\n  KEEP       {len(result['keep'])}")
    print(f"  UNRESOLVED {len(result['unresolved'])}")
    for name, current in result["unresolved"]:
        print(f"    {name[:44]:46} kept as {current}")
    total = sum(len(result[k]) for k in ("change", "keep", "unresolved"))
    print(f"\n  total      {total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry-run report)")
    args = parser.parse_args()

    import anthropic

    recipes = get_recipe_index(paths.recipes_dir(), include_ingredients=True)
    print(f"{len(recipes)} recipes")

    results = classify(recipes, anthropic.Anthropic())
    result = diff(recipes, results)
    _report(result)

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to write.")
        return 0

    written, skipped = apply_changes(result["change"])
    print(f"\nWrote {written} files (backups in .history/).")
    if skipped:
        print(f"Skipped {len(skipped)}: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ensure `scripts/` is importable as a package**

```bash
ls scripts/__init__.py || touch scripts/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_reclassify_dish_type.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/reclassify_dish_type.py scripts/__init__.py tests/test_reclassify_dish_type.py
git commit -m "$(cat <<'EOF'
feat: add the one-off dish_type reclassification script

Batch-classifies every recipe into the controlled vocabulary via a JSON-schema
enum, so an out-of-vocabulary answer is structurally impossible. Dry-run by
default; --apply backs each file up before writing.

Results are keyed by custom_id, never position — batch results arrive in
arbitrary order. Every recipe lands in exactly one of CHANGE / KEEP /
UNRESOLVED so nothing is silently dropped.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Run the repair against the real library

This task is operational, not code. It needs `ANTHROPIC_API_KEY` set and costs well under $1.

**Files:** none (mutates vault recipe frontmatter, backed up to `.history/`).

**Interfaces:**
- Consumes: `scripts/reclassify_dish_type.py` (Task 2).
- Produces: a vault where every `dish_type` is one of the 13 vocabulary values.

- [ ] **Step 1: Dry run**

```bash
.venv/bin/python scripts/reclassify_dish_type.py 2>&1 | tee /tmp/dish_type_dryrun.txt
```

Expected: a CHANGE / KEEP / UNRESOLVED report whose `total` equals the recipe count (239 at time of writing). Nothing written.

- [ ] **Step 2: Review the report with the user**

Show the CHANGE list. Confirm specifically that:
- `Butter Biscuits` moves off `dessert`
- `Ham Cheddar + Chive Protein Biscuits` moves off `biscuits`
- The 12 known strays (`Dinner`, `Tostada`, `Shakshuka`, `biscuits`, `mocktail`, `Breakfast Pastry`, `savory pie`, `smoothie mix`, `pasta alternative`, `Salad dressing`, `dessert or snack`) are all in CHANGE

**Do not proceed to Step 3 without the user's go-ahead** — this writes to the vault.

- [ ] **Step 3: Apply**

```bash
.venv/bin/python scripts/reclassify_dish_type.py --apply
```

- [ ] **Step 4: Verify every value is now in the vocabulary**

```bash
.venv/bin/python -c "
from lib import paths
from lib.normalizer import VALID_DISH_TYPES
from lib.recipe_index import get_recipe_index
idx = get_recipe_index(paths.recipes_dir(), include_ingredients=False)
bad = [(r['name'], r.get('dish_type')) for r in idx
       if r.get('dish_type') not in VALID_DISH_TYPES]
print('recipes:', len(idx), 'out-of-vocabulary:', len(bad))
for n, dt in bad: print('  ', n, '->', dt)
"
```

Expected: `out-of-vocabulary: 0`.

- [ ] **Step 5: Spot-check the biscuits**

```bash
.venv/bin/python -c "
from lib import paths
from lib.recipe_index import get_recipe_index
for r in get_recipe_index(paths.recipes_dir(), include_ingredients=False):
    if 'iscuit' in r['name']: print(f\"  {str(r.get('dish_type')):12} {r['name']}\")
"
```

Expected: no biscuit is `dessert`.

---

### Task 4: Chip groups in `lib/cook_now.py`

**Files:**
- Modify: `lib/cook_now.py` (add groups near the imports; add two keys to the dict built in `generate()` ~line 77)
- Test: `tests/test_cook_now.py`

**Interfaces:**
- Consumes: `normalizer.VALID_DISH_TYPES` (Task 1).
- Produces:
  - `cook_now.DISH_TYPE_GROUPS: dict[str, tuple[str, ...]]` — chip label → dish types.
  - `cook_now.group_for(dish_type: str | None) -> str` — chip label, defaulting to `"Mains"`.
  - `generate()` entries gain `"dish_type"` and `"group"` keys.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cook_now.py`:

```python
class TestChipGroups:
    def test_every_vocabulary_value_has_a_group(self):
        """A dish type with no chip would be unreachable in the UI."""
        from lib.normalizer import VALID_DISH_TYPES
        grouped = {dt for dts in cook_now.DISH_TYPE_GROUPS.values() for dt in dts}
        assert grouped == VALID_DISH_TYPES

    def test_no_dish_type_is_in_two_groups(self):
        seen, dupes = set(), []
        for dts in cook_now.DISH_TYPE_GROUPS.values():
            for dt in dts:
                if dt in seen:
                    dupes.append(dt)
                seen.add(dt)
        assert dupes == []

    def test_known_mappings(self):
        assert cook_now.group_for("dessert") == "Desserts"
        assert cook_now.group_for("main") == "Mains"
        assert cook_now.group_for("dip") == "Snacks"
        assert cook_now.group_for("bread") == "Sides"

    def test_unknown_and_missing_fall_back_to_mains(self):
        """A data gap must never hide a cookable recipe."""
        assert cook_now.group_for(None) == "Mains"
        assert cook_now.group_for("") == "Mains"
        assert cook_now.group_for("Tostada") == "Mains"

    def test_case_and_whitespace_insensitive(self):
        assert cook_now.group_for("  Dessert ") == "Desserts"


class TestGenerateCarriesGroup:
    def test_each_recipe_has_dish_type_and_group(self):
        items = [_item("Rice")]
        recipes = [{"name": "Plain Rice", "dish_type": "side",
                    "ingredient_items": ["rice", "salt", "olive oil"]}]
        result = cook_now.generate(items, recipes, today=TODAY)
        top = result["recipes"][0]
        assert top["dish_type"] == "side"
        assert top["group"] == "Sides"

    def test_note_rendering_is_unaffected_by_the_new_keys(self):
        """Cook Now.md must be byte-identical — the note is not part of this feature."""
        items = [_item("Rice")]
        recipes = [{"name": "Plain Rice", "dish_type": "side",
                    "ingredient_items": ["rice", "salt", "olive oil"]}]
        md = cook_now.render_markdown(cook_now.generate(items, recipes, today=TODAY))
        assert "Sides" not in md
        assert "dish_type" not in md
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_cook_now.py -v -k "ChipGroups or GenerateCarriesGroup"
```

Expected: FAIL — `AttributeError: module 'lib.cook_now' has no attribute 'DISH_TYPE_GROUPS'`.

- [ ] **Step 3: Add the groups**

In `lib/cook_now.py`, after the imports (after the `from lib.use_it_up import (...)` block, ~line 29), add:

```python
# The 13-value stored vocabulary collapsed into the 6 chips the page shows.
# Stored data stays precise; the interface stays usable. Adding a dish type to
# normalizer.VALID_DISH_TYPES without adding it here fails tests/test_cook_now.py.
DISH_TYPE_GROUPS = {
    "Mains": ("main", "sandwich", "soup"),
    "Breakfast": ("breakfast",),
    "Sides": ("side", "salad", "bread", "sauce"),
    "Snacks": ("snack", "appetizer", "dip"),
    "Desserts": ("dessert",),
    "Drinks": ("drink",),
}

# A recipe with a missing or unrecognized dish_type shows under Mains rather
# than vanishing: the filter must never make a cookable recipe unreachable
# because of a data gap.
DEFAULT_GROUP = "Mains"

_GROUP_FOR_DISH_TYPE = {
    dish_type: group
    for group, dish_types in DISH_TYPE_GROUPS.items()
    for dish_type in dish_types
}


def group_for(dish_type: Optional[str]) -> str:
    """The chip group a dish_type belongs to. Unknown values fall back to Mains."""
    return _GROUP_FOR_DISH_TYPE.get((dish_type or "").strip().lower(), DEFAULT_GROUP)
```

- [ ] **Step 4: Emit the keys from `generate()`**

In `lib/cook_now.py`, in the `recipes.append({...})` call inside `generate()` (~line 77), add two keys after `"image"`:

```python
        recipes.append({
            "recipe": recipe["name"],
            "image": recipe.get("image"),
            "dish_type": recipe.get("dish_type"),
            "group": group_for(recipe.get("dish_type")),
            "have": have,
            "total": total,
            "coverage": have / total,
            "missing": missing,
            "at_risk": at_risk,
        })
```

- [ ] **Step 5: Update the `generate()` docstring**

In `lib/cook_now.py`, in the `generate()` docstring, change the returned-entry line to:

```
    Returns ``{"recipes": [...]}``, each entry
    ``{recipe, image, dish_type, group, have, total, coverage, missing, at_risk}``,
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_cook_now.py -v
```

Expected: all pass, including the pre-existing tests.

- [ ] **Step 7: Commit**

```bash
git add lib/cook_now.py tests/test_cook_now.py
git commit -m "$(cat <<'EOF'
feat: map dish_type to Cook Now chip groups

Six chip groups over the 13 stored dish types. A missing or unrecognized value
falls back to Mains — the filter must never make a cookable recipe unreachable
because of a data gap.

Cook Now.md rendering is unchanged; render_markdown reads named fields, so the
two new keys don't reach the note.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `GET /api/cook-now`

**Files:**
- Modify: `api_server.py` (add beside `api_use_it_up`, ~line 2005)
- Test: `tests/test_api_cook_now.py`

**Interfaces:**
- Consumes: `cook_now.generate()` with `group` (Task 4).
- Produces: `GET /api/cook-now?limit=N` → `{"recipes": [{recipe, image, dish_type, group, have, total, coverage, missing, at_risk}]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_cook_now.py`:

```python
"""Contract for the Cook Now API used by the /cook-now page."""

import pytest

from api_server import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_returns_recipes_list(client, tmp_db, tmp_vault):
    resp = client.get("/api/cook-now")
    assert resp.status_code == 200
    assert "recipes" in resp.get_json()


def test_every_recipe_carries_a_group(client, tmp_db, tmp_vault):
    """The page filters on `group`; a recipe without one cannot be shown."""
    from lib import cook_now
    resp = client.get("/api/cook-now")
    for recipe in resp.get_json()["recipes"]:
        assert recipe["group"] in cook_now.DISH_TYPE_GROUPS


def test_limit_is_respected(client, tmp_db, tmp_vault):
    resp = client.get("/api/cook-now?limit=2")
    assert len(resp.get_json()["recipes"]) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_api_cook_now.py -v
```

Expected: FAIL — `assert 404 == 200`.

- [ ] **Step 3: Add the route**

In `api_server.py`, immediately after the `api_use_it_up` function (~line 2016), add:

```python
@app.route('/api/cook-now', methods=['GET'])
def api_cook_now():
    """Recipes ranked by how much of what they need is already on hand.

    Returns {recipes: [...]} — see lib/cook_now.generate. Each entry carries a
    `group` (the chip it belongs to); the page filters client-side from this one
    payload, so there is no per-chip round trip and no server-side filtering.
    """
    from lib import cook_now

    limit = request.args.get('limit', type=int) or 30
    return jsonify(cook_now.generate(limit=limit))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_api_cook_now.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_api_cook_now.py
git commit -m "$(cat <<'EOF'
feat: add GET /api/cook-now

Serves the coverage ranking with a chip group per recipe, so the page can
filter client-side from a single payload.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The `/cook-now` page

**Files:**
- Create: `templates/cook_now.html`
- Modify: `api_server.py` (route beside `review_page`, ~line 2740)
- Modify: `lib/web_dashboard.py` (`SECTIONS`, "Plan & cook" block, ~line 52)

**Interfaces:**
- Consumes: `GET /api/cook-now` (Task 5); `cook_now.DISH_TYPE_GROUPS` (Task 4).
- Produces: browsable page at `/cook-now`.

- [ ] **Step 1: Write the failing test**

The registration test already exists (`tests/test_web_dashboard.py::test_every_browsable_route_is_registered_or_exempt`). Confirm it fails once the route exists but isn't registered — this is the guard rail, so watch it work.

Add to `tests/test_api_cook_now.py`:

```python
def test_page_renders(client, tmp_db, tmp_vault):
    resp = client.get("/cook-now")
    assert resp.status_code == 200
    assert b"cook-now-chips" in resp.data


def test_page_is_registered_in_sections():
    """CLAUDE.md invariant: a browsable page must be in the SECTIONS registry."""
    from lib import web_dashboard as wd
    paths = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
    assert "/cook-now" in paths
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_api_cook_now.py -v -k "page"
```

Expected: FAIL — 404 for the page, and `/cook-now` not in `SECTIONS`.

- [ ] **Step 3: Create the template**

Create `templates/cook_now.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cook Now — KitchenOS</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; padding: 1rem; max-width: 900px; margin-inline: auto; }
  h1 { font-size: 1.4rem; margin: 0 0 .75rem; }
  #cook-now-chips { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .5rem; }
  .chip { border: 1px solid currentColor; border-radius: 999px; padding: .35rem .8rem;
          font-size: .9rem; cursor: pointer; background: none; color: inherit;
          opacity: .45; }
  .chip[aria-pressed="true"] { opacity: 1; font-weight: 600; }
  #hidden-note { font-size: .85rem; opacity: .7; margin: 0 0 1rem; }
  .recipe { padding: .6rem 0; border-bottom: 1px solid rgba(128,128,128,.25); }
  .recipe-head { display: flex; justify-content: space-between; gap: 1rem; }
  .name { font-weight: 600; }
  .cov { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .missing { font-size: .85rem; opacity: .75; margin-top: .2rem; }
  .group-tag { font-size: .75rem; opacity: .6; margin-left: .4rem; }
</style>
</head>
<body>
<h1>🥘 Cook Now</h1>

<div id="cook-now-chips"></div>
<p id="hidden-note"></p>
<div id="list">Loading…</div>

<script>
const GROUPS = ["Mains", "Breakfast", "Sides", "Snacks", "Desserts", "Drinks"];
const STORAGE_KEY = "kitchenos.cooknow.groups";

// Desserts starts off: the whole point of the filter is reviewing what to cook
// for a meal. The chip stays visible in its off state so nothing is hidden
// mysteriously.
const DEFAULT_ON = GROUPS.filter(g => g !== "Desserts");

let selected = loadSelection();
let recipes = [];

function loadSelection() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set(DEFAULT_ON);
    const parsed = JSON.parse(raw);
    // Ignore stale group names from an older build rather than showing nothing.
    const valid = parsed.filter(g => GROUPS.includes(g));
    return new Set(valid.length ? valid : DEFAULT_ON);
  } catch (e) {
    return new Set(DEFAULT_ON);
  }
}

function saveSelection() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...selected]));
  } catch (e) { /* private mode — filtering still works for this session */ }
}

function renderChips() {
  const box = document.getElementById("cook-now-chips");
  box.innerHTML = "";
  for (const group of GROUPS) {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.textContent = group;
    btn.setAttribute("aria-pressed", selected.has(group) ? "true" : "false");
    btn.addEventListener("click", () => {
      if (selected.has(group)) selected.delete(group); else selected.add(group);
      saveSelection();
      renderChips();
      renderList();
    });
    box.appendChild(btn);
  }
}

function renderList() {
  const shown = recipes.filter(r => selected.has(r.group));
  const hidden = recipes.length - shown.length;
  document.getElementById("hidden-note").textContent =
    hidden ? `${hidden} recipe${hidden === 1 ? "" : "s"} hidden by the filter` : "";

  const list = document.getElementById("list");
  if (!shown.length) {
    list.textContent = recipes.length
      ? "Nothing matches the selected chips."
      : "No recipes with ingredients in your library yet.";
    return;
  }
  list.innerHTML = "";
  for (const r of shown) {
    const pct = Math.round(r.coverage * 100);
    const div = document.createElement("div");
    div.className = "recipe";
    div.dataset.group = r.group;

    const head = document.createElement("div");
    head.className = "recipe-head";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = r.recipe;
    const tag = document.createElement("span");
    tag.className = "group-tag";
    tag.textContent = r.group + (r.at_risk ? " ⏳" : "");
    name.appendChild(tag);
    const cov = document.createElement("span");
    cov.className = "cov";
    cov.textContent = `${pct}% (${r.have}/${r.total})`;
    head.append(name, cov);
    div.appendChild(head);

    if (r.missing && r.missing.length) {
      const miss = document.createElement("div");
      miss.className = "missing";
      miss.textContent = "missing: " + r.missing.join(", ");
      div.appendChild(miss);
    }
    list.appendChild(div);
  }
}

async function load() {
  try {
    const resp = await fetch("/api/cook-now?limit=60");
    const data = await resp.json();
    recipes = data.recipes || [];
  } catch (e) {
    document.getElementById("list").textContent = "Could not load Cook Now.";
    return;
  }
  renderChips();
  renderList();
}

load();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the page route**

In `api_server.py`, immediately after the `review_page` function (~line 2740), add:

```python
@app.route('/cook-now')
def cook_now_page():
    """What you could cook right now, filterable by meal type."""
    return _serve_page_with_claude_bar('cook_now.html')
```

- [ ] **Step 5: Register in `SECTIONS`**

In `lib/web_dashboard.py`, in the `"Plan & cook"` block, add after the Meal Planner entry:

```python
            ("🥘", "Cook Now", "/cook-now",
             "what you could cook right now, ranked by how much you already "
             "have; filter by meal type to drop desserts"),
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_api_cook_now.py tests/test_web_dashboard.py -v
```

Expected: all pass.

- [ ] **Step 7: Propagate the registry (CLAUDE.md invariant)**

```bash
.venv/bin/python scripts/generate_web_dashboard.py
.venv/bin/python scripts/sync_safari_bookmarks.py --apply
```

The Safari sync quits and relaunches Safari — pre-authorized; it no-ops if Safari isn't running.

- [ ] **Step 8: Restart the API LaunchAgent and check the page live**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/cook-now
curl -s "http://localhost:5001/api/cook-now?limit=3" | head -c 400
```

Expected: `200`, and JSON whose recipes each carry a `group`.

- [ ] **Step 9: Commit**

```bash
git add templates/cook_now.html api_server.py lib/web_dashboard.py tests/test_api_cook_now.py
git commit -m "$(cat <<'EOF'
feat: add the /cook-now page with meal-type chips

Six chips filter a single payload client-side, so toggling is instant.
Desserts starts deselected — the point of the filter — with the chip left
visible in its off state and a count of what's hidden, so nothing disappears
without saying so. Selection persists in localStorage.

Registered in SECTIONS and propagated to the vault launcher note and Safari
bookmarks per the CLAUDE.md invariant.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Browser test for the chips

**Files:**
- Create: `tests/e2e/test_cook_now_filter.py`

**Interfaces:**
- Consumes: the `/cook-now` page (Task 6). Uses the existing `live_server`, `page`, `page_errors` fixtures from `tests/e2e/`.

- [ ] **Step 1: Confirm the e2e fixture names**

```bash
grep -n "def live_server\|def page_errors\|def page" tests/e2e/conftest.py
```

Use whatever names this prints; the test below assumes `live_server`, `page`, `page_errors`, matching `tests/e2e/test_weekly_loop.py`.

- [ ] **Step 2: Write the failing test**

Create `tests/e2e/test_cook_now_filter.py`:

```python
"""The Cook Now meal-type chips, driven in a real browser.

The value of this test is the default: desserts must be hidden on first load
without the user doing anything. That is the entire reason the filter exists.
"""


def test_desserts_hidden_on_first_load(live_server, page, page_errors):
    page.goto(f"{live_server}/cook-now")
    page.wait_for_selector(".chip")

    desserts = page.locator(".chip", has_text="Desserts")
    assert desserts.get_attribute("aria-pressed") == "false"
    assert page.locator('.recipe[data-group="Desserts"]').count() == 0
    assert page_errors == []


def test_toggling_desserts_reveals_them_without_refetching(live_server, page, page_errors):
    """Filtering is client-side: a chip toggle must not hit the API again."""
    calls = []
    page.route("**/api/cook-now*", lambda route: (calls.append(1), route.continue_())[-1])

    page.goto(f"{live_server}/cook-now")
    page.wait_for_selector(".chip")
    after_load = len(calls)

    before = page.locator(".recipe").count()
    page.locator(".chip", has_text="Desserts").click()

    assert page.locator(".chip", has_text="Desserts").get_attribute("aria-pressed") == "true"
    assert page.locator(".recipe").count() >= before
    assert len(calls) == after_load, "chip toggle refetched the API"
    assert page_errors == []


def test_selection_survives_reload(live_server, page, page_errors):
    page.goto(f"{live_server}/cook-now")
    page.wait_for_selector(".chip")
    page.locator(".chip", has_text="Desserts").click()

    page.reload()
    page.wait_for_selector(".chip")

    assert page.locator(".chip", has_text="Desserts").get_attribute("aria-pressed") == "true"
    assert page_errors == []
```

- [ ] **Step 3: Run the test**

```bash
.venv/bin/python -m pytest tests/e2e/test_cook_now_filter.py -v
```

Expected: 3 passed. If the vault under test has no dessert recipes with ingredients, `test_toggling_desserts_reveals_them` is trivially true — that is acceptable; the first test is the load-bearing one.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_cook_now_filter.py
git commit -m "$(cat <<'EOF'
test: drive the Cook Now chips in a browser

Pins the default that matters: desserts hidden on first load, no click needed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/API.md` (new endpoint), `docs/OPERATIONS.md` (new command), `CLAUDE.md` (new invariant), `docs/plans/INDEX.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Document the endpoint in `docs/API.md`**

Find the section listing `/api/use-it-up` and add alongside it:

```markdown
### `GET /api/cook-now`

Recipes ranked by ingredient coverage against current inventory.

**Query:** `limit` (int, default 30)

**Returns:** `{"recipes": [{recipe, image, dish_type, group, have, total, coverage, missing, at_risk}]}`

`group` is the meal-type chip the recipe belongs to — one of `Mains`, `Breakfast`,
`Sides`, `Snacks`, `Desserts`, `Drinks`. Filtering happens client-side on the
`/cook-now` page; this endpoint never filters.
```

- [ ] **Step 2: Document the script in `docs/OPERATIONS.md`**

Add to the maintenance/scripts section:

```markdown
### Reclassify recipe dish types (one-off repair)

```bash
.venv/bin/python scripts/reclassify_dish_type.py            # dry-run report
.venv/bin/python scripts/reclassify_dish_type.py --apply    # write changes
```

Batch-classifies every recipe into `normalizer.VALID_DISH_TYPES` via the Claude
Batches API. Dry-run by default. `--apply` backs each file up into `.history/`
before writing. Needs `ANTHROPIC_API_KEY`; costs well under $1 for ~240 recipes.
```

- [ ] **Step 3: Add the invariant to `CLAUDE.md`**

Add to the Invariants list:

```markdown
- **`dish_type` is a closed vocabulary.** `normalizer.VALID_DISH_TYPES` is derived from `DISH_TYPE_MAP`'s targets, and every value must map to a chip group in `lib/cook_now.py` `DISH_TYPE_GROUPS` — a dish type with no group is unreachable in the `/cook-now` filter, and `tests/test_cook_now.py` fails if one appears. Don't add a `DISH_TYPE_MAP` variant pointing at a brand-new target without adding that target to a chip group. Note that mapping a *savory* item to `dessert` (as `"biscuit"` once did) silently hides it from meal-type filtering.
```

- [ ] **Step 4: Update `docs/plans/INDEX.md`**

Add this row under the `## In Progress` section (the table is `| Date | Doc | Notes |`, and
links are relative to `docs/plans/`):

```markdown
| 2026-07-25 | [cook-now-meal-type-filter](../superpowers/specs/2026-07-25-cook-now-meal-type-filter-design.md) | Filter Cook Now by meal type. Repairs the `dish_type` vocabulary (one-off Claude Batches pass + drops the `biscuit → dessert` rule), then adds `/cook-now` with six chip groups. Branch `cook-now-meal-type-filter`. |
```

Move the row to `## Done` during the closure ritual, not now.

- [ ] **Step 5: Run the full test suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: all pass. **Report the actual output.** If anything fails, fix it before committing — do not claim green without the run.

- [ ] **Step 6: Commit**

```bash
git add docs/API.md docs/OPERATIONS.md CLAUDE.md docs/plans/INDEX.md
git commit -m "$(cat <<'EOF'
docs: record the cook-now endpoint, repair script, and dish_type invariant

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Completion

Update `BRANCH-STATUS.md` — check off the dev / testing / docs stages, then use
`superpowers:requesting-code-review` before the review stage and
`superpowers:finishing-a-development-branch` to merge.
