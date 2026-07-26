# See where inventory is stored

**Status:** Ready for Implementation · **Branch:** `inventory-location-visibility` · **Date:** 2026-07-26

## Problem

Every inventory row already carries a storage location — `fridge`, `freezer`, `pantry`,
`counter`, `other` (`lib/inventory.py:26`), part of the row's `(name, unit, location)`
uniqueness key. `Inventory.md` renders it as a table column (`lib/inventory.py:198`). The
iOS app and the receipt pipeline both set it.

The `/review` page never shows it. `subline()` (`templates/review.html:157`) builds each
row from expiry and, in Added order, the date added. `it.location` is in the JSON payload
but is used only to compute the merge key and to populate the "Move to" chips inside the
⋮ menu. So the page you actually use to put groceries away is the one page that can't tell
you where something is filed, and a mis-filed item is invisible until you go looking for it
in the wrong cupboard.

Sorting offers Expiry and Added. Neither groups by location, so even with the value
displayed there is no way to scan a location as a block.

### What the data actually looks like

222 inventory rows. By storage location: `pantry` 180, `freezer` 20, `fridge` 11,
`other` 7, `counter` 4.

That 180 looks alarming, because `pantry` is also the string `resolve_location` returns
when nothing matches. It is not, in fact, mostly guesswork. Classifying every row by which
tier of `config/storage_locations.json` resolved it:

| Tier | Rows | Assessment |
|---|---|---|
| `by_item` (29 hand-curated overrides) | 16 | authoritative |
| `pantry → pantry` | 159 | sound — shelf-stable goods belong in the pantry |
| `frozen → freezer` | 15 | sound |
| `dairy` / `produce` / `meat → fridge` | 11 | sound; onions and potatoes are already `by_item` exceptions |
| `household → other` | 7 | sound |
| `beverages → pantry` | 7 | coarse but defensible |
| `other → pantry` | 7 | **a shrug** — `other` is the catch-all category |
| bare `default` fallback | 0 | unreachable |

The bare fallback is unreachable because `by_category` has a rule for all ten values of
`lib/inventory.CATEGORIES`, and `normalize_category()` always yields one of those ten. Any
design that treats "hit the `default` fallback" as the signal for *we don't know* is
therefore dead on arrival — it would render on nothing, now or ever.

The real unknown is narrower and differently shaped: a row whose *category* is the
catch-all `other` has no meaningful category, so a location derived from that category is
not an answer. Seven rows today, and the natural home for every future item the
categoriser can't place.

## Approach

Show the location on every `/review` row, add a Location sort mode that groups rows under
headers, and record on each row *how* its location was decided so a machine guess is
distinguishable from a placement you confirmed yourself. Corrections teach
`config/storage_locations.json`, so the same wrong guess stops recurring on future
receipts.

Decisions, and what they ruled out:

| Decision | Rejected alternative |
|---|---|
| Store provenance in a `location_source` column | Deriving it at read time — re-runs the resolver on every page load, and a row's confidence silently flips when the config is edited |
| One `place_item()` router owning the tier ladder | Widening `resolve_location()` to return a tuple — breaks a public contract and its tests, and forces every future caller to unpack a value most don't want |
| Record all four tiers, render two states | A bare confirmed/unconfirmed boolean — same storage cost, less room to tune |
| A `by_category` hit on the catch-all `other` reports `default` | Treating every category rule as an answer (marks nothing); treating none of them as answers (marks 206 of 222 rows) |
| Category guesses are trustworthy | Requiring a hand-curated `by_item` hit before a row counts as placed |
| Teach `by_item` on every manual move | Leaving the config hand-edited — the same guesses recur on every future receipt |
| `freeze` stamps the row but does not teach | Teaching from freeze — permanently files bread in the freezer the first time you rescue a loaf |
| Longest matching `by_item` key wins | First dict-order match — degrades as teaching grows the table |
| Subline text + optional grouping | Emoji-only chip (subtler to scan); grouping alone (no per-row answer) |

## Design

### Part 1 — `location_source` on the row

One column, `location_source TEXT`, appended to `inventory` through the existing
`_MIGRATIONS` dict (`lib/inventory_db.py:122`). SQLite `ADD COLUMN` is append-only and
`connect()` already applies it to any DB missing it — no table rebuild. The column joins
`_INVENTORY_COLS` (`lib/inventory_db.py:115`) so it round-trips through
`replace_inventory_rows()`, and `InventoryItem` gains `location_source: str = "default"`.

