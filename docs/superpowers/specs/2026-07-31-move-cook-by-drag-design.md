# Move a scheduled cook by dragging its card

**Status:** Ready for Implementation · **Branch:** `move-cook-by-drag` · **Date:** 2026-07-31

## Problem

The planner is already a drag surface. A recipe drags from the library shelf into a slot,
a serving chip drags between slots, into the freezer, or onto the trash. The one thing
that cannot move is the card representing the meal you actually scheduled.

`initGridSortables()` sets `draggable: '.grid-card:not(.cook-card)'`
(`templates/meal_planner.html:2406`). The exclusion is deliberate and the comment above it
explains why: the grid Sortable's `onAdd` falls through to `debounceSave()` →
`saveMealPlan()`, which PUTs scale-less legacy meal-plan data over ledger-authored
Markdown. Cook cards were kept out of that path rather than given one of their own.

The consequence is invisible until you look at when board mode engages. `renderBoardIfActive()`
sets `boardMode` as soon as the week holds one cook (`templates/meal_planner.html:2928`),
and board mode clears every legacy `.grid-card` before rebuilding from the ledger. So on
any week with a single meal on it — that is, every real week — the draggable cards are gone
and only the excluded ones remain. Moving Tuesday's chili to Thursday means removing it and
adding it again, which discards its scale, its verdict, and its cook note.

The backend for the move already exists in pieces: `PATCH /api/cooks/<id>` accepts `date`
and `meal` (`_COOK_FIELDS`, `lib/serving_ledger.py:41`), and `move_servings()` moves
placements. Nothing joins them.

### What already works

| Gesture | Wiring | Endpoint |
|---|---|---|
| Library recipe → slot | `initSidebarSortable` + grid `onAdd` recipe branch | `POST /api/cooks` |
| Serving chip → slot / freezer / trash | `wireChipSortables` → `handleChipDrop` | `POST /api/placements/<id>/move` |
| Freezer / unscheduled chip → slot | same | `POST /api/placements` |
| Shelf resize | `initShelf` pointer handlers | — |
| **Cook card → slot** | **excluded** | **—** |

## Approach

Make the cook card draggable in board mode only, branching out of the legacy Sortable path
before it can reach `debounceSave()`, and land the whole move in one server-side
transaction behind a new `POST /api/cooks/<id>/move`.

**Move semantics.** Dragging the card moves the cook's anchor *and* the slot placements
sitting in the cell it left. Placements parked in other cells — planned leftovers — stay
where they are and keep rendering as labeled foreign chips, which is already how the board
draws an away-from-home serving (`renderBoardIfActive`, the `isHome` branch).

```
BEFORE                          AFTER (drag the card Tue dinner → Thu dinner)
Tue dinner  [Chili card] [1]    Tue dinner  (empty)
Wed lunch   [Chili 1]           Wed lunch   [Chili 1]   ← untouched
Thu dinner  (empty)             Thu dinner  [Chili card] [1]
```

Decisions, and what they ruled out:

| Decision | Rejected alternative |
|---|---|
| One atomic `POST /api/cooks/<id>/move` | Client fires `PATCH /api/cooks` then N × `POST /api/placements/<id>/move` — non-atomic, so a failure between them strands the card in a slot with no servings; also regenerates the week's Markdown twice per gesture |
| A named `/move` route | Extending `PATCH /api/cooks/<id>` — `update_cook` is a field-setter that rejects unknown fields, and making `{"date": …}` silently rewrite *placement* rows would mean two different things depending on which client sent it |
| Home placements follow, away placements stay | Shifting every placement by the same day offset — rewrites cells the user never touched and can push servings out of the visible week |
| Home placements follow | Moving the anchor alone — leaves a card with zero servings beside an orphaned labeled chip, which reads as a bug |
| Merge into an existing destination placement | Re-pointing blindly — `placements` has no UNIQUE constraint (`lib/inventory_db.py:104`), so a leftover of the *same* cook already parked in the destination yields two chips of one recipe in one cell |
| Reject a move whose date leaves `cook["week"]` | Updating `cooks.week` too — widens the endpoint past what the gesture can produce; leaving it stale is worse still, since `week_board()` filters on `cooks.week` and the card would silently vanish from both weeks |
| Card drag ships with a tap route | Drag only — `tests/e2e/test_planner_touch.py::TestTapToAssign` holds this page to WCAG 2.2 SC 2.5.7, and a fingertip drag across a 28-cell grid is the gesture least likely to survive contact with an iPad |

