# Ingredient Amount/Unit Split Design

## Overview

Split the ingredient "Amount" column into separate "Amount" and "Unit" columns for better Dataview queries and consistency. Handle informal measurements like "a pinch", "to taste", etc.

## Data Model

**Current schema**:
```json
"ingredients": [{"quantity": "1/2 cup", "item": "flour", "inferred": boolean}]
```

**New schema**:
```json
"ingredients": [{
  "amount": 0.5,
  "unit": "cup",
  "item": "flour",
  "inferred": boolean
}]
```

**Markdown table** (3 columns):
```
| Amount | Unit | Ingredient |
|--------|------|------------|
| 0.5 | cup | flour |
| 1 | a pinch | salt |
| 2 | whole | eggs |
```

## Parsing Rules

### Unit Normalization

Standard units normalize to abbreviations:

| Input variants | Output |
|----------------|--------|
| tablespoon, tablespoons, tbsp, tbs | tbsp |
| teaspoon, teaspoons, tsp | tsp |
| cup, cups | cup |
| ounce, ounces, oz | oz |
| pound, pounds, lb, lbs | lb |
| gram, grams, g | g |
| kilogram, kilograms, kg | kg |
| milliliter, milliliters, ml | ml |
| liter, liters, l | l |
| clove, cloves | clove |
| head, heads | head |
| knob | knob |
| bunch, bunches | bunch |
| sprig, sprigs | sprig |
| slice, slices | slice |
| piece, pieces | piece |
| can, cans | can |

### Informal Measurements

These go in the Unit column with Amount = 1:

- a pinch, a smidge, a dash, a sprinkle, a handful, a splash
- to taste, as needed
- some, a few, a couple

### Default Unit

When no unit is found (e.g., "2 eggs", "1/2 lemon"), use `"whole"`.

### Parsing Order

1. Check if string starts with an informal measurement → `amount=1, unit=<informal>`
2. Extract leading number (handles fractions like "1/2", mixed like "1 1/2")
3. Match next word(s) against unit map → normalize
4. If no unit found → `unit="whole"`
5. Remainder is the ingredient item

## Edge Cases

| Input | Amount | Unit | Ingredient |
|-------|--------|------|------------|
| `1" knob fresh ginger` | 1 | knob | fresh ginger |
| `3-4 cloves garlic` | 3-4 | clove | garlic |
| `Salt and pepper to taste` | 1 | to taste | salt and pepper |
| `Lavash bread` (no amount) | 1 | whole | lavash bread |
| `1/2 lemon, juiced` | 0.5 | whole | lemon, juiced |
| `One large onion` | 1 | whole | large onion |

**Range handling**: Keep ranges as strings ("3-4") rather than picking one value.

**Word numbers**: Convert "one", "two", "three" etc. to digits.

**Parsing failures**: Set `amount=1`, `unit="whole"`, `item=<original string>`, log warning.

**Empty ingredients**: Skip rows where both amount and ingredient are empty.

## Files to Modify

| File | Changes |
|------|---------|
| `lib/ingredient_parser.py` | **New file** - parsing functions |
| `templates/recipe_template.py` | Update table format to 3 columns |
| `prompts/recipe_extraction.py` | Update AI prompt for new schema |
| `recipe_sources.py` | Update webpage scraper for new schema |
| `migrate_recipes.py` | Add migration for existing recipes |

## Migration

- Parses each recipe markdown file
- For each ingredient row, runs parser on combined "Amount + Ingredient" text
- Rewrites ingredients table with 3 columns
- Backs up originals to `.history/` before modifying
- Supports `--dry-run` flag to preview changes
