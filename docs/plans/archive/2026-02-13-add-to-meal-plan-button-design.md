# Add to Meal Plan Button

**Date:** 2026-02-13
**Status:** Approved

## Summary

Add an "Add to Meal Plan" button to every recipe's Tools callout. Clicking it opens a mobile-friendly HTML form (served by the API) where you pick week, day, and meal slot. The recipe is appended as a `[[wikilink]]` to the chosen meal plan slot.

Also migrate all recipe button URLs from `localhost:5001` to the Tailscale IP (`100.111.6.10:5001`) so buttons work from the Obsidian iPhone app.

## User Flow

1. Open a recipe in Obsidian (Mac or iPhone)
2. Click "Add to Meal Plan" in the Tools callout
3. Browser/Safari opens a form at `http://100.111.6.10:5001/add-to-meal-plan?recipe=Recipe%20Name`
4. Pick week (current + next 3), day (Mon-Sun), meal (Breakfast/Lunch/Dinner)
5. Submit → API appends `[[Recipe Name]]` to the meal plan file
6. Success page confirms the addition

## API Design

### `GET /add-to-meal-plan?recipe=<name>`

Serves an HTML form with:
- Recipe name displayed (read-only)
- Week dropdown: current week + next 3 weeks
- Day dropdown: Monday-Sunday
- Meal dropdown: Breakfast, Lunch, Dinner
- Submit button

Form is mobile-friendly (large touch targets, readable on iPhone).

### `POST /add-to-meal-plan`

Form body: `recipe`, `week`, `day`, `meal`

Logic:
1. Validate inputs
2. Find or create the meal plan file (`Meal Plans/{week}.md`)
3. If file doesn't exist, generate it using `meal_plan_template.py`
4. Parse the markdown to find `## {Day}` → `### {Meal}` section
5. Append `[[Recipe Name]]` on a new line in that section
6. Write the file
7. Return success HTML page

### Conflict handling

Append mode — if a slot already has a recipe, the new one is added alongside it (multiple recipes per meal).

## Button Template Change

Current (recipe_template.py):
```markdown
> ```button
> name Re-extract
> type link
> url http://localhost:5001/reprocess?file=...
> ```
```

New:
```markdown
> ```button
> name Re-extract
> type link
> url http://100.111.6.10:5001/reprocess?file=...
> ```
> ```button
> name Add to Meal Plan
> type link
> url http://100.111.6.10:5001/add-to-meal-plan?recipe=...
> ```
```

All buttons use Tailscale IP for iPhone compatibility.

## Files Changed

| File | Change |
|------|--------|
| `api_server.py` | Add `GET /add-to-meal-plan` (form) and `POST /add-to-meal-plan` (handler) |
| `templates/recipe_template.py` | Add "Add to Meal Plan" button, change all URLs to Tailscale IP |
| `migrate_recipes.py` | Migration to update existing recipes: add new button + change URLs to Tailscale IP |

## Constraints

- Must work on iPhone Obsidian app via Tailscale
- Tailscale must be connected for buttons to work from iPhone
- Mac Mini must be running the API server
