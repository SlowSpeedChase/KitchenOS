# A KitchenOS web home page, linked from every page

**Status:** Ready for Implementation · **Branch:** `web-home-page` · **Date:** 2026-07-25

## Problem

`api_server.py` serves no `/` route at all. The list of KitchenOS pages lives in
`SECTIONS` in `lib/web_dashboard.py`, which renders the *vault note*
`Dashboards/KitchenOS Web.md` and feeds `scripts/sync_safari_bookmarks.py`. Both are
useful, but neither helps once you are already in the browser: from `/review` or
`/meal-planner` there is no way to reach another page without leaving for Obsidian or
digging through bookmarks.

## Approach

Make `SECTIONS` feed a third consumer. It is already the single registry behind the vault
note and the Safari bookmarks, and CLAUDE.md makes registering there mandatory for any new
page — so rendering it as HTML means a page added once shows up in all three places for
free, with no second list to keep in sync.

Decisions, and what they ruled out:

| Decision | Rejected alternative |
|---|---|
| Plain link list rendered from `SECTIONS` | Cards carrying live counts ("3 expiring soon"); a "what's expiring / cooking today" dashboard panel |
| Home link injected into `_CLAUDE_BAR_TEMPLATE` | Editing every template to add its own header link |
| `HOME` as the registry *root*, beside `SECTIONS` | An entry inside `SECTIONS` — the home page would then list itself |

The live-count and today-panel versions were cut deliberately: both couple the home page
to several endpoints and give it a way to break, for a page whose whole job is to be a
reliable set of links.

## Design

1. **`HOME` constant** (`lib/web_dashboard.py`) —
   `("🏠", "KitchenOS Home", "/", "every page, one tap away")`, declared beside `SECTIONS`
   as the root of the registry rather than a member of it. `render_markdown()` emits it at
   the top, so the vault note and the Safari bookmarks pick up the home link too.

2. **`render_html()`** (`lib/web_dashboard.py`) — pure, no I/O, sitting next to the
   existing `render_markdown()`: same input, second output format. Renders each section as
   a heading with its items as tappable cards (emoji, title, one-line description). Escapes
   its text, since the descriptions are free prose.

3. **`GET /`** (`api_server.py`) — serves `templates/home.html` through the existing
   `_serve_page_with_claude_bar`, passing `[('<!--SECTIONS-->', web_dashboard.render_html())]`
   to its `extra_replacements` parameter. No new serving mechanism.

4. **`templates/home.html`** — new and small, following the conventions the other pages
   already share: `color-scheme: light dark`, `Canvas`/`CanvasText` colors, system font
   stack, `viewport-fit=cover` with safe-area padding. Carries the `<!--SECTIONS-->`
   placeholder.

5. **Link back from everywhere** — a home link added to `_CLAUDE_BAR_TEMPLATE`
   (`api_server.py:96`), next to **Launch Claude**. Every HTML page KitchenOS serves —
   `/review`, `/system-health`, `/nutrition-review`, `/meal-planner`, `/receipt-paste`, and
   `/recipe/<name>` — goes through `_serve_page_with_claude_bar`, so this reaches all of
   them without touching a single template. `/current/meal-plan` and
   `/current/shopping-list` are `obsidian://` redirects rather than pages, so there is
   nothing to inject into and no gap.

## Testing

`tests/test_web_dashboard.py` — `render_html` output, `HOME`, and registry accounting. The
existing `TestPageRegistryIsComplete` will fail on the new `/` until it is accounted for;
account for it via `wd.HOME` rather than `NOT_BOOKMARKABLE`, because `/` is the most useful
bookmark on the phone and calling it unbookmarkable would be a lie the Safari sync then has
to work around.

`tests/test_claude_bar.py` — extend the existing parametrized page test so every page is
asserted to carry the home link, not just the bar.

`tests/e2e/test_weekly_loop.py` — add `/` to `SURFACES`.

Manual: open `/` on a phone over the tailnet, confirm every section and page from
`SECTIONS` is listed and tappable, then confirm the bar's home link returns to `/` from
`/review`, `/system-health`, and `/meal-planner`.

Per CLAUDE.md, a new browsable page must then be propagated:
`scripts/generate_web_dashboard.py` and `scripts/sync_safari_bookmarks.py --apply`.

## Out of scope / follow-ups

- Live per-card counts and a today panel (see above).
- Bulk inventory editing on `/review` — separate design,
  `2026-07-25-bulk-inventory-editing-design.md`.
