# Inventory Review (browse-first) — Design

**Date:** 2026-07-10
**Surfaces:** Web page (`/inventory`) + generated `Inventory.md`
**Status:** Ready for Implementation

## Goal

Give a genuinely usable way to **review what's in inventory** — search, filter,
and skim by culinary role and freshness — so questions like "what do I have to
make a smoothie?" are answerable at a glance. Today the only review surfaces are
a single flat 224-row `Inventory.md` table (sorted by storage category, no
search/filter, goes stale between regenerations) and a JSON API. Neither lets
you skim by what food actually *is*.

The driving example — "I want a smoothie, what do I have?" — is really a grouping
problem: the relevant items (frozen bananas/berries/peaches, greek yogurt, milk,
fresh fruit, juice) are scattered across the `frozen`, `produce`, `dairy`, and
`beverages` storage categories and across four locations. Grouping by culinary
role collapses them into `fruit` + `dairy` + `liquid`, which answers the question
without any recipe existing for it.

### Non-goals

- **Intent-driven suggestion** ("name a dish idea → propose what to combine even
  with no matching recipe") is a *separate* Phase 2 feature. Browse-first was
  chosen deliberately. The role classifier built here is the shared foundation it
  would build on, but no suggestion logic is built now.
- **No changes to the native iOS/iPad inventory screen.** Pruning/cleanup on that
  surface is covered by `2026-06-26-inventory-cleanup-screen-design.md`
  (Implemented). This design is web + markdown only.
- **Read-only browse.** Editing quantities/removing items stays where it already
  lives (native app, MCP tools, `/api/inventory/*` endpoints). This surface does
  not mutate inventory.

## Design principle alignment

- **Single DB truth** — both surfaces read `data/kitchenos.db` via the existing
  `read_inventory()`. No new source of truth; roles are computed at render time,
  not stored, so there is no column to keep in sync and no backfill.
- **Additive, never a chore** — the classifier is rules that run on read. Wrong
  guesses are visible in the output and fixed by editing one line in the map; no
  per-item upkeep.
- **Obsidian-native** — `Inventory.md` stays a generated, do-not-edit, read-only
  view; it just groups more usefully.

## Components

### 1. `lib/food_roles.py` — culinary-role classifier (shared core)

Pure-function module. An ordered list of `(role, keywords)` tried against the
lowercased item name; first match wins; fallback `"other"`.

```python
def classify(name: str) -> str: ...
```

Roles (culinary, not storage-based):

```
fruit · vegetable · protein · dairy · grain · fat_oil · sweetener ·
baking · spice_herb · condiment · liquid · beverage · snack ·
frozen_meal · nonfood · other
```

- `nonfood` deliberately captures dog food, magnesium citrate, psyllium husk, and
  household items so real ingredients can be visually separated from them.
- No schema change, no LLM, no backfill. Runs over whatever `read_inventory()`
  returns.
- The keyword map is the controlled vocabulary; per `lib/CLAUDE.md`, it lives in
  this module as the single definition both surfaces import.

### 2. Surface A — Web page `/inventory`

- New route `/inventory` in `api_server.py` serving `templates/inventory.html`
  via `open('templates/inventory.html').read()`, following the established
  `meal-planner` / `nutrition-review` / `system-health` pattern.
- **No new API endpoint.** The page fetches the existing `GET /api/inventory`,
  which already returns every item with `expiry_status`. The only backend change
  is enriching each item's dict in `api_inventory_list` with the computed `role`
  (one call into `lib/food_roles.classify`).
- Client-side rendered view over that JSON:
  - **Search box** — live substring filter across item name (and notes).
  - **Filter chips** — by role, by location (fridge/freezer/pantry/counter/other),
    and a freshness toggle (fresh / expiring-soon / expired) driven by the
    `expiry_status` already in the payload.
  - **Sort** — by name, by expiry date, or grouped by role.
  - **"Expiring soon" strip pinned at top** — same data buried in `Inventory.md`
    today, always current because it is live from the DB.
- Works on phone over Tailscale. Only limitation: requires the API to be up (same
  as the other web tools).

### 3. Surface B — improved `Inventory.md`

- Same generated file, same do-not-edit banner, regenerated on every
  `write_inventory()` (no change to *when* it regenerates).
- Structural change: group the table by **culinary role** (from
  `lib/food_roles.py`) instead of one flat storage-category sort. Keep the
  "⚠️ Expiring Soon" section at the top. Separate `nonfood` into its own trailing
  section so the pantry list reads as *food you can cook with*.
- Because both surfaces call the same classifier, they cannot disagree.

## Data flow

```
data/kitchenos.db
   │  read_inventory()  (lib/inventory.py — unchanged reader)
   ▼
InventoryItem[]  ──►  lib/food_roles.classify(name)  ──►  role per item
   │                                                          │
   ├── api_inventory_list: item.to_dict() + expiry_status + role ──► /api/inventory ──► /inventory web page
   │
   └── write_inventory(): render role-grouped table + nonfood section ──► Inventory.md
```

## Error handling

- Unknown/ambiguous item name → `role = "other"`; item still renders in an
  "Other" group (never dropped).
- Classifier is pure and total (always returns a string); it cannot raise on
  normal input, so neither surface can fail to render because of it.
- Web page degrades to the existing behavior if `/api/inventory` is unreachable
  (same failure mode as today's web tools); markdown surface is unaffected by API
  state.

## Testing

- `lib/food_roles.py` — unit tests: known items → expected roles, including
  `nonfood` cases (dog food, magnesium citrate, psyllium husk) and real ambiguous
  items from current inventory (`spinach rice`, `caramelized onions`,
  `frozen vegetable broth`).
- `Inventory.md` regeneration — test asserts role-grouped output structure and
  that `nonfood` items land in the trailing section.
- Web page — manual verification via the `verify` skill against live data
  (search, each filter chip, sort modes, expiring-soon strip).

## Future: Phase 2 (documented, not built)

Intent-driven "what can I make" — user names a dish idea; KitchenOS proposes what
on-hand items to combine even when no vault recipe matches. Builds directly on
`lib/food_roles.py`: the smoothie case becomes "surface `fruit` + `dairy` +
`liquid` items, ranked by freshness." Separate spec when pursued.
