# Tag Normalization & Import Validation Design

**Date:** 2026-02-21
**Status:** Approved

## Problem

Recipe tag fields contain inconsistent values from unvalidated Ollama extraction:
- **protein**: 50+ unique values (should be ~15). "chicken"/"Chicken"/"Chicken breast" all mean chicken.
- **dish_type**: 50+ unique values (should be ~13). "Main"/"Main Course"/"main course" all mean main.
- **difficulty**: 7 values (should be 3). Mostly case issues.
- **dietary**: 40+ unique values (should be ~11). "high-protein"/"High Protein"/"High-Protein" all mean high-protein.
- **meal_occasion**: Non-occasion values leaked in ("vegan", "dessert").

Additionally, the seasonal matching (Ollama fuzzy matcher) is too strict — only 8 of 187 recipes have `peak_months` data despite many containing obvious seasonal ingredients.

New recipes imported via `extract_recipe.py` have no validation layer, so the same inconsistencies continue.

## Solution

Three components:

### 1. Tag Migration Script

Extend `migrate_cuisine.py` (or add to it) to normalize all tag fields in existing recipes.

#### Controlled Vocabularies

**protein** (string, lowercase):
```
chicken, beef, pork, lamb, turkey, fish, seafood, tofu, tempeh,
eggs, beans, lentils, chickpeas, dairy, protein powder, null
```

Correction map:
- Case normalization: "Chicken" → "chicken", "Eggs" → "eggs"
- Cut consolidation: "Chicken breast", "chicken thighs", "Rotisserie chicken" → "chicken"
- Category consolidation: "ground beef" → "beef", "smoked sausage" → "pork"
- Bean variants: "Black beans", "White beans", "Butter beans" → "beans"
- Dairy variants: "cheese", "Feta", "Greek yogurt", "cottage cheese" → "dairy"
- Invalid values: "70g", "42g", "No specific protein listed" → null
- Comma-separated: take first/primary protein
- Per-recipe overrides for edge cases

**dish_type** (string, lowercase):
```
main, side, dessert, breakfast, snack, salad, soup, sandwich,
appetizer, drink, sauce, bread, dip
```

Correction map:
- Case + variant: "Main Course", "Main Dish", "Entrée", "pasta dish", "Bowl" → "main"
- Case: "Dessert" → "dessert", "Side" → "side"
- Merge: "Wrap" → "sandwich", "Smoothie" → "drink", "Condiment"/"Dressing" → "sauce", "Starter" → "appetizer"

**difficulty** (string, lowercase):
```
easy, medium, hard
```

Correction map:
- Case: "Medium" → "medium", "Easy" → "easy"
- Verbose: "Medium (due to need for planning...)" → "medium"

**dietary** (array of strings, lowercase hyphenated):
```
vegan, vegetarian, gluten-free, dairy-free, low-carb, low-calorie,
high-protein, high-fiber, keto, paleo, nut-free
```

Correction map:
- Case + format: "High Protein" → "high-protein", "Gluten-free" → "gluten-free"
- Remove ambiguous: standalone "dairy" → remove from dietary array

**meal_occasion** (array of strings, lowercase hyphenated):
```
weeknight-dinner, packed-lunch, grab-and-go-breakfast, afternoon-snack,
weekend-project, date-night, lazy-sunday, crowd-pleaser, meal-prep,
brunch, post-workout, family-meal
```

Cleanup:
- Remove leaked values: "vegan", "plant-based" (→ dietary), "dessert", "breakfast" (→ dish_type)

### 2. Import Normalization

Add `lib/normalizer.py` with a `normalize_recipe_data(recipe_data)` function that:

1. Applies the same correction maps used by migration
2. Lowercases and strips whitespace on all tag fields
3. Validates against controlled vocabularies
4. Unknown values → keeps value but sets `needs_review: true`
5. Called in `extract_recipe.py` after Ollama extraction, before saving

This ensures new recipes come in clean without needing future migrations.

### 3. Seasonal Matching Improvement

**Keyword fallback** (new, runs first):
- Simple substring/word matching of recipe ingredients against the 60 seasonal config entries
- Handles obvious cases: "corn" in ingredient → matches "corn" in config
- No Ollama call needed for clear matches

**Loosened Ollama prompt** (for remaining unmatched):
- Adjust prompt to be less strict about exact matches
- Run only for recipes where keyword fallback found 0 matches

**Re-run seasonal matching** on all 187 recipes after improvements.

## Architecture

```
extract_recipe.py
    ↓ (after Ollama extraction)
lib/normalizer.py:normalize_recipe_data()
    ↓ (after normalization)
lib/seasonality.py:match_ingredients_to_seasonal()  ← improved
    ↓
template → Obsidian

migrate_cuisine.py  ← extended with all tag fields
    ↓ (uses same maps as normalizer)
lib/normalizer.py  ← shared correction maps
```

## Testing

- Unit tests for each correction map
- Unit tests for `normalize_recipe_data()`
- Unit tests for keyword seasonal matching
- Dry-run migration on real vault before applying
- Verify recipe count and unique values after migration
