"""Prompt templates for cross-recipe task classification.

The model classifies each instruction step as prep / active / passive,
estimates duration, and flags do-ahead and parallelizable tasks.
"""

CLASSIFY_PROMPT = """You are a kitchen workflow assistant. The user has a week of meals
scheduled and wants to know which cooking steps can be done as advance prep
or in parallel with other recipes — so they can knock out one task at a time
when they have a spare 15 minutes, instead of facing a full cooking session.

## Scheduled meals this week
{recipes_block}

## Your task
For each numbered step in each recipe, classify it and emit a JSON task object.

Classification rules:
- type:
  - "prep" — chopping, marinating, soaking, mise en place, anything not requiring active heat
  - "active" — cooking that requires the user's attention (sauteing, flipping, stirring)
  - "passive" — heat is on but the user is free (simmering, baking, resting, cooling)
- time_minutes: integer estimate. Default 5 if unclear.
- can_do_ahead: true when the step can be safely done hours or a day before serving
  (e.g., marinades, dry rubs, chopped veg stored airtight, made-ahead sauces).
  False for time-sensitive steps (boiling pasta, plating).
- depends_on: list of step numbers within the SAME recipe that must finish first.
  Empty list when none.

Respond with ONLY a JSON array. Each object has these exact keys:
{{
  "recipe": "<recipe name>",
  "day": "<day>",
  "slot": "<breakfast|lunch|snack|dinner>",
  "step": <integer step number>,
  "text": "<original step text>",
  "type": "prep|active|passive",
  "time_minutes": <int>,
  "can_do_ahead": <bool>,
  "depends_on": [<int>, ...]
}}

No markdown fences. No explanation. Just the JSON array.
"""
