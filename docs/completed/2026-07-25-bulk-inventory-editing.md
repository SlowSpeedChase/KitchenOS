# Completed: Bulk Inventory Editing

**Completed:** 2026-07-25
**Branch:** bulk-inventory-editing
**Duration:** 1 day (started 2026-07-25)
**Design:** `docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md`
**Plan:** `docs/superpowers/plans/2026-07-25-bulk-inventory-editing.md`

## Summary

Mass select + edit on `/review`: per-row checkboxes, Select All, and a sticky
bar mirroring a row's own `Remove / +3d / +7d / ⋮` controls, backed by one
`POST /api/inventory/bulk` that does a single read-modify-write instead of N.

Two further changes landed mid-branch, both user-directed after the bulk work
was already review-ready: the `+3d` / `+7d` buttons became cumulative, and the
list gained a date-added sort.

## Key Changes

### 1. Bulk path addresses rows by the real uniqueness key (`lib/inventory.py`)

The DB's uniqueness key is `(name, unit, location)`, but every existing endpoint
addresses rows by `(name, location)` — and disagreed on what to do about it:
`remove_item` deleted *every* match while `set_expiry` / `set_category` /
`extend_expiry` / `move_item` updated only the *first*. Latent on one item, data
loss on fifteen.

Mutation logic was extracted into pure `_apply_*` helpers that mutate in memory
with no I/O. `bulk_apply()` does one `read_inventory()` → resolve refs by
`merge_key()` → dispatch → one `write_inventory()`. The single-item functions
became thin wrappers over the same helpers, so merge semantics have one source
of truth (`freeze_item` collapsed from 3 write cycles to 1).

**Scope guard held:** the single-item *routes* keep `(name, location)`
addressing and their current semantics; their tests pin that. Migrating them is
still an open follow-up.

### 2. `+3d` / `+7d` added time instead of resetting it (`lib/inventory.py`, `templates/review.html`)

Reported as "the add time buttons do nothing". They weren't broken.
`_apply_extend` set `expires = today + N` outright, so a second tap changed
nothing and `+3d` after `+7d` moved the date *backward*. On an inventory of
mostly 2027 dates, `+7d` also quietly pulled items ten months closer.

Now cumulative and computed **per row**: each advances from its own expiry,
falling back to today only when the row has lapsed, has no date, or has an
unparseable one — which preserves the guard the old behaviour existed for
(extending an expired row must not leave it expired). A staggered selection
stays staggered rather than collapsing onto one shared date.

Compounding the report: the row never re-sorted, so a rescued item stayed
pinned in the expired block. The list now re-sorts after an expiry change and
flashes the rows it moved.

This changed the **single-item** route too, not just bulk — it is shared code.

### 3. Sort by date added (`lib/inventory.py`, `templates/review.html`)

`purchased` is treated as the date-added stamp, so no migration was needed. It
was set on only 51 of 217 rows, so `add_items` now stamps today when creating a
row — but deliberately **not** on a merge, or re-ingesting a receipt would
present long-held stock as freshly bought. An explicit `purchased` still wins on
merge, which the receipt path relies on.

Rows predating the stamp sort last and read `added unknown` rather than being
backfilled with invented dates. Staples are unaffected: `seed_pantry_staples`
writes through `write_inventory`, not `add_items`, so they keep a null date —
correct for perpetual stock.

## Verification

The plan routed final verification through a 5-step manual phone script, on the
stated grounds that the repo has no JS test harness. **It does** — `tests/e2e/`
is a Playwright harness driving a real server against copies of the vault and
DB. All five steps became browser tests in `tests/e2e/test_bulk_inventory.py`,
so they stay verified instead of being hand-checked once. This mattered: the
~280 lines of new page JS had never been executed in a browser before that.

1426 → 1476 unit tests. E2E: 22 passed, 2 xfailed, 2 xpassed.

Also fixed a pre-existing race in `test_meal_planner_lists_recipes`, which
waited on the `#recipe-list` container (present in the static HTML, so it
resolved instantly) and then counted children before the fetch returned — it
passed or failed on cache warmth.

## Known Issue Left Open

**Undo cannot restore a deliberately cleared expiry.** The page's undo replays
removed rows through `POST /api/inventory/add`, and `add_items` auto-fills a
shelf-life expiry whenever `expires is None` — so an item whose expiry was
cleared via "🚫 Remove expiration" comes back dated (measured: a pantry item
returned with an expiry a year out). `POST /api/inventory/bulk` is **not** at
fault; its `removed` payload carries the null faithfully.

Pre-existing on main — the single-row remove path replays identically — but bulk
widens it from one row to a whole selection. Pinned as a **strict** xfail
(`test_undo_restores_a_deliberately_cleared_expiry`) so it flips to a failure
the day it is fixed. A real fix needs a way to add a row with an explicitly null
expiry, which is a contract decision beyond this branch.

## Follow-ups

- Migrate the single-item routes to `(name, unit, location)` addressing.
- The concurrent-writer lost-update TODO in `lib/inventory.py`: `bulk_apply`
  narrows the window from N writes to 1 but does not close it. Needs
  `INSERT … ON CONFLICT` in one transaction.
- Give `InventoryItem` a stable `id` (needs a migration; `write_inventory`
  delete-and-reinserts, so DB ids churn).
- Bulk quantity edit — every other row action generalizes to a selection;
  setting one quantity across heterogeneous items does not.
