# Meal Occasion Field

**Date:** 2026-02-09
**Status:** Approved

## Summary

Add a `meal_occasion` field to every recipe — a list of up to 3 freeform strings describing when/how you'd actually make this recipe (e.g. "weeknight-dinner", "grab-and-go-breakfast", "meal-prep").

## Motivation

Recipes currently have `cuisine` and `dish_type` but nothing about the real-life *situation* they fit into. This field enables:
- Meal plan filtering (e.g. "show me all grab-and-go breakfasts")
- Dataview browsing grouped by occasion
- Combining with cuisine for themed weeks ("Italian meal prep week")

## Schema

```json
"meal_occasion": ["weeknight-dinner", "grab-and-go-breakfast"]
```

Up to 3 values per recipe. Freeform for now — standardize later once patterns emerge.

Values are slugified (lowercase, spaces → hyphens) and added to the tags list.

### Frontmatter Output

```yaml
meal_occasion:
  - weeknight-dinner
  - grab-and-go-breakfast
tags:
  - weeknight-dinner
  - grab-and-go-breakfast
```

### Example Occasions

weeknight-dinner, weekend-project, meal-prep, grab-and-go-breakfast, afternoon-snack, packed-lunch, lazy-sunday, date-night, crowd-pleaser, post-workout

## Files Changed

| File | Change |
|------|--------|
| `prompts/recipe_extraction.py` | Add `meal_occasion` to both prompt schemas with examples |
| `templates/recipe_template.py` | Add `meal_occasion` to frontmatter output + tags list |
| `extract_recipe.py` | Pass `meal_occasion` through (flows naturally) |
| `migrate_recipes.py` | New migration: infer `meal_occasion` for existing recipes via Ollama |

## Future

Once ~20 recipes have been tagged, review generated occasions, standardize into a fixed list, and run a re-classification migration.
