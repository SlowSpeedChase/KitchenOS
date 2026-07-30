# Kitchen Today — a state-first phone home page

**Status:** Ready
**Created:** 2026-07-30
**Updated:** 2026-07-30

---

## Problem

The Obsidian canvas homepage is unusable on a phone, and the failure is structural, not
cosmetic.

**It's slow.** Both `Home.canvas` and `Dashboards/KitchenOS Dashboard.canvas` embed
`Dashboards/Dashboard.md`, which holds five Dataview blocks — two of them `dataviewjs` —
and every one scans all **252** recipes. "Browse by Cuisine" renders all 252 into tables;
"In Season Now" iterates all 252 again. `KitchenOS Dashboard.canvas` additionally embeds
`Discover.md` (more Dataview), `Recipes by Cuisine.base`, and a full shopping-list note.
Opening it fires roughly eight full-vault scans at once, on the weakest CPU in the house.

**It's small and requires zooming.** Canvas nodes are absolute pixels: `Dashboard.md` is
pinned at 1560×1040, the shopping list at 980×880. A phone viewport is ~390pt. That is a
4× zoom-out to read one node, and canvas has no responsive reflow — it cannot be tuned
away. Canvas is the wrong container for a phone, permanently.

**And the deeper problem is recall, not navigation.** Asked what actually fails in the
kitchen, the answer was *"I forget the features exist."* That rules out a better menu. A
list of page names cannot remind anyone of anything — the existing `/` home is exactly
such a list ("every page, one tap away", grouped Plan & cook / Nutrition / Stock / System),
and it does not solve this.

Meanwhile the interesting state is all there, fast, and invisible. Measured live on
2026-07-30:

- **6 recipes at 100% coverage** — cookable with zero shopping (`/api/cook-now`, 80–127 ms)
- **1 item already expired** (sliced ham, Jul 29), limes expiring Jul 31, 4 within a week,
  with recipe suggestions already attached (`/api/use-it-up`, 36 ms)
- **10 recipes added Jul 29**, 22 in July — with nothing on the web surfacing them

## Solution

Turn `/` from a page directory into **Kitchen Today**: four cards, each showing a live fact
that doubles as the entry point to one workflow. The state *is* the reminder — "6 recipes
need nothing you don't have" tells you Cook Now exists **and** that it is worth tapping.
"Every page, one tap away" does neither.

Scope is set by the two workflows named as real, plus one request:

1. **What do I eat right now?** → Cook Now
2. **Plan the week / shop** → Plan Week
3. **See what's recently added** → a new `/recent` page
4. *(kept)* **What's about to go bad?** → Use It Up — it costs 36 ms and prevents waste

The existing `SECTIONS` registry survives intact as a collapsed **All pages** row, so
nothing becomes unreachable; it just stops being the first thing on screen.

## Design

### Data flow

```
                 read_inventory()          get_recipe_index(include_ingredients=True)
                       │                                  │
                       └──────────────┬───────────────────┘
                                      │  parsed ONCE, injected into both
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
                 cook_now.generate()        use_it_up.generate()
                        │                           │
                        └─────────────┬─────────────┘
                                      ▼
                          kitchen_today.gather()  ──►  four Card records
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
                  render_html()              (future) render_markdown()
                    '/' home page              regenerated vault note
```

`cook_now.generate()` and `use_it_up.generate()` both accept injected `items` and
`recipe_index`. Today, called bare, they each independently parse all 252 recipe files.
Gathering both for one page must parse **once** and inject — otherwise the home page
reintroduces the very cost that makes the canvas slow.

### `lib/kitchen_today.py` (new)

One module, one job: compute the four cards and render them. Pure functions with injectable
inputs, mirroring the conventions already used by `cook_now` / `use_it_up` / `web_dashboard`.

- `gather(items=None, recipe_index=None, today=None) -> list[Card]` — the state.
- `render_html(cards) -> str` — the fragment substituted into `templates/home.html`.
- `Card` = `(emoji, title, line, href, tone)`. `line` is the live fact; `tone` drives
  colour (`urgent` when something has already expired, `normal` otherwise).

Every card degrades to a still-tappable link if its query fails or returns nothing. A card
that cannot compute its number must never take the home page down with it — a home page
that 500s is worse than the canvas.

