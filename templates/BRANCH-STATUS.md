# Branch Status: phase-X.Y/feature-name

**Created:** YYYY-MM-DD
**Design Doc:** docs/plans/YYYY-MM-DD-design.md
**Current Stage:** planning
**Last Rebased:** YYYY-MM-DD

## Overview

Brief description of what this branch implements.

## Dependencies

- List any dependencies on other branches or external factors
- None | Waiting on phase-X.Y | Requires [external thing]

---

## Stages

### Planning
- [ ] Design doc exists and approved
- [ ] Conflict check completed (no overlapping work)
- [ ] Dependencies identified and noted
- [ ] Branch and worktree created
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

Running notes, decisions, questions, etc.

---

## Blocked Items

Move any blocked checklist items here with reason:

- [ ] BLOCKED: [Item] - [Reason]
