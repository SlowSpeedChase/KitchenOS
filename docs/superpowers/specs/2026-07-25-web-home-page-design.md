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
   the top of the vault note.

   Keeping `HOME` out of `SECTIONS` has a cost that must be paid explicitly:
   `desired_bookmarks()` (`scripts/sync_safari_bookmarks.py:62-69`) iterates
   `web_dashboard.SECTIONS` and nothing else, so the home page would silently never reach
   Safari. That function must be updated to prepend `HOME`, and a test must pin it —
   otherwise the most useful bookmark on the phone is the one bookmark that goes missing.

2. **`render_html()`** (`lib/web_dashboard.py`) — pure, no I/O, sitting next to the
   existing `render_markdown()`: same input, second output format. Renders each section as
   a heading with its items as tappable cards (emoji, title, one-line description). Escapes
   its text, since the descriptions are free prose.

3. **`GET /`** (`api_server.py`) — serves `templates/home.html` through the existing
   `_serve_page_with_claude_bar`, passing `[('<!--SECTIONS-->', web_dashboard.render_html())]`
   to its `extra_replacements` parameter. No new serving mechanism.

4. **`templates/home.html`** — new and small, matching the dashboard design system that
   `system_health.html`, `nutrition_review.html`, and `receipt_paste.html` all share: the
   `:root` CSS-variable block (`--bg: #f5f5f7`, `--card-bg: #ffffff`, `--border: #e5e5e7`,
   `--text: #1d1d1f`, `--text-muted: #86868b`, `--accent: #0071e3`), the
   `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif` stack, and
   `.card` at `border-radius: 14px`. Light-only, like all three — `review.html` is the
   lone `Canvas`/`color-scheme: light dark` page and is the odd one out, not the pattern
   to copy. Carries the `<!--SECTIONS-->` placeholder.

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

`tests/test_web_dashboard.py`, new `TestSafariBookmarks` — `desired_bookmarks()` includes
the home page and lists it first. Without this the home bookmark can regress silently,
since nothing else would notice `HOME` missing from a list built out of `SECTIONS`. The
test file already reasons about the Safari sync, and `scripts/` is importable from tests
via implicit namespace packages (`tests/test_dedupe_recipes.py:7` does the same).

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
