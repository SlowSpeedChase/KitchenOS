# Branch Status: bulk-inventory-editing

**Created:** 2026-07-25
**Design Doc:** docs/superpowers/specs/2026-07-25-bulk-inventory-editing-design.md
**Impl Plan:** docs/superpowers/plans/2026-07-25-bulk-inventory-editing.md
**Current Stage:** planning
**Last Rebased:** 2026-07-25 (branched from main @ 51f0007)

## Overview

Mass select + edit on `/review`: checkboxes + Select All, a sticky selection bar
mirroring a row's own `Remove / +3d / +7d / ⋮` controls, and one
`POST /api/inventory/bulk` doing a single read-modify-write instead of N.

Also fixes item addressing on the bulk path. The DB's uniqueness key is
`(name, unit, location)`, but every existing endpoint addresses rows by
`(name, location)` — and handles the disagreement inconsistently: `remove_item`
deletes *every* match while `set_expiry` / `set_category` / `extend_expiry` /
`move_item` update only the *first*. Latent on one item, data loss on fifteen.

Deliverables (6 tasks):
1. Pure `_apply_*` mutators in `lib/inventory.py` — mutate in memory, no I/O
2. `bulk_apply(action, refs, **params)` — one read, one write, `merge_key()` addressing
3. Single-item functions rewritten as thin wrappers over the same helpers
   (`freeze_item` collapses from 3 write cycles to 1)
4. `POST /api/inventory/bulk` + `_serialize_item` extracted from `_item_response`
5. Selection UI in `templates/review.html` — generalized `openMenu(target, anchor)`
6. Verification against the running server + `docs/API.md`

## Dependencies

- None blocking. `web-home-page` (the design doc's stated predecessor) merged to
  main on 2026-07-25 @ 51f0007.
- No conflict with the other active worktrees: `macro-planner-phase-1` (parked,
  nutrition/servings) and `inventory-scan-and-extend` (its `/review` +
  `/api/inventory/extend` work is already present on main).

---

## Stages

### Planning
- [x] Design doc exists and approved — "Ready" in docs/plans/INDEX.md since 2026-07-25
- [x] Conflict check completed (no overlapping work) — `git worktree list`, INDEX "In Progress"
- [x] Dependencies identified and noted
- [x] Branch and worktree created
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [ ] Tests written first (superpowers:test-driven-development)
- [ ] Core implementation complete
- [ ] All tests passing
- [ ] No linting/type errors
- [ ] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — required, both change

### Testing
- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing completed — the 5-step phone script in Task 6, Step 3
- [ ] Edge cases verified
- [ ] Verified with superpowers:verification-before-completion

### Docs
- [ ] Doc obligations met per CLAUDE.md table — `docs/API.md` (new endpoint contract)
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

- **Baseline:** 1405 tests passing on main @ 51f0007. The plan adds ~35.
- **No new page route**, so the `SECTIONS` / bookmark-sync invariant in CLAUDE.md
  does not apply — `/review` is already registered.
- **Scope guard:** the single-item routes keep `(name, location)` addressing and
  their current semantics. Their tests pin that behavior; migrating them is an
  explicit out-of-scope follow-up.
- **`InventoryItem` is a plain dataclass**, so `==` is by value. Removal from the
  working list must be by identity — hence `_drop()`. Using `list.remove()` here
  would be a real bug, not a style preference.
- The concurrent-writer lost-update TODO at `lib/inventory.py:308` is narrowed by
  this work (one write instead of N) but **not closed**. Still needs
  `INSERT … ON CONFLICT` in one transaction.

---

## Blocked Items

None.
