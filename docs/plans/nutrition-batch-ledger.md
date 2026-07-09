# Nutrition Batch Ledger (Phase 2) Design

**Status:** Ready
**Created:** 2026-07-09
**Updated:** 2026-07-09

> Phase 2 of nutrition accuracy. Supersedes the deferred "gated LLM portion fallback +
> hand density tables" approach in [nutrition-portion-resolution.md](nutrition-portion-resolution.md)
> (Phase 1, shipped). Reframe from a 2026-07-09 Fable consult: this is a **batch** problem,
> not a runtime parsing problem.

---

## Problem

After Phase 1 (energy nutrient-ID fix, FDC household portions, 429 backoff, caloric-sanity
guard, vault re-backfill), measured over 228 recipes / ~2570 lines:

- Calorie-weighted coverage **0.571**, item coverage 0.760, fully-covered recipes 12.7%.
- Remaining leak, ranked by calorie impact:
  - **322 "food known, grams failed"** — food resolved (`per_100g` known) but amount+unit
    couldn't convert to grams (cup/tbsp/tsp with no density + no FDC household portion;
    `whole`/`scoop`/`can` with no piece weight). **These contribute 0 kcal today — a 100%
    error on each.** The dominant remaining leak.
  - **95 "food not found"** — cryptic names, plurals, compound descriptors.
  - **201 spices/seasonings** — ~0 kcal, cosmetic; should be marked negligible, not chased.
  - **29 Foundation records with no summary energy** — oils/butter (fatty-acid rows only).

### The smell (why Phase 1's approach converges slowly)

We built a **general-purpose runtime NL→nutrition pipeline** — hand-maintained density/
piece-weight tables + live USDA lookups + string-match heuristics — for a corpus of ~2570
lines **that mostly never change**. Two structural mistakes fall out:

1. **Runtime USDA API calls violate our own local-first principle** and created the entire
   rate-limit saga (429 backoff, paced refresh, throttled measurement) that dominated Phase 1.
2. **We treat a finite, static corpus as a parser to perfect.** The "endless long tail"
   (unit synonyms, plurals, `1 scoop`, `a drizzle`, `granulated white sugar (50 g)`) is
   actually enumerable. We can afford to resolve every unique line **once**, validate it,
   and materialize the answer — instead of re-deriving it live forever.

---

## Solution

**The LLM becomes a table generator, not a runtime component.** Resolve each unique
ingredient line once, band-validate, and write it to a deterministic, human-auditable
**resolution ledger** (`line → canonical_food, grams, confidence, rationale`). Consume the
ledger deterministically forever; new lines are rare and append-only.

Keep the two-lookup split, but move the boundary:

- **LLM side (semantic):** line → `{canonical food, quantity, unit, grams}`. Portion
  knowledge ("1 medjool date ≈ 24 g", "1 scoop protein ≈ 30 g") is exactly what LLMs know
  cold. This replaces the hand-tabled density/piece-weight work.
- **Deterministic side (nutritional):** canonical food → per-100g macros, always from a
  **local** database, never from the LLM (per-100g hallucinates plausibly and loses
  provenance).

The LLM never emits macros end-to-end (only a flagged last-resort tier may). Every LLM
output is checked against sanity bands before it lands.

---

## Design

### Component A — Atwater energy fallback (do first, ~1 hr)

When a resolved food has macros but 0 summary energy (the 29 oils/butter), compute
`kcal/100g = 4·protein + 4·carbs + 9·fat` in `lib/food_db._per_100g` (after the 1008 →
2047 → 2048 chain). Oils → ~884. Fully general, no new data, no network.

### Component B — Bulk USDA → local SQLite (~1 day)

Download FDC bulk data (Foundation + SR Legacy + **FNDDS/Survey**) and load into a local
table. **FNDDS is the unlock**: built for dietary-recall coding, so every food carries
household portion weights ("1 cup", "1 medium", "1 slice") and complete summary energy —
directly attacking the 322 grams-failed.

- New `lib/food_db_local.py` (or a table in `data/kitchenos.db`): `foods(fdc_id, desc,
  per_100g, dataType)` + `food_portions(fdc_id, label, gram_weight)`.
- A loader `scripts/load_fdc_bulk.py` (download → parse CSV/JSON → upsert). Refresh is
  occasional (nutrition data barely changes); stamp a version.
- Repoint `usda_search`/`usda_food_detail` to the local table. **Delete the runtime API
  path + 429 backoff + paced-refresh machinery** (keep a thin optional live fallback behind
  a flag for genuinely novel foods).

### Component C — LLM-drafted resolution ledger (~1–2 days; the 0.57 → ~0.9 move)

- One batch pass (Ollama overnight, or a ~$2 Claude run) over every currently-unresolved
  unique line (~417). Prompt → strict JSON `{canonical_food, grams, confidence, rationale}`.
