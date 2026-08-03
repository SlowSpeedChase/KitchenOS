# Completed: plates-ledger-native

**Completed:** 2026-08-03
**Branch:** `plates-ledger-native`
**Duration:** same day

## Summary

A composite plate placed on a planner board week now contributes its macros to that day's
totals row. It previously contributed nothing — recorded as a deliberate gap in `CLAUDE.md`
and `docs/ARCHITECTURE.md`, and as Phase 5 Decision C in the daily-driver audit ("keep
composite meals, which now means making them ledger-native").

The 16 plates seeded by the `plates` branch were the concrete reason to do it.

## The shape: a bundle of ordinary cooks

A plate expands to **one ordinary cook row per sub-recipe**, sharing two new nullable columns,
`cooks.bundle_id` and `cooks.bundle_name`. Not a `kind='meal'` row.

That choice is the whole design. Because every row stays "one recipe at one scale",
`day_totals`, the shopping list, the freezer, `cook_history`, `on_track`, `verdict_nudge` and
`cook_sweep` needed **no changes at all**. The alternative — a single meal-kind row — would
have required an "if meal, expand" branch in each of about twelve consumers, every one of them
a place a future change forgets.

It is also the same expansion `week_view.import_legacy_week` already performed on a
`[[Meal: X]]` link. It just used to throw the bundle identity away at that moment.

Columns rather than a `bundles` table: such a table would still need `cooks.bundle_id`, and
there is no bundle-level state to hold — `week`/`date`/`meal` must stay per-cook or `move_cook`
and `placements_for_week` get a second source of truth. With columns, the bundle *is* the set
of cooks sharing the id, so the last member's deletion retires it with nothing to collect.

## The identity, and why the gate had to move

    day_totals[date]  ==  meal_nutrition(meal) × outer

`meal_nutrition` sums `per_serving × sub_multiplier(1.0, sub.servings)`; `day_totals` sums
`per_serving × placement.count`. Setting each member's initial placement count equal to its
share makes those the same arithmetic. Placing `1.0` per member instead breaks it for every
fractional sub-recipe — 13 of the 45 in the corpus are `0.5`, one is `0.15`.

The gate had to be shared for the identity to hold. `day_totals` applied only the plausibility
bounds while `meal_nutrition` applied the full `macro_eligible`, so the same recipe could be
trusted by one surface and not the other. Both now go through
`nutrition_quality.eligible_macros`.

**Verified against the real vault: the identity holds for 16 of 16 plates.** Osso Buco Plate
contributes exactly 1337 kcal / 102 g protein to its day, matching its card.

## The cost of the stricter gate, measured

| | count |
|---|---|
| Newly excluded from `day_totals` | **107 of 403** |
| …coverage below threshold | 90 |
| …unknown serving count | 9 |
| …both | 8 |
| Already excluded (implausible) | 58 |

Coverage fails in the **undercount** direction (unresolved ingredient lines), so affected days
now read low rather than high. Across the last three planned weeks that is **one day**:
2026-08-02 moves 587 → 500 kcal, dropping one low-coverage recipe.

That is only honest if the omission is visible, so the same work fixed two surfaces that hid
it: `week_view` rendered the `Totals:` line only when a macro was non-zero, so a day whose
only recipe was excluded came out **completely blank** — no figure, no ⚠, no reason; and
`print_week` never carried `excluded` at all, so on paper a ⚠ named nothing and could not be
chased.

## Three live bugs found in the seam

- **The board spent the pantry twice for every cook.** `markCookCooked` PATCHed `cooked_at`
  — which consumes server-side — and *then* POSTed `/api/cook`, which calls the
  non-idempotent `consume_recipe` again. A prerequisite fix: a plate's single 🍳 would
  otherwise have double-spent N recipes at once.
- **Scheduling a plate from Obsidian silently lost it.** `_schedule_meal_token` wrote a raw
  `[[Meal: X]]` with none of the ledger's guards, so on a board week the next regen erased it
  and `_import_legacy_if_first_write` never picked it up. Exactly the failure
  `_schedule_recipe_directly` was rewritten to fix, left in place on the meal branch.
- **Six API routes were ungated** (`/api/meals` ×5, `/api/freezer`) while every neighbouring
  ledger route was gated.

## Two things pinned by deliberately breaking them

- **The migration trap.** `connect()` runs `executescript(_SCHEMA)` *before* `_migrate`, so an
  index on `bundle_id` placed beside `idx_cooks_week` raises `no such column` and breaks
  **every** `connect()` — inventory and nutrition cache included. Moving the index into
  `_SCHEMA` was confirmed to fail the new test.
- **The keystone identity.** Forcing the placement count to `1.0` fails
  `TestTheIdentity` at all three outer scales, so it bites rather than passing by construction.

## Lessons learned

**A change that no test pins goes green whether or not it worked.** Nothing in
`tests/test_serving_ledger.py` pinned the old gate behaviour — `test_day_totals_flags_low_coverage`
asserted only `incomplete is True`, which stayed true either way. The suite would have passed
an entirely broken gate switch. The strengthened assertions had to land in the same commit.

**The unit suite could not see the worst bug in this branch.** The JS `groupBundles` built
standalone-cook groups without `date`/`meal`, and the renderer skips a group missing them — so
**every plain cook card stopped being drawn** and any week without a plate would have come up
empty. 4003 unit tests passed; four e2e tests caught it. Running e2e against a `main` baseline
first is what made "9 failures" legible as "4 of these are mine".

**A test double should match the contract it stands in for.** `test_cook_sweep`'s
`consume_recipe` stub returned `list.append`'s `None`; once `consume_for_cook` began returning
the summary, every successful sweep read as a failure. Two other tests passed trivially —
`make_again: 1` is rejected by `_coerce_verdict` with a 400, so they never reached the branch
they claimed to check.

**The codebase was right and my test was wrong**, once: placing a plate must *not* write cook
history, because a plan is intent, not evidence. Counting planned rows is how 10 recipes came
to carry `last_cooked` against 2 real cooks.

## Still open

- **28 `/api/` routes remain ungated**, including `/api/inventory/*`, `/api/pantry` PUT and
  `/api/shopping-list/confirm`. Now listed in `KNOWN_UNGATED` in `tests/test_api_auth.py`, so
  a *new* ungated route fails the suite — the gap is pinned and visible, not closed.
- **No page in `templates/` sends an Authorization header.** The moment `KITCHENOS_API_TOKEN`
  is set, every gated route 401s for a remote browser and the planner stops working from any
  machine but the mini. The token is currently unset, which is the only reason this isn't
  biting. Deferred deliberately; it needs its own decision about how a browser holds a secret.
- **The bundle card shows no macro line.** Deriving one client-side would be a third
  implementation of the eligibility gate; reading it off the meal file would show the plate's
  *current* rollup rather than what was placed. The day-totals row is the honest number.
- **`meal_loader._yaml_quote` is hand-rolled** instead of `lib/frontmatter.scalar()`, against a
  hard invariant — a newline in a plate name injects a YAML key. Untouched here; own commit.
- **`MealEntry.sub_recipes`** is declared, never populated, with a stale docstring.
- 5 pre-existing e2e failures remain, unchanged from `main`.

## Verification

4003 unit tests pass (from 3927). E2E at parity with `main`: the same 5 pre-existing failures,
123 passed against main's 120. Ruff at exact per-file parity with `main`.
