"""Prompts for the two constrained LLM jobs in the nutrition engine.

The LLM never invents macros. It does two narrow, checkable jobs:

1. **Food resolution** — pick the best-matching candidate (by index) from a list
   of real USDA/OFF foods. It can only choose among the given options.
2. **Portion → grams** — estimate the gram weight of one count unit ("1 medium
   shallot") when no deterministic conversion exists.

Both return strict JSON validated by the caller (``lib/food_resolver.py``).
"""

FOOD_RESOLUTION_PROMPT = """You are matching a recipe ingredient to the correct food in a nutrition database.

Ingredient: {ingredient}

Candidates:
{candidates}

Pick the candidate that best matches the ingredient as it is used in cooking
(consider the food form — raw, cooked, the specific variety). You must choose
one of the numbered candidates above; do not invent a food.

Return ONLY a JSON object with exactly these keys:
{{"choice_index": <integer index of the best candidate>, "confidence": <0.0 to 1.0>, "reason": "<short>"}}
If none match well, pick the closest and use a low confidence."""

PORTION_GRAMS_PROMPT = """Estimate the weight, in grams, of ONE "{unit}" of "{item}" as used in cooking.
{portion_hint}
Return ONLY a JSON object with exactly these keys:
{{"grams_per_unit": <number of grams for a single {unit}>, "confidence": <0.0 to 1.0>, "basis": "<short>"}}"""
