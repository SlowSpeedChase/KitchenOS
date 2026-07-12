# Inventory Scan & Extend (edit-first) — Design

**Date:** 2026-07-12
**Surfaces:** Web page (`/review`) + one new API route + a link in generated `Inventory.md`
**Status:** Ready for Implementation

## Goal

Give a fast, phone-friendly way to **walk the fridge/pantry and act**: skim
everything sorted by what's expiring soonest, and with one tap either **remove**
an item (it's gone/used up/tossed) or **add more time** to it (it's still good).
Today the app can change quantity or delete an item, but there is **no way to
extend an item's expiry** — `expires` is only auto-computed at add-time — and no
review surface sorted by freshness that is reachable from Obsidian on a phone.

The driving moment: standing at the open fridge, phone in hand, wanting to clear
out what's dead and give a few more days to what's fine — without typing.

### Non-goals

- **Not the browse page.** A separate, still-unbuilt design
  (`2026-07-10-inventory-review-design.md`) covers a read-only `/inventory`
  browse surface (search, filter, culinary-role grouping, "what can I make").
  That answers *"what do I have?"*; this answers *"walk the fridge and act."*
  They are complementary surfaces on the same DB. This spec does **not** build,
  block on, or modify that page; a future implementer may share a template or
  fold them together, but that is out of scope here.
- **No new inventory data model.** No new columns. Extend reuses the existing
  `expires` column and the existing centralized write path.
- **No changes to the native iOS/iPad inventory screen.**
- **Not barcode/camera/voice.** Explicitly a quick-review list (decided during
  brainstorming).

## Design principle alignment

- **Single DB truth** — the page reads live inventory via the existing
  `GET /api/inventory`; every mutation funnels through
  `lib/inventory.py::write_inventory()` → `inventory_db.replace_inventory_rows()`.
  No parallel source of truth; `Inventory.md` and `Cook Now.md` regenerate for
  free on every write.
- **Additive, never a chore** — extend is a single tap; the page is generated
  live from the DB and never needs manual upkeep.
- **Obsidian-native** — `Inventory.md` stays a generated, do-not-edit view; it
  only gains one link at the top pointing at the live page.

## Components

### 1. Backend — `extend_expiry()` (the missing primitive)

New function in `lib/inventory.py`:

```python
def extend_expiry(name: str, days: int, location: str | None = None,
                  today: date | None = None) -> InventoryItem | None: ...
```

- Resolves the target row by `name` (+ optional `location`) using the same
  matching the existing `remove_item()` / `update_quantity()` use.
- Sets `expires = (today or date.today()) + timedelta(days=days)`.
  **"Add time" = today + N** (decided during brainstorming) — predictable
  "good for N more days from now," independent of the old date.
- **Works on no-expiry (shelf-stable) items too**: if `expires` was `None`,
  extend simply sets a fresh date `today + days`.
- Persists via the existing `write_inventory()` path so the vault view + Cook
  Now regenerate. Returns the updated item, or `None` if no row matched.

### 2. Backend — `POST /api/inventory/extend`

New route in `api_server.py`, placed with the other inventory mutation routes
(`add` l.1931, `remove` l.2107, `update` l.2122).

- Body: `{ "name": str, "days": int, "location": str | null }`.
- Calls `inventory.extend_expiry(...)`; returns the updated item dict (with
  recomputed `expiry_status`) or a 404-style `{ "ok": false }` if not found.
- **Ungated**, matching the sibling `add`/`remove`/`update` routes (which are
  **not** `@require_token`-decorated). The page therefore works over Tailscale
  with no token, consistent with the existing inventory surface.

### 3. Web page — `GET /review` + `templates/review.html`

New route serving a single self-contained page, following the established
`open('templates/<x>.html').read()` pattern (`meal_planner` l.1667,
`system_health` l.2442, `nutrition_review` l.2449).

- **Self-contained**: inline CSS + JS, no external dependencies. On load it
  `fetch`es `GET /api/inventory` (which already returns every item with
  `expiry_status`).
- **Sort order — soonest-expiring first**: 🔴 expired → 🟡 soon → ok →
  no-expiry last. Reuses the same status vocabulary as the app
  (`expired`/`soon`/`ok`).
