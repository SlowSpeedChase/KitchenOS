# Branch Status: command-engine

**Created:** 2026-11-12
**Design Doc:** docs/superpowers/specs/2026-11-12-command-engine-design.md
**Current Stage:** docs
**Last Rebased:** 2026-11-12

## Overview

Sentence + screen context → typed actions → ledger/inventory, with Undo. Gold kitchen and
gold command set as the standing test standard. Shopping actions deferred to a follow-on plan.

## Dependencies

- None

---

## Stages

### Planning
- [x] Design doc exists and approved
- [ ] Conflict check completed (no overlapping work)
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [x] Tests written first (superpowers:test-driven-development)
- [x] Core implementation complete
- [ ] All tests passing
- [ ] No linting/type errors
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed

### Testing
- [x] Unit tests pass
- [x] Integration tests pass (if applicable)
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

- 2026-11-13 — Tasks 1-10 of `docs/superpowers/plans/2026-11-12-command-engine.md` implemented;
  all command tests pass. Full non-e2e suite: 5676 passed; the 22 errors are all
  `tests/test_cooking_packet_render.py` (Chromium could not launch in the agent sandbox), not this branch.
  `tests/e2e` was not run.
- "All tests passing" and "LaunchAgent restarted" are left unticked: the browser tests above were not
  run to green here, and nothing is deployed — the live API does not have this code.

---

## Blocked Items

Move any blocked checklist items here with reason:

- [ ] BLOCKED: Model scorecard gate (`WRONG` must be 0) - real run 2026-11-13 scored WRONG = 1 for
  both `qwen2.5:3b` and `granite4.1:8b` on gold case `plan-or-move` once the model was warm. The gold
  answer is "ask", but that tie is exactly what the planner hands to the decider, so any model that
  answers scores wrong. Needs a design decision (always ask the user on a plan/move tie, or change
  the gold expectation). `DEFAULT_MODEL` unchanged. Cold-load is 54-79 s against a 20 s decider timeout.
