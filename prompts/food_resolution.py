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

PORTION_GRAMS_PROMPT = """Estimate the weight, in grams, of ONE "{unit}" of "{item}" \
as a single recipe would use it.
{portion_hint}
Estimate the AMOUNT A RECIPE CALLS FOR, never the size of the package it is sold in.

This matters most when the unit is "whole", which this pipeline also emits when a
recipe stated no amount at all. "One whole olive oil" is not a 1-litre bottle,
"one whole flour" is not a 1 kg bag, and "one whole honey" is not a full jar — for
anything poured, spooned or scooped, answer with a normal cooking quantity (a
tablespoon of oil, a cup of flour) even though "one whole" of it is not really a
thing. Reserve large weights for items that genuinely come as one countable piece:
a whole chicken, a block of tofu, a head of romaine.

Return ONLY a JSON object with exactly these keys:
{{"grams_per_unit": <number of grams for a single {unit}>, "confidence": <0.0 to 1.0>, "basis": "<short>"}}"""