`merge_key()` is untouched. Row identity stays `(name, unit, location)`; provenance is an
attribute of a row, not part of its address.

No API route changes are needed. `fetch_inventory_rows()` selects `_INVENTORY_COLS`, and
both `/api/inventory` and `_serialize_item` (`api_server.py:2296`) shape their payload
through `InventoryItem.to_dict()`, which is `asdict(self)` (`lib/inventory.py:53`). Adding
the dataclass field carries it to the client everywhere at once.

Four values:

| Value | Meaning |
|---|---|
| `manual` | you placed it — a move, a freeze, or an explicit `location` in an API call |
| `item` | a hand-curated `by_item` override matched |
| `category` | a `by_category` rule matched a real category |
| `default` | nothing meaningful matched |

Only `default` renders as unsure.

**Backfill.** The migration classifies existing rows once by running `place_item()` over
each name and category, touching only rows where `location_source` is NULL. Re-running is
a no-op, and it never re-derives a row you have since hand-placed. On today's data this
yields 16 `item`, 199 `category`, and 7 `default`.

**A NULL reads as `default`.** Anything that escapes the backfill surfaces for review
rather than posing as confirmed. The failure direction is always toward being asked.

### Part 2 — the placement router

`lib/storage_locations.py` gains:

```python
@dataclass(frozen=True)
class Placement:
    location: str   # a LOCATIONS value
    source: str     # "item" | "category" | "default"

def place_item(name: str, category: str | None = None) -> Placement: ...
```

`place_item` owns the tier ladder. `resolve_location()` becomes
`place_item(name, category).location` — an identical contract, so
`tests/test_storage_locations.py` and all four existing callers keep working untouched.

A missing or empty `category` behaves the same as the catch-all: `by_item` still gets its
chance, and failing that the result is `pantry` with `source="default"`.

Two behavioural changes live in the router:

1. **The catch-all category is not a match.** A `by_category` hit where the category is
   `other` returns `source="default"`. "We couldn't categorise this" is not a placement
   answer, and this is what makes the `default` tier reachable at all. `normalize_category()`
   (`lib/inventory.py:61`) funnels every unrecognised value to `other`, so this is exactly
   the set of rows the categoriser gave up on — today: pet food, three supplements, and a
   bag of tortilla chips.

2. **Longest matching key wins.** The `by_item` subset scan
   (`lib/storage_locations.py:77`) currently returns the first dict-order key whose words
   are all contained in the item name. At 29 hand-written entries that is harmless. Teaching
   on every move grows the table toward hundreds, at which point `milk → fridge` starts
   capturing `milk chocolate chips`. Selecting the longest match makes the most specific
   rule win, and without it the feature slowly poisons its own lookup table.

### Part 3 — write paths

Five row-creating sites move from `resolve_location` to `place_item` and pass the resulting
source into `InventoryItem`:

| Site | Source recorded |
|---|---|
| `lib/receipt_ingest.py:104` | from `place_item` |
| `ingest_csa.py:92` | from `place_item` |
| `lib/receipt_paster.py:99` | from `place_item` |
| `api_server.py:2088` (`/api/inventory/add`) | `manual` when the body carries an explicit `location`, otherwise from `place_item` |
| `seed_pantry_staples` (`lib/inventory.py:336`) | `item` |

Staples record `item` because `config/pantry_staples.json` is hand-authored — recording
them as `default` would push several dozen deliberately-listed staples into the review
queue.

**Merge precedence.** `add_items` sums quantities when a purchase lands on an existing row,
and the two rows can disagree about provenance. The winner is `manual` > `item` >
`category` > `default`, so restocking something you hand-placed never downgrades it back to
a guess.

**Teaching.** `move_item()` (`lib/inventory.py:788`), `_apply_move()`
(`lib/inventory.py:586`) and the bulk `to_location` path stamp `location_source="manual"`
and call the existing, currently-uncalled `save_item_override()`
(`lib/storage_locations.py:90`).

`freeze_item()` (`lib/inventory.py:810`) stamps `manual` but does **not** teach. It clears
the row's expiry, which marks it as rescuing one item from spoiling rather than declaring
where that food lives.

