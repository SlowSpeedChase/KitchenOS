# Branch Status: security-data-integrity

**Created:** 2026-08-23
**Design Doc:** docs/superpowers/specs/2026-08-23-security-data-integrity-design.md
**Current Stage:** review
**Last Rebased:** 2026-08-23

## Overview

Hard-disable the unauthenticated Claude bridge, contain request-derived vault paths, and
make receipt/inventory persistence atomic and safe under concurrent writers.

## Dependencies

- `ios27-new-siri` owns Apple/search/auth behavior. It also touches `api_server.py` in
  currently disjoint recipe-search/health regions, so the final rebase needs an explicit
  shared-file review.
- The dirty main checkout owns uncommitted retry-cap/dead-letter work; this branch does
  not copy or commit it.
- Baseline: `4086 passed, 1 skipped, 133 deselected` on clean `main` at `1f37217`.

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (`docs/superpowers/plans/2026-08-23-security-data-integrity.md`)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete
- [x] No hard test failures; expected dispositions recorded
- [ ] No new linting/type errors
- [ ] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed

### Testing
- [x] Unit tests pass
- [x] Integration tests pass
- [ ] Manual testing completed
- [x] Edge cases verified
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table
- [ ] README updated if interface changed
- [x] docs/plans/INDEX.md updated
- [x] Code comments updated

### Review
- [ ] Requested review
- [ ] Review feedback addressed
- [ ] Changes approved

### Ready
- [ ] Rebased on latest main
- [ ] Final test pass after rebase
- [ ] BRANCH-STATUS.md fully checked
- [ ] Ready for merge

## Notes

- Shared GitOps instructions were loaded from `/Users/chaseeasterling/Dev/dotfiles/dev/claude/GITOPS.md`;
  KitchenOS has no repository-specific GitOps stub.
- The user approved the committed design on 2026-08-23.
- Documentation was measured from the completed Tasks 1–5 source: `api_server.py`
  has 91 `@app.route` decorators and 82 unique literal paths.
- Focused security/persistence suite (2026-08-23): `1555 passed, 1 skipped in
  5.35s` — `tests/test_page_chrome.py`, `test_claude_send.py`,
  `test_api_endpoints.py`, `test_safe_paths.py`, `test_api_server.py`,
  `test_shopping_list_generator.py`, `test_inventory_db.py`,
  `test_inventory.py`, `test_pantry.py`, and `test_receipt_ingest.py`.
- Final-review focused inventory/database/API/receipt suite (2026-08-23): `281
  passed in 3.66s` — `tests/test_inventory_db.py`, `test_inventory.py`,
  `test_api_server.py`, `test_api_endpoints.py`, and `test_receipt_ingest.py`.
- Default suite (2026-08-23, after final receipt/view fixes): `4108 passed, 1
  skipped, 133 deselected, 9 warnings in 34.00s`. Baseline was `4086 passed, 1
  skipped, 133 deselected, 9 warnings`: pass count is +22; skip, deselection,
  and warning counts match.
- E2E suite (2026-08-23): `128 passed, 1 skipped, 4106 deselected, 3 xfailed,
  1 xpassed in 111.04s (0:01:51)`; no hard failures. Verbatim dispositions:
  - `SKIPPED [1] tests/e2e/test_planner_library.py:52: no prose servings values in the current library`
  - `XFAIL tests/e2e/test_bulk_inventory.py::test_undo_restores_a_deliberately_cleared_expiry[chromium] - Undo replays the removed rows through POST /api/inventory/add, and add_items auto-fills a shelf-life expiry whenever expires is None. So a deliberately-cleared expiry ('🚫 Remove expiration') comes back dated — here a year out. The bulk endpoint is not at fault: its removed payload carries the null faithfully. Pre-existing on main via the single-row remove path, which replays the same way; bulk only widens it to a whole selection. Fixing it needs a way to add a row with an explicitly null expiry, which is a schema/contract decision outside this branch's scope.`
  - `XFAIL tests/e2e/test_live_state.py::test_current_week_plan_has_at_least_one_meal - generate_meal_plan.py writes an empty template and nothing fills the slots, so each week arrives blank and only gets meals if they are added by hand. Non-strict because it legitimately oscillates: XPASS means the week has been planned (good), xfail means it is still the bare scaffold. Either way the signal is visible rather than silent.`
  - `XFAIL tests/e2e/test_live_state.py::test_current_week_has_a_shopping_list - Known: no shopping list has been generated since 2026-W27, so /current/shopping-list redirects into Obsidian to a note that does not exist.`
  - `XPASS tests/e2e/test_weekly_loop.py::test_cold_planner_load_is_quick_enough_to_keep_a_habit[chromium] - Timing-sensitive, so non-strict. /api/tasks/<week> rebuilds its sidecar through Ollama on a cold week; measured at 9.7s when the model had to load and well under 1s once mistral:7b is resident. The cost is therefore Ollama's first-inference warm-up rather than a per-load penalty — but it lands on whoever opens the planner first after a reboot, and a 10s wait on a phone is a habit-killer.`
- E2E was not rerun after the final-review documentation/source-comment correction:
  the changed receipt boundaries are covered by the focused and default suites
  above, and the exact prior E2E evidence is preserved verbatim.
- `git diff --check main...HEAD` is clean. The security branch modifies
  `BRANCH-STATUS.md`, `api_server.py`, `docs/API.md`, and `docs/ARCHITECTURE.md`
  in common with `ios27-new-siri`.
  The `api_server.py` changes are semantically disjoint today: this branch removes
  Claude bridge/page wiring and adds path, shopping-week, and receipt handling;
  `ios27-new-siri` adds `include_ingredients` handling only inside
  `GET /api/recipes`. Rebase risk is low but not zero because both alter the same
  Flask module and this branch's removed lines shift all later line numbers; merge
  the hunk changes deliberately, retaining the token decorator and existing
  ingredient-filter cache behavior while keeping this branch's security routes absent.
  The shared docs have no runtime coupling, but resolve their adjacent content by
  preserving the Siri branch's `include_ingredients` contract alongside this
  branch's measured route count and security/data-integrity contracts.
- LaunchAgent restart remains unchecked until merge. Production continues serving
  `main`; no production service was restarted from this worktree.

## Blocked Items

- None for this branch.
