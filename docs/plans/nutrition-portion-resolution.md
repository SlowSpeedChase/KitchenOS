# Nutrition Portion Resolution Design

**Status:** Ready
**Created:** 2026-07-09
**Updated:** 2026-07-09

> Supersedes the informal "Phase A2 = leaked-amount cleanup" as the next nutrition
> priority. Diagnosis (2026-07-09) shows portion resolution, not text cleanup, is the
> load-bearing lever under per-serving macro accuracy. See
> [ingredient-data-cleaning.md](ingredient-data-cleaning.md) for the complementary
> text-cleanup work (now lower priority).

---

## Problem

Per-serving macros are trustworthy on only **7% of the vault** (16/228 recipes fully
covered). The headline "grams coverage 0.65" *understates* the problem for macros:
measured **calorie-weighted coverage is ~0.47** — the engine captures under half of each
recipe's calories. At that level the numbers are close to a coin flip and can't drive a
macro planner.

**Why the item-coverage number is misleading (measured over 947 unresolved lines):**

| Bucket | Count | Calorie impact | Root cause |
|---|---|---|---|
| Spices / seasonings | ~474 (50%) | ~0 kcal | Negligible test is **unit-keyed** (`to taste`/pinch), so `1 tsp garlic powder` falls through to the density table and misses. Cosmetic — doesn't move macros. |
| Material foods, **portion failed** | 374 | **large** | Food already resolved (`per_100g` known); `to_grams()` couldn't convert the unit. **All 374 are quantified** (cup 126, whole 126, tbsp 61, tsp 19). This is the calorie leak. |
| Material foods, **not found** | 158 | large | FDC search miss / bad match (e.g. `honey` returns no hit). Separate matching bug. |

The load-bearing bucket is the **374 quantified, food-known, portion-failed lines.**

### Why the machinery that exists doesn't land (verified 2026-07-09)

The portion path is already wired: `to_grams(..., usda_portions=...)`,
`units._match_portion()`, `_resolve_grams()` passes `record["portions"]`, and a gated LLM
fallback (`food_resolver.estimate_portion_grams`) exists. It fails for three concrete
reasons, **not** for lack of a feature:

1. **`portion_provider` defaults to `"none"`** (`nutrition_engine.py:287`). When the
   deterministic conversion misses, there is **no fallback** — the line dies unresolved.
   The default-off was chosen because LLM portions measured "~52% error" — but that was
   across *all* rows, including unquantified ones absent from our addressable set.
2. **`_match_portion` is too narrow / FDC labels are unhelpful.** Probes:
   - `cottage cheese [cup] → 226 g` ✓ (works when a clean household portion exists)
   - `all-purpose flour [cup] → None` — FDC returns one portion labeled `"1.0 RACC"` (an
     FDA regulatory unit), unmatchable to "cup".
   - `butter [tbsp] → None` — FDC detail has **zero** foodPortions.
3. **Volume units are half the misses** (cup/tbsp/tsp ≈ 206 of 374) and are a **density**
   problem, not a count-portion problem. `_match_portion` only serves count/"whole" units;
   there is no density lookup for most foods, so volume conversions with no household
   portion silently fail.

Portion *data availability* is **not** the bottleneck: **90% of cached food records
(1636/1819) already carry FDC portions.** The gap is matching + density + fallback.

4. **USDA rate-limiting silently corrupts backfill + measurement (found 2026-07-09).**
   `food_db.usda_search` swallows any non-200 into `[]` — including HTTP 429
   `OVER_RATE_LIMIT`. USDA FDC's keyed limit is ~1,000 req/hour; a full-vault backfill
   (228 recipes × several foods each) plus repeated coverage runs blows through it, so
   **resolvable foods return empty, never cache, and land in the "food-not-found"
   bucket** — inflating it with transient failures, not real gaps. Two consequences:
   (a) `usda_search`/`usda_food_detail` need **429 detection + backoff/retry** (and
   should distinguish "no match" from "throttled"); (b) the coverage meter must run
   **offline (cache-only)** so measurement never depends on the live API. Re-running the
   backfill within a fresh rate window will recover an unknown slice of the 158
   food-not-found lines for free.

---

## Solution

Make portion resolution a **layered cascade** with a real fallback, matched to the two
unit classes, and stop the spice noise. In priority order per line:

1. **Deterministic — count units** (`whole`, `each`, `clove`, `can`…): FDC household
   portion via a **broadened `_match_portion`** → existing piece-weight table → fallback.
2. **Deterministic — volume units** (`cup`, `tbsp`, `tsp`…): FDC "1 cup = X g" portion
   when present (cottage cheese case) → **density** (`ml × g/ml`) using a canonical density
   set + FDC-derived density where available → fallback.
3. **Gated LLM fallback** (`portion_provider="claude"`): only for **quantified material**
   rows the deterministic cascade misses. Constrained schema (`grams_per_unit`,
   `confidence`), validated range, cached per `(item, unit)` — the same pattern that scored
   100% on food resolution. Never invoked on spices or unquantified rows.
4. **Spices/seasonings → negligible-by-food**: a food-keyed negligible set (or one shared
   spice density ≈ 2.3 g/tsp, which is *correct*, not a fudge) so seasonings stop polluting
   coverage and stop reaching the LLM.

Local-first ordering (deterministic before LLM) honors the repo's local-first principle
and keeps cost/latency down; the LLM only touches the residue.

---

## Design

### Components (extend, don't replace)

