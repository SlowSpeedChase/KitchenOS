# Bulk select and edit on the inventory review page

**Status:** Ready for Implementation · **Branch:** _(not yet started)_ · **Date:** 2026-07-25

## Problem

`/review` (`templates/review.html`) gives each inventory row `Remove | +3d | +7d | ⋮`,
where `⋮` opens a menu for set-expiry-date, clear-expiry, freeze, move-to-location, and
set-category. That works well for a single item, but all four real workflows are plural:

- **fridge/pantry cleanout** — bulk remove
- **post-receipt cleanup** — 30 items land with wrong categories and locations
- **freezer batch** — move a group to the freezer at once
- **expiry sweep** — fix a batch of missing or wrong dates

Each means N trips through the row menu today.

## Approach

**Bulk means one action applied to many items, in one write.** Not a general-purpose
multi-edit form. The action set is exactly the one a row already has, so there is no new
vocabulary to learn: the selection bar mirrors a row's own controls, and `⋮` opens the
*same* menu, applied to the selection.

Decisions, and what they ruled out:

| Decision | Rejected alternative |
|---|---|
| Plain checkboxes + one Select All | Filter chips, group-header checkboxes, tap-first/tap-last range select |
| Sticky bottom bar mirroring a row (`Remove +3d +7d ⋮`) | A bottom sheet listing every action flat; a single `Actions ▾` button putting Remove one level down |
| Undo toast restoring all removed items | A confirm dialog before bulk remove — adds a tap to the most common action, and a wrong confirm is unrecoverable |
| One batch endpoint, one read-modify-write | The client looping the existing per-item endpoints |

The selection aids were cut on the user's call: plain checkboxes only, even for the
30-item receipt case.

**Why a batch endpoint and not a client loop.** Every mutation does `read_inventory()` →
mutate → `write_inventory()`, and `write_inventory` (`lib/inventory.py:246`) replaces the
whole inventory table, rewrites `Inventory.md`, *and* regenerates `Cook Now.md` (which
scans the recipe library). 20 items via the existing routes = 20 table replacements and 40
note regenerations. `freeze_item` (`lib/inventory.py:525`) is worse — it calls `move_item`
→ `set_category` → `set_expiry`, each with its own read and write, so a single freeze is
already 3 replacements and 6 regenerations with no atomicity between them. There is also a
correctness reason: `lib/inventory.py:308` carries a standing TODO that read-modify-write
loses updates with concurrent writers (Flask threads + the ingest LaunchAgent), so a client
firing bulk edits in parallel would actively drop them.

**Item addressing is fixed as part of this work.** The table's uniqueness key is
`(name, unit, location)` (`lib/inventory_db.py:51-64`), but every existing endpoint
addresses rows by `(name, location)`. The two disagree, and the current code handles the
disagreement inconsistently: `remove_item` deletes *every* name+location match, while
`set_expiry` / `set_category` / `extend_expiry` / `move_item` update only the *first*. On
one item that is latent; on fifteen it is data loss. The bulk path addresses rows by the
real key, which `InventoryItem.merge_key()` (`lib/inventory.py:46`) already returns and
`/api/inventory` already ships (`to_dict()` is `asdict()` over a dataclass including
`unit`). Existing single-item routes keep their current signatures and semantics — their
tests pin that behavior, and changing it is not in scope.

## Design

1. **Pure mutators** (`lib/inventory.py`) — extract the mutation logic out of the
   read/write wrappers into in-memory helpers that take the item list plus the matched
   items, mutate in place, and do no I/O: `_apply_remove`, `_apply_extend`,
   `_apply_set_expiry`, `_apply_set_category`, `_apply_move`, `_apply_freeze`.
   `_apply_move` preserves the destination-merge rule documented at
   `lib/inventory.py:475-522` (colliding rows sum quantities, source row dropped); with a
   multi-item selection two selected rows can now merge into the *same* destination, so
   matches are processed sequentially against the shared list.

2. **`bulk_apply(action, refs, **params)`** (`lib/inventory.py`) — one `read_inventory()`,
   resolve every `{name, unit, location}` ref through `merge_key()`, dispatch to the
   `_apply_*` helper, one `write_inventory()`. Returns
   `{applied, items, removed, not_found}`.

   A ref must carry all three fields; `unit` and `location` are required, not optional.
   That is the whole point of the addressing fix, and the client always has them because
   `/api/inventory` returns them. A ref missing either field is a 400, not a
   fall-back-to-`(name, location)` match — silently widening the match is exactly the bug
   being fixed. `items` carries the updated rows for every action except `remove`;
   `removed` carries the full pre-delete rows for `remove` and is empty otherwise. Both
   keys are always present so the client never branches on their absence.

3. **Single-item functions become thin wrappers** over the same helpers — read, resolve
   the first `(name, location)` match (all matches, for `remove_item`), apply, write. One
   source of truth for the merge logic, every existing test preserved, and `freeze_item`
   collapses from three write cycles to one.

4. **API** — `POST /api/inventory/bulk`, ungated like its `/api/inventory/*` siblings.
   Body `{action, refs, days?, expires?, category?, to_location?}` where `action` is one of
   `remove | extend | set-expiry | set-category | move | freeze`. 400 on missing/invalid
   action, empty `refs`, or a missing action parameter. Refs matching nothing go into
   `not_found` rather than 404-ing the call — the client's list can be stale, and one dead
   ref must not discard 13 good edits. Items are serialized through the existing
   `_item_response` shape so bulk and single responses are identical.

5. **Selection UI** (`templates/review.html`) — checkbox per row, selection held in a `Set`
   keyed by the merge key (not DOM position, so it survives a re-render); Select All in the
   header with an indeterminate state; `#bulkbar` sticky at the bottom, hidden while the
   selection is empty, rendering `N selected ✕ | Remove | +3d | +7d | ⋮`.
   `openMenu(it, li, anchor)` is generalized to take a target that is either one item or
   the selection, rather than growing a second menu builder — with one behavior change,
   that a heterogeneous selection has no single current value, so all locations and
   categories are shown instead of skipping the item's own. Results patch into rows via the
   existing `applyUpdate`; a non-empty `not_found` triggers a full `load()`. Undo POSTs the
   returned `removed` rows to the existing `/api/inventory/add`, exactly as the single-item
   undo at `templates/review.html:261-271` already does.

## Testing

`tests/test_inventory.py` — `bulk_apply` per action, two selected rows merging into one
destination on bulk move, partial `not_found`, and single-item behavior unchanged.

`tests/test_api_endpoints.py` — bulk route contract and validation, including the 400 on a
ref missing `unit` or `location`.

Manual, from a phone on the tailnet: bulk `+7d` on 3 items advances all three in one
refresh; bulk move to freezer merges two same-name/same-unit rows with summed quantity;
bulk remove of 5 then Undo restores all five with original quantity, unit, category,
location, and expiry, and `select count(*) from inventory` returns to its starting value.

## Out of scope / follow-ups

- Giving `InventoryItem` a stable `id`. The DB has one, but `write_inventory` does
  delete-and-reinsert so ids churn on every write; addressing by `merge_key()` is the
  correct fix at this size. A real id would need a migration.
- Migrating the single-item routes to `(name, unit, location)` addressing.
- The concurrent-writer lost-update TODO at `lib/inventory.py:308` — `bulk_apply` narrows
  the window (one write instead of N) but does not close it. The fix is still
  `INSERT … ON CONFLICT` inside one transaction.
- Bulk quantity edit. Every other row action generalizes to a selection; setting one
  quantity across heterogeneous items does not.