Teaching runs inside a `try`/`except` after the row is written. `save_table()` already uses
`tmp + replace`, so a failed write leaves the previous table intact: you lose the lesson,
never the correction.

`config/storage_locations.json` is git-tracked, so each correction leaves a one-line diff
in the working tree. That is intended — the overrides become reviewable history rather than
invisible state — but it does mean `git status` is dirty after a put-away session.

### Part 4 — the `/review` page

**Subline.** The location leads, ahead of the expiry:

```
❄️ fridge · exp 2026-07-27 🟡 soon
🫙 pantry? · no expiry
```

A `default` row takes a question mark, with a `title` attribute explaining that nothing
matched. Location glyphs are fridge ❄️, freezer 🥶, pantry 🫙, counter 🧺, other 📍 — chosen
not to collide with the category emoji at `templates/review.html:95`, where `frozen` is
already 🧊.

**Grouping.** A third `Location` option joins the `#sortby` select, persisting through the
same `reviewSort` localStorage key as the existing modes. `SORTS.location` orders by the
`LOCATIONS` vocab order (`templates/review.html:99`), then unsure-first, then delegates to
the existing expiry comparator — so each block opens on the rows that actually want a
decision.

Headers render only in this mode, as non-selectable `<li class="group">` rows carrying a
count:

```
🫙 pantry — 180 · 7 unsure
```

They are emitted wherever the location changes between consecutive rows, in both `load()`
and `resort()` (`templates/review.html:330`), so one code path builds them. Select-all and
the bulk count skip them.

**Moves re-home their row.** `keyOf()` includes location (`templates/review.html:116`), so
a move changes a row's identity. The bulk path already handles this by clearing selection
and calling `load()` (`templates/review.html:258-262`); the single-row path does not — it
patches in place via `applyUpdate()` and leaves the `rows` Map under the stale pre-move key.
Since a move now also changes which block a row belongs to, single moves adopt the same
full-`load()` path and then flash the row under its new key. That unifies the two paths and
fixes the stale-key bug rather than adding a second way to be wrong.

### Part 5 — `Inventory.md`

The generated view already has a Location column. Its cell gains the same `?` suffix on
`default` rows. No other change.

## Testing

`tests/test_storage_locations.py` — a case per tier of the ladder; the catch-all `other`
category reporting `default`; longest-key-wins when two `by_item` keys both match; and a
regression test proving `resolve_location`'s return values are unchanged.

`tests/test_inventory.py` — merge precedence across all four sources; move stamps `manual`
and teaches; bulk move teaches every affected item; freeze stamps `manual` and does not
teach; a failed `save_item_override` still commits the move.

`tests/test_inventory_db.py` — the column is added to a DB that lacks it, backfill
classifies NULL rows only, and re-running the migration changes nothing.

Browser test — the location renders in the subline, group headers appear only in Location
mode, a `default` row shows `?`, and a single move re-homes its row into the destination
block.

Manual, from a phone on the tailnet: switch to Location, confirm each block's header count
matches its rows; move an item out of the pantry block and watch it land under the correct
header; confirm `config/storage_locations.json` gained a matching `by_item` entry; re-run a
receipt ingest of that same item and confirm it now files correctly on the first pass.

Restart the API LaunchAgent after implementation — `lib/` and template edits are held in
memory (`com.kitchenos.api`), and stale code shows up as behaviour that looks like a data
bug.

## Out of scope / follow-ups

- **The iOS app.** It reads the same API and would show the new field for free, but no
  Swift-side work is planned here.
- **The parked zone/shelf layout.** `place_item` is the seam it needs: a richer placement
  becomes a wider `Placement` return value rather than a rewrite of five call sites.
- **`beverages → pantry`.** Coarse — some belong in the fridge. Left as a category-tier
  answer rather than flagged, on the reasoning that per-rule confidence flags are config
  complexity bought for seven rows. Revisit if the guesses prove annoying in use.
- **Pruning the taught `by_item` table.** Teaching only grows it. Longest-key-wins keeps
  growth safe, but there is no compaction pass and no way to un-teach from the UI.
- **The concurrent-writer lost-update window** at `lib/inventory.py:308`, unchanged here.
