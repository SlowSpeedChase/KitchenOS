# Branch Status: bulk-inventory-and-home

**Created:** 2026-07-25
**Design Doc:** docs/superpowers/specs/2026-07-25-bulk-inventory-and-web-home-design.md
**Current Stage:** planning
**Last Rebased:** 2026-07-25 (branched from main at `5a2b994`)

## Overview

Two changes to the KitchenOS web app:

1. **Bulk inventory editing** on `/review` — checkboxes + Select All, a sticky bottom bar
   mirroring a row's own controls (`Remove | +3d | +7d | ⋮`), and a new
   `POST /api/inventory/bulk` that applies one action to many items in a single
   read-modify-write. Fixes `(name, location)` → `(name, unit, location)` addressing along
   the way.
2. **A web home page** at `/` rendered from the existing `SECTIONS` registry, plus a home
   link in `_CLAUDE_BAR_TEMPLATE` so every page links back with no per-template edits.

## Dependencies

- Builds on `f87fa17` (per-item inventory actions) and `bd7d739` (page registry + Safari
  bookmark sync), both merged to main on 2026-07-25.
- None outstanding.

## Conflict check (2026-07-25)

- `.worktrees/inventory-scan-and-extend` (6 commits) touches the same four files, but is
  **fully superseded by main** — its additions are main's older pre-Claude-bar and
  pre-kebab-menu code, and its one real fix (`4efee5c`, restore `source`/`notes` on Undo)
  is present at `templates/review.html:268`. Safe to prune; flagged to the user, not
  deleted.
- `.worktrees/macro-planner-phase-1` (6 commits) — PARKED, no file overlap.
- `.claude/worktrees/recipe-accuracy-pass` — 0 commits ahead of main.

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [ ] Implementation plan written (superpowers:writing-plans)

### Dev
- [ ] Tests written first (superpowers:test-driven-development)
- [ ] Core implementation complete
- [ ] All tests passing
- [ ] No linting/type errors
- [ ] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed

### Testing
- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing completed
- [ ] Edge cases verified
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
- [ ] README updated (if interface changed)
- [ ] docs/plans/INDEX.md updated
- [ ] Code comments where needed

### Review
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed
- [ ] Changes approved

### Ready
- [ ] Rebased on latest main
- [ ] Final test pass after rebase
- [ ] BRANCH-STATUS.md fully checked
- [ ] Ready for merge

---

## Notes

- **New page → new bookmark invariant.** `/` must be accounted for in
  `tests/test_web_dashboard.py::TestPageRegistryIsComplete` via `wd.HOME` (not
  `NOT_BOOKMARKABLE`), then propagated with `scripts/generate_web_dashboard.py` and
  `scripts/sync_safari_bookmarks.py --apply`.
- **API restart caveat.** Any `lib/` or `templates/` edit needs a `com.kitchenos.api`
  LaunchAgent reload or the server serves stale code as 500s that look like data bugs.
- Baseline on this branch at creation: **1386 passed, 15 deselected**.

---

## Blocked Items

- [ ] None
