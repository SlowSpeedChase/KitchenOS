# Shopping List Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generated weekly shopping list clean — consolidated names, kitchen-inventory subtracted by default, quantities rounded up to how you actually buy them, grouped by store category.

**Architecture:** Two new deterministic modules (`lib/ingredient_normalizer.py` for name/amount hygiene, `lib/grocery_catalog.py` for category + shoppable-package rounding, both config-driven) slot into the existing generation pipeline in `lib/shopping_list_generator.py`. Inventory subtraction (already implemented in `lib/pantry.py`) becomes the default. The template renders category sections instead of one flat list. Recipes are never modified.

**Tech Stack:** Python 3.11, pytest, hand-editable JSON configs (`config/*.json`), no new dependencies, no LLM.

## Global Constraints

- **Python 3.11** — run everything via `.venv/bin/python`.
- **No new pip dependencies.** Deterministic code only — no LLM calls in this feature.
- **Vault paths** always via `lib/paths.py` helpers; never hardcode.
- **DB is the single source of truth** for inventory; read it only through `lib.inventory` / `lib.pantry`. Do not reintroduce a JSON/markdown inventory source.
- **Config files** are hand-editable JSON written atomically (tmp + `os.replace`), matching `config/storage_locations.json` / `config/item_aliases.json` conventions.
- **Tests** use the `tmp_db` fixture / `KITCHENOS_DB` + `KITCHENOS_VAULT` env overrides (see `tests/conftest.py`); never touch the real DB or vault.
- **Branch:** all work happens on a new branch `shopping-list-cleanup` cut from a clean `main`. Do not commit to `main` or `docs-reorg`.
- **Unit-family helpers**: use `lib.ingredient_aggregator.get_unit_family` / `convert_to_base_unit` / `convert_from_base_unit` (families `volume`/`weight`/`count`/`other`) throughout this feature — NOT `lib.units.get_unit_family` (which names the family `mass`). Consistency with the pantry split depends on this.

---

### Task 1: Branch setup

**Files:** none (VCS only)

