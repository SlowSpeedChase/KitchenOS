# Ingredient Data Cleaning — Plan

**Status:** Phase A1 shipped; remainder deferred (lower priority)
**Updated:** 2026-07-09

> **2026-07-09 update — priority pivot.** Phase A1 (table gaps: informal units, piece
> weights, densities, accents) **shipped** on the merged `ingredient-grams-coverage`
> branch (item coverage 0.56→0.65; see `docs/completed/2026-07-09-ingredient-grams-coverage.md`).
> A follow-up diagnosis then showed **this plan is not the load-bearing lever.** Measured
> **calorie-weighted** coverage is only **~0.47**, and 374 of the material misses are
> quantified, food-known lines that fail at *portion resolution* — a matching/density/
> fallback gap, not a text-cleanup gap. That work now lives in
> **[nutrition-portion-resolution.md](nutrition-portion-resolution.md)** and takes
> priority. The Phase A2 (leaked-amount) / Phase B (item-name) cleanup below is real but
> **secondary** — pursue it after portion resolution moves calorie coverage.
>
> **Original 2026-07-08 framing (for reference):** lift nutrition-engine grams coverage
> (median 0.58) via table gaps in this order — informal units, piece weights, densities,
> food-not-found aliases; amount-leaked-into-item (Phase A2) after.

## Context

The gram-based nutrition engine is only as accurate as its input. A vault audit
(`scripts/ingredient_quality_report.py`, see below) found **~66% of 3,254
ingredient rows are clean; ~34% have problems** that corrupt macro math or food
matching. The engine already flags these `needs_review`, but the fix is upstream:
make ingredient rows clean enough that the math is right.

User priorities: **(1) mathematical accuracy first, presentation later**, and
**(2) amounts stored as decimals, never fractions.**

### Where malformations originate (pipeline map)

- **Ollama extraction** violates its own schema: amount captures the item
  (`amount="Tomato Sauce"`), oven temps leak in (`"°f oil"`), units dropped so
  volume items become `whole` (`1 whole maple syrup`), duplicated words.
- **JSON-LD scraping & Crouton import skip `validate_ingredients()` entirely** —
  only the Ollama/free-text paths validate.
- **Markdown round-trip loss**: `templates/recipe_template.py` writes the
  `inferred` flag *into the item text* as `*(inferred)*`; `parse_ingredient_table`
  lowercases but never strips it, so markers accumulate and the flag is lost.
- **Parser gaps** (`lib/ingredient_parser.py`): Unicode fractions (`½ ⅓ ¼`) aren't
  parsed (fall back to `1`); embedded amounts in the item aren't re-extracted.

### Reuse (don't duplicate)

