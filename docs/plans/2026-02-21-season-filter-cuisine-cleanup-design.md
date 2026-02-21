# Season Filter & Cuisine Cleanup Design

**Date:** 2026-02-21
**Status:** Approved

## Problem

1. The meal planner dashboard's cuisine filter list appears incomplete — 38 of 156 recipes (24%) have `cuisine: null`, and the remaining have 31 unique values with duplicates, misclassifications, and non-cuisine labels.
2. The seasonality system (seasonal_ingredients, peak_months) exists in recipe frontmatter but isn't exposed to the dashboard, and most recipes have empty seasonal data.

## Solution

A combined migration script + dashboard UI change:

1. **Cuisine data cleanup** — deterministic correction map
2. **Batch seasonal data population** — Ollama fuzzy matching for all recipes
3. **"In Season" toggle chip** — new filter on the meal planner dashboard

## Part 1: Cuisine Data Cleanup

### Script: `migrate_cuisine.py`

Standalone migration script with `--dry-run` support.

### Correction Map

```python
# Variant consolidation (→ base cuisine)
CUISINE_CORRECTIONS = {
    "Asian-inspired": "Asian",
    "Korean-inspired": "Korean",
    "Korean-American": "Korean",
    "Japanese-American fusion": "Japanese",
    "Chinese (Sichuan) or Asian": "Chinese",
    "Italian (inferred from Murcattt channel)": "Italian",
    "Vegan": None,        # dietary label, not cuisine — handled per-recipe
    "Vegetarian": None,
    "Not specified": None,
    "International": None,
    "Fusion": None,
    "protein:": None,      # corrupt data
}

# Per-recipe overrides (null fills + misclassifications)
RECIPE_OVERRIDES = {
    # Misclassified
    "Seneyet Jaj O Batata": "Middle Eastern",
    "Macarona Bi Laban": "Middle Eastern",
    "Beef Steak Pepper Lunch Skillet": "Japanese",
    "Spicy Baked Black Bean Nachos": "Tex-Mex",
    "Queso Dip Recipe": "Tex-Mex",
    "Chili Cheese Tortillas": "Tex-Mex",
    "Cilantro Lime Chicken": "Mexican",
    "Ginger-Lime Marinade For Chicken": "Asian",

    # Dietary labels → actual cuisine
    "200G Lentils And 1 Sweet Potato": "Indian",
    "Cauliflower Steak With Butter Bean Puree And Chimichurri": "South American",
    "High-Protein Bean Lentil Dip (Crouton)": "Middle Eastern",

    # Null fills
    "Pasta Aglio E Olio Inspired By Chef": "Italian",
    "Hash Brown Casserole": "American",
    "Rich Fudgy Chocolate Cake": "American",
    "Large Batch Freezer Biscuits": "American",
    "Lime Cheesecake": "American",
    "Meal Prep Systems": "American",
    # ... remaining ~25 null-cuisine recipes (mostly American baking/desserts)
}
```

### Logic

1. Scan all `.md` files in Recipes directory
2. Apply `RECIPE_OVERRIDES` first (specific per-recipe fixes)
3. Apply `CUISINE_CORRECTIONS` for variant consolidation
4. For remaining nulls, infer "American" for obvious baking/desserts
5. Write updated frontmatter back to file
6. Report: changes made, skipped, errors

### Expected Result

~20 clean, consistent cuisine values. Zero null cuisines for classifiable recipes.

## Part 2: Batch Seasonal Data Population

### Same Script, Second Phase

After cuisine fixes, populate seasonal data for recipes with empty `seasonal_ingredients`.

### Logic

1. For each recipe with `seasonal_ingredients: []`:
   - Parse ingredients from markdown body
   - Call `match_ingredients_to_seasonal(ingredients)` (Ollama fuzzy matching)
   - Call `get_peak_months(matches)`
   - Write both fields to frontmatter
2. Skip recipes with existing non-empty seasonal data
3. Requires Ollama running (`mistral:7b`)

### Performance

~1-2 seconds per recipe. ~156 recipes = 3-5 minutes total. Progress output per recipe.

### Error Handling

Log failures and continue. Script is idempotent — rerun to catch failures.

## Part 3: "In Season" Toggle Chip

### Backend

**`lib/recipe_index.py`**: Add `"peak_months"` to `FILTER_FIELDS` tuple.

No other backend changes needed — the API already returns all filter fields dynamically.

### Frontend (`templates/meal_planner.html`)

1. **New chip**: "In Season" rendered before dynamic filter chips
2. **Filter logic**: Show recipes where `peak_months` includes current month (1-12)
3. **AND combination**: Works with existing filters (cuisine + "In Season" = recipes matching both)

### Styling

- **Inactive**: White background, green border (#34C759), green text
- **Active**: Green background (#34C759), white text
- **Position**: First chip, before cuisine/protein/occasion chips
- **Label**: "In Season"

### Data Flow

```
Recipe frontmatter: peak_months: [2, 3, 4]
  → recipe_index.py includes peak_months in API response
  → meal_planner.html reads peak_months per recipe
  → "In Season" chip checks: currentMonth ∈ peak_months
  → Combined with search + other active filter chips
```

## Files Changed

| File | Change |
|------|--------|
| `migrate_cuisine.py` (new) | Migration script for cuisine cleanup + seasonal population |
| `lib/recipe_index.py` | Add `peak_months` to `FILTER_FIELDS` |
| `templates/meal_planner.html` | Add "In Season" chip with green styling and filter logic |
| `CLAUDE.md` | Document new migration script |

## CLI

```bash
# Preview changes
.venv/bin/python migrate_cuisine.py --dry-run

# Apply cuisine fixes + populate seasonal data
.venv/bin/python migrate_cuisine.py

# Apply cuisine fixes only (skip Ollama)
.venv/bin/python migrate_cuisine.py --no-seasonal
```
