# Branch Status: web-home-page

**Created:** 2026-07-25
**Design Doc:** docs/superpowers/specs/2026-07-25-web-home-page-design.md
**Current Stage:** ready
**Last Rebased:** 2026-07-25 (branched from main at `5a2b994`)

## Overview

A KitchenOS web home page at `/`, rendered from the existing `SECTIONS` registry in
`lib/web_dashboard.py`, plus a home link injected into `_CLAUDE_BAR_TEMPLATE` so every
page KitchenOS serves links back to it with no per-template edits.

`SECTIONS` already feeds the vault launcher note and the Safari bookmark sync; this makes
it feed a third consumer, so a page registered once appears in all three.

## Dependencies

- Builds on `bd7d739` (page registry + Safari bookmark sync), merged to main 2026-07-25.
- None outstanding.

## Conflict check (2026-07-25)

- `.worktrees/inventory-scan-and-extend` (6 commits) — **fully superseded by main**; its
  additions are main's older pre-Claude-bar and pre-kebab-menu code, and its one real fix
  (`4efee5c`, restore `source`/`notes` on Undo) is present at `templates/review.html:268`.
  Safe to prune; flagged to the user, not deleted. No overlap with this branch's files.
- `.worktrees/macro-planner-phase-1` (6 commits) — PARKED, no file overlap.
- `.claude/worktrees/recipe-accuracy-pass` — 0 commits ahead of main.

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans) — `docs/superpowers/plans/2026-07-25-web-home-page.md`

### Dev
- [x] Tests written first (superpowers:test-driven-development) — TDD per task, RED/GREEN evidence in `.superpowers/sdd/task-*-report.md`
- [x] Core implementation complete (5 tasks, subagent-driven)
- [x] All tests passing — 1405 passed, 16 deselected
- [x] No linting/type errors
- [x] Code follows project patterns
- [ ] BLOCKED: LaunchAgent restart — deferred to post-merge. `com.kitchenos.api.plist` runs the **main** checkout (`WorkingDirectory` = `/Users/chaseeasterling/Dev/KitchenOS`), so restarting from this worktree reloads code without the `/` route. Confirmed live during execution: `/health` 200, `GET /` 404.

### Testing
- [x] Unit tests pass — 1405 passed
- [x] Integration tests pass — Flask test-client coverage of `/` and the shared bar across all 6 pages
- [ ] BLOCKED: Manual testing — needs the merged code running; see "Post-merge deployment" in the plan
- [x] Edge cases verified — markup injection via registry prose, escaping of real titles (`Plan & cook`, `This week's meal plan`), unsubstituted-placeholder guard
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table — `docs/API.md` row for `/`; CLAUDE.md invariant updated for the third accounting bucket (`HOME`)
- [x] README updated (if interface changed) — n/a, README carries no page inventory
- [x] docs/plans/INDEX.md updated
- [x] Code comments where needed — stale `SECTIONS`-consumer prose corrected in `lib/web_dashboard.py` and `scripts/sync_safari_bookmarks.py`

### Review
- [x] Requested review — per-task review after each of 5 tasks, plus a final whole-branch review
- [x] Review feedback addressed — final review's 4 actionable findings fixed in `11a3949` and `8e22f51`
- [x] Changes approved — final verdict "ready with fixes"; fixes applied and re-verified

### Ready
- [x] Rebased on latest main — branched from `5a2b994`, main unchanged since
- [x] Final test pass after rebase — 1405 passed, 16 deselected
- [x] BRANCH-STATUS.md fully checked
- [x] Ready for merge

---

## Notes

- **New page → new bookmark invariant.** `/` must be accounted for in
  `tests/test_web_dashboard.py::TestPageRegistryIsComplete` via `wd.HOME` (not
  `NOT_BOOKMARKABLE`), then propagated with `scripts/generate_web_dashboard.py` and
  `scripts/sync_safari_bookmarks.py --apply`. The Safari sync quits and relaunches
  Safari — pre-authorized per CLAUDE.md.
- **API restart caveat.** Any `lib/` or `templates/` edit needs a `com.kitchenos.api`
  LaunchAgent reload or the server serves stale code as 500s that look like data bugs.
- **Bulk inventory editing was split out** of the original combined design and is *not*
  built here. Its spec is
  `docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md`, sitting in "Ready"
  with no branch yet.
- Baseline on this branch at creation: **1386 passed, 15 deselected**.

---

## Blocked Items

- [ ] None
