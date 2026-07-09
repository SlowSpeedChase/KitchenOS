# Purchase-Based Nutrition (Branded Overrides) Design

**Status:** Vision
**Created:** 2026-07-09
**Updated:** 2026-07-09

> Captured from a 2026-07-09 idea: use what the user actually buys to get more
> accurate, personal recipe macros. Not yet ready — see "Open questions / blockers".

---

## Problem

Recipe macros currently resolve every ingredient to a **generic** USDA record
("heavy cream" → USDA "Cream, heavy"). That ignores that the user buys *specific
branded products* — a particular 2% milk, protein powder, soy sauce — whose label
nutrition is exact for what they actually eat. It also leaves branded/packaged
items that USDA matches poorly (protein powder, mirin, sriracha) as failures.

## Solution (sketch)

Layer a **branded override** on top of the existing USDA-backed engine: when a
recipe ingredient matches something the user has **purchased** (via the existing
inventory ↔ recipe matching used by Cook Now / `for_recipe`), prefer that product's
**branded label nutrition** over the generic USDA record.

Bonus: branded labels carry **serving-size-in-grams**, which also helps the portion
problem for exactly the packaged items USDA portions cover worst.

## Design notes

- **Receipts do NOT carry nutrition or barcodes** (verified: `purchases` =
  `raw_name, canonical_name, quantity, unit, price, category`; `trips` = raw text).
  A receipt only *identifies the product*; nutrition still comes from a **branded
  source** (Open Food Facts / USDA Branded), matched by the (cryptic) purchase name.
  So this moves the matching problem to branded lookup, it doesn't remove it.
- **Augments, never replaces.** Produce, pantry staples, spices, CSA veg have no
  branded label or recent purchase — USDA stays the backbone. This only overrides
  the branded-packaged subset.
- **Reuse existing scaffolding:** the `food_resolution` table already has a
  `resolver` field and supports human-pinned overrides; this would auto-populate a
  "purchased" resolver. Inventory↔recipe matching already exists.

## Open questions / blockers

- **No data yet:** `purchases` / `trips` / `inventory` are currently **0 rows** in
  `data/kitchenos.db`. Needs the receipt ingest actually flowing before this can be
  built or even evaluated.
- Match rate of cryptic receipt names → Open Food Facts branded records is unknown.
  **First cheap test (do before building):** ingest a receipt or two, resolve a
  handful of branded items against OFF, measure hit rate + presence of serving-gram
  data.
- Not the highest-ROI next step: the dominant calorie bug (energy nutrient ID) is
  already fixed without receipts, and the remaining accuracy risk (wrong generic
  matches like apple→strudel) is mostly produce, where receipts don't help.

## Relationship to other work

Complements [nutrition-portion-resolution.md](nutrition-portion-resolution.md)
(generic USDA accuracy). This is the *personalized* layer on top, revisit once
receipt data exists.
