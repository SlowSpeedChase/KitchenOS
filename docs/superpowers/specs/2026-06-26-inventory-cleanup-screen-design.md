# Inventory Cleanup Screen — Design

**Date:** 2026-06-26
**Surface:** Native iPad/iOS app (`KitchenOSSiri/`)
**Status:** Approved

## Goal

Make it easy to **prune inventory** — remove items that are no longer good
(expired/spoiled) or no longer in storage (used up) — from the native app's
inventory screen. Surface **date added (purchased)** and **expiration** per item
so the user can see at a glance what to clean up.

The existing `InventoryView` already supports add, per-item quantity stepper, and
swipe/trash delete, grouped alphabetically by category. It shows only
qty/unit/location — no dates, and the Swift model has no `expires` field at all.
This feature adds dates + expiry badges and tightens the cleanup flow. It does
**not** change the web meal-planner.

This stays within the established inventory design principle (additive, not a
chore; items auto-age-out on expiry): manual removal is a complement to, not a
replacement for, the automatic pruning.

## Components

### 1. Backend — expose computed expiry status

`GET /api/inventory` (in `api_server.py`, `api_inventory_list`) already returns
`purchased` and `expires`, but not a status flag. Add an `expiry_status` field to
each item in the response, computed by the existing
`lib/expiry.py:expiry_status()`.

- That function already reads thresholds from `config/expiry_windows.json` and is
  the same logic `Inventory.md` uses, so the app badges and the markdown view
  cannot drift.
- Values: `"expired"`, `"soon"`, or `null`/absent (ok / no expiry).
- Roughly 2 lines: compute per item and merge into the `to_dict()` payload.
- No change to request shape or filters; the field is additive, so existing
  consumers (incl. the Swift client) are unaffected.

### 2. Data model — add `expires` + `expiryStatus` (Swift)

In `KitchenOSKit` `Models.swift`, `InventoryItem` currently has `purchased` but no
`expires`. Add:

- `expires: String?` — ISO date string, decoded from the API.
- `expiryStatus: String?` — decoded from the new `expiry_status` field;
  `"expired"`, `"soon"`, or `nil`.

The `id` computed property (`name|unit|location`) is unchanged.

### 3. Row UI — dates + badges (`InventoryView.swift`)

Each row keeps name, quantity stepper, unit, and delete affordance, and gains a
**secondary line** beneath the name:

```
Whole milk                    [ − 1 + ]  1 gal  🗑
Added Jun 13 · Expired Jun 23 🔴
```

- **Added**: short date from `purchased`; omit the segment entirely if `purchased`
  is `nil`.
- **Expiry**: short date from `expires` with a trailing badge — 🔴 for
  `expiryStatus == "expired"`, 🟡 for `"soon"`, none otherwise. When `expires` is
  `nil` (shelf-stable / staples / household), show **"No expiry"** instead of a
  date.
- Date formatting: medium/short style (e.g. "Jun 13"); a relative phrasing
  ("Expired 3d ago") is acceptable but not required — keep it simple.

**Sort within each category section:** expired → soon → everything else (then the
existing order). Category grouping is preserved; the items worth tossing rise to
the top of their own group.

### 4. Removal flow

- Keep both existing paths: trash button and swipe-to-delete, each calling
  `POST /api/inventory/remove` (hard delete), then reloading the list.
- **New:** stepping an item's quantity down to **0** removes the item (calls
  `/api/inventory/remove`) instead of leaving a zero-quantity row. This is the
  "used it up" path.
- No new confirmation dialogs — removal is cheap and receipts re-add items
  automatically.

## Data flow

```
InventoryView.load()
  → GET /api/inventory                       (now includes expiry_status)
  → decode [InventoryItem]                    (now includes expires + expiryStatus)
  → group by category, sort expired→soon→rest within each
  → render rows with Added / Exp secondary line + badge

Remove (trash / swipe / stepper→0)
  → POST /api/inventory/remove {name, location}
  → reload

Quantity change (stepper, >0)
  → POST /api/inventory/update {name, quantity, location}
  → reload
```

## Error handling

- API failures on load: existing behavior (show prior list / empty); no regression.
- Remove/update failures: surface the existing error path; reload reflects true
  server state.
- Malformed/absent `expires` or `expiry_status`: treated as "no expiry" — the row
  renders "No expiry", never crashes on date parsing.

## Testing

- **Backend:** unit-test `api_inventory_list` returns `expiry_status` matching
  `expiry_status()` for expired, soon, and no-expiry items (extend existing API
  tests). Confirm the field is additive and filters still work.
- **Swift:** decode `InventoryItem` with and without `expires`/`expiry_status`
  present (back-compat). Verify the secondary-line string builder: with date +
  status, with date + nil status, with nil expires ("No expiry"), with nil
  purchased (Added omitted).
- **Sort:** within a category, an expired item precedes a soon item precedes an ok
  item.
- **Manual:** on iPad, confirm badges match `Inventory.md`, swipe/trash/stepper-to-0
  all remove and reload.

## Out of scope

- Web meal-planner inventory UI (separate surface).
- Editing expiry/purchased dates from the app (still receipt/auto-driven).
- Soft-delete / archive (removal stays a hard delete, per existing backend).
- Bulk "clear all expired" action (could be a future enhancement).
