# Branch Status: consume-on-cook

**Created:** 2026-07-26
**Design Doc:** docs/superpowers/specs/2026-07-26-consume-on-cook-design.md
**Current Stage:** planning
**Last Rebased:** 2026-07-26 (branched from main @ c33d867)

## Overview

Make consume-on-cook work. Today 234 of the 236 recipes with parseable
ingredients decrement nothing when marked cooked — of 2,634 ingredient lines,
exactly 2 subtract.

Three coupled defects: `split_against_pantry` and `apply_decisions` use different
unit-compatibility rules (the shopping list credits limes the cook won't spend);
`lib/pantry.find_match` still runs the substring matcher that `436597d` deleted
everywhere else; and the UI reads only `consumed`, rendering failure as a green
success toast.

The governing constraint is that inventory holds **containers, not quantities** —
188 of 198 count rows are qty exactly `1.0`, meaning one package. So the fix
centres on a container gate: a qty-1 row is use-stamped, never decremented.

Target end state (measured): 18 decrements, 455 use-stamps across 90 rows,
199 of 239 recipes reporting something, **zero false decrements**.

## Dependencies

- None blocking.
- **Coordination:** `inventory-scan-and-extend` (worktree, unmerged) touches
  `api_server.py`, `lib/inventory.py`, `docs/API.md`, `templates/review.html`,
  `tests/test_api_endpoints.py`, `tests/test_inventory.py`. Overlap assessed as
  benign — it adds `extend_expiry()` and a review-page banner, in different
  regions than this branch's dataclass-field and decorator changes. The one real
  collision, surfacing `last_used` in `/review`, is **dropped from scope** here.
- `inventory-location-visibility` is docs-only so far (spec + plan, no code).

Conflict-check method: `git log main..<branch> --name-only`. Do **not** use
`git diff main..<branch>` — it also lists files where the branch is merely
*behind* main, which produces false conflicts.

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

**Worktree setup required before running anything** (learned on
`cook-now-meal-type-filter`): a fresh worktree has no `.env` (git-ignored) and no
`vault/` (listed in `.git/info/exclude`). Symlink both from the main checkout, or
`paths.recipes_dir()` silently falls through to the dead default. Copy — do not
symlink — `data/kitchenos.db` if a test needs real rows, so nothing can write
through to production.

**Never run `consume_recipe`, `save_pantry` or `write_inventory` against the real
DB during development.** All measurement so far has been read-only dry runs.

**Design escalated to Claude Fable 5**, which corrected three things worth
remembering: the container reality (the "obvious" count-unit fix would have
deleted jars); the coupling between the predicate fix and the matcher fix (11
peanut-butter lines would otherwise start decrementing the `butter` staple row);
and a live hole in the shipped `436597d` matcher — `_STOPWORDS` collapses
`shredded cheese` to `{cheese}`, so **Cook Now today credits corn-syrup coverage
from a can of corn**.

**Closure obligation:** main currently carries a stale `BRANCH-STATUS.md` from
`cook-now-meal-type-filter` — the previous branch's closure ritual missed
deleting it. `ls BRANCH-STATUS.md` must fail on main. Delete it when this branch
closes.

## Blocked Items

None.
