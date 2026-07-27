# Branch Status: consume-on-cook

**Created:** 2026-07-26
**Design Doc:** docs/superpowers/specs/2026-07-26-consume-on-cook-design.md
**Current Stage:** review
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
- [x] Implementation plan written (superpowers:writing-plans)

### Dev
- [x] Tests written first (superpowers:test-driven-development) — RED observed for every task
- [x] Core implementation complete — Tasks 1–9 all landed
- [x] All tests passing — 2708 unit (from a 2691 baseline), 28 e2e + 3 xfail + 1 xpass
- [x] No linting/type errors — `ruff check` clean on every file this branch *authored*.
      Three findings sit in files this branch touches, all three pre-existing and
      confirmed identical on `main` (`c33d867`): `E722` bare except and `E741`
      ambiguous `l` in `api_server.py`, and `F401` unused `re` import in
      `lib/ingredient_aggregator.py`. Not fixed here — unrelated to this change.
- [x] Code follows project patterns
- [ ] LaunchAgent restarted if lib/, templates/, or prompts/ changed — **deliberately not
      done, and owed at merge time.** The plist runs
      `/Users/chaseeasterling/Dev/KitchenOS/api_server.py`, i.e. the *main* checkout, so a
      restart from this worktree would bounce the live service without loading any of
      these changes. Restart after the merge lands on main.

### Testing
- [x] Unit tests pass
- [x] Integration tests pass (if applicable) — Playwright e2e, incl. 3 new cook-toast tests
- [ ] Manual testing completed — **not done on purpose.** No real cook has been run; all
      measurement so far is the read-only census. A live cook writes to the production DB
      and should be the reviewer's deliberate call, not a side effect of implementation.
- [x] Edge cases verified — container gate, garbage units, unparseable amounts, duplicate
      ingredient lines, no-op cooks, stamp survival across a DELETE-all + re-INSERT
- [x] Verified with superpowers:verification-before-completion

### Docs
- [x] Doc obligations met per CLAUDE.md table (ARCHITECTURE / API / OPERATIONS / invariants)
      — `docs/API.md` `/api/cook` row (contract + 🔒), container-gate invariant in `CLAUDE.md`
- [x] README updated (if interface changed) — n/a, README documents no API routes
- [x] docs/plans/INDEX.md updated
- [x] Code comments where needed

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

## Owed after merge

Not blockers, but this branch creates the obligation:

1. **Restart the `com.kitchenos.api` LaunchAgent.** `lib/` and `templates/` changed;
   the plist runs the *main* checkout, so the restart only makes sense post-merge.
2. **Surface `last_used` / `use_count` somewhere.** The columns are currently
   write-only — no view reads them. `Inventory.md`'s `HEADER` is unchanged, and
   `/review` surfacing was descoped from this branch to avoid colliding with
   `inventory-scan-and-extend`. Until something reads them, 453 of the 472
   ingredient lines that now touch inventory leave no user-visible trace beyond a
   transient toast. Natural home: the `/review` subline, alongside the
   `inventory-location-visibility` work.
3. **Decide the token story for the browser pages.** `/api/cook` is now gated,
   matching `/api/cooks`. Both are called from `templates/meal_planner.html`
   with no `Authorization` header, so if `KITCHENOS_API_TOKEN` is ever set both
   cook buttons 401 for any non-localhost browser — and the tailnet is the normal
   way these pages get opened. Inert today (the var is unset in `.env` and the
   plist). Either the pages send the token or the exemption gets written down, as
   `docs/API.md` already does for `/api/receipt/paste`.

## Known remaining inaccuracy (matcher-level, not this branch)

`find_match("pumpkin puree")` resolves to a fresh-`pumpkin` row, so one line in
`Dubai Chocolate Brownies` decrements a row it arguably shouldn't. It now only
*reduces* the row (the never-delete guard covers the destructive case in
`Rich Fudgy Chocolate Cake`), which is the self-healing direction. Fixing the
match itself is matcher work, deliberately out of scope here.

## Blocked Items

None.
