# Completed: KitchenOS web home page

**Completed:** 2026-07-25
**Branch:** `web-home-page` (merged to main, worktree removed)
**Duration:** 1 day

## Summary

KitchenOS had no `/` route at all. The list of browsable pages lived in `SECTIONS` in
`lib/web_dashboard.py`, feeding an Obsidian vault note and the Safari bookmark sync — both
useful from outside the browser, neither any help once you were already in it. From
`/review` or `/meal-planner` there was no way to reach another page.

`SECTIONS` now feeds a third consumer: an HTML renderer, served at `/`. Every page links
back to it via the shared Claude bar, so a page registered once shows up in the vault note,
in Safari, and on the home page.

## Key Changes

- **`lib/web_dashboard.py`** — `render_html()`, a pure renderer emitting `SECTIONS` as an
  escaped HTML fragment (relative links by default, so you stay on whatever host served the
  page). `HOME` added as the registry *root*, deliberately outside `SECTIONS` because the
  home page renders `SECTIONS` and would otherwise list itself.
- **`scripts/sync_safari_bookmarks.py`** — `desired_bookmarks()` built its list from
  `SECTIONS` alone, so a `HOME` outside it would silently never reach Safari. Now prepends
  it, with a test pinning the ordering.
- **`api_server.py`** — `GET /` serving `templates/home.html` through the existing
  `_serve_page_with_claude_bar`, and a `ko-home-link` anchor in `_CLAUDE_BAR_TEMPLATE`.
  That one line reaches every HTML page — `/review`, `/system-health`, `/nutrition-review`,
  `/meal-planner`, `/receipt-paste`, `/recipe/<name>` — with no per-template edits.
- **`templates/home.html`** — new, following the CSS-variable design system shared by
  `system_health.html`, `nutrition_review.html`, and `receipt_paste.html`.
- **`CLAUDE.md`** — the "new browsable page" invariant now documents a third accounting
  bucket (`HOME`) alongside `SECTIONS` and `NOT_BOOKMARKABLE`.

Tests: 1386 → 1405 passing (15 → 16 deselected; the new one is the `/` e2e surface).

## Design Doc

`docs/superpowers/specs/2026-07-25-web-home-page-design.md` ·
plan: `docs/superpowers/plans/2026-07-25-web-home-page.md`

## Lessons Learned

- **Keeping a constant out of a collection has a cost somewhere.** `HOME` sits outside
  `SECTIONS` for a good reason, but `desired_bookmarks()` iterated `SECTIONS` and nothing
  else — so the most useful bookmark on the phone would have been the one that never
  synced. Caught by reading the consumer rather than trusting the design doc's claim that
  it came along "for free". The `--check` pass at deploy confirmed it precisely: *1 of 8
  pages not bookmarked: KitchenOS Home.*
- **Escaping breaks naive test assertions on real data.** `"Plan & cook"` and
  `"This week's meal plan"` both change under `html.escape`, so `assert title in html`
  fails. Two separate tasks would have hit this.
- **A worktree cannot verify anything the LaunchAgent serves.** `com.kitchenos.api.plist`
  runs the main checkout, so the plan's in-branch restart-and-curl step was unrunnable —
  `/health` returned 200 while `GET /` returned 404. Deployment belongs after the merge,
  and nothing in the test suite would have said so.
- **The design system is not what `review.html` does.** Three of four templates share the
  CSS-variable block; `review.html` is the lone `Canvas` / `color-scheme: light dark` page.
  Picking the wrong exemplar would have made the new page the odd one out.

## Follow-ups

- Bulk select and edit on `/review` — split out of the original combined design and sitting
  in "Ready" with no branch:
  `docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md`.
- `docs/API.md`'s `/review` row is stale — it predates the per-item kebab menu from
  `f87fa17`. Belongs with the bulk-inventory work.
