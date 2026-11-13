# Make the Shopping List True (E1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the "Inventory matches — verify" flood so the weekly list shows what to buy, what to check, and a one-line "assumed on hand" summary. Never credit the wrong food.

**Architecture:** Three changes inside `lib/pantry.split_against_pantry`, plus their renderers:
1. A shopping-specific **identity** that ignores descriptors that don't change the food ("freshly ground", "fresh", "extra-virgin" vs "extra virgin", kosher/sea salt → salt).
2. A **head-noun guard**: a broad match whose head noun differs (garlic → *Garlic powder*, black beans → *Kosher salt*) is a plain buy, not a review.
3. A new **`on_hand`** status: a small ask (≤ 3 tbsp, ≤ 30 g, pinch/dash) against an exact-identity *package* row (ct/ea/jar…) is assumed covered. It is never decremented, never sent to Reminders, and is summarised in one plain bullet.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

## Global Constraints

- Run everything with `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python` from the worktree `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/shopping-list-true`.
- **Precision first (from #78):** a false credit is worse than a false negative. `on_hand` requires *exact shopping identity* **and** a package-unit row **and** a small ask. Anything else keeps today's behaviour.
- **`on_hand` lines carry `from_pantry: None` and `to_buy: None`.** This matters. `cooking_packet_builder.allocate_pull_sources` treats a truthy `from_pantry` as permission to `_convert` units, which raises on ct↔tsp. Also, `apply_decisions` must never decrement a container for a pinch (CLAUDE.md: "Inventory rows are containers, not counts").
- Match notes stay **plain bullets, never `- [ ]`** (CLAUDE.md shopping-list invariant). `items`/`purchase_items` stay purchase-only.
- `split_against_pantry` is also called per-row by `allocate_pull_sources`. Every change must be safe when `pantry` is a single-entry list.
- Don't touch `find_match` (Cook Now / Use It Up share the broad matcher).
- Restart the API LaunchAgent after merging (`lib/` is held in memory).

## Measured baseline (live pantry, 2026-11-12, read-only)

| Week | Lines | buy | credited | review | of which related / pkg-unknown / units |
|---|---|---|---|---|---|
| 2026-W45 | 34 | 13 | 0 | 21 | 13 / 6 / 2 |
| 2026-W46 | 31 | 10 | 0 | 21 | 12 / 2 / 7 |
| 2026-W48 | 218 | 102 | 4 | 110 | 75 / 23 / 12 |

Task 5's script reproduces this table. Acceptance: **review count falls by ≥ 50% on W48, with zero new false credits** (each new `on_hand`/`credited` line is hand-checked in Task 5).

## Out of scope (record in the PR, don't build)

- Duplicate cook rows inflating demand (W46 has `Dilly Green Olive Dense Bean Salad` ×2). Each may be a deliberate second batch, so this needs the user's call.
- Ingredient-parse junk (`"2 tomatoes)"`, `"1 /4 cup cottage cheese"`, `"2 cups"`). That's the parser, not the reconciler.
- The 365-day `pantry` expiry window. Staples no longer expire and `prune_expired` already runs daily (`generate_meal_plan.refresh_inventory_views`), so audit item 22 is effectively closed.

## File Structure

- Create `lib/shopping_identity.py`: `shopping_identity(name) -> str`, one responsibility.
- Modify `lib/pantry.py`: `split_against_pantry` uses the identity, the head guard and `on_hand`.
- Modify `lib/shopping_list_generator.py`: `shopping_sections` emits the on-hand summary bullet, and the `compute_lines` docstring lists the new status.
- Modify `lib/cooking_packet_builder.py`: the status re-settle loop keeps `on_hand`.
- Create `scripts/measure_shopping_list.py`: read-only before/after table.
- Tests: `tests/test_shopping_identity.py` (new), `tests/test_pantry.py`, `tests/test_shopping_list_generator.py`, `tests/test_cooking_packet_builder.py`.
- Docs: `CLAUDE.md` shopping-list invariant; `docs/plans/INDEX.md` row.

---

### Task 1: Shopping identity

**Files:**
- Create: `lib/shopping_identity.py`
- Test: `tests/test_shopping_identity.py`

**Interfaces:**
- Consumes: `lib.ingredient_normalizer.normalize_name(raw: str) -> str`
- Produces: `lib.shopping_identity.shopping_identity(name: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shopping_identity.py
import pytest

from lib.shopping_identity import shopping_identity


@pytest.mark.parametrize("a, b", [
    ("freshly ground black pepper", "black pepper"),
    ("extra-virgin olive oil", "extra virgin olive oil"),
    ("ground cinnamon", "Cinnamon"),
    ("ground allspice", "Allspice"),
    ("fresh thyme", "Thyme"),
    ("fresh parsley", "parsley"),
    ("freshly squeezed lemon juice", "lemon juice"),
    ("pure maple syrup", "maple syrup"),
    ("salt", "Kosher salt"),
    ("sea salt", "Celtic sea salt"),
    ("kosher salt such as diamond crystal", "Diamond Crystal kosher salt"),
    ("fine sea salt", "salt"),
])
def test_same_food_shares_identity(a, b):
    assert shopping_identity(a) == shopping_identity(b)


@pytest.mark.parametrize("a, b", [
    ("ground beef", "beef"),          # ground is the cut for meat, not a descriptor
    ("ground turkey", "turkey"),
    ("garlic salt", "salt"),          # seasoned salts are not salt
    ("celery salt", "salt"),
    ("onion salt", "kosher salt"),
    ("dried oregano", "oregano"),     # dried vs fresh herbs differ
    ("garlic", "garlic powder"),
    ("smoked paprika", "paprika"),
])
def test_different_foods_stay_distinct(a, b):
    assert shopping_identity(a) != shopping_identity(b)


def test_empty_is_empty():
    assert shopping_identity("") == ""
    assert shopping_identity(None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shopping_identity.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.shopping_identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/shopping_identity.py
"""Identity of an ingredient for shopping credit.

`ingredient_normalizer.normalize_name` keeps every adjective, so "freshly
ground black pepper" never equals the "black pepper" row and "salt" never
equals "Kosher salt". The shopping list then sends every owned staple to
"verify". This layer drops only descriptors that do not change which product
you buy. Anything that does change it (dried, smoked, garlic salt, ground
*meat*) stays. Keep this list closed and pinned by
tests/test_shopping_identity.py: a descriptor wrongly treated as noise
becomes a false credit, and a false credit means a missing ingredient at the
stove.
"""
from __future__ import annotations

import re

from lib.ingredient_normalizer import normalize_name

_LEADING = re.compile(
    r"^(?:freshly\s+(?:ground|grated|squeezed|cracked)|fresh|pure)\s+"
)
_SUCH_AS = re.compile(r"\s+such as\b.*$")
# "ground" is a descriptor for spices but the cut itself for meat.
_MEATS = {"beef", "pork", "turkey", "chicken", "lamb", "veal", "bison",
          "meat", "sausage", "venison"}
# Words that may precede "salt" and still mean plain salt.
_PLAIN_SALT_WORDS = {"kosher", "sea", "table", "fine", "flaky", "coarse",
                     "celtic", "diamond", "crystal", "morton", "himalayan",
                     "pink", "iodized", "flake"}


def shopping_identity(name: str | None) -> str:
    s = normalize_name(name or "")
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.replace("-", " ")).strip()
    s = _SUCH_AS.sub("", s)
    while True:
        stripped = _LEADING.sub("", s)
        if stripped == s:
            break
        s = stripped
    words = s.split()
    if len(words) > 1 and words[0] == "ground" and words[-1] not in _MEATS:
        words = words[1:]
    if words and words[-1] == "salt" and set(words[:-1]) <= _PLAIN_SALT_WORDS:
        return "salt"
    return " ".join(words)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_shopping_identity.py -q`
Expected: PASS (all parametrized cases). If `normalize_name`'s alias map rewrites one of the inputs, print `normalize_name(x)` for that case and adjust the test input, not the descriptor list.

- [ ] **Step 5: Commit**

```bash
git add lib/shopping_identity.py tests/test_shopping_identity.py
git commit -m "feat(shopping): descriptor-insensitive shopping identity

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Use the identity and the head-noun guard in `split_against_pantry`

**Files:**
- Modify: `lib/pantry.py` (`split_against_pantry`, currently lines ~197-244)
- Test: `tests/test_pantry.py`

**Interfaces:**
- Consumes: `shopping_identity` (Task 1); `lib.fdc_local.query_head(item: str) -> tuple[str, str]` returns `(head, qualifier)`, or `("", "")` when too noisy. Import it **inside the function**, because `lib.fdc_local` is heavier and may import `lib.pantry` transitively.
- Produces: `split_against_pantry` unchanged signature. Head-mismatched candidates now return `status: "buy"` with `matched_inventory: None` and `warning: None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_pantry.py`)

```python
def test_split_credits_descriptor_variants_as_same_food():
    pantry = [{"item": "extra virgin olive oil", "amount": "500", "unit": "ml"}]
    out = split_against_pantry("extra-virgin olive oil", "2", "tbsp", pantry)
    assert out["status"] == "credited"
    assert out["to_buy"] is None


def test_split_head_mismatch_is_a_plain_buy_not_review():
    pantry = [{"item": "Garlic powder", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("garlic cloves", "5", "", pantry)
    assert out["status"] == "buy"
    assert out["matched_inventory"] is None
    assert out["warning"] is None


def test_split_salt_does_not_match_black_beans():
    pantry = [{"item": "Kosher salt", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("no-salt-added black beans", "2", "cans", pantry)
    assert out["status"] == "buy"
    assert out["matched_inventory"] is None


def test_split_same_head_related_item_still_reviews():
    # caramelized onions are onions, but not the raw onion asked for
    pantry = [{"item": "caramelized onions", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("onion", "1", "", pantry)
    assert out["status"] == "review"
    assert out["matched_inventory"]["item"] == "caramelized onions"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pantry.py -q -k "descriptor_variants or head_mismatch or black_beans or same_head"`
Expected: the first three FAIL (status `review`). The fourth may already pass, which is fine: it pins behaviour.

- [ ] **Step 3: Implement.** In `lib/pantry.py` add `from lib.shopping_identity import shopping_identity` to the imports. Then replace the top of `split_against_pantry` through the "related item" return with:

```python
    needed = {"amount": amount, "unit": unit}
    item_identity = shopping_identity(item)
    pantry_entry = next(
        (entry for entry in pantry
         if shopping_identity(entry.get("item") or "") == item_identity),
        None,
    )
    if pantry_entry is None:
        pantry_entry = find_match(item, pantry)
    buy = {
        "from_pantry": None,
        "to_buy": needed,
        "warning": None,
        "status": "buy",
        "matched_inventory": None,
    }
    if pantry_entry is None:
        return buy

    matched = pantry_entry.get("item") or "inventory item"
    p_unit = pantry_entry.get("unit") or ""
    p_amount = pantry_entry.get("amount")
    p_label = " ".join(str(part) for part in (p_amount, p_unit) if part not in (None, ""))
    match_label = f"{matched} ({p_label})" if p_label else matched

    # Discovery matching deliberately accepts broader food relationships. A
    # shopping credit has the opposite risk profile: a merely-related product
    # may be useful for suggestions, but must not remove the ingredient needed
    # to execute the plan.
    if shopping_identity(item) != shopping_identity(matched):
        # A broad match whose head noun differs names a different food
        # (garlic -> Garlic powder, black beans -> Kosher salt). Listing it
        # under "verify" was a third of every list; it is simply a purchase.
        from lib.fdc_local import query_head
        demand_head, _ = query_head(_match_text(item))
        matched_head, _ = query_head(matched)
        if demand_head and matched_head and demand_head != matched_head:
            return buy
        return {
            "from_pantry": None,
            "to_buy": needed,
            "warning": f"inventory has {match_label}, a related item; not credited",
            "status": "review",
            "matched_inventory": pantry_entry,
        }
```

Leave everything from the `# Receipt and conversational ingest use ct` comment down unchanged in this task.

- [ ] **Step 4: Run the pantry, generator and packet suites**

Run: `.venv/bin/python -m pytest tests/test_pantry.py tests/test_shopping_list_generator.py tests/test_cooking_packet_builder.py -q`
Expected: PASS. If an existing test asserted `review` for a head-mismatched pair (search the failure for "related item"), read it. If its pair really is different food, update the expectation to `buy` and say so in the commit body. If the pair is the same food, the guard is wrong: stop and report.

- [ ] **Step 5: Commit**

```bash
git add lib/pantry.py tests/test_pantry.py
git commit -m "fix(shopping): match by shopping identity; head-noun mismatch is a buy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `on_hand` for small asks against an owned package

**Files:**
- Modify: `lib/pantry.py` (new helpers above `split_against_pantry`, plus one branch inside it)
- Modify: `lib/shopping_list_generator.py` (`compute_lines` docstring, `shopping_sections`)
- Test: `tests/test_pantry.py`, `tests/test_shopping_list_generator.py`

**Interfaces:**
- Consumes: `convert_to_base_unit(amount: float, unit: str, family: str) -> float` and `get_unit_family(unit) -> str`, already imported in `lib/pantry.py` from `lib.ingredient_aggregator`.
- Produces: `split_against_pantry` may return `{"status": "on_hand", "from_pantry": None, "to_buy": None, "warning": None, "matched_inventory": <row>}`. `shopping_sections(lines)` returns `{"purchase": [...], "inventory_matches": [...]}`. When any line is `on_hand`, `inventory_matches` ends with exactly one bullet starting `"Assumed on hand — "`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pantry.py`:

```python
import pytest as _pytest


@_pytest.mark.parametrize("amount, unit", [
    ("1", "tsp"), ("2", "tbsp"), ("3", "tbsp"), ("15", "g"), ("1", "pinch"),
])
def test_small_ask_against_owned_package_is_on_hand(amount, unit):
    pantry = [{"item": "Kosher salt", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("salt", amount, unit, pantry)
    assert out["status"] == "on_hand"
    assert out["from_pantry"] is None   # never a decrement, never a pull
    assert out["to_buy"] is None
    assert out["warning"] is None


@_pytest.mark.parametrize("amount, unit", [("10.33", "tbsp"), ("1", "cup"), ("40", "g")])
def test_large_ask_against_package_still_reviews(amount, unit):
    pantry = [{"item": "Olive oil", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("olive oil", amount, unit, pantry)
    assert out["status"] == "review"
    assert "package quantity is unknown" in out["warning"]


def test_small_ask_needs_exact_identity_not_related():
    pantry = [{"item": "Smoked paprika", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("paprika", "1", "tsp", pantry)
    assert out["status"] != "on_hand"


def test_small_ask_against_measured_row_is_not_on_hand():
    # a measured row is compared by quantity as before, never assumed
    pantry = [{"item": "sesame oil", "amount": "1", "unit": "oz"}]
    out = split_against_pantry("sesame oil", "1.5", "tsp", pantry)
    assert out["status"] != "on_hand"


def test_unitless_count_against_package_is_not_on_hand():
    pantry = [{"item": "Garlic powder", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("garlic powder", "1", "", pantry)
    assert out["status"] != "on_hand"


def test_apply_decisions_ignores_on_hand_lines():
    pantry = [{"item": "Kosher salt", "amount": "1", "unit": "ct"}]
    out = split_against_pantry("salt", "1", "tsp", pantry)
    assert out["from_pantry"] is None   # so no decision can be built from it
```

Append to `tests/test_shopping_list_generator.py`:

```python
from lib.shopping_list_generator import compute_lines, shopping_sections


def test_on_hand_lines_summarised_in_one_plain_bullet_and_never_purchased():
    pantry = [
        {"item": "Kosher salt", "amount": "1", "unit": "ct"},
        {"item": "Ground cumin", "amount": "1", "unit": "ct"},
    ]
    lines = compute_lines([
        {"amount": "1", "unit": "tsp", "item": "salt"},
        {"amount": "0.5", "unit": "tsp", "item": "ground cumin"},
        {"amount": "2", "unit": "", "item": "carrots"},
    ], pantry=pantry)
    sections = shopping_sections(lines)
    assert sections["purchase"] == ["2 carrots"]
    summary = [n for n in sections["inventory_matches"] if n.startswith("Assumed on hand — ")]
    assert len(summary) == 1
    assert "salt" in summary[0] and "ground cumin" in summary[0]
    assert not any(n.lstrip().startswith("- [") for n in sections["inventory_matches"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pantry.py tests/test_shopping_list_generator.py -q -k "on_hand or large_ask or small_ask or unitless_count or apply_decisions_ignores"`
Expected: the `on_hand` cases FAIL (`review` returned). The negative cases may pass already, which is fine.

- [ ] **Step 3: Implement in `lib/pantry.py`.** Add these above `split_against_pantry`:

```python
# Units that mean "one container exists", not a measured amount.
_PACKAGE_UNITS = {"ct", "ea", "each", "pkg", "package", "jar", "bottle",
                  "can", "bag", "box", "container", "tub", "tin"}
_TRACE_UNITS = {"pinch", "pinches", "dash", "dashes", "smidgen"}
# The most a recipe line may ask of an owned container before a person
# should look: three tablespoons, or thirty grams.
_SMALL_VOLUME_BASE = convert_to_base_unit(3, "tbsp", "volume")
_SMALL_WEIGHT_BASE = convert_to_base_unit(30, "g", "weight")


def _is_small_ask(amount, unit: str) -> bool:
    """Whether a demand is small enough that an owned container covers it."""
    unit = (unit or "").lower().strip()
    if unit in _TRACE_UNITS:
        return True
    n = parse_amount_to_float(amount)
    if n is None:
        return False
    family = get_unit_family(unit)
    if family == "volume":
        return convert_to_base_unit(n, unit, family) <= _SMALL_VOLUME_BASE
    if family == "weight":
        return convert_to_base_unit(n, unit, family) <= _SMALL_WEIGHT_BASE
    return False
```

Then inside `split_against_pantry`, directly **after** the related-item block from Task 2 and **before** the `# Receipt and conversational ingest use ct` comment, insert:

```python
    p_unit_norm = p_unit.lower().strip()
    unit_norm = (unit or "").lower().strip()
    # A pinch of salt against a box of salt: the box covers it. Assumed, not
    # credited. from_pantry stays None so neither apply_decisions nor the
    # cooking packet's pull allocation ever treats a container as spendable
    # by the teaspoon.
    if p_unit_norm in _PACKAGE_UNITS and _is_small_ask(amount, unit_norm):
        return {
            "from_pantry": None,
            "to_buy": None,
            "warning": None,
            "status": "on_hand",
            "matched_inventory": pantry_entry,
        }
```

and delete the now-duplicate `p_unit_norm = ...` / `unit_norm = ...` lines that followed the ct comment.

- [ ] **Step 4: Implement in `lib/shopping_list_generator.py`.** In the `compute_lines` docstring change the status line to `"status": "buy" | "credited" | "review" | "on_hand" | "excluded",`. Replace `shopping_sections` with:

```python
def shopping_sections(lines: list[dict]) -> dict[str, list[str]]:
    """Split generated demand into purchases and inventory matches to verify.

    Any inventory candidate belongs in the verification section, regardless of
    whether its quantity was creditable. Only lines with no candidate become
    purchase checkboxes (and therefore Reminders items). Lines assumed covered
    by an owned container (`on_hand`) collapse into one closing plain bullet,
    so a week of salt, oil and spices reads as one line instead of forty.
    """
    purchase: list[str] = []
    inventory_matches: list[str] = []
    on_hand: list[str] = []
    for line in lines:
        status = line.get("status")
        if status == "excluded":
            continue
        if status == "on_hand":
            name = line.get("item", "")
            if name and name not in on_hand:
                on_hand.append(name)
            continue

        matched = line.get("matched_inventory")
        if matched:
            inventory_matches.append(_inventory_match_note(line))
            continue

        to_buy = line.get("to_buy")
        if to_buy:
            purchase.append(format_ingredient({
                "amount": to_buy.get("amount", ""),
                "unit": to_buy.get("unit", ""),
                "item": line.get("item", ""),
            }))

    if on_hand:
        inventory_matches.append(
            "Assumed on hand — small amounts from packages you have: "
            + ", ".join(sorted(on_hand, key=str.lower))
        )
    return {"purchase": purchase, "inventory_matches": inventory_matches}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_pantry.py tests/test_shopping_list_generator.py tests/test_shopping_note.py -q`
Expected: PASS. (If `tests/test_shopping_note.py` doesn't exist, drop it from the command.)

- [ ] **Step 6: Commit**

```bash
git add lib/pantry.py lib/shopping_list_generator.py tests/test_pantry.py tests/test_shopping_list_generator.py
git commit -m "feat(shopping): assume small asks are on hand from owned packages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Cooking packet keeps `on_hand`

`build_week_draft` re-settles every line's status from its pulls (`lib/cooking_packet_builder.py`, the loop ending `line["status"] = "credited" if credited else "review" if line.get("warning") else "buy"`). An `on_hand` line has no pulls, so it would be rewritten to `buy` with `to_buy = needed` and land back on the packet's shopping list.

**Files:**
- Modify: `lib/cooking_packet_builder.py`
- Test: `tests/test_cooking_packet_builder.py`

**Interfaces:**
- Produces: `_settle_line(line: dict, credited: float) -> None` (module-private, mutates `line`).

- [ ] **Step 1: Write the failing test** (append)

```python
from lib.cooking_packet_builder import _settle_line


def test_settle_keeps_on_hand_lines_off_the_buy_list():
    line = {"status": "on_hand", "needed": {"amount": "1", "unit": "tsp"},
            "from_pantry": None, "to_buy": None, "warning": None}
    _settle_line(line, 0.0)
    assert line["status"] == "on_hand"
    assert line["to_buy"] is None


def test_settle_uncredited_line_still_buys():
    line = {"status": "buy", "needed": {"amount": "2", "unit": ""},
            "from_pantry": None, "to_buy": None, "warning": None}
    _settle_line(line, 0.0)
    assert line["status"] == "buy"
    assert line["to_buy"] == {"amount": "2", "unit": ""}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_builder.py -q -k settle`
Expected: FAIL with `ImportError: cannot import name '_settle_line'`

- [ ] **Step 3: Implement.** Extract the `if line.get("status") != "excluded":` block into a helper and call it from the loop:

```python
def _settle_line(line: dict, credited: float) -> None:
    """Re-derive a line's status from the stock actually pulled for it.

    `excluded` (water, ice) and `on_hand` (a pinch from an owned container)
    have no pulls by design; re-deriving them would put them back on the
    packet's shopping list.
    """
    if line.get("status") in ("excluded", "on_hand"):
        return
    needed_amount = _quantity(line["needed"]["amount"])
    unit = line["needed"]["unit"]
    line["from_pantry"] = {"amount": credited, "unit": unit} if credited else None
    to_buy = max(0.0, needed_amount - credited)
    line["to_buy"] = {"amount": to_buy if credited else line["needed"]["amount"],
                      "unit": unit} if to_buy > 1e-12 else None
    line["status"] = "credited" if credited else "review" if line.get("warning") else "buy"
```

In `build_week_draft` replace the inline block with `_settle_line(line, credited)`. Keep the surrounding `line["done"] = False` and the warnings append unchanged.

Also in `allocate_pull_sources`, change `if line.get("status") == "excluded":` to `if line.get("status") in ("excluded", "on_hand"):`, so an owned container is never allocated as a pull.

- [ ] **Step 4: Run the packet suite**

Run: `.venv/bin/python -m pytest tests/test_cooking_packet_builder.py tests/test_cooking_packet_render.py -q`
Expected: PASS. The render tests launch Chromium and must run **unsandboxed**. Run them unsandboxed instead of skipping them.

- [ ] **Step 5: Commit**

```bash
git add lib/cooking_packet_builder.py tests/test_cooking_packet_builder.py
git commit -m "fix(packet): keep on-hand lines off the packet shopping list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Measure on the live pantry, hand-check, document

**Files:**
- Create: `scripts/measure_shopping_list.py`
- Modify: `CLAUDE.md` (the "Generating a shopping list compares inventory" invariant), `docs/plans/INDEX.md`

- [ ] **Step 1: Write the read-only measurement script**

```python
#!/usr/bin/env python3
"""Read-only: shopping-list disposition counts per week against the live pantry.

Usage: .venv/bin/python scripts/measure_shopping_list.py 2026-W45 2026-W46 2026-W48 [--show on_hand,credited]
Never writes inventory or notes: generate_shopping_list only computes.
"""
import os
import sys
from collections import Counter

os.environ.setdefault("KITCHENOS_NO_LLM", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import pantry as pantry_module  # noqa: E402
from lib.shopping_list_generator import generate_shopping_list  # noqa: E402


def main(argv):
    show = set()
    if "--show" in argv:
        i = argv.index("--show")
        show = set(argv[i + 1].split(","))
        argv = argv[:i] + argv[i + 2:]
    pan = pantry_module.load_pantry()
    print("| Week | Lines | buy | credited | on_hand | review |")
    print("|---|---|---|---|---|---|")
    detail = []
    for week in argv:
        lines = generate_shopping_list(week, pantry=pan).get("lines") or []
        c = Counter(line["status"] for line in lines)
        print(f"| {week} | {len(lines)} | {c['buy']} | {c['credited']} | {c['on_hand']} | {c['review']} |")
        for line in lines:
            if line["status"] in show:
                m = line.get("matched_inventory") or {}
                detail.append(f"{week} {line['status']:8} {line['display']} <- {m.get('item')} {m.get('amount')} {m.get('unit')}")
    print("\n".join(detail))


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 2: Run it from the main checkout's data** (the worktree has no `vault/`/`data/`; `lib/paths` reads `KITCHENOS_VAULT` from the main checkout's `.env`; if paths resolve wrong, `cp ../../.env .env` in the worktree. It's git-ignored.)

Run: `.venv/bin/python scripts/measure_shopping_list.py 2026-W45 2026-W46 2026-W48 --show on_hand,credited`
Expected: W48 review ≤ 55 (≥ 50% below 110). Paste the table into the PR.

- [ ] **Step 3: Hand-check every `on_hand` and `credited` line printed.** Each must be the same food, with the right form. Any wrong one is a false credit. Fix it by adding a pinned *distinct* pair to `tests/test_shopping_identity.py::test_different_foods_stay_distinct`, then narrow `lib/shopping_identity.py`. Never fix it by loosening a test.

- [ ] **Step 4: Update `CLAUDE.md`.** In the invariant beginning **"Generating a shopping list compares inventory; only confirming spends it."**, append:

> A small ask (≤ 3 tbsp, ≤ 30 g, pinch/dash) against an *exact-identity* package row (`ct`/`ea`/jar…) is `on_hand`: `from_pantry` and `to_buy` are both `None`, it is summarised in one closing "Assumed on hand — …" plain bullet, and it is never a pull or a decrement — `allocate_pull_sources` would otherwise `_convert` ct↔tsp and raise. Identity for credit is `lib/shopping_identity.shopping_identity`, which drops only descriptors that don't change the product; a broad match whose `fdc_local.query_head` differs is a plain buy, not a review.

- [ ] **Step 5: Add a Done row to `docs/plans/INDEX.md`** (top of the Done table), with this plan's link, the date, the PR link, and the before/after table numbers.

- [ ] **Step 6: Full suite + ruff**

Run: `.venv/bin/python -m pytest -q -x --ignore=tests/e2e 2>&1 | tail -3` and `.venv/bin/ruff check . | tail -1`
Expected: no new failures (baseline: the corpus-schema test may fail on live data, which is pre-existing); ruff ≤ 162.

- [ ] **Step 7: Commit, push, PR**

```bash
git add scripts/measure_shopping_list.py CLAUDE.md docs/plans/INDEX.md docs/superpowers/plans/2026-11-12-shopping-list-true.md
git commit -m "docs(shopping): on-hand tier invariant, measurement script, results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin feat/shopping-list-true
```

Open the PR with the before/after table, the hand-check list, and the out-of-scope items above. After merge: restart `com.kitchenos.api`.
