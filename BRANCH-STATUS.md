# Branch Status: home-web-gateway

**Created:** 2026-09-26
**Design Doc:** https://github.com/SlowSpeedChase/dotfiles/blob/main/docs/home-web-gateway.md
**Current Stage:** review
**Last Rebased:** 2026-09-26

## Overview

Canonical HTTPS origin for public KitchenOS links and exact legacy iOS endpoint migration.

## Dependencies

- Shared dotfiles home gateway (DNS, TLS, Caddy).
- Isolated from the dirty calendar checkout; base origin/main 3633209.

---

## Stages

### Planning
- [x] Design doc exists and approved
- [x] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete
- [x] Original focused Python (391 after review round 1), ConfigTests (6), and full KitchenOSKit (76) pass
- [x] No new Ruff findings (17 existing in touched files, same as baseline)
- [x] Code follows project patterns
- [ ] Deployment deferred: do not restart LaunchAgents or regenerate production artifacts in this task

### Testing
- [x] Unit tests pass
- [x] Synthetic Flask integration coverage passes in the focused suite
- [ ] Physical device / gateway rollout verification deferred; no deployment authorized
- [x] Edge cases verified
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
- [x] README updated (if interface changed)
- [x] docs/plans/INDEX.md updated
- [x] Code comments where needed

### Review
- [ ] Requested review (superpowers:requesting-code-review)
- [ ] Review feedback addressed
- [ ] Changes approved

### Ready
- [x] Rebased on latest main
- [ ] Final test pass after rebase
- [ ] BRANCH-STATUS.md fully checked
- [ ] Ready for merge

---

## Notes

- Task 6 of the controller-approved shared home gateway plan; base `origin/main` 3633209.
- Python RED: 29 failures / 332 passes before implementation; one migration test import corrected and separately proved RED (1 fail / 7 pass).
- Swift RED: 6 expected assertions for three retired default origins, before migration implementation.
- Initial Python GREEN before review fixes: 363 focused tests; Swift ConfigTests 6 and full package 76 pass.
- All Python runs set `PYTHON_DOTENV_DISABLED=1`, synthetic `/tmp` vault/DB, and `KITCHENOS_NO_LLM=1`; per-test fixtures further isolate data.
- Bare pytest is excluded: corpus tests resolve main-worktree vault data, and `tests/test_backfill_nutrition.py::TestFoodStoreFloorCoversEveryTable::test_the_real_store_passes` explicitly overrides the temp DB with production. No e2e/live/corpus suite ran.
- New Python files pass Ruff. Changed Python files have 17 findings already present at HEAD; zero added findings. `git diff --check` passes.
- Explicit active-file allowlist only; no modifications to docs/plans/archive, docs/history, docs/superpowers, or docs/completed.
- Self-review complete; independent controller review remains the review gate. No implementer subagents or Shepherd agent run (controller ruling).
- No production vault/DB/bookmarks/server/.env/credentials accessed. No app deployment or production artifact regeneration.
- The iOS conditional default has a test, but SwiftPM runs here execute on macOS; on-device verification belongs to rollout.

---

## Blocked Items

No implementation blockers. Controller review and deployment verification remain pending.


## Review fix round 1

- P2: reject malformed/encoded authorities; retain bracketed IPv6, IDNA and valid DNS labels/ports.
- P3: autouse fixture clears both public-origin environment variables; individual tests set only their chosen layer. Reload the recipe compatibility constant after isolation.
- RED with ambient WEB/API overrides: 31 failed / 358 passed (18 authority, 13 consumer failures).
- Self-review regression: max-length DNS label with port initially failed (1 failed / 44 passed); IDNA encoding corrected to apply to host only.
- GREEN with both ambient variables set: 391 focused Python tests passed; changed-file Ruff and `git diff --check` passed.
- Swift untouched; no rerun. Production/corpus/e2e restrictions unchanged. Ready for controller re-review.

## Final-review fix wave

- Proxy auth reproduced RED (4 failures / 19 passes), then GREEN. Immediate
  loopback is the only trusted proxy; nearest forwarded clients keep bearer auth.
  Direct remote spoofing, valid-token forwarding, and local exemptions are covered.
- Added `scripts/deploy_api.py`: exact-SHA Git archive outside all checkouts,
  separate venv, private external data/config, named API shim, saved plist/load
  state, release-identity/auth probes, transactional rollback and CLI serialization.
- External `KITCHENOS_ITEM_ALIASES` preserves learned cache entries across releases;
  its regression failed first. Production alias overrides are cleared in tests.
- **459 focused synthetic Python tests pass**, with hostile ambient origin/cache
  overrides. This supersedes 424 before receipt-cache coverage; the earlier
  363/391 counts describe initial implementation/review round 1 respectively.
- New/touched utility and test files pass Ruff; `git diff --check` passes.
- Full pytest remains excluded for the same documented production-store/corpus
  reads; no production data, live endpoint, device, LaunchAgent or primary checkout
  was touched. Swift was unchanged; prior 76-package-test result remains historical.
- Self-review complete; final controller re-review is pending. No deployment or
  merge approval is claimed. Shared mutable config and any new-shim TCC grants
  must be verified during the separate approved production rollout.
