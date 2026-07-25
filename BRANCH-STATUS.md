# Branch Status: cook-now-meal-type-filter

**Created:** 2026-07-25
**Design Doc:** docs/superpowers/specs/2026-07-25-cook-now-meal-type-filter-design.md
**Current Stage:** planning
**Last Rebased:** 2026-07-25

## Overview

Filter Cook Now by meal type, so reviewing "what could I cook right now?" can exclude
desserts. Two sequential parts:

1. **Repair `dish_type`** — a one-off Claude Batches pass reclassifies all 239 recipes into
   a 12-value controlled vocabulary, with a dry-run diff report before anything is written.
   Also deletes the `"biscuit": "dessert"` rule in `lib/normalizer.py` that mis-files savory
   biscuits and would re-corrupt the data after the repair.
2. **`/cook-now` page + `GET /api/cook-now`** — 6 chip groups over the 12 stored values,
   filtering client-side, Desserts deselected on first load.

The generated `Cook Now.md` vault note is deliberately unchanged; the page is additive.

## Dependencies

- None. Part 2 depends on Part 1 landing first (chips are only as good as `dish_type`).

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

**Conflict check (2026-07-25):** clean. Checked with
`git log main..<branch> --name-only` per branch — i.e. only commits *ahead* of main, not
`git diff main..<branch>`, which also flags files where a branch is merely behind main and
gives false conflicts.

| Branch | Ahead of main | Touches cook_now / normalizer / web_dashboard |
|---|---|---|
| `inventory-scan-and-extend` | 6 commits | no |
| `macro-planner-phase-1/servings-backfill` | 6 commits | no |
| `worktree-recipe-accuracy-pass` | 0 commits (stale) | no |

**Doc obligations expected at the docs stage** (per the CLAUDE.md table):
- `docs/API.md` — new `GET /api/cook-now` endpoint contract.
- `docs/OPERATIONS.md` — new `scripts/reclassify_dish_type.py` command.
- `CLAUDE.md` — possible new invariant covering the `dish_type` controlled vocabulary.
- `SECTIONS` propagation is a code obligation, not just docs: `generate_web_dashboard.py`
  plus `sync_safari_bookmarks.py --apply`.

**Cost note:** the reclassification is one Batches job over 239 recipes, well under $1.

**Deferred, found while diagnosing the biscuits cook (not this branch):** consume-on-cook
decrements silently no-op — `pantry.find_match` is substring-only and misses `deli ham` vs
`sliced ham off the bone`; inventory is 190/222 rows in `ct` while recipes call for
cups/oz, so cross-family conversion always fails; and `meal_planner.html:2505` reads only
`consumed`, discarding the `unconvertible` / `not_tracked` the API already returns.

---

## Blocked Items

Move any blocked checklist items here with reason:

- None
