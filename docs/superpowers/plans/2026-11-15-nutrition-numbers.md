# Fix the Nutrition Numbers (E2) Implementation Plan

> Source: `docs/plans/2026-08-02-daily-driver-audit.md` §3.2 and Phase 3 items 16–19.
> Phase E row E2 of `docs/superpowers/plans/2026-11-10-land-unmerged-work.md`.

**Goal:** Stop the four resolution defects that still put impossible macros on real
recipes, measured on the live corpus before and after.

**Tech stack:** Python 3.11, pytest. No new dependencies. Worktree
`.worktrees/nutrition-numbers`, branch `feat/nutrition-numbers`.

## What is already done (checked 2026-11-15, don't redo)

- Item 17's first half: `resolution_guard.vet` already runs on the fdc-local path
  (`nutrition_engine._resolve_food`).
- Phase 1's plausibility gate (`nutrition_quality.implausible`) already keeps bad
  numbers out of the suggester and day totals. This plan fixes the numbers it catches.

## Measured baseline (live corpus, offline, cache only, no LLM)

461 recipes recomputed; **79 implausible** (43 kcal_too_high, 36 protein_too_high,
23 kcal_too_low, 4 protein_share_impossible).

| Defect | Evidence |
|---|---|
| Eggs → *Egg, white, dried* (79.9 g protein/100 g) | ~60 lines: `eggs` ×20, `large eggs` ×20, `egg` ×7 … Ranker: dried white 4.4 vs whole raw 4.3 — `raw`/`fresh` are stopwords, and the Foundation rank bonus decides. |
| Package-weight ledger rows | `protein powder\|whole` = 300.0 (passes `> 300`), `pie dough rounds` 500/round, `sesame oil\|whole` 284, `mozzarella\|whole` 340, `cocoa powder\|whole` 250, cans at 800 g. The band is checked on **write** only, so a row written before a band change is used forever. |
| Frying medium counted as eaten | Chick-Fil-A nuggets: 8 cups peanut oil = 16,128 kcal; Crispy Tofu Katsu 2–4 cups; Tofu 65 deep-frying oil 7,017 kcal. |
| `black peppercorns` → *Black Russian* (a cocktail) | Then weighed with the 100 g piece weight: 30 "whole" = 3 kg, 8,370 kcal in Tofu Tikka Masala. |

Out of scope (measured, not this plan): `servings: 1` whole-batch recipes (servings
backfill), unresolved-but-caloric undercounts (`kcal_too_low`).

## Tasks

1. **Egg ranks as whole raw egg.** In `fdc_local.score_candidate`, penalise a state word
   (`dried`, `dehydrated`, `powder(ed)`, `frozen`, `pasteurized`) that the candidate has and
   the query does not, gated on some candidate lacking it (`_available_head` rule) and
   exempting `Spices,` records (a bare spice is dried by default). A bare head prefers the
   record whose second field is exactly `whole` (Egg, whole). Tests seeded from real rows.
2. **Peppercorns are pepper.** Query alias `peppercorn(s)` → `black pepper` before recall,
   so the spice record wins and the spice piece-weight guard applies.
3. **Re-band the portion ledger, and band on read.** `>=` for the bulk-whole ceiling;
   `can`/`tin` ceiling 800 g (largest retail can, 28 oz = 794 g); extend
   `_BULK_SUBSTANCES` with `cheese`, `cocoa`, `spray`, `dough`. `_resolve_grams` re-validates
   every ledger row against the current band with the resolved record's kcal, so stale rows
   stop counting without a DB purge.
4. **Frying-medium rule.** An oil/shortening/lard line is a frying medium when its text says
   fry/frying, or it weighs ≥ 400 g (~2 cups oil). Count `FRYING_ABSORBED_FRACTION` (0.10)
   of it, mark the line `needs_review` with a note saying so.
5. **Measure and re-derive.** Re-run the corpus measurement; whole-corpus before/after diff
   of every recipe that moved. Then `backfill_nutrition.py --force` so stored frontmatter
   matches.
6. **Docs.** CLAUDE.md invariant (frying + ledger band on read), INDEX.md row, ROADMAP.

## Acceptance

- Implausible count falls; every recipe that **got worse** is explained in the PR.
- No egg line resolves to a dried record unless the line says dried/powder.
- Full unit suite green.
