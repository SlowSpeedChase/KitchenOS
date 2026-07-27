# Consume-on-cook — completed 2026-07-27

**Design:** `docs/superpowers/specs/2026-07-26-consume-on-cook-design.md`
**Plan:** `docs/superpowers/plans/2026-07-26-consume-on-cook.md`
**Branch:** `consume-on-cook` (23 commits, merged fast-forward to `main`)

## What was wrong

Marking a recipe cooked was a near-total no-op. Of the 236 recipes with parseable
ingredients, **234 changed no inventory at all**; of 2,634 ingredient lines, exactly
**2** subtracted. The UI reported success either way, so the failure was invisible.

Three coupled defects:

1. `split_against_pantry` and `apply_decisions` hand-wrote *different* unit-compatibility
   rules, so the shopping list credited limes the cook then refused to spend.
2. `pantry.find_match` still ran the substring matcher that `436597d` had deleted
   everywhere else — 11 peanut-butter lines matched the `butter` staple row.
3. Both cook call sites read only `consumed`, rendering total failure as a green toast.

## The governing insight

**Inventory holds containers, not measured quantities.** 188 of 198 count-family rows
sit at quantity exactly `1.0` — the ingest default meaning "one package" — and 15 of 17
`oz` rows are a `1.0 oz` package. The naive fix (subtract harder) would have deleted a
whole jar of bay leaves for a recipe calling for three.

The design escalation to Claude Fable 5 is what surfaced this; it also caught that the
predicate fix and the matcher fix are coupled (fixing one alone would have started
decrementing the `butter` staple from 11 peanut-butter lines).

## What shipped

- `unit_compatibility()` — one predicate, both pantry functions delegate to it.
- `find_match` adopts the shared head-noun matcher; `_ATOMIC_FOODS` extended so
  compound foods stop matching single-token rows.
- `inventory.last_used` / `use_count` columns via the append-only `_MIGRATIONS`
  mechanism, plus `stamp_inventory_use()` — a targeted UPDATE, so a cook no longer
  rewrites all 222 rows and regenerates two vault notes.
- `consume_recipe()` rewritten: four-outcome classification (`consumed` /
  `use_recorded` / `not_tracked` / `skipped_staples`), the container gate, and
  `save_pantry` skipped entirely when nothing decrements.
- `POST /api/cook` gated behind `require_token` — it mutates inventory but, unlike
  `/api/cooks`, accepted unauthenticated non-localhost callers.
- One `renderCookToast()` replacing two duplicated blocks.

## What code review changed

The branch was green, self-verified, and **wrong in a way that destroyed data.** Review
found the container gate under-firing in three reachable ways, all in the un-healable
direction:

| Finding | Evidence |
|---|---|
| Weight packages aren't qty 1.0 | The live `pumpkin, 5 oz` row was **deleted** by `250 g pumpkin puree` in *Rich Fudgy Chocolate Cake* — 222 → 221 rows |
| Rows summed across locations | `load_pantry` sums `(name, unit)`, so two 1-ct jars read as one 2.0 and the gate fired on neither; `save_pantry` then dropped one row *with its stamps* |
| Cumulative subtraction | The per-line guard checked the *original* quantity, so two 100 g lines against a 5 oz (≈141.7 g) row each passed and jointly emptied it |

Plus two the plan never contemplated:

- **`mcp_server.cook_recipe` had the identical read-only-`consumed` defect** — the exact
  bug this branch exists to kill, in the Claude-facing client. Post-gate `use_recorded`
  outnumbers decrements ~24:1, so it would have answered "Nothing to decrement" for
  almost every cook that did touch inventory.
- **`use_count` double-incremented** when one row was both decremented by one line and
  merely used by another (verified: `use_count=2` from a single cook).

The invariant is consequently the absolute one — *a cook may reduce a row but never
delete one* — enforced in four cases. Count-family full depletion is still legitimate
and still happens (5 whole limes against a 5 ct row empties it).

## Measured outcome

| Metric | Spec target | Actual |
|---|---|---|
| Decrements | 18 | **19** |
| Use-stamps | 455 | **453** |
| Distinct rows touched | 90 | **90** |
| Recipes reporting | ~199 | **198** |
| False decrements | 0 | **0** |

2691 → **2715** unit tests; 25 → **28** e2e. `ruff` clean on every file authored.

Both safety nets were proven load-bearing by removing them: without the container gate,
cooking one recipe reduced the test inventory to a **single row**.

## Deliberately not fixed

- **`find_match("pumpkin puree")` → fresh-`pumpkin` row.** Matcher work. The harm is now
  capped at a reduction rather than a deletion.
- **`save_pantry` collapses duplicate-location rows unconditionally**
  (`lib/pantry.py:109-110`). Pre-existing, and reachable from the shopping-list confirm
  path with *no cook involved* — `save_pantry(apply_decisions([], load_pantry()))` merges
  two rows into one. The cook path is now safe; this is where the residual data loss
  lives. Fixing it is what would let the gate's `rows > 1` clause be narrowed later.
- **`split_against_pantry`'s volume/weight branch** keeps its own cross-family precheck,
  so delegation to `unit_compatibility` is not yet total. Zero corpus occurrences; the
  `CLAUDE.md` invariant was scoped to say so rather than overstate.

## Owed

1. ~~Reload the `com.kitchenos.api` LaunchAgent~~ — done at merge; `/health` 200, and the
   production DB migrated cleanly on first connect (222 rows, no NULL `use_count`).
2. **Surface `last_used` / `use_count` somewhere.** The columns are currently write-only —
   no view reads them, since `/review` surfacing was descoped to avoid colliding with
   `inventory-scan-and-extend`. Natural home is the `/review` subline, alongside
   `inventory-location-visibility`.
3. **Settle the token story for the browser pages.** `/api/cook` and `/api/cooks` are both
   gated and both called from `templates/meal_planner.html` with no `Authorization`
   header, so if `KITCHENOS_API_TOKEN` is ever set both cook buttons 401 for any
   non-localhost browser — and the tailnet is how these pages normally get opened.
   Inert today (the var is unset).
4. **No real cook has been run.** All measurement was read-only dry runs; the first live
   cook is a deliberate user action, not an implementation side effect.
