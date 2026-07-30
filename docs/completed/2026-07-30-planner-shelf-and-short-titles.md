# Planner Shelf, Tap-to-Assign, and Recipe Short Titles

**Completed:** 2026-07-30
**Merged:** `a10e5c8` (PR #47), `0e9c387` (PR #50)
**Design:** [planner-shelf-and-tap-to-assign](../plans/2026-07-30-planner-shelf-and-tap-to-assign.md) ·
[recipe-short-titles](../plans/2026-07-30-recipe-short-titles.md)

---

## What prompted it

> "I don't understand how to do anything other than look for recipes and drop them to the
> day where they belong."

That was an accurate reading of what the screen offered, not a failure to explore. Driving
a real browser at iPad size showed why:

| Measured | |
|---|---|
| Visible controls under Apple's 44 pt floor | **526 of 607** |
| Under 30 pt | 477 |
| `.card-menu-btn` (⋮) | **17 × 20** |
| Grid cells reading "Drop recipe" | **26 of 28** |
| Dead space below the grid, portrait | ~700 px |
| Recipe names over 32 chars | **70 of 252** |

Three structural failures, each against the user's own stated principle — *see as much of
the big picture as possible, then zoom into details*, independently the [Visual
Information-Seeking Mantra](https://www.cs.umd.edu/~ben/papers/Shneiderman1996eyes.pdf):

1. The library was off-canvas behind a FAB in portrait, while ~700 px sat empty.
2. The grid advertised exactly one verb, 26 times.
3. Drag was the *only* way to assign, which [WCAG 2.2 SC 2.5.7](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
   forbids and [NN/g](https://www.nngroup.com/articles/drag-drop/) calls precision-hostile
   on touch.

## What shipped

- **A docked bottom shelf** below 1080 px, so the week and the library are on screen
  together. Landscape keeps the rail it already had.
- **Empty cells 80 → 44 px**, label `+`. An empty slot holds no information, so it costs
  no space — and at the old height the week overflowed the room the shelf leaves.
- **Tap-to-assign** alongside drag. Both routes end in the same `createCook()`.
- **526 sub-44 pt controls → 0**, plus one documented exception (`.prep-task`'s checkbox,
  tied to the filed plan to move Today's Prep off this screen).
- **Short recipe titles** — 70 backfilled, every rendered title now ≤ 32 chars, zero
  collisions. The extraction prompt is fixed at the root so new captures don't need it.

## What the work taught

**Three of the tap targets were fixed by deleting a control, not growing one.** Under
touch the card already opens the action sheet, so the ⋮ and both title links were
redundant; they stay live for a mouse, where the sheet is otherwise unreachable.

**Narrowing the device target found a bug rather than hiding one.** Once only the 11" and
13" iPads mattered, all eight configurations got asserted — and `.grid-card-name-link`
turned out to measure 31 px on a 13" and over 44 on an 11", because the same recipe name
wrapped to a different number of lines. The floor was silently a function of screen width
and title length; it read as passing only because a 13" had never been measured.

**Two constants had to be measured, not assumed.** `.app` is
`calc(100dvh - var(--chrome-h))` because the injected chrome bar is sticky at the top of
`<body>`, so a plain `100dvh` ran the shelf off the bottom of the screen — caught by a
test, not by looking. And 44 dvh is the largest shelf default at which the week still
fits above it (48 dvh overflows 820×1180 by 7 px).

**The shelf had to earn its space.** As first built, a 167 px header and a 152 px chip wall
left **83 px** for the recipe list — a library you could technically see and practically
couldn't. Search and sort now share a line: list 83 → 232 px.

**For the titles, the validator is what holds the line, not the prompt.** Every rule in
`validate_short_title` was added in response to something a model actually produced. The
organising idea is that shortening *deletes words*, and deletion preserves both membership
and order — so a valid short title is a **subsequence** of the original. Membership alone
stops `Beef Birria` → `Chicken Tacos`; order additionally stops `19 Calorie Fudgy Brownies
(Crouton)` → `Fudgy (Crouton) Brownies`, which passes a set check and reads wrong.
Non-Latin names are exempt because they must be translated to be readable at all.

**Same proposer/validator split as the portion ledger, same result.** Ollama 8/16, Claude
13/16 on identical recipes with identical validation.

**A test was asserting the user's meal plan.** `test_an_empty_slot_still_suggests...`
clicked Friday lunch, but the e2e vault is a *copy of the live one* — so it only held
while nobody had planned a Friday lunch. Both order-dependent tests are now pinned to an
empty far-future week with an explicit guard against going vacuous.

## Numbers

- 2996 → **3036** unit tests (37 short-title, 3 recipe-index)
- 63 → **90** e2e (27 new in `test_planner_touch.py`)
- Zero new ruff errors
- Mutation-checked: reverting the two headline fixes fails 4 tests

## Left open

- **Today's Prep** should leave the planner — a *today* object on a *week* screen.
- **Use It Up** ranks by `(uses_count, urgency, -len(recipe))`, so with one matchable
  at-risk item the real tiebreak is *shortest recipe name*. Live, that renders 10 lime
  recipes and **zero** for the ham expiring today. The wanted pantry-coverage ranking
  already exists as `meal_suggester.score_overlap` and is simply not wired in.
- `templates/meal_planner.html` is ~4,400 lines; the next planner change should split it.
- `Roasted Chicken & Mediterranean Avocado Sala` is truncated at the source — the recipe's
  own name is missing the "d". Renaming is unsafe (see the invariant in `CLAUDE.md`).
