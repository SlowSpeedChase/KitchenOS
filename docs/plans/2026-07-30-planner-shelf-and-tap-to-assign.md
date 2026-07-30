# Planner Shelf & Tap-to-Assign Design

**Status:** Done
**Created:** 2026-07-30
**Updated:** 2026-07-30
**Branch:** `planner-shelf-tap-assign`

---

## Problem

The user's verdict on `/meal-planner`: *"I don't understand how to do anything other
than look for recipes and drop them to the day where they belong."*

That is an accurate reading of what the screen offers. Measured on a real browser at
iPad size (`tests/e2e/test_planner_touch.py` drives the same measurement):

| Finding | Measured |
|---|---|
| Visible controls below Apple's 44pt floor | **526 of 607** |
| Below 30pt (miss-prone with a fingertip) | **477** |
| `.card-menu-btn` (⋮ on a meal card) | **17 × 20** |
| `.recipe-info-link` (preview ⓘ) | **20 × 20** |
| `.scale-btn` (− / +) | **32 × 32** |
| Empty grid cells advertising "Drop recipe" | **26 of 28** |
| Dead space below the grid, iPad portrait | **~700 px** |

Three structural failures, each a violation of the user's own stated principle —
*"see as much of the big picture as I can, and then zoom into the little things as
they need to be filled in"* (independently the [Visual Information-Seeking
Mantra](https://www.cs.umd.edu/~ben/papers/Shneiderman1996eyes.pdf): overview first,
zoom and filter, details on demand):

1. **The library is hidden in portrait.** At ≤1080 px the sidebar goes off-canvas
   behind a 56 px FAB. The most-used surface in the app costs a tap to even see —
   while ~700 px of the screen sits empty. Landscape (≥1081 px) already docks it and
   already works; this is a portrait-only failure.
2. **The grid advertises exactly one verb.** 26 of 28 cells say "Drop recipe". Drag is
   the only interaction the screen names, which is precisely why it is the only one
   the user found.
