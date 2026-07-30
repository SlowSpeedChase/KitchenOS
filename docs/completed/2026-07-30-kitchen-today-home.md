# Kitchen Today — a state-first phone home page

**Merged:** 2026-07-30 · PR [#41](https://github.com/SlowSpeedChase/KitchenOS/pull/41) → `82757d0`
**Design:** [`2026-07-30-kitchen-today-home-design.md`](../superpowers/specs/2026-07-30-kitchen-today-home-design.md)

---

## The problem, and why it wasn't fixable in place

The Obsidian canvas homepage was unusable on a phone for **structural** reasons.

Both `Home.canvas` and `Dashboards/KitchenOS Dashboard.canvas` embed
`Dashboards/Dashboard.md`, which holds five Dataview blocks — two of them
`dataviewjs` — and every one scans all **252** recipes. "Browse by Cuisine" renders
all 252 into tables; "In Season Now" iterates them again. The second canvas adds
`Discover.md`, `Recipes by Cuisine.base`, and a whole shopping-list note on top:
roughly eight full-vault scans fired at once, on the weakest CPU in the house.

And canvas nodes are absolute pixels — `Dashboard.md` pinned at 1560×1040 against a
~390pt viewport is a 4× zoom-out to read one node. Canvas has no responsive reflow.
No amount of tuning fixes either half.

**But the framing that mattered came from asking.** The stated failure was *"I forget
the features exist."* That rules out a better menu: a list of page names cannot remind
anyone of anything — and the existing `/` was exactly such a list ("every page, one tap
away"). Had this been built as "a faster launcher", it would have missed.

## What shipped

`/` became **Kitchen Today** — four live cards, each a fact that doubles as a workflow
entry point, because **the state is the reminder**. "9 recipes need nothing you don't
have" says Cook Now exists *and* that it's worth tapping.

| card | live line at merge |
|---|---|
| 🍳 Cook something now | 9 recipes need nothing you don't have |
| ✨ New recipes | 17 recipes added — newest yesterday |
| ⏳ Use it up | 1 item expired · lime goes tomorrow *(urgent)* |
| 🗓️ Plan week 32 | nothing planned yet |

The full `SECTIONS` registry survives in a collapsed **All pages** — nothing became
unreachable, it just stopped being the first thing on screen.

- **`lib/kitchen_today.py`** parses the recipe library **once** and injects it into
  `cook_now` / `use_it_up`, which each re-parse it when called bare. Skipping this
  would have reintroduced the exact cost that made the canvas slow. **135 ms** measured.
- Every card computes under `_safe` and degrades to a still-tappable link. A home page
  that 500s is worse than the canvas it replaced.
- **`/recent`** — ordered by file **birth time**, not mtime. The nutrition resolver
  rewrites recipe files long after they land, so an mtime ordering would reshuffle on
  every backfill and stop meaning "recently added" at all.

## The dead triggers

**Shopping-list generation was never broken.** The W31 preview succeeded with 23 items
the whole time. What was dead was the *trigger*: the vault's buttons use the
`kitchenos://` scheme, served by a macOS helper app that no longer exists after the
machine rebuild. LaunchServices still claimed the scheme, pointing at a missing app,
so the buttons failed **silently**. That is the entire reason no shopping list existed
between W27 and W31.

Being macOS-only, they had also **never worked from a phone**, on any machine. A
workflow whose only trigger is a `kitchenos://` button is unreachable from the device
this project is actually used on.

`/current/meal-plan` and `/current/shopping-list` therefore stopped 302'ing to
`obsidian://` — which from a phone browser dead-ends or ejects you out of the browser —
and now render HTML via `lib/note_view.py`, with plain HTTP buttons for both actions.
Verified live: **24 items generated for W31** (first list in a month) and **all 24 sent
into Apple Reminders**.

`note_view` is deliberately not a general Markdown renderer — it handles only what our
own generators emit, because adding a Markdown dependency to display two files we write
ourselves is a poor trade in a project with one runtime dependency. Unknown syntax falls
through as escaped text rather than vanishing. Checkbox state renders **read-only**: making
the boxes tickable would fork a second truth from the vault note the moment either side moved.

## Two defects caught mid-branch

**Button dispatch inferred the action from the page.** `_render_fence` fell back to the
*page's* week whenever it couldn't parse an action, so all of a note's buttons collapsed
into "Generate shopping list" — including the Obsidian `type command` QuickAdd button,
which has no web equivalent at all. Only visible by rendering the real note and counting
the buttons. Dispatch is now on the declared action, and un-honourable buttons render as
nothing: a dead control is worse than an absent one.

**`lib/reminders.py` interpolated untrusted text into AppleScript.** The escaping was
`item.replace('"', '\\"')` — quotes only, backslashes missed entirely. These strings are
ingredient lines an LLM extracted from arbitrary recipe pages, so they are untrusted, and
`a" & (do shell script "…") & "b` was confirmed as a **working command-execution
payload**. Items now pass to `osascript -` as `argv` with the script on stdin, which
removes the escaping problem instead of trying to out-escape it. Verified against that
payload plus quotes, backslashes and non-ASCII in a throwaway list: all stored literally,
nothing executed.

It also spawned **one subprocess per item**. Batched to one call: 24 items in 8.8s.
Worth stating precisely — batching removes the ~0.4s process launch but not Reminders'
per-item Apple Event cost, so this is roughly **2×**, not the order of magnitude the
process count suggests.

## Verification

- **2897** unit tests (2881 → 2897; **54 new**), covering card computation, fail-safe
  degradation, escaping, note rendering, button dispatch, and AppleScript non-injection
- e2e **36 passed / 1 xfailed / 3 xpassed** — unchanged from baseline
- `ruff`: **zero** new errors, established by diffing the full report against `main`
  (a raw count would have blamed three pre-existing uncommitted scripts)
- All four pages at a **390pt viewport, both themes: no horizontal scroll, ≥44px tap
  targets** (Playwright). The first run caught the "All pages" summary at 33px.
- Both buttons **tapped in a real browser**, network stubbed so the check couldn't write
  — each posts to its own endpoint with the week from its own action; zero console errors

## Carried forward

- **`/meal-planner` is 154 KB in a single file** and genuinely heavy on a phone. It's
  step 2 of planning, not an entry point, so it was left alone — but it is the next
  obvious phone-performance target.
- **The `kitchenos://` handler is still unregistered.** Nothing in the shopping-list or
  meal-plan path depends on it any more, but `scripts/kitchenos-uri-handler/install.sh`
  has still not been re-run since the rebuild, and any *other* button on that scheme is
  still silently dead.
- The `.canvas` files stay on disk. `Dashboard.md`'s Dataview is genuinely useful on a
  **desktop**, where a 252-recipe scan is fine; only its role as the phone homepage ended.
- The Claude bar injected into every page consumes ~140px of the first phone screen and
  is styled outside the design language. Pre-existing and untouched here.