- [ ] **Step 1: Create the branch from clean main**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git fetch origin
git checkout main
git pull --ff-only
git checkout -b shopping-list-cleanup
```

Expected: on branch `shopping-list-cleanup`, working tree clean.

---

### Task 2: Ingredient name & amount normalizer

Deterministic cleanup of a recipe ingredient's `item` string (strip descriptors, apply a synonym map) and detection of junk amounts (`to taste`). This is what makes `red onion, thinly sliced` and `1 of a large red onion` collapse to one line, and kills `2 to tastes salt`.

**Files:**
- Create: `lib/ingredient_normalizer.py`
- Create: `config/shopping_aliases.json`
- Test: `tests/test_ingredient_normalizer.py`

**Interfaces:**
- Produces:
  - `normalize_name(raw: str) -> str` — canonical lowercased item name (grouping key).
  - `is_noise_unit(unit: str) -> bool` — True for units like `to tastes`, `tastes`, `taste`, `to`, `pinch`, `dash` that should be treated as "no quantity".
  - `load_aliases() -> dict[str, str]` — raw→canonical synonym map from `config/shopping_aliases.json`.

- [ ] **Step 1: Create the alias config**

Create `config/shopping_aliases.json`:

```json
{
  "mayo": "mayonnaise",
  "limes juice of": "lime juice",
  "limes": "lime",
  "scallions": "green onion",
  "green onions": "green onion",
  "cilantro leaves": "cilantro",
  "roma tomatoes": "tomato",
  "cherry tomatoes": "cherry tomato"
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ingredient_normalizer.py`:

```python
from lib.ingredient_normalizer import normalize_name, is_noise_unit


def test_strips_parentheticals_and_prep():
    assert normalize_name("red onion, thinly sliced") == "red onion"
    assert normalize_name("0.25 head of iceberg lettuce (about 2-3 cups)") == "head of iceberg lettuce"
    assert normalize_name("basil leaves, slivered (8g)") == "basil leaves"


def test_strips_noise_tokens():
    assert normalize_name("boiled potatoes *(inferred)*") == "boiled potatoes"
    assert normalize_name("paprika (optional)") == "paprika"
    assert normalize_name("white vinegar (not shown)") == "white vinegar"
    assert normalize_name("optional: rosemary") == "rosemary"


def test_strips_leading_article_and_size():
    assert normalize_name("1 of a large red onion, (thinly sliced)") == "red onion"


def test_alias_map_merges_synonyms():
    assert normalize_name("mayo") == "mayonnaise"
    assert normalize_name("limes juice of") == "lime juice"


def test_variants_share_a_grouping_key():
    keys = {
        normalize_name("red onion, thinly sliced"),
        normalize_name("0.5 small red onion, (very thinly sliced)"),
        normalize_name("2 whole red onion"),
    }
    assert keys == {"red onion"}


def test_noise_units():
    assert is_noise_unit("to tastes") is True
    assert is_noise_unit("taste") is True
    assert is_noise_unit("pinch") is True
    assert is_noise_unit("cup") is False
    assert is_noise_unit("") is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_normalizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.ingredient_normalizer'`.

- [ ] **Step 4: Implement the normalizer**

Create `lib/ingredient_normalizer.py`:

```python
"""Deterministic cleanup of recipe ingredient item names for shopping lists.

Strips descriptor noise (parentheticals, prep clauses, "(inferred)", "to taste",
etc.) and applies a hand-editable synonym map so that descriptor variants of the
same ingredient collapse to one canonical grouping key. No LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from functools import lru_cache

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "shopping_aliases.json"

# Units that mean "an unmeasured amount" — treated as no quantity, never summed.
_NOISE_UNITS = {
    "to tastes", "to taste", "tastes", "taste", "to",
    "pinch", "pinches", "dash", "dashes", "splash", "as needed", "some",
}

# Leading qualifiers to drop when they precede the real noun.
_LEADING = re.compile(
    r"^(?:\d+(?:\.\d+)?\s+)?(?:of\s+)?(?:a\s+|an\s+)?"
    r"(?:large|small|medium|medium-large|whole|of a large|of a small)?\s*",
    re.IGNORECASE,
)
_NOISE_TOKENS = re.compile(
    r"\*+|\(inferred\)|\(optional\)|\(not shown\)|optional:?", re.IGNORECASE
)


@lru_cache(maxsize=1)
def load_aliases() -> dict:
    if not _CONFIG.exists():
        return {}
    try:
        return {k.lower().strip(): v for k, v in json.loads(_CONFIG.read_text()).items()}
    except (json.JSONDecodeError, OSError):
        return {}


def is_noise_unit(unit: str) -> bool:
    return bool(unit) and unit.lower().strip() in _NOISE_UNITS


def normalize_name(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # Drop parentheticals and their contents.
    s = re.sub(r"\([^)]*\)", "", s)
    # Drop explicit noise tokens (*, (inferred), optional:, ...).
    s = _NOISE_TOKENS.sub("", s)
    # Keep only the part before the first comma (prep clause: ", thinly sliced").
    s = s.split(",")[0]
    # Drop "to taste" / "as needed" trailing phrases.
    s = re.sub(r"\b(to taste|as needed)\b", "", s, flags=re.IGNORECASE)
    # Strip a leading count/size qualifier ("1 of a large ...").
    s = _LEADING.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower().strip(" .-")
    # Alias map wins over the stripped form.
    return load_aliases().get(s, s)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingredient_normalizer.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add lib/ingredient_normalizer.py config/shopping_aliases.json tests/test_ingredient_normalizer.py
git commit -m "feat(shopping): deterministic ingredient name normalizer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Grocery catalog — category + shoppable quantity

Config-driven category assignment and package round-up. Turns `mayonnaise 1.5 cup` into `1 jar (30 oz)` and `potatoes 4.4 lb` into `5 lb`; unknown items fall back to native-unit round-up and category `other`.

**Files:**
- Create: `lib/grocery_catalog.py`
- Create: `config/grocery_items.json`
- Test: `tests/test_grocery_catalog.py`

**Interfaces:**
- Consumes: `lib.ingredient_aggregator.{parse_amount_to_float, get_unit_family, convert_to_base_unit, convert_from_base_unit}`.
- Produces:
  - `assign_category(item: str) -> str` — one of inventory's `CATEGORIES`, else `"other"`.
  - `shoppable_quantity(item: str, amount, unit: str) -> dict` — `{"amount": str, "unit": str}`; `amount == ""` means "no quantity" (unmeasured).

- [ ] **Step 1: Create the grocery config (seed ~30–40 common items)**

Create `config/grocery_items.json`:

```json
{
  "by_item": {
    "mayonnaise": {"category": "pantry", "buy_unit": "jar", "package": {"qty": 3.5, "unit": "cup"}, "label": "30 oz"},
    "potatoes": {"category": "produce", "buy_unit": "lb"},
    "russet potatoes": {"category": "produce", "buy_unit": "lb"},
    "yukon gold potatoes": {"category": "produce", "buy_unit": "lb"},
    "eggs": {"category": "dairy", "buy_unit": "dozen", "package": {"qty": 12, "unit": "ct"}, "label": "12 ct"},
    "milk": {"category": "dairy", "buy_unit": "gal"},
    "heavy cream": {"category": "dairy", "buy_unit": "pint"},
    "sour cream": {"category": "dairy", "buy_unit": "tub"},
    "cheddar cheese": {"category": "dairy", "buy_unit": "bag", "package": {"qty": 2, "unit": "cup"}, "label": "8 oz"},
    "shredded cheddar cheese": {"category": "dairy", "buy_unit": "bag", "package": {"qty": 2, "unit": "cup"}, "label": "8 oz"},
    "parmesan": {"category": "dairy", "buy_unit": "wedge"},
    "feta cheese": {"category": "dairy", "buy_unit": "block"},
    "cotija cheese": {"category": "dairy", "buy_unit": "package"},
    "butter": {"category": "dairy", "buy_unit": "lb"},
    "onion": {"category": "produce", "buy_unit": "each"},
    "red onion": {"category": "produce", "buy_unit": "each"},
    "green onion": {"category": "produce", "buy_unit": "bunch"},
    "garlic": {"category": "produce", "buy_unit": "head"},
    "carrots": {"category": "produce", "buy_unit": "lb"},
    "celery": {"category": "produce", "buy_unit": "bunch"},
    "cabbage": {"category": "produce", "buy_unit": "each"},
    "zucchini": {"category": "produce", "buy_unit": "each"},
    "cucumber": {"category": "produce", "buy_unit": "each"},
    "lime": {"category": "produce", "buy_unit": "each"},
    "lime juice": {"category": "produce", "buy_unit": "each"},
    "avocado": {"category": "produce", "buy_unit": "each"},
    "tomato": {"category": "produce", "buy_unit": "each"},
    "cilantro": {"category": "produce", "buy_unit": "bunch"},
    "parsley": {"category": "produce", "buy_unit": "bunch"},
    "chicken thighs": {"category": "meat", "buy_unit": "lb"},
    "chicken breast": {"category": "meat", "buy_unit": "lb"},
    "bone-in chicken breast": {"category": "meat", "buy_unit": "lb"},
    "ground beef": {"category": "meat", "buy_unit": "lb"},
    "beef chuck": {"category": "meat", "buy_unit": "lb"},
    "ground lamb": {"category": "meat", "buy_unit": "lb"},
    "deli ham": {"category": "meat", "buy_unit": "lb"},
    "mushrooms": {"category": "produce", "buy_unit": "package"},
    "frozen peas": {"category": "frozen", "buy_unit": "bag"},
    "hawaiian sweet rolls": {"category": "bakery", "buy_unit": "pack"},
    "sourdough": {"category": "bakery", "buy_unit": "loaf"}
  },
  "by_category": {
    "produce": {"buy_unit": "each"},
    "meat": {"buy_unit": "lb"},
    "seafood": {"buy_unit": "lb"},
    "dairy": {"buy_unit": "each"},
    "bakery": {"buy_unit": "each"},
    "pantry": {"buy_unit": "each"},
    "frozen": {"buy_unit": "bag"},
    "beverages": {"buy_unit": "each"},
    "household": {"buy_unit": "each"},
    "other": {"buy_unit": "each"}
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_grocery_catalog.py`:

```python
from lib.grocery_catalog import assign_category, shoppable_quantity


def test_assign_category_by_item():
    assert assign_category("mayonnaise") == "pantry"
    assert assign_category("chicken thighs") == "meat"
    assert assign_category("red onion") == "produce"


def test_assign_category_word_subset():
    # "boneless skinless chicken thighs" should still hit "chicken thighs"
    assert assign_category("boneless skinless chicken thighs") == "meat"


def test_assign_category_unknown_is_other():
    assert assign_category("dragonfruit foam") == "other"


def test_package_round_up_volume():
    # 1.5 cups mayo, 3.5-cup jar -> 1 jar
    assert shoppable_quantity("mayonnaise", "1.5", "cup") == {"amount": "1", "unit": "jar (30 oz)"}


def test_package_round_up_needs_two():
    # 8 cups mayo -> ceil(8/3.5) = 3 jars
    assert shoppable_quantity("mayonnaise", "8", "cup") == {"amount": "3", "unit": "jars (30 oz)"}


def test_buy_unit_weight_round_up():
    # 4.4 lb potatoes, no package -> 5 lb
    assert shoppable_quantity("potatoes", "4.4", "lb") == {"amount": "5", "unit": "lb"}


def test_count_package_dozen():
    assert shoppable_quantity("eggs", "1", "ct") == {"amount": "1", "unit": "dozen (12 ct)"}


def test_unknown_item_native_round_up():
    assert shoppable_quantity("dragonfruit foam", "1.2", "cup") == {"amount": "2", "unit": "cup"}


def test_no_amount_returns_blank():
    assert shoppable_quantity("salt", None, "to taste") == {"amount": "", "unit": ""}
    assert shoppable_quantity("salt", "", "") == {"amount": "", "unit": ""}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_grocery_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.grocery_catalog'`.

- [ ] **Step 4: Implement the catalog**

Create `lib/grocery_catalog.py`:

```python
"""Category + shoppable-quantity lookup for shopping lists.

Reads config/grocery_items.json (by_item overrides -> by_category defaults) to
answer two questions per ingredient:
  * what store category is it? (for grouping)
  * how do you buy it, and how many packages does the needed amount round up to?

Deterministic, hand-correctable. No LLM.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from functools import lru_cache
from typing import Optional

from lib.ingredient_aggregator import (
    parse_amount_to_float,
    get_unit_family,
    convert_to_base_unit,
    convert_from_base_unit,
)

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "grocery_items.json"

_PLURAL = {"loaf": "loaves"}


@lru_cache(maxsize=1)
def _load() -> dict:
    if not _CONFIG.exists():
        return {"by_item": {}, "by_category": {}}
    try:
        data = json.loads(_CONFIG.read_text())
    except (json.JSONDecodeError, OSError):
        return {"by_item": {}, "by_category": {}}
    data.setdefault("by_item", {})
    data.setdefault("by_category", {})
    return data


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _match_by_item(item: str) -> Optional[dict]:
    """Exact match, then word-subset (like storage_locations)."""
    by_item = _load()["by_item"]
    key = _norm(item)
    if not key:
        return None
    if key in by_item:
        return by_item[key]
    tokens = set(key.split())
    for cand, entry in by_item.items():
        cand_tokens = set(cand.split())
        if cand_tokens and cand_tokens <= tokens:
            return entry
    return None


def assign_category(item: str) -> str:
    entry = _match_by_item(item)
    if entry and entry.get("category"):
        return entry["category"]
    return "other"


def _buy_unit(entry: Optional[dict], category: str) -> Optional[str]:
    if entry and entry.get("buy_unit"):
        return entry["buy_unit"]
    return _load()["by_category"].get(category, {}).get("buy_unit")


def _pluralize(unit: str, n: int) -> str:
    if n <= 1 or not unit:
        return unit
    if unit in _PLURAL:
        return _PLURAL[unit]
    return unit if unit.endswith("s") else unit + "s"


def _labeled(buy_unit: str, label: Optional[str], n: int) -> str:
    u = _pluralize(buy_unit, n)
    return f"{u} ({label})" if label else u


def shoppable_quantity(item: str, amount, unit: str) -> dict:
    """Round a needed (amount, unit) up to how the item is purchased.

    Returns {"amount": str, "unit": str}. amount == "" means unmeasured
    (e.g. "to taste") — the line should show the item with no quantity.
    """
    amt = parse_amount_to_float(amount)
    if amt is None or amt <= 0:
        return {"amount": "", "unit": ""}

    entry = _match_by_item(item)
    category = entry["category"] if (entry and entry.get("category")) else "other"
    buy_unit = _buy_unit(entry, category)
    package = entry.get("package") if entry else None
    label = entry.get("label") if entry else None

    if package and buy_unit:
        pkg_qty = parse_amount_to_float(package.get("qty"))
        pkg_unit = package.get("unit", "")
        if pkg_qty and pkg_qty > 0:
            need_fam = get_unit_family(unit)
            pkg_fam = get_unit_family(pkg_unit)
            if need_fam == pkg_fam and need_fam in ("volume", "weight"):
                need_base = convert_to_base_unit(amt, unit, need_fam)
                pkg_base = convert_to_base_unit(pkg_qty, pkg_unit, pkg_fam)
                n = math.ceil(need_base / pkg_base) if pkg_base > 0 else 1
            elif need_fam == pkg_fam:  # count / other, same family
                n = math.ceil(amt / pkg_qty)
            else:
                n = 1  # can't convert across families -> assume one package covers
            return {"amount": str(n), "unit": _labeled(buy_unit, label, n)}

    if buy_unit:
        need_fam = get_unit_family(unit)
        bu_fam = get_unit_family(buy_unit)
        if need_fam == bu_fam and need_fam in ("volume", "weight"):
            base = convert_to_base_unit(amt, unit, need_fam)
            n_units = convert_from_base_unit(base, buy_unit, bu_fam)
            n = math.ceil(n_units)
        else:
            n = math.ceil(amt)
        return {"amount": str(n), "unit": _pluralize(buy_unit, n)}

    # No config entry at all: round up in the native unit.
    return {"amount": str(math.ceil(amt)), "unit": unit}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_grocery_catalog.py -v`
Expected: PASS (9 passed). If `test_buy_unit_weight_round_up` fails because `convert_from_base_unit` returns a hair over 4.0 for 4.4 lb, that's expected math (4.4 → ceil = 5); if it fails at a different value, inspect the `WEIGHT_UNITS` ratio for `lb` in `lib/ingredient_aggregator.py`.

- [ ] **Step 6: Commit**

```bash
git add lib/grocery_catalog.py config/grocery_items.json tests/test_grocery_catalog.py
git commit -m "feat(shopping): grocery catalog for category + shoppable quantities

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Group aggregation on normalized names

Route the aggregator's grouping key through `normalize_name` so descriptor variants consolidate, and store the canonical name on the combined item so downstream category/package lookups work.

**Files:**
- Modify: `lib/ingredient_aggregator.py` (`normalize_item_name`, and the combined-item name)
- Test: `tests/test_ingredient_aggregator.py` (add cases; create the file if it does not exist)

**Interfaces:**
- Consumes: `lib.ingredient_normalizer.normalize_name`.
- Produces: `aggregate_ingredients` now groups by normalized name; each result dict's `item` is the normalized canonical name.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingredient_aggregator.py` (create it with this import header if absent):

```python
from lib.ingredient_aggregator import aggregate_ingredients


def test_descriptor_variants_consolidate_to_one_line():
    ings = [
        {"amount": "0.25", "unit": "cup", "item": "red onion, thinly sliced"},
        {"amount": "0.5", "unit": "small", "item": "small red onion, (very thinly sliced)"},
        {"amount": "2", "unit": "whole", "item": "2 whole red onion"},
    ]
    out = aggregate_ingredients(ings)
    names = [o["item"] for o in out]
    assert names == ["red onion"]


def test_mayo_alias_merges_before_summing():
    ings = [
        {"amount": "1.29", "unit": "cup", "item": "mayo"},
        {"amount": "0.25", "unit": "cup", "item": "mayonnaise"},
    ]
    out = aggregate_ingredients(ings)
    assert len(out) == 1
    assert out[0]["item"] == "mayonnaise"
    assert out[0]["unit"] == "cup"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingredient_aggregator.py -v`
Expected: FAIL — names come back as the raw strings (`red onion, thinly sliced`, etc.), not consolidated.

- [ ] **Step 3: Implement — normalize the grouping key and stored name**

In `lib/ingredient_aggregator.py`, add the import near the top (after the existing imports):

```python
from lib.ingredient_normalizer import normalize_name
```

Replace `normalize_item_name` (currently lowercase+strip only):

```python
def normalize_item_name(item: str) -> str:
    """Normalize item name for grouping (strips descriptors + applies aliases)."""
    return normalize_name(item)
```

Then in `aggregate_ingredients`, ensure the combined item carries the normalized name. After the line `combined = combine_ingredient_group(items)` and before `results.extend(combined)`, set each combined item's name to the group key:

```python
    for key, items in groups.items():
        combined = combine_ingredient_group(items)
        for c in combined:
            c["item"] = key  # canonical normalized name
        results.extend(combined)
```

(`key` is already `normalize_item_name(item)`.)

- [ ] **Step 4: Run the full aggregator + normalizer suite**

Run: `.venv/bin/python -m pytest tests/test_ingredient_aggregator.py tests/test_ingredient_normalizer.py -v`
Expected: PASS. If any pre-existing aggregator test asserted a raw descriptor name, update that assertion to the normalized name (the new behavior is intended).

- [ ] **Step 5: Commit**

```bash
git add lib/ingredient_aggregator.py tests/test_ingredient_aggregator.py
git commit -m "feat(shopping): consolidate ingredients on normalized names

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Inventory subtraction default-on + shoppable records in the generator

Make `generate_shopping_list` load DB inventory by default, and attach per-line category + shoppable-quantity display so the template can group and render. Preserve the legacy `items: list[str]` contract.

**Files:**
- Modify: `lib/shopping_list_generator.py` (`generate_shopping_list`, `generate_shopping_list_from_path`, `compute_lines`)
- Test: `tests/test_shopping_list_generator.py` (add cases; create if absent)

**Interfaces:**
- Consumes: `lib.pantry.load_pantry`, `lib.grocery_catalog.{assign_category, shoppable_quantity}`, `lib.ingredient_normalizer.is_noise_unit`.
- Produces: result dict gains `records: list[dict]` where each record is `{"item": str, "category": str, "display": str}`. `items` stays a sorted `list[str]` of the same `display` strings. A module sentinel `_AUTO` distinguishes "auto-load inventory" (default) from explicit `None` (no subtraction).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_shopping_list_generator.py`:

```python
from lib.shopping_list_generator import build_records, format_shopping_line


def test_format_shopping_line_with_qty():
    rec = {"item": "mayonnaise", "amount": "1", "unit": "jar (30 oz)"}
    assert format_shopping_line(rec) == "mayonnaise — 1 jar (30 oz)"


def test_format_shopping_line_no_qty():
    rec = {"item": "salt", "amount": "", "unit": ""}
    assert format_shopping_line(rec) == "salt"


def test_build_records_assigns_category_and_shoppable():
    # aggregated + already inventory-subtracted lines (to_buy amounts)
    lines = [
        {"item": "mayonnaise", "to_buy": {"amount": "1.5", "unit": "cup"}, "warning": None},
        {"item": "chicken thighs", "to_buy": {"amount": "4", "unit": "lb"}, "warning": None},
        {"item": "salt", "to_buy": {"amount": "15.25", "unit": "to tastes"}, "warning": None},
        {"item": "red onion", "to_buy": None, "warning": None},  # fully covered by pantry -> dropped
    ]
    records = build_records(lines)
    by_item = {r["item"]: r for r in records}
    assert "red onion" not in by_item                      # dropped: nothing to buy
    assert by_item["mayonnaise"]["category"] == "pantry"
    assert by_item["mayonnaise"]["display"] == "mayonnaise — 1 jar (30 oz)"
    assert by_item["chicken thighs"]["display"] == "chicken thighs — 4 lb"
    assert by_item["salt"]["display"] == "salt"            # noise unit -> no quantity
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v -k "build_records or format_shopping_line"`
Expected: FAIL — `build_records` / `format_shopping_line` not defined.

- [ ] **Step 3: Implement record building + shoppable formatting**

In `lib/shopping_list_generator.py`, add imports near the top:

```python
from lib.grocery_catalog import assign_category, shoppable_quantity
from lib.ingredient_normalizer import is_noise_unit
```

Add these two functions (place them after `compute_lines`):

```python
def format_shopping_line(rec: dict) -> str:
    """Render 'item — qty' (or just 'item' when there is no quantity)."""
    item = rec.get("item", "")
    amount = rec.get("amount", "")
    unit = rec.get("unit", "")
    qty = " ".join(p for p in (amount, unit) if p).strip()
    return f"{item} — {qty}" if qty else item


def build_records(lines: list[dict]) -> list[dict]:
    """Turn pantry-split lines into grouped shopping records.

    Drops lines with nothing left to buy; rounds each remaining line up to a
    shoppable quantity; assigns a store category. Returns
    [{item, category, display}, ...].
    """
    records: list[dict] = []
    for line in lines:
        to_buy = line.get("to_buy")
        if not to_buy:
            continue  # fully covered by inventory (or nothing needed)
        item = line["item"]
        amount = to_buy.get("amount", "")
        unit = to_buy.get("unit", "")
        if is_noise_unit(unit):
            sq = {"amount": "", "unit": ""}
        else:
            sq = shoppable_quantity(item, amount, unit)
        display = format_shopping_line({"item": item, "amount": sq["amount"], "unit": sq["unit"]})
        records.append({
            "item": item,
            "category": assign_category(item),
            "display": display,
        })
    return records
```

- [ ] **Step 4: Run the new unit tests**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v -k "build_records or format_shopping_line"`
Expected: PASS (3 passed).

- [ ] **Step 5: Wire default-on inventory + records into the generator**

In `lib/shopping_list_generator.py`, add a sentinel near the top (after imports):

```python
_AUTO = object()  # sentinel: caller did not specify pantry -> auto-load from DB
```

Change `generate_shopping_list` and `generate_shopping_list_from_path` signatures from `pantry: Optional[list[dict]] = None` to `pantry=_AUTO`, and resolve the sentinel at the top of `generate_shopping_list_from_path`:

```python
def generate_shopping_list_from_path(meal_plan_path: Path, pantry=_AUTO) -> dict:
    if pantry is _AUTO:
        from lib import pantry as pantry_module  # local import avoids cycle
        pantry = pantry_module.load_pantry()
    ...
```

And forward the same in `generate_shopping_list`:

```python
def generate_shopping_list(week: str, pantry=_AUTO) -> dict:
    ...
    return generate_shopping_list_from_path(meal_plan_path, pantry=pantry)
```

Then, at the end of `generate_shopping_list_from_path`, build records and expose them. Replace the return block so it computes records from `lines` and derives `items` from record displays:

```python
    aggregated = aggregate_ingredients(all_ingredients)
    lines = compute_lines(aggregated, pantry=pantry)
    records = build_records(lines)
    items = sorted(r["display"] for r in records)

    return {
        "success": True,
        "items": items,
        "records": records,
        "lines": lines,
        "recipes": loaded_recipes,
        "warnings": warnings,
    }
```

(Delete the old `if pantry is None: formatted = ...` branch — records now drive both `items` and grouping. Note `pantry is None` still means "no subtraction" because `compute_lines` treats `None` as no splitter; only the *default* changed from None to auto-load.)

- [ ] **Step 6: Run the full generator suite + confirm no regressions**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_generator.py -v`
Expected: PASS. Any pre-existing test that called `generate_shopping_list(week)` and asserted inventory was NOT subtracted must now pass `pantry=None` explicitly — update those call sites (the default is intentionally inventory-aware now).

- [ ] **Step 7: Commit**

```bash
git add lib/shopping_list_generator.py tests/test_shopping_list_generator.py
git commit -m "feat(shopping): default-on inventory subtraction + shoppable records

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Grouped-by-category template + wire the API

Render `###` category sections. Add a records-aware renderer, keep the old flat renderer for callers that only have plain strings, and update the two API write sites.

**Files:**
- Modify: `templates/shopping_list_template.py` (add `generate_grouped_shopping_list_markdown`)
- Modify: `api_server.py` (`/generate-shopping-list` ~line 595; `/api/shopping-list/confirm` ~line 1497)
- Test: `tests/test_shopping_list_template.py` (add cases; create if absent)

**Interfaces:**
- Consumes: `lib.grocery_catalog.assign_category` (to categorize plain manual/confirm strings).
- Produces: `generate_grouped_shopping_list_markdown(week: str, records: list[dict]) -> str` where each record is `{"display": str, "category": str}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_shopping_list_template.py`:

```python
from templates.shopping_list_template import generate_grouped_shopping_list_markdown


def test_groups_into_category_sections_in_store_order():
    records = [
        {"display": "mayonnaise — 1 jar (30 oz)", "category": "pantry"},
        {"display": "chicken thighs — 4 lb", "category": "meat"},
        {"display": "red onion — 2", "category": "produce"},
        {"display": "shredded cheddar — 1 bag (8 oz)", "category": "dairy"},
    ]
    md = generate_grouped_shopping_list_markdown("2026-W27", records)
    # Produce before Meat before Dairy before Pantry
    assert md.index("### Produce") < md.index("### Meat & Seafood")
    assert md.index("### Meat & Seafood") < md.index("### Dairy")
    assert md.index("### Dairy") < md.index("### Pantry")
    assert "- [ ] red onion — 2" in md
    assert "- [ ] mayonnaise — 1 jar (30 oz)" in md
    # buttons still present
    assert "Send to Reminders" in md
    assert "kitchenos://send-to-reminders?week=2026-W27" in md


def test_empty_sections_are_omitted():
    records = [{"display": "red onion — 2", "category": "produce"}]
    md = generate_grouped_shopping_list_markdown("2026-W27", records)
    assert "### Produce" in md
    assert "### Frozen" not in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_template.py -v -k grouped`
Expected: FAIL — `generate_grouped_shopping_list_markdown` not defined.

- [ ] **Step 3: Implement the grouped renderer**

In `templates/shopping_list_template.py`, add:

```python
# Display order + heading labels for store categories (inventory CATEGORIES vocab).
_CATEGORY_ORDER = [
    ("produce", "Produce"),
    ("meat", "Meat & Seafood"),
    ("seafood", "Meat & Seafood"),
    ("dairy", "Dairy"),
    ("bakery", "Bakery"),
    ("pantry", "Pantry"),
    ("frozen", "Frozen"),
    ("beverages", "Beverages"),
    ("household", "Household"),
    ("other", "Other"),
]


def generate_grouped_shopping_list_markdown(week: str, records: list[dict]) -> str:
    """Render a shopping list grouped into store-category sections.

    records: [{"display": str, "category": str}, ...]
    """
    match = re.match(r'\d{4}-W(\d{2})', week)
    week_num = int(match.group(1)) if match else 0
    try:
        title = f"# Shopping List - Week {week_num:02d} ({format_week_range(week)})"
    except ValueError:
        title = f"# Shopping List - Week {week_num:02d}"

    lines = [title, "", f"Generated from [[{week}|Meal Plan]]", ""]

    # Collapse seafood into the meat heading; keep one section per heading label.
    seen_headings: list[str] = []
    for cat, heading in _CATEGORY_ORDER:
        if heading in seen_headings:
            continue
        # All categories that share this heading (meat + seafood).
        cats = {c for c, h in _CATEGORY_ORDER if h == heading}
        section = sorted(r["display"] for r in records if r.get("category") in cats)
        if not section:
            continue
        seen_headings.append(heading)
        lines.append(f"### {heading}")
        for disp in section:
            lines.append(f"- [ ] {disp}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "```button",
        "name Add Ingredients",
        "type command",
        "action QuickAdd: Add Ingredients to Shopping List",
        "```",
        "",
        "```button",
        "name Send to Reminders",
        "type link",
        f"action kitchenos://send-to-reminders?week={week}",
        "```",
        "",
    ])
    return '\n'.join(lines)
```

- [ ] **Step 4: Run the template tests**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_template.py -v`
Expected: PASS.

- [ ] **Step 5: Wire `/generate-shopping-list` to the grouped renderer**

In `api_server.py`, add to the imports at line 28:

```python
from templates.shopping_list_template import (
    generate_shopping_list_markdown,
    generate_grouped_shopping_list_markdown,
    generate_filename as shopping_list_filename,
)
from lib.grocery_catalog import assign_category
```

Replace the markdown build in the `/generate-shopping-list` handler (currently lines ~591-595):

```python
    # Combine generated records with any manual items (categorized on the fly).
    records = list(result.get("records", []))
    for manual in manual_items:
        records.append({"display": manual, "category": assign_category(manual)})

    markdown = generate_grouped_shopping_list_markdown(week, records)
```

- [ ] **Step 6: Wire the confirm endpoint to the grouped renderer**

In `api_server.py`, replace line ~1497 (`markdown = generate_shopping_list_markdown(week, items)`) with:

```python
    records = [{"display": it, "category": assign_category(it)} for it in items]
    markdown = generate_grouped_shopping_list_markdown(week, records)
```

- [ ] **Step 7: Restart the API LaunchAgent and smoke-test**

Editing `api_server.py` / templates requires a restart or the server serves stale code:

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
curl -s http://localhost:5001/health
```

Expected: health returns OK.

- [ ] **Step 8: Commit**

```bash
git add templates/shopping_list_template.py api_server.py tests/test_shopping_list_template.py
git commit -m "feat(shopping): render shopping list grouped by store category

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: End-to-end integration test on a temp vault

Prove the four mess symptoms are gone against a realistic meal plan, using an isolated vault + DB so nothing touches real data.

**Files:**
- Create: `tests/test_shopping_list_integration.py`

**Interfaces:**
- Consumes: `lib.shopping_list_generator.generate_shopping_list_from_path`, `lib.inventory` (to seed inventory), `KITCHENOS_VAULT` / `KITCHENOS_DB` env overrides.

- [ ] **Step 1: Write the integration test**

Create `tests/test_shopping_list_integration.py`:

```python
"""End-to-end: a messy meal plan -> a clean, grouped, inventory-aware list."""
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Recipes").mkdir(parents=True)
    (vault / "Meal Plans").mkdir(parents=True)
    (vault / "Shopping Lists").mkdir(parents=True)
    monkeypatch.setenv("KITCHENOS_VAULT", str(vault))
    # Force lib.paths to re-read the env (it caches nothing, but reload to be safe).
    import importlib
    from lib import paths
    importlib.reload(paths)
    return vault


def _write_recipe(vault: Path, name: str, rows: list[str]):
    body = "## Ingredients\n\n| Amount | Unit | Item |\n|---|---|---|\n"
    body += "\n".join(rows) + "\n"
    (vault / "Recipes" / f"{name}.md").write_text(f"# {name}\n\n{body}", encoding="utf-8")


def test_messy_plan_becomes_clean(tmp_vault, tmp_db):
    from lib.inventory import add_items
    from lib.shopping_list_generator import generate_shopping_list_from_path

    # Two recipes that reproduce the W27 mess: onion variants, mayo/mayonnaise,
    # summed salt, descriptor noise.
    _write_recipe(tmp_tmp := tmp_vault, "Salad", [
        "| 0.25 | cup | red onion, thinly sliced |",
        "| 1.29 | cup | mayo |",
        "| 1 | to taste | salt |",
    ])
    _write_recipe(tmp_vault, "Slaw", [
        "| 2 | whole | red onion |",
        "| 0.25 | cup | mayonnaise |",
        "| 1 | to taste | salt |",
    ])
    plan = tmp_vault / "Meal Plans" / "2026-W27.md"
    plan.write_text("## Monday\n- Dinner: [[Salad]]\n- Lunch: [[Slaw]]\n", encoding="utf-8")

    # Seed inventory so red onion is fully covered and should drop out.
    add_items([{"name": "red onion", "quantity": 10, "unit": "each", "category": "produce"}])

    result = generate_shopping_list_from_path(plan)  # inventory auto-loaded
    assert result["success"], result
    displays = "\n".join(r["display"] for r in result["records"])

    # 1. No descriptor noise.
    assert "(inferred)" not in displays
    assert "thinly sliced" not in displays
    # 2. Onion variants consolidated AND removed (in inventory).
    assert "onion" not in displays.lower()
    # 3. mayo + mayonnaise merged into a single shoppable line.
    mayo_lines = [r for r in result["records"] if r["item"] == "mayonnaise"]
    assert len(mayo_lines) == 1
    assert "jar" in mayo_lines[0]["display"]
    # 4. Salt has no absurd summed quantity (noise unit -> no number).
    salt_lines = [r for r in result["records"] if r["item"] == "salt"]
    assert salt_lines and salt_lines[0]["display"] == "salt"
```

Note on `add_items`: confirm the exact seeding helper name in `lib/inventory.py` (`grep -n "^def " lib/inventory.py`). If it is not `add_items`, use the actual add function (e.g. `write_inventory` with `InventoryItem`s) — the test's intent is "put a red onion in inventory". Adjust the two seeding lines only.

Note on the parser: confirm `parse_ingredient_table` accepts the `| Amount | Unit | Item |` layout by checking an existing recipe file's Ingredients table format (`grep -rl "## Ingredients" vault/KitchenOS/Recipes | head -1`) and matching the column headers/order exactly. Adjust the `_write_recipe` header row to match if needed.

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/test_shopping_list_integration.py -v`
Expected: PASS. If it fails on parsing (empty ingredients), fix the table format in `_write_recipe` to match the real recipe schema, not the assertions.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS (no regressions). Fix any pre-existing shopping/aggregator test that asserted old raw-name or non-inventory-subtracted behavior — those assertions are now intentionally outdated.

- [ ] **Step 4: Commit**

```bash
git add tests/test_shopping_list_integration.py
git commit -m "test(shopping): end-to-end clean-list integration test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Regenerate the real W27 list + docs

Verify against the actual acceptance fixture and update docs.

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md` (shopping-list pipeline + new configs)
- Regenerate: `vault/KitchenOS/Shopping Lists/2026-W27.md`

- [ ] **Step 1: Regenerate W27 and eyeball it**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
.venv/bin/python shopping_list.py --week 2026-W27 --dry-run
```

Expected: grouped sections; no `15.25 tsp salt`, no `1.29 cups mayo`, no `(inferred)`, no duplicate onion lines, inventory-covered items absent. If `shopping_list.py` has no `--dry-run`/`--week` combination that prints grouped output, generate via the API instead:

```bash
curl -s -X POST http://localhost:5001/generate-shopping-list \
  -H "Content-Type: application/json" -d '{"week":"2026-W27"}' | python3 -m json.tool
```

Then open `vault/KitchenOS/Shopping Lists/2026-W27.md` and confirm the grouped, clean output.

- [ ] **Step 2: Document the pipeline change**

In `docs/ARCHITECTURE.md`, update the shopping-list section to note the pipeline:
`normalize names → aggregate → subtract inventory (default) → round to shoppable package → group by category`, and that `lib/ingredient_normalizer.py` + `lib/grocery_catalog.py` are the new stages.

In `docs/OPERATIONS.md`, add `config/grocery_items.json` (category + buy-unit + package sizes) and `config/shopping_aliases.json` (synonym map) to the list of hand-correctable configs, and note that shopping-list generation now subtracts kitchen inventory by default (`--no-pantry` / `use_pantry:false` opts out).

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md docs/OPERATIONS.md "vault/KitchenOS/Shopping Lists/2026-W27.md"
git commit -m "docs(shopping): document cleanup pipeline; regenerate W27 list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Push the branch**

```bash
git push -u origin shopping-list-cleanup
```

---

## Self-Review

**Spec coverage:**
- Decision #1 (inventory-arbiter, default-on) → Task 5 (default-on) + Task 7 (drops covered items). ✓
- Decision #2 (deterministic name normalization + alias map, no variety-merge) → Task 2. ✓
- Decision #3 (config table + category fallback, round-up) → Task 3. ✓
- Decision #4 (group by store category) → Task 6. ✓
- Pipeline stages (normalize → aggregate → subtract → round → categorize → render) → Tasks 2,4,5,3,6. ✓
- Edge cases (unknown→other+native, to-taste→no qty, cross-family warning preserved, deli weight) → Tasks 3 & 5 tests. ✓
- Testing + docs sections → Tasks 7 & 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two explicit "confirm the real name/format" notes in Task 7 are verification instructions (inventory seeding helper, recipe table format), not placeholders — they exist because those names live outside the files this plan creates.

**Type consistency:** `normalize_name` (Task 2) consumed in Task 4; `assign_category`/`shoppable_quantity` (Task 3) consumed in Task 5; `build_records`/`format_shopping_line` (Task 5) produce `{item,category,display}` consumed by `generate_grouped_shopping_list_markdown` (Task 6) which reads `display`/`category` — consistent. `_AUTO` sentinel semantics preserved across `generate_shopping_list` / `generate_shopping_list_from_path`. Records key names match across Tasks 5, 6, 7.