3. **Drag is the *only* way to assign.** [WCAG 2.2 SC 2.5.7](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
   requires a single-pointer alternative, and [NN/g](https://www.nngroup.com/articles/drag-drop/)
   is blunt that drag is precision-hostile on touch. A fingertip on a moving target is
   the worst case of an already-hard interaction.

## Solution

Three changes, all serving *overview first*:

1. **The library becomes a persistent bottom shelf in portrait**, occupying the dead
   space. Landscape keeps its docked left rail unchanged.
2. **Empty cells compress** so the whole week fits above the shelf without scrolling.
   Both halves of the big picture on screen at once.
3. **Tap-to-assign**: tap a recipe to arm it, tap a slot to place it. Drag keeps
   working for anyone who prefers it.

Plus a floor: **no interactive control under 44 × 44 pt**, enforced by a test.

### Explicitly out of scope

Deferred to their own docs so this ships in one pass:

- **Today's Prep relocation** — it is a *today* object on a *week* screen. Belongs on
  the Kitchen Today home page and pushed to Reminders. Untouched here.
- **Use It Up rework** — currently ranks by `(uses_count, urgency, -len(recipe))`
  (`lib/use_it_up.py:252`), so with one matchable at-risk item every candidate ties on
  `uses_count` and the real tiebreak is *shortest recipe name*. Live, that renders 10
  lime recipes and **zero** for the ham expiring today. The wanted ranking —
  pantry coverage — already exists as `meal_suggester.score_overlap`
  (`lib/meal_suggester.py:167`) and is simply not wired in. Its own doc.
- **Splitting `meal_planner.html`** (4354 lines). Real debt, but bundling a file split
  with a behaviour change makes both unreviewable.

---

## Design

### 1. Portrait shelf

`.app` is `display: flex` row with `.sidebar` then `.main`. At ≤1080 px it currently
rips the sidebar out to `position: fixed` + `translateX(-100%)`.

Instead, at ≤1080 px the axis rotates:

```
.app            flex-direction: column
.main           order: 1   flex: 1 1 auto   min-height: 0
.sidebar        order: 2   position: static   width: 100%
                height: var(--shelf-h, 40dvh)
```

- `--shelf-h` defaults to **44 dvh** and persists to `localStorage`
  (`planner.shelfHeight`), clamped 96 px–70 dvh.
- A new `#shelf-handle` is both the resize grip and the collapse toggle (drag =
  resize, tap = collapse). `#sidebar-toggle` (the FAB) is **hidden** in shelf mode
  rather than repurposed: a 56 px circle floating on top of the shelf is a worse
  control than the full-width bar already sitting at its edge, and this removes an
  affordance instead of adding one.
- `.sidebar-backdrop` is unused in portrait and stays hidden — nothing is modal now.
- `closeSidebar()` no-ops in shelf mode. It is called on every drop, and collapsing
  the shelf each time you placed something would hide the thing the shelf exists for.

**Two measured constants, not guesses:**

- `.app` is `calc(100dvh - var(--chrome-h))`, not `100dvh`. The injected Claude bar
  is `position: sticky` at the top of `<body>`, so `.app` starts ~60 px down and a
  full-viewport height pushed the shelf's bottom **off the screen**. With a docked
  rail that only clipped empty sidebar; with a shelf it clipped the shelf.
  `syncAppHeight()` measures the offset rather than hardcoding it, because that bar
  is not this template's markup. Caught by `test_collapsing_leaves_the_handle_reachable`.
- **44 dvh** is the largest default at which the compressed 28-slot week still fits
  above the shelf. Measured: 48 dvh overflows 820×1180 by 7 px; 44 dvh clears every
  target device. Being proportional, it also *scales the right way* — a 13" gets a
  601 px shelf against an 11"'s 519 px, so the bigger screen buys more library
  rather than more whitespace.

### Target devices

Only the **11" and 13" iPads**. Every one of their portrait widths is ≤ 1080, so the
breakpoint lands exactly right: portrait gets the shelf, landscape keeps the rail.
Smaller iPads (768 × 1024 mini/classic) are not a target and are not asserted.

| Device | Portrait | Landscape |
|---|---|---|
| Air 11 M2 / Air 4–5 | 820 × 1180 | 1180 × 820 |
| Pro 11 M4 | 834 × 1210 | 1210 × 834 |
| Air 13 M2 / Pro 12.9 | 1024 × 1366 | 1366 × 1024 |
| Pro 13 M4 | 1032 × 1376 | 1376 × 1032 |

All eight verified: zero grid overflow, 28/28 slots on screen, zero sub-44 pt
controls. Portrait shelves run 519–605 px (2–3 recipe cards visible); landscape
rails give 372–584 px of list (4–6 cards).

**Shelf density.** The shelf only pays off if the list gets the room. As first built,
`shelf-handle` + a 167 px `sidebar-header` + tabs + a 152 px chip block left **83 px**
for the recipe list — a library you technically could see and practically could not.
Search and sort now share a line, the redundant "Recipes" title is dropped (the handle
says it), and the chip wall collapses to about one row, still scrollable and still
drag-resizable. Header 167 → **65 px**; list 83 → **232 px**.

Landscape (≥1081 px) is untouched: the measured landscape screenshot already shows a
working docked rail.

### 2. Compressed empty cells

The shelf only delivers *overview* if the week still fits above it. Today an empty cell
is `min-height: 80px` with a `min-height: 60px` centred "Drop recipe" label, so four
empty rows cost ~700 px in a ~600 px space — it would just scroll, and the big picture
would be lost exactly where we tried to create it.

Empty cells drop to `min-height: 44px` (still a legal tap target) and the label becomes
a thin centred `+`. Filled cells are unchanged — detail stays where there is detail.
This is *zoom and filter*: empty means nothing to see, so it takes no room.

### 3. Tap-to-assign

Arm-then-place, chosen over a modal day/meal picker because it keeps the week visible
while choosing — a picker would cover the big picture to ask about it.

```
tap recipe card ──▶ armed
                    · card gets .armed ring
                    · #assign-bar appears: "Placing <name> — tap a slot"  [Cancel]
                    · empty cells get .placing (accent dash, "+ here")
tap grid cell  ──▶ POST the same endpoint drag uses, disarm, toast
tap Cancel / Esc / the armed card again ──▶ disarm
```

Constraints this has to respect:

- **Drag must still work.** SortableJS runs with `forceFallback`, so a tap that never
  moves still emits a `click`. Arming binds `click` on the card and ignores any event
  where Sortable reported a drag (`onEnd` sets a suppress flag for one tick).
- **Assignment goes through the existing write path**, not a parallel one — same
  endpoint, same optimistic update, same toast. Two ways to *ask*, one way to *do*.
- **The ⓘ preview button keeps its own handler** and calls `stopPropagation`, so
  opening a preview never arms.

### 4. 44 pt floor

| Control | Count | Now | After |
|---|---|---|---|
| `.recipe-info-link` (preview ⓘ) | 252 | 20 × 20 | 44 × 44 hit area |
| `.recipe-name` (title link) | 252 | 269 × 18 | `pointer-events: none` |
| `.useitup-recipe-link` | 10 | 94 × 16 | 44 tall |
| `.scale-btn` | 4 | 32 × 32 | 44 × 44 |
| `.card-menu-btn` (⋮) | 2 | 17 × 20 | removed under touch |
| chrome bar (`ko-*`, `api_server.py`) | 3 | ~40 × 38 | 44 min |
| `.sort-select`, `.nav-link-review` | 2 | 35 / 15 tall | 44 |

Three of these are resolved by *deleting* a target rather than growing one, which is
the better answer wherever it applies:

- The **⋮** is redundant under touch — the whole card already opens the same action
  sheet — so it goes, exactly as `remove`/`servings`/`cooked`/`retry` already did. It
  stays for mouse, where tap-to-open is gated off by `IS_TOUCH` and the sheet (and so
  the make-again verdict) would otherwise be unreachable.
- The **title links** — both `.recipe-name-link` in the shelf and `.grid-card-name-link`
  on a placed card — become `pointer-events: none` under touch. The card owns the tap
  now (arming the recipe, or opening the action sheet), so the titles are not
  independently actionable; left live they would be 252 sub-44 "targets" duplicating
  the card. They stay real `obsidian://` links on desktop, the only place that
  distinction has anywhere to go.

  The grid-card one is the reason it was worth testing four device sizes rather than
  one: its height is a function of how the recipe name *wraps*, so it measured 31 px
  on a 13" (wide column, two lines) and over 44 on an 11" (three lines). It read as
  passing until the 13" was in the matrix.
- The **preview ⓘ** keeps its 26 px disc but grows its *hit area* to 44, painted with a
  `radial-gradient` rather than a wrapper element so the existing markup and the
  `has-image` contrast variant both keep working. Inflating the disc itself would
  swallow the card's already-tight top row.

**One documented exception:** `.prep-task input[type=checkbox]` (~20 px). A native
checkbox cannot reach 44 without an `appearance: none` rebuild of a component that is
scheduled to leave this screen entirely. Named in `KNOWN_SMALL` with that reason rather
than silently skipped — if Today's Prep is still here when someone next reads the test,
the exception has outlived its justification.

---

## Implementation Notes

**Affected files**

| File | Change |
|---|---|
| `templates/meal_planner.html` | Portrait shelf CSS, compressed empty cells, shelf density, 44 pt sizing, arm/place JS, `#assign-bar`, `#shelf-handle`, `syncAppHeight()` |
| `api_server.py` | Chrome-bar buttons to a 44 px min — they are on *every* page, so fixing beat excluding them from the test |
| `tests/e2e/test_planner_touch.py` | **New**, 16 tests: tap-target floor + shelf + tap-to-assign |
| `tests/e2e/test_planner_library.py` | Existing 24 tests still pass (drag path unchanged) |

**Server:** the `api_server.py` edit needs a LaunchAgent restart; the template does not.

**Test notes.** Two properties this suite has to hold onto:

- *Guard the guard.* The tap-target sweep asserts it measured **> 200** controls before
  concluding none are too small — a typo'd selector or a page that never rendered would
  otherwise report a clean zero and pass while measuring nothing.
- *Order independence.* The fits-above-the-shelf test pins itself to an empty far-future
  week (`?week=2030-W20`). The server fixture is session-scoped, so the tap-to-assign
  test placing a cook was silently changing the grid's height for whatever ran after it.
  The claim under test is that the *empty compressed* grid fits; a slot holding a photo
  card is content that has earned its height.

The suite was mutation-checked: reverting the two headline fixes (44 pt preview target,
column-direction shelf) fails 4 tests, so it is not vacuous.

**Registry:** `/meal-planner` is already in `SECTIONS`; no new route, so no
`generate_web_dashboard` / `sync_safari_bookmarks` propagation.

---

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below
- [x] **ADHD check passed** — below
- [x] **Scope check** — one template + one new test file; < 1 day
- [x] **No blockers** — no server, schema, or data dependency

### Acceptance Criteria

- [x] In portrait the recipe library is visible **without any tap**
- [x] All 7 days × 4 meals visible **without scrolling the grid** — 28/28 on every
      11" and 13" iPad, both orientations
- [x] Tapping a recipe then a slot assigns it, with no drag
- [x] Drag-to-assign still works — `test_planner_library.py` stays green
- [x] **Zero** interactive controls below 44 × 44 pt at both iPad orientations
      (526 → 0, plus one documented exception)
- [x] Shelf height survives a reload
- [x] Landscape (1180 × 820) layout is unchanged from today

**Verified:** 2996 unit tests pass, 90 e2e pass (63 + 27 new), zero new ruff errors
(`api_server.py`'s 2 pre-date this branch).

### ADHD Design Check

- [x] **Reduces friction?** Library needs no tap to reach; assigning drops from
      "press, hold, drag accurately, release" to two taps.
- [x] **Visible?** Both the week and the library are on screen at once — the whole
      point. Nothing recallable is hidden behind a FAB.
- [x] **Externalizes cognition?** The armed state says what is being placed and where
      it can go, rather than the user holding "I'm moving the chili" in their head
      mid-drag.
- [x] **Additive, never a chore?** No new upkeep; no new state to maintain.

---

## Links

- Supersedes nothing. Sibling docs to follow: Today's Prep relocation, Use It Up rework.
- Measurement harness: `tests/e2e/test_planner_touch.py`
- [WCAG 2.2 SC 2.5.7 Dragging Movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
- [NN/g — Drag-and-Drop: How to Design for Ease of Use](https://www.nngroup.com/articles/drag-drop/)