- **Validate against bands** before accepting:
  - volume ⇒ implied density 0.1–2 g/ml;
  - a tbsp of anything < 150 kcal; a tsp < 50 kcal;
  - piece weights within a plausible range for the food class;
  - grams > 0 and < `MAX_INGREDIENT_GRAMS`.
- In-band → write to `data/kitchenos.db` ledger `resolution_ledger(line_norm, food_fdc_id,
  grams, confidence, rationale, source, version)`. Out-of-band / low-confidence → an
  **Obsidian review-queue note** (do-not-edit-style, one row per line) for human sign-off.
  Expected human budget: ~100–150 lines, once.
- `_resolve_food`/`_resolve_grams` consult the ledger first (deterministic hit), before any
  table/portion logic.

### Component D — Metric + guardrails (fold in)

- Mark the 201 spice/seasoning lines `negligible` (0 kcal) so they stop counting as gaps.
- **Report calorie-weighted coverage only** (item coverage is misleading — Phase 1 lesson).
- **Recipe-level sanity check** in the backfill: flag any per-serving total < 100 or
  > 1500 kcal for a main → catches tbsp↔cup unit blunders that line-level checks miss.

### Steady state (new recipes)

ledger hit → local FNDDS portion → LLM draft (flagged, band-validated) → review queue.
Append-only; no runtime API, no hand tables.

---

## Implementation Notes

- **Sequence:** A (Atwater, 1 hr, immediate win) → B (bulk FNDDS, removes the rate-limit
  class of problems) → C (LLM ledger, the coverage jump) → D (metric/guardrails, throughout).
- **Reuse:** `scripts/calorie_coverage_report.py` (+ `--offline`, now the honest gate),
  the `food_cache`/`food_resolution` tables (ledger is a sibling), the constrained-JSON LLM
  pattern already used for food resolution, `MAX_INGREDIENT_GRAMS` backstop, the
  do-not-edit generated-note convention for the review queue.
- **Dependencies:** FDC bulk files (public download, no key/limit); Ollama (always) /
  Claude (`ANTHROPIC_API_KEY`, present) for the one-time ledger pass.
- **Data staleness:** bulk FDC is versioned + occasionally refreshed; acceptable — macros
  are stable.

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** — below.
- [x] **ADHD check passed** — below.
- [x] **Scope check** — A ~1 hr, B ~1 day, C ~1–2 days, D folded in; ~1 focused week,
      phaseable so each lands independently.
- [x] **No blockers** — FDC bulk is public; LLM keys present; Phase 1 merged.

### Acceptance Criteria

- [ ] **Calorie-weighted coverage 0.571 → ≥ 0.90** (`calorie_coverage_report.py`).
- [ ] **"Food known, grams failed" 322 → < 30** (portion resolution via FNDDS + ledger).
- [ ] **No runtime USDA API dependency** for a normal backfill (bulk-local + ledger);
      429 backoff / paced-refresh code deleted.
- [ ] **Ledger is human-auditable** and every entry is band-validated or human-approved;
      out-of-band lines land in the Obsidian review queue, not silently.
- [ ] **Golden set:** per-serving kcal within ±15% on ≥ 9/10 hand-labeled recipes.
- [ ] Recipe-level sanity flags fire on injected tbsp↔cup blunders; full suite green.

### ADHD Design Check

- [x] **Reduces friction?** Macros just work; no hand-table upkeep, no rate-limit babysitting.
- [x] **Visible?** Ledger + review-queue notes in Obsidian; calorie-coverage dashboard.
- [x] **Externalizes cognition?** The ledger *is* the memory — resolve once, never re-derive.
- [x] **Additive, never a chore?** Append-only; new lines auto-draft + queue, self-cleaning.

---

## What we STOP doing (explicit)

- Hand-extending density / piece-weight tables (FNDDS + ledger replace them).
- Runtime USDA API calls and all rate-limit engineering.
- String-match heuristics for the not-found tail (LLM picks the canonical record once).
- Generalizing the "52% LLM error" number — it was measured on *unquantified* rows; the
  322 are all quantified, where LLM portion estimation runs ~10–20% (vs today's 100% —
  zero calories).
- Optimizing item coverage; calorie-weighted coverage is the only metric that matters.

## Links

- **Supersedes (deferred parts of):** [nutrition-portion-resolution.md](nutrition-portion-resolution.md) (Phase 1, Done).
- **Related:** [purchase-based-nutrition.md](purchase-based-nutrition.md) (Vision; branded
  overrides layer on top of the ledger).
- **Origin:** 2026-07-09 Fable strategic consult (batch/ledger reframe).
- **Branch:** (added when implementation starts)
- **PR:** (added when complete)
