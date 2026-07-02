# Shopping List Cleanup — Design Spec

**Date:** 2026-07-02
**Status:** Approved design, pending implementation plan
**Scope:** Shopping-list *generation* pipeline only. Recipes are not modified.

---

## Problem

The generated weekly shopping list (`vault/KitchenOS/Shopping Lists/2026-W27.md`, the
acceptance fixture) is unusable: ~170 flat alphabetical lines full of noise. Four
independent root causes, all in the generation pipeline:

1. **No inventory subtraction by default.** `generate_shopping_list` only subtracts a
   pantry when one is explicitly loaded (interactive CLI). The API/normal path produced
   W27 with items already in the kitchen (`red onion`, `feta`, staples) still on the list.
2. **Grouping keys off the raw ingredient string** (`normalize_item_name` = lowercase+strip).
   So `red onion`, `onion`, `small red onion`, `1 of a large red onion`, `2 whole red onion`
   are all separate lines and never consolidate.
3. **Descriptor noise flows straight through** from recipe ingredient tables:
   `(inferred)`, `(optional)`, `(not shown)`, `, thinly sliced`, `(75-80 ml)`, `to taste`,
   trailing `*`. `to taste` even mis-parses into fake amounts (`2 to tastes salt`).
4. **Amounts summed into nonsense.** Tiny/`to taste` spice amounts summed across recipes
   into absurd precise totals (`15.25 tsp salt`, `14 tsp garlic powder`, `3.17 tbsp onion
   powder`, `1.29 cups mayo`). A shopping list should say what you put in the cart, not a
   summed decimal.

## Goal

Rework generation so the list is: consolidated (clean names, one line per real item),
inventory-aware (drop what the kitchen already has), expressed in **shoppable quantities**
(rounded up to how you buy it — `1 jar`, `5 lb`, `1 dozen`), and **grouped by store
category**.

---

## Locked decisions (from brainstorming)

1. **Inventory filter — one unified rule, always on.** Drop any item — staple or not —
   that current kitchen inventory (`data/kitchenos.db`) covers; reduce partially-covered
   items; keep everything else, **including staples not tracked in inventory** (e.g. buy
   cumin if you have no cumin on hand). Staples are *not* auto-assumed present. This differs
   from the "staples always assumed" convention used elsewhere (Use-It-Up, seasonal); here
   the user explicitly wants inventory to be the single arbiter for the buy list.
2. **Name normalization — deterministic, no LLM.** Strip descriptors + a small hand-editable
   alias/synonym map. Merge obvious synonyms (`mayo`→`mayonnaise`), but do **not** merge
   distinct varieties (`red onion` ≠ `yellow onion`).
3. **Shoppable quantities — config table + category fallback.** A hand-editable
   `config/grocery_items.json` maps items to how you buy them; round needed amount up to
   whole packages; unknown items fall back to native-unit rounded-up.
4. **Layout — grouped by store category** using inventory's existing `CATEGORIES` vocab.

---

## Pipeline (data flow)

```
recipe ingredients (parsed from recipe tables)
  → normalize names          (NEW  lib/ingredient_normalizer.py)
  → aggregate within family  (existing lib/ingredient_aggregator.py — groups cleanly now)
  → subtract inventory       (existing lib/pantry split — now DEFAULT ON)
  → round up to package       (NEW  package rounding via config/grocery_items.json)
  → assign category           (NEW  from config/grocery_items.json + fallback)
  → render grouped template   (CHANGED templates/shopping_list_template.py)
```

---

## Components

### 3a. `lib/ingredient_normalizer.py` — NEW
Deterministic item-name cleanup. Pure functions, no I/O beyond loading the alias map.
- **Strip** parentheticals `(...)`, trailing prep clauses after the first comma
  (`red onion, thinly sliced` → `red onion`), noise tokens (`(inferred)`, `(optional)`,
  `(not shown)`, `to taste`, leading/trailing `*`, `optional:`), and leading article/size
  qualifiers where safe (`1 of a large red onion` → `red onion`).
- **Alias map**: small hand-editable JSON (same spirit/atomic-write pattern as
  `config/item_aliases.json`) mapping raw→canonical (`mayo`→`mayonnaise`,
  `limes juice of`→`lime juice`). Alias wins over the stripped form.
- The normalized name becomes the **grouping key** for aggregation, so descriptor
  variants collapse to one line.
- **Amount hygiene**: `to taste` / non-numeric amount junk is dropped to "no amount"
  rather than parsed as a number — kills the `2 tastes salt` garbage.
- Genuinely different items stay separate (no variety-merging — declined in brainstorming).

### 3b. `config/grocery_items.json` — NEW
One home per item, `by_item` + `by_category` + fallback (exact pattern of
`config/storage_locations.json` / `config/expiry_windows.json`). Carries **both** category
and package data so a single lookup drives grouping *and* rounding.

