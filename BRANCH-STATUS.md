# Branch Status: phase-4/shopping-list-inventory-split

**Created:** 2026-09-01
**Design Doc:** docs/superpowers/specs/2026-09-01-truthful-shopping-inventory-design.md
**Current Stage:** ready for integration
**Last Synced with `main`:** 2026-09-01 (merge of `origin/main`)

## Overview

Make shopping-list inventory comparison precision-first, then split the weekly
note into unmatched purchases and explicit inventory matches so Reminders only
receives what likely needs to be bought.

## Dependencies

- None. Rich package-size inventory modeling remains a separate follow-up.

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
- [x] Focused tests passing
- [x] No linting/type errors
- [x] Code follows project patterns
- [x] Updated branch API exercised on temporary port 5002 (production agent waits for merge)

### Testing
- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual W36 regeneration completed
- [x] Edge cases verified
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] API and workflow behavior documented
- [x] README reviewed (behavior is documented in API/workflow docs)
- [x] docs/plans/INDEX.md updated
- [x] Code comments where needed

### Review
- [x] Requested review (superpowers:requesting-code-review)
- [x] Review feedback addressed
- [x] Changes approved

### Ready
- [x] Synced with latest `origin/main`
- [x] Final test pass after sync
- [x] BRANCH-STATUS.md updated with the W36 two-way split
- [x] Ready for merge

---

## Notes

- Baseline before the approved output split: 4,181 passed, 1 skipped, 133 deselected.
- Final default suite after cross-consumer review fixes: 4,207 passed, 1 skipped,
  133 deselected. Shopping/planner contract subset: 1,473 passed, 1 skipped.
- Live W36: 69 demand lines → 29 **Need to purchase** checkboxes, 39
  **Inventory matches — verify** bullets, 1 excluded household item, and 0
  automatic credits. Saved checkboxes and match bullets exactly equal the preview;
  pistachios appear only as an inventory match; manual/stale count is 0.
- Read-only proof: the ordered inventory-table SHA-256 was identical before and
  after generation (`c7be821e…e3289feaf6`). Reminders was not invoked.
- Unrelated modifications remain only in the main checkout and are untouched.
- PR #78 merged the precision-first comparison while this follow-up was under
  review; this branch now contains only the approved two-way output follow-up.

---

## Blocked Items

- None.