- **`lib/units.py`**
  - `_match_portion`: widen unit synonyms (tbsp/tablespoon, tsp, cup, piece/whole/each),
    **ignore non-household labels** (`RACC`, gram-only), and prefer a portion whose
    label's measure matches the requested unit family.
  - Volume path: when unit family is volume and no matching household portion exists, use
    density (`density_g_per_ml` on the record, else a canonical `config/food_density.json`
    entry). Density already partly exists — extend coverage for the common volume foods in
    the residue.
- **`lib/nutrition_engine.py` / `food_resolver.py`**
  - Flip the effective default for the backfill path to `portion_provider="claude"` **for
    quantified material rows only**; keep `"none"` for unquantified/spice rows.
  - Keep the existing `(item|unit|provider)` cache so each portion is estimated once.
- **`config/`**: food-keyed negligible spice set (or shared spice density); extend
  `food_density.json` / `piece_weights.json` only where FDC has no usable portion.
- **`lib/food_db.py`**: for the 10% of records lacking portions and the 158 not-found
  (honey-class), a targeted re-resolve that fetches `usda_food_detail` (portions live on
  detail, not search) and fixes the search-normalization miss.

### Measurement (promote the throwaway validator)

`scripts/calorie_coverage_report.py` (from the 2026-07-09 scratch validator): reports
item coverage, fully-covered %, **estimated calorie coverage**, and the
grams-failed-by-bucket split. Deterministic sample → like-for-like before/after.

**Golden set:** hand-label ~10 recipes with trusted per-serving macros (from the source
page where available) to anchor the estimated calorie-coverage number, since true
calorie coverage has no ground truth in the vault today.

### Data flow (unchanged shape, new fallbacks)

```
line (amount, unit, item)
  → resolve food (per_100g, fdc portions, density)         [mostly cached, 90% have portions]
  → to_grams:
       count unit  → _match_portion(broadened) → piece_weight → LLM(gated)
       volume unit → fdc household portion → density → LLM(gated)
       spice       → negligible (0 g)
  → macros = per_100g × grams / 100
```

---

## Implementation Notes

- **Phase 1 (deterministic, no LLM):** broaden `_match_portion`, add volume/density path,
  spice-negligible set, re-fetch detail for the 183 portion-less records. Measure. This is
  the safe, offline core and should recover a large share of the 374 on its own.
  - **DONE (2026-07-09):** volume path now consults FDC household portions
    (`to_grams` used density-only and ignored `usda_portions` for volume units).
    Offline-measured: **+179 previously-dead volume lines** resolved from cache, no LLM,
    no new data. Commit `33ee3fc`.
  - **429 backoff** in `usda_search`/`usda_food_detail` + a cache-only mode for the meter
    (see root cause #4). Do this before the next backfill so the rate limit stops
    dropping real foods.
- **Phase 2 (gated LLM):** enable `portion_provider="claude"` for quantified material
  residue; **first re-measure the "52% error" claim on the addressable quantified set** —
  if it's still high, keep LLM confined to count units where it's strongest and lean on
  density for volume.
- **Migration:** after each phase, `backfill_nutrition.py --force` to re-derive macros,
  then the coverage report before/after. Restart `com.kitchenos.api` after `lib/` edits.
- **Dependencies:** `USDA_FDC_API_KEY` (present), `ANTHROPIC_API_KEY` (present, already
  load-bearing). No new services.
- **Reuse:** `units.lookup_density`/`lookup_piece_weight`/`get_unit_family`,
  `food_resolver.estimate_portion_grams` (exists, gated off), `food_db._portions_from_detail`
  (exists), the `(item|unit|provider)` resolution cache.

---

## Ready for Implementation Checklist

- [x] **Acceptance criteria defined** - see below
- [x] **ADHD check passed** - see below
- [x] **Scope check** - Phase 1 is ~2–3 days; Phase 2 ~1–2 days. Phaseable, each < 1 week.
- [x] **No blockers** - both API keys present; portion machinery + data already exist.

### Acceptance Criteria

- [ ] **Grams-failed-on-known-food: 374 → < 40** (≥90% of the portion-failure bucket
      resolved) on the full vault.
- [ ] **Estimated calorie coverage: ~0.47 → ≥ 0.80** via `calorie_coverage_report.py`.
- [ ] **Fully-covered recipes: 7% → ≥ 50%** (spices-negligible + portions together).
- [ ] **Golden set:** per-serving kcal within **±15%** on ≥8/10 hand-labeled recipes.
- [ ] No regression: full test suite green; new table-driven tests for `_match_portion`
      widening, volume/density path, spice-negligible, and the gated-LLM boundary
      (quantified-only, never spices).

### ADHD Design Check

- [x] **Reduces friction?** Macros just work; no manual portion entry.
- [x] **Visible?** Surfaced on the nutrition dashboard + coverage report.
- [x] **Externalizes cognition?** System resolves "1 cup of X → grams", not the user.
- [x] **Additive, never a chore?** Portion cache builds automatically; no upkeep.

---

## Links

- **Diagnosis:** this doc's Problem section (measured 2026-07-09; scratch scripts in the
  session scratchpad — promote `calorie_coverage_report.py` into `scripts/`).
- **Related:** [ingredient-data-cleaning.md](ingredient-data-cleaning.md) (text cleanup,
  complementary, lower priority) · [2026-07-08-macro-meal-planner-design.md](2026-07-08-macro-meal-planner-design.md)
  (the parked planner this unblocks).
- **Branch:** (added when implementation starts)
- **PR:** (added when complete)
