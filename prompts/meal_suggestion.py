"""Prompt templates for meal suggestion engine."""

NORMALIZE_PROMPT = """Normalize these ingredient names to base grocery items.
Remove preparation words (diced, minced, sliced), sizes (large, small),
and descriptors (fresh, frozen, boneless, skinless).
Group equivalent cuts of the same protein (e.g. chicken breast, chicken thigh → chicken).

Input ingredients:
{ingredients}

Respond with ONLY a JSON array of normalized names, same order as input.
Example: ["chicken", "tomato", "greek yogurt"]"""


SUGGEST_PROMPT = """You are a meal planning assistant. The user is planning meals for the week and wants to minimize grocery shopping by reusing ingredients and leftovers across meals.

## Already planned this week:
{planned_meals}

## Candidate recipes (ranked by ingredient overlap with planned meals):
{candidates}

Pick the best candidate for {day} {meal} considering:
1. Can leftovers from an earlier meal be directly reused? (e.g., roast chicken → chicken soup)
2. Which candidate adds the fewest NEW ingredients to the shopping list?
3. Does it make sense for the position in the week? (batch cook early, use leftovers later)

If no candidate is a strong fit, suggest a simple new recipe idea that builds on this week's ingredients.

Respond with ONLY this JSON (no markdown, no explanation):
{{"name": "Recipe Name", "reason": "one sentence explaining ingredient reuse", "is_new_idea": false, "new_ingredients_needed": ["item1", "item2"]}}"""


SUGGEST_EMPTY_WEEK_PROMPT = """You are a meal planning assistant. The user is starting a fresh week with no meals planned yet.

## Available recipes in their library:
{recipe_summaries}

Suggest the best recipe to start the week for {day} {meal}. Choose a recipe that:
1. Uses versatile ingredients that can be reused in other meals later in the week
2. Works well for batch cooking or produces useful leftovers

Respond with ONLY this JSON (no markdown, no explanation):
{{"name": "Recipe Name", "reason": "one sentence explaining why this is a good starting point", "is_new_idea": false, "new_ingredients_needed": []}}"""