`lib/units.py` (`get_unit_family`, `lookup_density`, `lookup_piece_weight`,
`parse_amount_to_float`), `lib/ingredient_parser.py` (`parse_ingredient`,
`normalize_unit`), the `config + persist` alias pattern in `lib/item_aliases.py`,
and the existing `lib/ingredient_validator.py` (extend, don't replace).

---

## Phase A — Mathematical accuracy (do first)

These change the numbers that feed grams → macros. Goal: every row has a
**decimal amount + a unit whose family is known + a food-name item**, or it is
explicitly flagged.

### A1. Decimal amounts everywhere (incl. Unicode fractions) — high value, low risk
Extend `parse_amount` / `parse_amount_to_float` (`lib/ingredient_parser.py`,
`lib/units.py`) to:
- Map Unicode fractions `½ ⅓ ¼ ⅔ ¾ ⅛ ⅜ ⅝ ⅞ …` → decimals.
- Always emit **decimals** (`1/2`→`0.5`, `1 1/2`→`1.5`, `3/4`→`0.75`), rounded to
  2 dp. Word numbers (`one`→`1`) already handled.
- Ranges → decimal **midpoint** (`3-4`→`3.5`), matching what the engine already
  does internally, so storage and computation agree.
Fixes the 69 non-numeric-amount rows and makes all amounts decimal.

### A2. Re-extract amount/unit embedded in the item
When the amount field is non-numeric (`"Tomato Sauce"`, `"Large bunch"`) or the
item begins with a quantity (`"¾ cup greek yogurt"`, `"(estimated) 1/2 cup
parmesan"`, `"(14-ounce) can coconut milk"`), re-parse with `parse_ingredient`
to move the real amount/unit out of the item. Strip amount-bearing parentheticals
(`(estimated)`, `(14-ounce)`) into amount/unit. This is the single biggest
macro-accuracy win.

### A3. Unit correctness + family validation
Using `lib/units.get_unit_family` + `lookup_density`/`lookup_piece_weight`:
- If unit is `whole`/empty but the item is a known **liquid/powder** (density
  table) — a count unit is wrong → flag `needs_review` (don't silently miscount;
  we can't safely invent the volume).
- Normalize units (`normalize_unit`) and reject family `other` for
  non-informal items → flag.

### A4. Drop/flag non-ingredient rows
Temperature/instruction leakage (`°`, `degrees`, `preheat`, `minutes`, `°f oil`)
→ recognized as **not an ingredient**, removed (so it can't become a phantom row
or an absurd LLM portion estimate). The `MAX_INGREDIENT_GRAMS` cap already in the
engine is the backstop; this removes the cause.

### A5. LLM repair fallback (Claude), cached
Rows still malformed after A1–A4 go to Claude with a strict schema
`{amount: number, unit: string, item: string, confidence: 0..1}` — the same
constrained pattern that scored 100% on food resolution. Cache corrections in a
hand-correctable `config/ingredient_aliases.json` (the `item_aliases.py` pattern),
keyed by the raw row, so each bad string is fixed once.

---

## Phase B — Item-name cleanup (matching + presentation; defer)

Lower math impact (these items usually still resolve), so after Phase A:
- Strip `*(inferred)*`, `**`, markdown, and prep parentheticals (`(for brushing)`,
  `(optional)`) from the item; keep a clean food name.
- Collapse duplicated words (`"egg whites egg whites"`) with a whitelist for
  legitimate repeats (`"milk or vegan milk"`).
- **Root-cause fix**: stop encoding `inferred` in the item text. Render it without
  corrupting the name (and have the parser strip any legacy markers on read), so
  round-trips stop accumulating junk and the flag survives.

---

## Phase C — Wire in + migrate + measure

- **`lib/ingredient_cleaner.py`**: one `clean_ingredient(raw) -> CleanIngredient`
  (amount: float, unit, item, dropped: bool, needs_review, note) that A1–A5 feed.
  Funnel **all** sources through it — closing the JSON-LD and Crouton validation
  gaps — and extend `validate_ingredients` to call it.
- **Migration** `clean_ingredients.py` (mirrors `backfill_nutrition.py`):
  `--dry-run` prints per-row before/after, `--apply` rewrites the ingredient
  tables with `backup.create_backup()` first, flags `needs_review`. Then re-run
  `backfill_nutrition.py --force` so macros reflect the cleaned data.
- **Metric** `scripts/ingredient_quality_report.py`: the audit script made
  repeatable — reports clean%% by category. Target: **66%% → 90%%+** clean after
  Phase A migration. This is the accuracy gate, re-run before/after.

---

## Verification

- Unit tests: `tests/test_ingredient_cleaner.py` — table-driven per failure mode
  (unicode fractions → decimals, embedded amount extraction, unit-family mismatch
  flagging, temp-leak drop, dup-word collapse). Parser tests for the new decimal
  output.
- End-to-end: `clean_ingredients.py --dry-run` on a sample, then
  `ingredient_quality_report.py` before/after to confirm the clean% jump, then
  `validate_nutrition.py` to confirm macro error drops on the golden set.
- Follow the `finish-feature` checklist; update CLAUDE.md ingredient-pipeline docs.

## Critical files
- `lib/ingredient_parser.py` (A1, A2), `lib/units.py` (A1 shared parse)
- `lib/ingredient_validator.py` (extend), new `lib/ingredient_cleaner.py`
- `recipe_sources.py`, `import_crouton.py`, `api_server.py` (funnel all sources)
- `templates/recipe_template.py` + `lib/recipe_parser.py` (Phase B round-trip fix)
- new `clean_ingredients.py`, `scripts/ingredient_quality_report.py`,
  `config/ingredient_aliases.json`