```json
{
  "by_item": {
    "mayonnaise": {"category": "pantry",  "buy_unit": "jar",   "package": "30 oz"},
    "potatoes":   {"category": "produce", "buy_unit": "lb"},
    "eggs":       {"category": "dairy",   "buy_unit": "dozen", "package": "12 ct"},
    "shredded cheddar cheese": {"category": "dairy", "buy_unit": "bag", "package": "8 oz"}
  },
  "by_category": {
    "produce": {"buy_unit": "lb"},
    "dairy":   {"buy_unit": "each"},
    "meat":    {"buy_unit": "lb"}
  }
}
```

- `package` (when present, expressed in a `lib/units.py`-convertible unit) is the pack size
  used to round up: need `1.5 cups mayonnaise` → convert to the package's unit → round up to
  `1 jar (30 oz)`.
- Hand-correctable, atomic writes, seeded with ~30–40 of the most common items from the
  recipe corpus so it's useful day one.

### 3c. Package rounding — helper (in `lib/ingredient_aggregator.py` or a small new module)
After inventory subtraction, convert each remaining need to whole packages via
`grocery_items.json` + `lib/units.py`, rounding **up**. Missing config entry →
native-unit rounded-up (e.g. `4.4 lb` → `5 lb`), never a crash.

### 3d. Inventory subtraction — DEFAULT ON (`lib/shopping_list_generator.py`)
Change `generate_shopping_list` / `generate_shopping_list_from_path` to load DB inventory
by default (via `lib.pantry.load_pantry()`), rather than only when a caller passes one.
- Fully covered line → dropped. Partially covered → reduced to the shortfall.
- Existing `--no-pantry` CLI flag and an API opt-out still bypass it.
- Existing cross-family mismatch `warning` from `split_against_pantry` is preserved.
- This is the mechanism implementing locked decision #1.

### 3e. `templates/shopping_list_template.py` — CHANGED
Render `###` sections in a fixed store order — Produce, Meat & Seafood, Dairy, Bakery,
Pantry, Frozen, Beverages, Household, Other — using inventory's `CATEGORIES` vocab. Items
sorted within each section; empty sections omitted. Line format `- [ ] item — qty`
(em-dash separator). The two buttons (Add Ingredients, Send to Reminders) are unchanged.

---

## Output shape (what W27 becomes)

```markdown
# Shopping List - Week 27 (Jun 29 - Jul 5, 2026)

Generated from [[2026-W27|Meal Plan]]

### Produce
- [ ] red onion — 2
- [ ] potatoes — 5 lb

### Meat & Seafood
- [ ] chicken thighs — 4 lb

### Dairy
- [ ] shredded cheddar — 1 bag (8 oz)

### Pantry
- [ ] mayonnaise — 1 jar (30 oz)
```

Gone: `15.25 tsp salt`, `1.29 cups mayo`, `(inferred)`, duplicate onion/lime lines, and
anything the kitchen already stocks.

---

## Edge cases / decisions baked in
- **Unknown item** (not in config) → category `other`, native-unit rounded-up quantity.
- **`to taste` / no numeric amount** → item listed with no quantity, not a fake number.
- **Cross-family unit mismatch** during inventory split → preserved `warning`, item kept.
- **Deli / weight items** (`0.25 lb turkey`) → stay as weight; already shoppable.
- **Partial pantry coverage** → reduced to shortfall, then package-rounded.

---

## Testing
Unit tests per component, using the repo's `KITCHENOS_DB` tmp-fixture convention:
- normalizer: descriptor strip, alias merge, `to taste`/junk-amount handling, grouping-key
  collapse of onion/lime variants.
- package rounding: round-up correctness, package-unit conversion, unknown-item native
  fallback.
- category assignment: `by_item` → `by_category` → `other` resolution.
- grouped template render: section order, empty-section omission, line format.
- **Integration**: regenerate the W27 plan end-to-end and assert the four mess symptoms are
  gone (no summed-spice decimals, no descriptor noise, no duplicate variants, no
  inventory-covered items).

## Docs to update on completion
- `docs/ARCHITECTURE.md` — shopping-list pipeline flow (new normalize + package steps).
- `docs/OPERATIONS.md` — `config/grocery_items.json` and the alias map as hand-correctable
  configs; note inventory subtraction is now default-on.
- `CLAUDE.md` — only if a new cross-module invariant emerges (likely none).

## Out of scope
- Recipe ingredient tables themselves.
- Variety-merging (`red onion`→`onion`) — explicitly declined.
- LLM-based normalization or sizing — explicitly declined.
- Reminders / QuickAdd button behavior.

## Implementation note
Work happens on its own branch (per user instruction), cut at implementation time — not
during design or planning.
