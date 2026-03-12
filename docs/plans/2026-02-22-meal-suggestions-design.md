# Meal Suggestion Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

Tap an empty meal slot in the meal planner to get an ingredient-aware recipe suggestion. The system minimizes grocery shopping by reusing ingredients and leftovers across the week.

## Architecture

Hybrid local (Ollama) + cloud (Claude API) pipeline:

```
User taps empty cell → POST /api/suggest-meal
    ↓
Backend collects context:
  1. Parse ingredient lists for all planned meals this week
  2. Load recipe library ingredient index
    ↓
Ollama (local, mechanical):
  - Normalize ingredient names (cached per recipe)
  - Python scores each unplanned recipe by ingredient overlap
  - Return top 10 candidates as structured JSON
    ↓
Tier decision:
  - Week empty → skip scoring, send library summary to Claude
  - Top score >= 0.5 → use directly (no Claude call)
  - Top score < 0.5 → send candidates to Claude
    ↓
Claude API (when needed):
  - Receives planned meals + top candidates + shared ingredients
  - Picks best match OR suggests new recipe idea
  - Returns: { name, reason, is_new_idea, new_ingredients_needed }
    ↓
Frontend auto-fills the cell, shows reason toast
```

## Ingredient Overlap Scoring

For each unplanned recipe R:

```
shared = intersection(R.ingredients, planned_ingredients)  # by normalized item name
overlap_score = len(shared) / len(R.ingredients)           # 0.0 to 1.0
```

### Matching rules

- Normalize items to base grocery item (lowercase, strip adjectives like "diced", "fresh")
- Group equivalent proteins: "chicken breast" ≈ "chicken thigh" → "chicken"
- Ignore pantry staples (configurable in `config/pantry_staples.json`)
- Use existing `lib/ingredient_parser.py` for parsing

### Pantry staples (excluded from scoring)

```json
["salt", "pepper", "olive oil", "vegetable oil", "butter", "garlic",
 "onion", "flour", "sugar", "water", "cooking spray"]
```

### Threshold

- `overlap_score >= 0.5` → use candidate directly without Claude call
- Below threshold → escalate to Claude API

## Prompt Design

### Ollama: Ingredient normalization

```
Given these ingredient items from recipes, normalize each to its base
grocery item. Remove preparation methods, sizes, and adjectives.
Group equivalent proteins.

Input: ["boneless skinless chicken thighs", "fresh diced tomatoes",
        "low-fat Greek yogurt", "extra virgin olive oil"]

Output JSON: ["chicken", "tomato", "greek yogurt", "olive oil"]
```

Runs once per recipe when building the ingredient index (cacheable).

### Claude API: Meal selection

```
You are a meal planning assistant. The user is planning meals for the week
and wants to minimize grocery shopping by reusing ingredients and leftovers.

## Already planned this week:
{planned_meals_with_ingredients}

## Candidate recipes (ranked by ingredient overlap):
{top_candidates_with_shared_ingredients}

Pick the best candidate for {day} {meal} considering:
1. Can leftovers from a planned meal be directly reused?
2. Which candidate adds the fewest NEW ingredients to the shopping list?
3. Does it make sense for the day/position in the week?

If no candidate is a good fit, suggest a simple new recipe idea that
builds on the week's ingredients.

Respond as JSON:
{
  "name": "Recipe Name",
  "reason": "one sentence why",
  "is_new_idea": false,
  "new_ingredients_needed": ["list", "of", "items"]
}
```

Token budget: ~500-800 input tokens, ~50 output tokens. Cost: ~$0.005/suggestion.

## Tier Decision Rules

| Scenario | Model used | Rationale |
|----------|-----------|-----------|
| Week empty, first meal | Claude with library summary | No overlap data, need creative pick |
| 1+ meals planned, top score >= 0.5 | Local scoring only | High overlap = obvious match |
| 1+ meals planned, top score < 0.5 | Ollama scores → Claude picks | Need reasoning about leftovers |
| No good existing recipe | Claude suggests new idea | Creative task beyond local model |

## UI Changes

### Empty cell tap behavior

1. Tap empty cell → "Drop recipe" label becomes spinner, cell border pulses blue
2. Suggestion arrives → auto-fills with standard grid card + ↻ (retry) button
3. Failure → toast "No suggestions available", cell returns to empty state

### Suggested card elements

Identical to manually-placed cards (image, remove button, servings) plus:
- **↻ button** (top-left, opposite the × button) — requests next suggestion
- ↻ button disappears after auto-save (becomes a regular card)

### "New idea" cards

When Claude suggests a recipe not in the library:
- Dashed border instead of solid
- Name in italics
- Saved as plain text in meal plan (not a `[[wikilink]]`)

### Toast messages

- Overlap match: "Shares chicken, yogurt with Monday's Shawarma"
- Claude reasoning: "Uses leftover chicken from Monday"
- New idea: "New idea: make stock from Monday's chicken bones"

### No new chrome

No buttons added to header or sidebar. Interaction is tapping the empty cell.

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No `ANTHROPIC_API_KEY` | Ollama scoring only, no creative suggestions |
| Ollama not running | Error toast, no suggestions |
| Claude API fails | Fall back to top Ollama-scored candidate |
| No planned meals yet | Claude gets library summary, suggests starting point |
| Recipe has no ingredients | Excluded from scoring |

## Configuration

### Environment

```
ANTHROPIC_API_KEY=sk-ant-...  # Required for Claude suggestions
```

### Claude API settings

- **Model:** `claude-haiku-4-5-20251001`
- **Max tokens:** 200
- **Estimated cost:** ~$0.10/week if every slot uses Claude

### New config file

`config/pantry_staples.json` — ingredients excluded from overlap scoring

## File Changes

### New files

| File | Purpose |
|------|---------|
| `lib/meal_suggester.py` | Core suggestion logic (scoring + Claude/Ollama calls) |
| `prompts/meal_suggestion.py` | Prompt templates for Ollama and Claude |
| `config/pantry_staples.json` | Pantry staples list |

### Modified files

| File | Change |
|------|--------|
| `api_server.py` | New `/api/suggest-meal` endpoint |
| `templates/meal_planner.html` | Tap-to-suggest on empty cells, retry button, new-idea styling |
| `lib/recipe_index.py` | Extend to optionally include parsed ingredients |

### New dependency

`anthropic` Python package for Claude API calls.

## User Story

1. Open meal planner, drag Chicken Shawarma to Monday dinner
2. Tap empty Tuesday dinner cell → spinner → auto-fills **Chicken Gyros** ("Shares chicken, yogurt, pita with Monday")
3. Tap ↻ → fills **Fattoush Salad** ("Uses leftover cucumber, tomato, lemon")
4. Tap empty Wednesday dinner → low overlap → Claude suggests **Chicken Fried Rice** ("Use leftover chicken from Monday's shawarma batch")
5. Tap empty Thursday dinner → nothing matches → Claude suggests new idea: "Chicken Stock Soup" shown with dashed border