- **Each row**: category emoji + name + expiry date/badge, then
  `[Remove] [+3d] [+7d]` buttons.
- **Remove** → `POST /api/inventory/remove` `{name, location}`, then a brief
  **Undo toast** (~5s). The page holds the removed item's full snapshot
  client-side (name, quantity, unit, category, location, purchased, expires,
  for_recipe); tapping **Undo** re-adds it verbatim via `POST /api/inventory/add`
  so a mis-tap restores the exact row.
- **+3d / +7d** → `POST /api/inventory/extend` `{name, location, days}`; on
  success the row's date text + badge update **in place** (no full reload) from
  the returned item.
- **Refresh control** to re-pull `/api/inventory` on demand.
- Works on phone over Tailscale (`http://100.111.6.10:5001/review`). Only
  limitation: requires the API to be up (same as every other web tool).

### 4. Obsidian entry point — link at top of `Inventory.md`

In `lib/inventory.py::render_inventory_md()`, add one markdown link in the
generated header block (immediately after the do-not-edit banner, above the
"⚠️ Expiring Soon" section):

```
**▶ [Open Review](http://100.111.6.10:5001/review)** — remove or add time, tap-to-act
```

- The base URL is built from a config value, not hardcoded in three places:
  reuse the existing host/port config the other web tools use (or a
  `KITCHENOS_WEB_BASE` env fallback to `http://100.111.6.10:5001`) so localhost
  vs Tailscale is one knob. Confirm the exact existing convention during
  implementation rather than inventing a second one.
- One tap from the note opens the live scan page in the phone browser.

## Data flow

```
data/kitchenos.db
   │  read_inventory()  (unchanged reader)
   ▼
GET /api/inventory  (item.to_dict() + expiry_status)  ──►  /review page
                                                              │  tap
   ┌──────────────────────────────────────────────────────────┤
   ▼ Remove                          ▼ +3d / +7d
POST /api/inventory/remove       POST /api/inventory/extend
   │                                 │  extend_expiry(name, days)  → expires = today+N
   ▼ (Undo → POST /add snapshot)     ▼
        write_inventory()  →  replace_inventory_rows()  →  regenerate Inventory.md + Cook Now.md
```

## Error handling

- **Item not found on extend/remove** (renamed/pruned since page load) →
  backend returns `{ ok: false }`; page shows a small inline error on that row
  and offers Refresh. Never silently no-ops.
- **Undo after the toast expires** → the toast is the only Undo affordance; once
  gone, the item is simply gone (re-add manually). Documented, acceptable.
- **Stale page vs concurrent change** (item edited elsewhere) → mutations target
  by `(name, location)`, the same identity the API already uses; a Refresh
  re-syncs. No optimistic-lock needed for a single-user tool.
- **API down** → page shows a load error and a Retry button; `Inventory.md`
  itself is unaffected (the link just won't open a live page).
- **API restart caveat** — editing `lib/inventory.py` / `api_server.py` /
  templates requires a `launchctl` reload of `com.kitchenos.api` or the server
  serves stale code (project invariant). Part of the test/deploy step.

## Testing

- **`extend_expiry()` unit tests** (against a temp `KITCHENOS_DB`):
  - sets `expires` to `today + days` for an item that already had an expiry;
  - sets a fresh expiry on a no-expiry (shelf-stable) item;
  - returns `None` when no row matches;
  - merge identity `(name, unit, location)` and other fields are untouched.
- **`POST /api/inventory/extend` route test**: happy path returns the updated
  item with recomputed `expiry_status`; unknown item returns the not-found shape.
- **`render_inventory_md()` test**: asserts the Review link appears in the header
  block above the Expiring-Soon section and uses the configured base URL.
- **Manual verification** via the `verify` skill against live data over
  Tailscale: load `/review`, confirm sort order, Remove + Undo restores the exact
  row, +3d/+7d update the badge in place, Refresh re-pulls. Reload the
  LaunchAgent first.

## Open items (resolve during implementation, non-blocking)

- **Extend amounts**: ship `+3d` and `+7d` (brainstorming default). A `+14d` or
  custom-entry control is a trivial later add if wanted — not built now.
- **Web base URL config**: confirm and reuse the existing host/port convention
  the other templates use rather than adding a parallel one.
