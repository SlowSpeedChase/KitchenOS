# KitchenOS Roadmap

Unbuilt feature ideas worth keeping. These were salvaged from stale feature
branches before those branches were deleted — each entry records the source
branch + commit so the original implementation is recoverable from git's
reflog / object store (`git show <sha>`) until garbage-collected.

Audited 2026-06-24 against `main`. Branches whose every idea was already built
(`refine-local-plan`, `recipe-link-detection`, `recipe-update-system`,
`reprocess-button`) were deleted with nothing to preserve.

---

## Inventory: spatial zone + shelf layout

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec` (2026-04-25)
**Status today:** GAP. `main` has flat location categories only
(`fridge/freezer/pantry/counter/other` in `lib/inventory.py`).

Model the kitchen as a zone → shelf → group hierarchy instead of flat
categories. Items route to a specific shelf; `Inventory.md` and the UI group by
shelf. Branch introduced `config/storage_locations.json` (declarative layout +
per-group defaults), `Location/Shelf/Group` dataclasses, and `route_item()`.

- Declarative kitchen-layout schema (zones, shelves, item groups)
- Per-shelf grouping in the rendered inventory + a sidebar zone picker
- Native equivalent: a Mac/iOS Inventory screen organized by zone/shelf

## Inventory: markdown receipt-paste ingestion

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** GAP. `main` ingests receipts only via email (`ingest_receipts.py`).

A second, manual ingestion path: paste a markdown table (Item / Qty / Unit /
Group / Location / Expires / Notes), preview the parsed + routed rows, then
commit. Branch had `lib/receipt_paster.py`, `manage_inventory.py --paste`, a
"Paste from Claude" web modal, and `POST /api/inventory/paste` + `/commit`
(preview-then-commit). Complementary to email receipts — good for ad-hoc adds.

## Inventory: expiry tracking + default expiry windows

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** PARTIAL. `InventoryItem.purchased` exists; no expiry concept.

Add an `expires` field to inventory items, auto-filled from per-group default
expiry windows (`default_expiry_days`) on add, with UI warnings as items
approach expiry. Branch logic: `apply_default_expiry(row, layout, today)`.

## Inventory: printable kitchen labels

**Source:** `claude/kitchen-inventory-system-EdBZI` @ `f19dcec`
**Status today:** GAP. No label generation in `main`.

Generate a printable `Kitchen Labels.md` (shelf/zone labels) from the layout
config. Branch had `templates/labels_template.py`, `manage_inventory.py
--labels`, and `scripts/generate_labels.py`. Lowest priority of the set.

---

## Ingredients: ML parser with confidence scoring

**Source:** `feature/ingredient-parsing` @ `9247a01` (2026-01-08)
**Status today:** GAP. `main` parses ingredients rule-based
(`lib/ingredient_parser.py` + `lib/ingredient_cleaner.py`); no confidence signal.

Add an ML parse path (`ingredient-parser-nlp`, needs Python 3.11+) that returns
`{amount, unit, item, preparation, confidence}` per ingredient and flags rows
below a confidence threshold (~0.8) for review. Branch had
`lib/ingredient_normalizer.py`, a batch `normalize_ingredients()`, and edge-case
tests.

**Recommended framing:** not a replacement — an *optional fast-path*. Use the ML
parser for simple lines; fall back to the existing regex + cleaner (which already
emits explicit `needs_review` flags) for low-confidence / edge cases. The two
approaches are complementary: probabilistic vs. defensive-rule-based.

---

## Meal plan: timed calendar events

**Source:** `feature/timed-meal-events` @ `bbb5ec1` (2026-01-10)
**Status today:** PARTIAL. Snacks are fully built (template, parser, count,
Swift `MealSlot.snack`). The calendar export is the gap.

`main`'s calendar sync (`lib/ics_generator.py` / `sync_calendar.py`) emits a
single all-day event per day. Branch emitted separate 30-minute timed events per
meal slot (breakfast 8:00, lunch 12:00, snack 15:00, dinner 19:30) marked
`TRANSP: TRANSPARENT` (shown as free). Makes the meal plan readable as an actual
day schedule in any calendar app.

> Note: the branch also *removed* `MealEntry` / `flatten_to_recipes()` from the
> parser — that drops composite `[[Meal: Bundle]]` expansion and is a
> regression, **not** part of this roadmap item. Only the timed-event ICS change
> is worth porting.