### `/recent` (new page)

Recipes newest-first, tapping through to the existing recipe card. "Added" must come from
**file birth time**, not mtime: nutrition recomputation rewrites recipe files, so mtime
would reshuffle the list every time the resolver runs and "recently added" would be a lie.
`get_recipe_index` gains an `added` field (one `stat()` per file — free next to the
read-and-parse it already does).

### Fixing `/current/*`

`/current/meal-plan` and `/current/shopping-list` currently 302 to
`obsidian://open/?vault=KitchenOS&file=…`. From a phone browser that dead-ends or ejects
you into another app — two of the six "Plan & cook" entries are unusable from the device
this project is for. They will render HTML in-browser, keeping an **Open in Obsidian** link
for desktop use.

### Making the shopping list reachable at all

Diagnosed while scoping this: shopping-list generation is **not broken**. The W31 preview
returns success with 23 items from 2 recipes. What is dead is the *trigger* — the only path
to generating a list is a `kitchenos://generate-shopping-list?week=…` button inside an
Obsidian note. LaunchServices still claims the scheme (`com.kitchenos.uri`) but the handler
app no longer exists, the known macOS-rebuild failure mode, so the button silently does
nothing. That explains zero shopping lists since W27.

`kitchenos://` is macOS-only regardless, so **from a phone that button has never worked.**
The Plan card therefore generates over plain HTTP, giving the workflow its first
phone-reachable trigger.

### Out of scope

`/meal-planner` is 154 KB in a single file and is genuinely heavy on a phone, but it is
step 2 of planning, not an entry point. Slimming it is its own project. The `.canvas` files
stay on disk — `Dashboard.md`'s Dataview blocks are useful on a *desktop*, where 252-recipe
scans are fine. Only their role as the phone homepage goes away.

## Implementation Notes

| File | Change |
|---|---|
| `lib/kitchen_today.py` | **new** — `gather()`, `render_html()`, `Card` |
| `lib/recipe_index.py` | add `added` (file birth time, mtime fallback) |
| `templates/home.html` | Kitchen Today cards + collapsed All pages |
| `templates/recent.html` | **new** — recently-added recipes |
| `api_server.py` | `/` renders cards; new `/recent`; `/current/*` render HTML; expose shopping-list generation to the card |
| `lib/web_dashboard.py` | register `/recent` in `SECTIONS` (the registry test requires it) |
| `tests/test_kitchen_today.py` | **new** — card computation + graceful degradation |

Adding an HTML route without registering it in `SECTIONS` fails
`tests/test_web_dashboard.py` by design.

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below
- [x] **ADHD check passed** — below
- [x] **Scope check** — one module, one template, four routes; well under a week
- [x] **No blockers** — every data source measured working on 2026-07-30

### Acceptance Criteria

- [ ] `/` shows four cards, each with a live number, above a collapsed All pages section
- [ ] The page renders with **no horizontal scroll and no zoom** at a 390pt viewport
- [ ] Home page responds in **< 300 ms** warm, parsing the recipe index **once**
- [ ] A failing card degrades to a plain link; the page still returns 200
- [ ] `/recent` lists recipes newest-first by **birth time**, linking to recipe cards
- [ ] `/current/meal-plan` and `/current/shopping-list` return HTML, not an `obsidian://`
      redirect, and still offer an Open in Obsidian link
- [ ] A shopping list can be generated for the current week **from the phone**, over HTTP
- [ ] Every page previously in `SECTIONS` is still reachable
- [ ] Full unit + e2e suites stay green; `ruff` no worse than main

### ADHD Design Check

- [x] **Reduces friction?** One tap from the iOS home screen, versus canvas → wait → zoom
      → pan → find node → tap.
- [x] **Visible?** This is the entire point. The state is on the first screen, so the
      feature cannot be forgotten — it announces itself.
- [x] **Externalizes cognition?** The system reports what is cookable, what is dying, and
      what arrived. None of it has to be held in your head.
- [x] **Additive, never a chore?** Every number is derived from existing data. There is
      nothing to maintain, tick off, or clean up; it self-ages.

---

## Links

- **Branch:** `feat/kitchen-today-home`
- **PR:** (added when complete)
