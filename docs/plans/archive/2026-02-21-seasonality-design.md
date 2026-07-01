# Seasonality Feature Design

**Date:** 2026-02-21
**Status:** Implemented

## Goal

Add seasonality awareness to KitchenOS so recipes are ranked by how many in-season ingredients they use. Meal plans should cluster recipes sharing common seasonal produce to minimize grocery waste and maximize freshness.

## Requirements

- Surface seasonal recipes on the Obsidian Dashboard and use seasonality as a strong signal in meal plan generation
- Texas-region produce calendar
- Static JSON as source of truth for seasonal data
- LLM (Ollama) fuzzy matching at extraction time to map ingredient names to seasonal entries
- Cache results in recipe frontmatter for Dataview access
- Migration script to backfill existing 180+ recipes

## Data Layer

**File:** `config/seasonal_ingredients.json`

```json
{
  "region": "texas",
  "ingredients": {
    "tomato": { "peak_months": [4, 5, 6, 10, 11], "category": "fruit" },
    "squash": { "peak_months": [5, 6, 7, 8], "category": "vegetable" },
    "peach": { "peak_months": [5, 6, 7], "category": "stone fruit" },
    "sweet potato": { "peak_months": [9, 10, 11], "category": "root" },
    "spinach": { "peak_months": [1, 2, 3, 4, 10, 11, 12], "category": "leafy green" }
  }
}
```

- ~60-80 entries covering Texas seasonal produce
- Each entry has `peak_months` (array of month numbers) and `category` (loose grouping)
- Pantry staples (flour, oil, soy sauce) are intentionally excluded — only fresh/seasonal produce

## LLM Fuzzy Matching

At extraction time (and during migration), Ollama matches recipe ingredients to seasonal JSON entries.

**Prompt pattern:**

```
Given these recipe ingredients:
["butternut squash", "olive oil", "garlic", "fresh sage", "parmesan"]

And these seasonal produce items:
["squash", "tomato", "peach", "spinach", "sage", ...]

Return ONLY the matches as a JSON array:
[{"ingredient": "butternut squash", "matches": "squash"}, {"ingredient": "fresh sage", "matches": "sage"}]

Rules:
- Only match fresh produce, skip pantry staples (oil, flour, spices, etc.)
- Match variants (butternut squash → squash, baby spinach → spinach)
- If no match, omit the ingredient
```

- Runs once per recipe, result cached in frontmatter
- Pantry staples naturally excluded (not in the seasonal JSON)
- LLM handles variant names ("butternut squash" → "squash", "baby arugula" → "arugula")

## Frontmatter Changes

New fields added to recipe YAML frontmatter:

```yaml
seasonal_ingredients: ["squash", "sage"]   # matched seasonal items from the JSON
peak_months: [5, 6, 7, 8]                  # union of all matched items' peak months
```

## Migration

Extends existing `migrate_recipes.py` with a new migration step:

1. Parse ingredients from each recipe's markdown body
2. Send ingredient list + seasonal JSON keys to Ollama for fuzzy matching
3. Write `seasonal_ingredients` and `peak_months` into frontmatter
4. Supports `--dry-run`
5. ~180 Ollama calls for backfill (small prompts, fast)

## Dashboard Integration

New "In Season Now" Dataview section on `Dashboard.md`:

1. Get current month
2. Filter recipes where `peak_months` contains current month
3. Sort by count of `seasonal_ingredients` (most seasonal first)
4. Group by shared seasonal ingredient

**Display:**

```
## In Season Now

### Squash (6 recipes)
- Butternut Squash Soup
- Roasted Squash Tacos
- ...

### Spinach (4 recipes)
- Spinach Artichoke Dip
- ...
```

## Meal Plan Generator Integration

Scoring changes in `generate_meal_plan.py`:

1. **Season score**: count of `seasonal_ingredients` in peak for current month
2. **Strong preference**: heavily favor higher-scoring recipes, but allow non-seasonal to fill gaps
3. **Ingredient clustering**: after picking a high-scoring recipe, boost other recipes sharing the same `seasonal_ingredients` — "buy squash once, use in 3 meals"
4. Respects existing constraints (variety, no excessive repetition)

## Components

| Component | Purpose |
|-----------|---------|
| `config/seasonal_ingredients.json` | Texas produce calendar (~60-80 items) |
| `lib/seasonality.py` | Score calculation, LLM matching, seasonal lookups |
| `prompts/seasonal_matching.py` | Ollama prompt template for fuzzy matching |
| `migrate_recipes.py` (extend) | Backfill seasonal frontmatter on existing recipes |
| `extract_recipe.py` (extend) | Run seasonal matching during extraction pipeline |
| `generate_meal_plan.py` (extend) | Season scoring + ingredient clustering |
| `Dashboard.md` (extend) | New "In Season Now" Dataview section |
| `templates/recipe_template.py` (extend) | Include new frontmatter fields |
