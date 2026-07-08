# Smart Fill for Meal Plans

**Date:** 2026-02-14
**Status:** Approved

## Summary

Add "Smart Fill" to meal plans — an Ollama-powered feature that fills empty meal slots in a partially-filled weekly plan. You pin a few recipes you want, then Smart Fill picks recipes for the remaining slots, optimizing for variety (protein, cuisine), time constraints (quick on weekdays), and meal_occasion matching.

## Core Concept

1. Read the meal plan file, identify empty slots
2. Load the recipe catalog — all recipe files' frontmatter (title, cuisine, protein, dish_type, meal_occasion, difficulty, prep_time, cook_time)
3. Send one Ollama prompt with: the catalog, the already-filled slots, day-of-week context (weekday vs weekend), and constraints
4. Ollama returns recipe picks for each empty slot
5. Write `[[recipe]]` wikilinks into the empty slots

### Constraints Passed to AI

- Weekday dinners should be ≤30 min total time
- Don't repeat the same protein on consecutive days
- Don't repeat the same cuisine within 3 days
- Match `meal_occasion` when available (breakfast recipes for breakfast, etc.)
- Prefer recipes that haven't been used in recent meal plans (last 2 weeks)

## Invocation

### CLI

```bash
# Fill empty slots in existing meal plan
python generate_meal_plan.py --fill 2026-W07

# Preview without modifying
python generate_meal_plan.py --fill 2026-W07 --dry-run
```

If the meal plan file doesn't exist yet, create the blank template first, then fill.

### Obsidian Button

Add a "Smart Fill" button to the meal plan template alongside "Generate Shopping List":

```markdown
```button
name Smart Fill
type link
url {API_BASE_URL}/fill-meal-plan?week=2026-W07
```
```

New API endpoint: `GET /fill-meal-plan?week=<week>`

### Behavior

- Only touch empty slots — never overwrite manually-placed recipes
- After filling, the file is a normal meal plan — swap anything you don't like
- Read previous 2 weeks of meal plan files to avoid recent repeats

## Prompt Design

### Recipe Catalog Format

One line per recipe to keep token count manageable (~15 tokens each, ~1000 total for 63 recipes):

```
1. Cilantro Lime Chicken | american | chicken | sandwich | 20min | easy | occasions: []
2. Chocolate PB Protein Pancake Bowl | american | breakfast | 2min | medium | occasions: breakfast, lazy-sunday
3. Chicken Fricassée | french | chicken | stew | 45min | medium | occasions: []
```

### Prompt Structure

- **System:** "You are a meal planning assistant. Given a recipe catalog and a partially-filled weekly meal plan, fill the empty slots."
- **Rules:** Variety, time, occasion matching, avoid recent repeats
- **Input:** Catalog + current plan state + recent history
- **Output:** JSON — `{"monday": {"breakfast": 12, "dinner": 45}, "tuesday": {"lunch": 3}}` (recipe numbers for empty slots only)

### Handling Sparse Data

- If `meal_occasion` is empty, fall back to `dish_type` for slot matching (e.g., dish_type "Breakfast" → breakfast slot)
- If `prep_time`/`cook_time` is null, treat as unknown — don't penalize, but prefer recipes with known times for weeknight slots
- Normalize time strings to minutes before sending (strip "(estimated)", parse "20 minutes" → 20)

### Token Budget

~63 recipes × ~15 tokens = ~1000 tokens for catalog. Well within Mistral 7B's context window.

## Error Handling

- **Invalid recipe from Ollama:** Validate every returned recipe number against catalog. Skip invalid picks, log warning.
- **Picks for filled slots:** Ignore — only write to slots that were empty.
- **No meal plan file:** Create blank template first, then fill.
- **Too few recipes:** Relax constraints — better to repeat than leave slots empty.
- **Ollama down:** Fail gracefully with clear error message.

## Out of Scope

- No macro optimization (My Macros.md doesn't exist, most recipes lack nutrition data)
- No grocery/pantry awareness
- No user preference learning over time

## Files Changed

| File | Change |
|------|--------|
| `lib/smart_fill.py` | New — catalog loader, time normalizer, prompt builder, Ollama call, response parser |
| `prompts/smart_fill.py` | New — system prompt and user prompt templates |
| `generate_meal_plan.py` | Add `--fill` flag, call smart_fill |
| `api_server.py` | Add `/fill-meal-plan` endpoint |
| `templates/meal_plan_template.py` | Add "Smart Fill" button to template |
