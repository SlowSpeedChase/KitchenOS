# Today's Prep Off The Planner Design

**Status:** Done
**Created:** 2026-07-30
**Updated:** 2026-07-30
**Branch:** `prep-off-the-planner`

---

## Problem

> "I love the Today's Prep as an idea, but that might need to be something that gets
> printed or put into a daily note or something somewhere else. Maybe it goes into a task
> app or a today page."

Today's Prep is a **today** object living on a **week** screen, and it pays for that twice:

1. **It's in the way.** It floats in the planner's bottom-right dock, over the week grid.
   Opening Use It Up used to push it off the top of the screen — fixed by capping the dock
   in the shelf work, but the underlying problem is that neither panel belongs there.
2. **It's unreachable when you'd act on it.** Prep is what you do *this afternoon*. You
   read that on your phone, on the home screen — not by opening a week planner and
   expanding a collapsed accordion in the corner.

The planner's job is arranging the week. Prep is the answer to "what should I be doing
right now", which is exactly the question `/` already exists to answer.

## Solution

Move it to the two places you'd actually act from:

**Kitchen Today (`/`)** gains a fifth card — `🔪 Today's prep · 3 to do` — leading to a new
**`/prep`** page with the checkboxes. Both surfaces already exist; the card slots into the
same live-state row as Cook Now and Use It Up, and it degrades to a plain link like they do.

**Reminders** gets a *Send to Reminders* button on `/prep`, the same mechanism the shopping
list already uses (`lib/reminders.py`, one batched `osascript` call, items passed as
`argv`). Prep lands in the app where the rest of your day lives.

The panel is **removed** from the planner. Not hidden behind a setting — the planner stops
carrying a today-object at all.

### Why not the alternatives

- **Printed only** — `/print/week` already includes do-ahead prep, and paper can't be
  ticked off or reflect a plan edited on Tuesday.
- **Daily note only** — another vault to open on the phone, and the checkboxes wouldn't
  sync back to KitchenOS, so `done` would live in two places that disagree.

---

## Design

### The card

`lib/kitchen_today.py` gains `_prep_card()`, following the existing shape exactly: build
inside `_safe()` so a failure degrades to a plain link rather than 500-ing the home page,
and return a `Card`. Line reads `N to do · M can be done ahead`, or `nothing to prep today`.

**It must not slow the home page.** `/` currently renders in ~135 ms because
`lib/kitchen_today.py` parses the recipe library **once** and injects it into both
`cook_now` and `use_it_up`. Prep is different — it reads the week's task sidecar
(`<week>.tasks.json`), not the library — but `task_extractor.extract_tasks` **regenerates
the sidecar with an LLM call** when the meal plan is newer. That cannot happen on a page
load. So the card reads the sidecar **only if it is fresh**, and reports nothing rather
than blocking; `/prep` itself is where a regeneration may happen.

### The page

`templates/prep.html`, modelled on `recent.html` (the simplest existing page): tokens.css,
KitchenOS coral top border, `<!--SUB-->` and `<!--PREP-->` injection points. Two sections —
**Today** and **Get ahead** — matching what the panel showed.

Checkboxes POST to the existing `/api/tasks/<week>/<task_id>/done`. No new persistence:
`done` already survives plan regeneration because task IDs are
`sha1(recipe|day|slot|step)`.

Tap targets at 44 pt, per the floor established in the planner work.

### Reminders

`POST /api/prep/reminders` → `add_to_reminders(items, "Prep")`, a separate list from
"Shopping" so a grocery run and an afternoon of cooking don't interleave. Items carry the
recipe name so a bare "Chill until ready to serve" is attributable.

Sends **today's** tasks only. Get-ahead items are a suggestion, not a commitment, and
pushing them would put next Friday's work in today's list.

### Registration

`/prep` is a new browsable page, so it goes in `SECTIONS` in `lib/web_dashboard.py` and is
propagated with `scripts/generate_web_dashboard.py` and
`scripts/sync_safari_bookmarks.py --apply`. Skipping any of that fails
`tests/test_web_dashboard.py`.

---

## Implementation Notes

| File | Change |
|---|---|
| `lib/kitchen_today.py` | `_prep_card()`; fresh-sidecar-only read |
| `templates/prep.html` | **New.** Today / Get ahead, checkboxes, Send to Reminders |
| `api_server.py` | `/prep` route; `POST /api/prep/reminders` |
| `templates/meal_planner.html` | Remove the prep panel, its CSS, `renderPrepPanel`, `loadTasks` |
| `lib/web_dashboard.py` | `/prep` in `SECTIONS` |
| `tests/test_kitchen_today.py` | Prep card, including the degrade path |
| `tests/e2e/test_prep_page.py` | **New.** Page renders, ticking persists, planner no longer carries it |

**Server:** `lib/` edits — LaunchAgent restart required.

---

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below
- [x] **ADHD check passed** — below
- [x] **Scope check** — one new page, one card, one deletion; well under a day
- [x] **No blockers** — tasks, reminders and the card framework all exist

### Acceptance Criteria

- [x] `/` shows a prep card with today's real count
- [x] `/prep` lists Today and Get ahead, and ticking a box persists across a reload
- [x] Send to Reminders puts prep in a **Prep** list with the recipe attached
      (verified live: 2 steps sent)
- [x] The planner no longer has a Today's Prep panel — 108 lines removed
- [x] `/` stays fast — **104 ms**, *faster* than the 135 ms before this
- [x] `/prep` is in `SECTIONS`, on the vault launcher, and bookmarked in Safari
      (13 pages verified)

### Two things the build changed my mind about

**The prep card made the home page slower, then faster.** Importing
`task_extractor` pulls in the Anthropic SDK, which cost **265 ms on first call** —
paid on the first home-page load, for a client the card never uses. The client is
now built lazily inside `_client()`, so the SDK isn't imported at all unless
something actually classifies. First call: 265 ms → **56 ms**, and `/` came out
*below* its previous baseline.

**Gating Send-to-Reminders on today's steps left a dead end.** On a day with only
get-ahead work — exactly the day that work is what you'd want queued — the button
disappeared. It now follows what's on the page and says which it will send; the
endpoint takes `scope=today|ahead`. The two are still never sent together: mixing
"do this now" with "you could do this for Friday" in one flat list is how a task
list stops being trusted.

### A bug the e2e test caught

The row is a `<label>`, so a tap fires `click` on the label **and** a forwarded
`click` on the checkbox — the handler ran twice and the two toggles cancelled
out. Ticking did nothing. Now it listens to `change` on the input, which fires
once after the native toggle, and the label still makes the whole row tappable.

### ADHD Design Check

- [x] **Reduces friction?** Prep is on the screen you already open, instead of behind a
      planner and a collapsed accordion.
- [x] **Visible?** It's a card with a number on the home page — the thing that stops you
      forgetting the feature exists.
- [x] **Externalizes cognition?** Reminders holds "what am I meant to be doing", which is
      where you already look.
- [x] **Additive, never a chore?** Derived from the meal plan; nothing to maintain.

---

## Links

- Siblings: [planner-shelf-and-tap-to-assign](2026-07-30-planner-shelf-and-tap-to-assign.md) ·
  [use-it-up-by-item](2026-07-30-use-it-up-by-item.md)
- Completes the three-item list from the planner-UI conversation.