## Backend

### `lib/serving_ledger.move_cook(cook_id, date, meal) -> dict`

Validates `meal in MEALS` and `_validate_date(date)`, then opens `_write_txn` (BEGIN
IMMEDIATE — the module's rule for any check-then-write, and this is one):

1. Read the cook row. Missing → `ValueError`.
2. New date outside `cook["week"]` → `ValueError`. Computed inline from
   `_date.fromisoformat(date).isocalendar()` (the module already imports `date as _date`),
   matching `api_server._iso_week_of`. The grid renders one week, so a drag cannot produce
   this; the endpoint is public, so it is stated rather than assumed.
3. Anchor unchanged → return `get_cook(cook_id)` untouched. A no-op is a success, not an error.
4. `UPDATE cooks SET date = ?, meal = ? WHERE id = ?`.
5. Select this cook's `slot` placements at the **old** `(date, meal)`. For each: delete it,
   then `_merge_or_insert(conn, cook_id, 'slot', new_date, new_meal, count)` — the same
   helper `move_servings()` uses, so the merge-on-arrival case is handled by already-tested code.

Returns `get_cook(cook_id)`. No capacity check: total placed count is conserved by a move,
the same reasoning `move_servings()` records.

Note the old anchor may be NULL (an unscheduled cook has no card and so no drag), in which
case step 5 selects nothing and the call simply anchors the cook. `date IS ?` matches the
`_merge_or_insert` idiom and handles NULL correctly.

### `POST /api/cooks/<int:cook_id>/move`

Mirrors `api_cook_update`: `@require_token`, `@_ledger_error`, 404 when `get_cook` returns
None. Body `{date, meal}`. On success `_regen_weeks(cook["week"])` and
`_sync_cook_history(cook["recipe"])` — one week, not two, because step 2 above has already
guaranteed the move stayed inside it.

`_ledger_error` already maps `ValueError` → 400 and `sqlite3.OperationalError` → 503, so
every rejection above surfaces as JSON the board can read.

## Frontend

### The drag

In `initGridSortables()` (`templates/meal_planner.html:2392`):

- `draggable: boardMode ? '.grid-card' : '.grid-card:not(.cook-card)'`. Safe because board
  mode has already removed every legacy `.grid-card` before this runs, so in board mode
  `.grid-card` *is* the set of cook cards.
- `filter: '.remove-btn, .scale-btn, .servings-btn, .cooked-btn, .card-menu-btn'` with
  `preventOnFilter: false`. Without the filter a slow press on `+` starts a drag instead of
  scaling; the `false` is there for the reason the sidebar Sortable already documents —
  Sortable otherwise swallows a filtered element's click on touch. The list covers both
  card shapes, since this Sortable serves legacy weeks too: cook cards carry `.scale-btn`,
  legacy grid cards carry `.servings-btn`. The card's name link is deliberately *not*
  filtered, since it is most of the card's draggable area.
- `onAdd` gains a first branch, ahead of everything that can reach `debounceSave()`:
  `if (item.classList.contains('cook-card')) { moveCookCard(item, cell); return; }`
- `onEnd`'s existing `debounceSave()` gets the same guard.

The comment at `templates/meal_planner.html:2400-2405` is **rewritten, not deleted**. Its
rule still holds — a cook card must never reach `saveMealPlan()` — only the mechanism
changes, from "not draggable" to "branches out before the legacy path". Deleting it would
lose the reason the exclusion existed.

### `moveCookCard(card, cell)`

Modelled on `handleChipDrop`:

- `ledgerBusy` guard: toast "Busy — try again" and reload, matching the chip path.
- `POST /api/cooks/<id>/move` with `{date: dayDates[cell.dataset.day], meal: cell.dataset.meal}`.
- Non-OK → toast `err.error`.
- `finally { await loadWeekBoard(currentWeek); ledgerBusy = false; }` — always reload, even
  on failure, so the DOM that Sortable already mutated snaps back to server truth.

No manual node cleanup: `renderBoardIfActive()` clears every `.cook-card` unconditionally
before rebuilding. (`handleChipDrop` needs its `chip.remove()` only because `#trash-target`
is not a `.chip-tray` and so is never cleared by the re-render; no such target exists here.)

### The single-pointer alternative

`openCardSheet()` gains **"Move to another slot"** for cook cards, which arms the card and
closes the sheet. On desktop the sheet is reachable via ⋮; on touch, via tap.

Arming needs no new machinery: `armRecipe()` reads `card.dataset.name` and
`displayNameFor()`, both of which cook cards carry. The branch goes in `placeArmedRecipe()`
— if the armed node is a `.cook-card`, call the same `moveCookCard()` and return, before
the `ensureLegacyImported()` / `createCook()` path that would otherwise schedule a second
cook of the same recipe.

The assign bar's verb is currently a bare literal in the markup
(`<span class="assign-bar-text">Placing <span id="assign-bar-name">…`). It gets its own
`<span id="assign-bar-verb">`, set to "Moving" when a cook card is armed and "Placing"
otherwise. A move that announces itself as placing looks like it is about to duplicate the
meal.

## Acceptance criteria

- [ ] Dragging a cook card to another slot moves the card and its home servings; the board
      shows the result without a manual refresh.
- [ ] A leftover chip of the same cook in another cell is left where it is.
- [ ] Dropping onto a cell that already holds a leftover of the same cook yields **one**
      merged chip, not two.
- [ ] Dragging a card never issues a legacy `PUT /api/meal-plan/<week>`.
- [ ] Scale, verdict, and cook note survive the move.
- [ ] Pressing `+`/`−`/🍳/×/⋮ on a card still actuates the button and does not start a drag.
- [ ] ⋮ → "Move to another slot" → tap a slot performs the same move; the bar reads "Moving".
- [ ] A failed move leaves the board showing server truth, not the dragged-to position.

## Testing

| Layer | File | Covers |
|---|---|---|
| Unit | `tests/test_serving_ledger.py` | anchor + home placements move; away placement untouched; merge into an existing destination placement; NULL old anchor; no-op move; bad meal; bad date; date outside `cook["week"]` |
| API | `tests/test_api_ledger.py` | 200 and response shape, 404 unknown cook, 400 bad meal, week Markdown regenerated |
| E2E | `tests/e2e/test_planner_touch.py` | the tap route: ⋮ → Move → tap slot lands the card; the bar reads "Moving" |

The drag gesture itself gets one e2e test. No existing e2e helper drives a SortableJS drag,
and `forceFallback: true` means Playwright's `drag_to()` will not work — it needs stepped
`mouse.move()` calls. If that test proves flaky it will be removed and this document
updated to say the tap route carries the coverage; it will not be left quarantined.

## Documentation

- `docs/API.md` — the new endpoint.
- `CLAUDE.md` — a **new** invariant. The rule "a cook card must never reach
  `saveMealPlan()`" is currently recorded only as a comment inside
  `templates/meal_planner.html`; `CLAUDE.md` says nothing about cook cards today. The
  comment is rewritten in place, and the rule is promoted to a repo invariant, because its
  enforcement stops being structural (the card was simply not draggable) and becomes a
  branch someone can delete without the tests obviously objecting.

## Out of scope

- Dragging a card onto the trash to delete the cook — the × button and the sheet already do
  it, and the trash belongs to the `servings` Sortable group.
- Meal bundles on board weeks (still rejected with the existing toast).
- Cross-week drag. The grid renders one week; `move_cook` rejects a date outside it.

## Ready for Implementation

- [x] Acceptance criteria defined
- [x] ADHD check — removes a remove-and-re-add chore that silently discarded scale, verdict,
      and notes; the gesture is the one already used everywhere else on the page
- [x] Scope check — one ledger function, one endpoint, one Sortable branch, one sheet action
- [x] No blockers — PR #57 (`planner-dark-mode`) merged 2026-07-31, so `meal_planner.html`
      is conflict-free; branched from `main` at `212fbfd`
