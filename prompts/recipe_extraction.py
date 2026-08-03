"""Prompt templates for AI recipe extraction"""

# Stated once and shared by both extraction prompts. The recipe name becomes the
# FILENAME, which is the recipe's identity everywhere (cooks rows, meal plans,
# task-ID hashes), so a video title landing here is not a cosmetic problem — it
# is permanent. See lib/short_title.py for the display-side repair of names that
# were captured before this rule existed.
NAMING_RULE = """- recipe_name is the NAME OF THE DISH, not the title of the video. Video titles
  carry things a dish name must not: channel names, "Recipe", "| EASY!", emoji,
  "- YouTube", episode numbers, and clickbait ("You Won't Believe..."). Strip all
  of it and write what you would call the dish on a menu.
  Aim for under 30 characters; never exceed 60.
  If the video title is not in English, name the dish in English
  ("Korean Potato Cheese Bread", not the original title).
  Keep a qualifier ONLY when it distinguishes this version from the plain dish
  (e.g. "High-Protein", "Slow Cooker", "No-Bake") — those change what you cook."""

# Batch cooking only buys variety if the leftovers keep, and nothing in the
# corpus recorded whether they do. Deliberately biased toward null: a wrong
# `true` sends a portion into the freezer to be thrown out weeks later, which is
# worse than no answer at all.
FREEZING_RULE = """- freezes_well: true only if the source says leftovers freeze, or the dish is
  unambiguously freezer-safe (soups, stews, braises, chilis, curries, cooked
  grain-and-protein dishes, baked goods, meatballs, sauces).
  false only if it clearly does not keep: leafy salads, fried or crisp coatings,
  dishes built on chunks of potato, cream/mayo/yogurt dressings, custards,
  anything raw or served fresh.
  null whenever you are unsure — that is the expected answer for most recipes."""

# Used by scripts/backfill_freezes_well.py for the recipes captured before
# `freezes_well` existed. Same rule as the extractor so a backfilled answer and
# a freshly-extracted one mean the same thing.
FREEZES_WELL_PROMPT = """Do this dish's leftovers survive being frozen and reheated?

RECIPE: {name}
INGREDIENTS: {ingredients}

""" + FREEZING_RULE + """

Answer with JSON only, no other text:
{{"freezes_well": true, "reason": "under 12 words"}}
{{"freezes_well": false, "reason": "under 12 words"}}
{{"freezes_well": null, "reason": "under 12 words"}}"""

SYSTEM_PROMPT = """You are a recipe extraction assistant. Given a YouTube video transcript
and description about cooking, extract a structured recipe.

Rules:
- Extract ONLY what is shown/said in the video
""" + NAMING_RULE + """
""" + FREEZING_RULE + """
- When inferring (timing, quantities, temperatures), mark with "(estimated)"
- If a field cannot be determined, use null
- Set needs_review: true if significant inference was required
- List confidence_notes explaining what was inferred vs explicit
- For ingredients: use standard unit abbreviations (tbsp, tsp, cup, oz, lb, g, ml)
- For informal amounts (a pinch, to taste), set amount to 1 and use the phrase as unit
- For unitless items (eggs, lemons), use "whole" as unit

Output valid JSON matching this schema:
{
  "recipe_name": "string (the dish name, NOT the video title — see the naming rule)",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
  "freezes_well": true|false|null,
  "dietary": ["array of tags"],
  "equipment": ["array of items"],
  "ingredients": [
    {"amount": "number or string", "unit": "string", "item": "string", "inferred": boolean}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
  "meal_occasion": ["up to 3 strings - when would someone make this? e.g. weeknight-dinner, grab-and-go-breakfast, meal-prep, weekend-project, packed-lunch, afternoon-snack, date-night, post-workout, crowd-pleaser, lazy-sunday"],
  "variations": ["array of strings"],
  "nutritional_info": "string or null",
  "needs_review": boolean,
  "confidence_notes": "string"
}"""

USER_PROMPT_TEMPLATE = """Extract a recipe from this cooking video.

VIDEO TITLE: {title}
CHANNEL: {channel}

DESCRIPTION:
{description}
{comment_section}
TRANSCRIPT:
{transcript}"""


def build_user_prompt(title, channel, description, transcript, comment=None):
    """Build the user prompt with video data.

    Args:
        comment: Optional first comment text to include as additional context.
    """
    comment_section = ""
    if comment:
        comment_section = f"\nFIRST COMMENT:\n{comment}\n"

    return USER_PROMPT_TEMPLATE.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        description=description or "No description",
        comment_section=comment_section,
        transcript=transcript or "No transcript"
    )


# Prompts for extracting recipes from video descriptions
DESCRIPTION_EXTRACTION_PROMPT = """You are extracting a recipe from a YouTube video description.
The description contains a written recipe - parse it accurately.

Rules:
- Extract EXACTLY what is written (no inference needed)
""" + NAMING_RULE + """
""" + FREEZING_RULE + """
- Parse quantities and ingredients precisely
- Number the instructions in order
- Set needs_review: false (this is explicit text)
- For ingredients: use standard unit abbreviations (tbsp, tsp, cup, oz, lb, g, ml)
- For informal amounts (a pinch, to taste), set amount to 1 and use the phrase as unit
- For unitless items (eggs, lemons), use "whole" as unit

Output valid JSON matching this schema:
{
  "recipe_name": "string (the dish name, NOT the video title — see the naming rule)",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
  "freezes_well": true|false|null,
  "dietary": ["array of tags"],
  "equipment": ["array of items"],
  "ingredients": [
    {"amount": "number or string", "unit": "string", "item": "string", "inferred": false}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
  "meal_occasion": ["up to 3 strings - when would someone make this? e.g. weeknight-dinner, grab-and-go-breakfast, meal-prep, weekend-project, packed-lunch, afternoon-snack, date-night, post-workout, crowd-pleaser, lazy-sunday"],
  "variations": ["array of strings"],
  "needs_review": false,
  "confidence_notes": "Extracted from video description text."
}"""

SHORT_TITLE_PROMPT = """Shorten this recipe name so it fits on a small card.

RECIPE NAME: {name}
INGREDIENTS: {ingredients}

Return the shortest name a cook would still recognise this dish by, at most
{max_len} characters.

Rules:
- Drop only noise: "Recipe", "- YouTube", channel names, emoji, marketing words
  ("Best", "Easy", "Viral", "Amazing"), ingredient counts ("5-Ingredient"),
  calorie claims ("19 Calorie"), and trailing prose after a dash or "With".
- Keep the remaining words IN THE ORDER THEY ALREADY APPEAR. You are deleting
  words, not rewriting the name.
- Never abbreviate. "Cauliflower" not "Cauli", "with" not "w/", "Chocolate" not
  "Choc". A truncated word is harder to read than a longer name.
- Never split a compound food name. "Cottage Cheese" is one ingredient — dropping
  "Cheese" leaves "Cottage", which is not a food.
- KEEP anything that distinguishes this from the plain version of the dish —
  "High-Protein", "Slow Cooker", "No-Bake", "(Crouton)", a trailing "A"/"B".
  Two recipes in this collection often differ by exactly one such word, and
  dropping it makes them the same dish.
- Do NOT rename the dish or introduce words that are not already in the name.
  The one exception: if the name is not in English, translate it
  ("Korean Potato Cheese Bread").
- If the name is already short and clean, return it unchanged.

Return ONLY a JSON object with exactly these keys:
{{"short_title": "<the shortened name>", "confidence": <0.0 to 1.0>, "dropped": "<what you removed>"}}"""

DESCRIPTION_USER_TEMPLATE = """Extract the recipe from this video description.

VIDEO TITLE: {title}
CHANNEL: {channel}

DESCRIPTION:
{description}"""


def build_description_prompt(title: str, channel: str, description: str) -> str:
    """Build prompt for description recipe extraction"""
    return DESCRIPTION_USER_TEMPLATE.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        description=description or "",
    )


# Prompts for extracting cooking tips from video transcripts
TIPS_EXTRACTION_PROMPT = """You are extracting cooking tips from a video transcript.
Given a recipe and the video transcript, find practical tips mentioned in the video
that are NOT already in the written recipe.

Focus on:
- Visual/sensory cues ("when you see it turning brown")
- Timing guidance ("this only takes 30 seconds")
- Technique details ("stir constantly")
- Warnings ("be careful not to burn")
- Substitutions mentioned

Exclude:
- Ingredients already listed
- Steps already in instructions
- Banter, jokes, personal stories
- Sponsorships, outros

Return a JSON object with a "tips" key containing an array of 3-5 short tip strings. If no useful tips found, return {"tips": []}.

Example output:
{"tips": ["Watch for the garlic to turn golden, not brown - it burns quickly",
 "Reserve pasta water before draining - you'll need about 1/4 cup",
 "Let the pan cool slightly before adding the pasta to avoid splattering"]}"""

TIPS_USER_TEMPLATE = """Extract cooking tips from this video that aren't in the recipe.

RECIPE:
{recipe_json}

TRANSCRIPT:
{transcript}"""


def build_tips_prompt(recipe: dict, transcript: str) -> str:
    """Build prompt for tips extraction"""
    import json
    return TIPS_USER_TEMPLATE.format(
        recipe_json=json.dumps(recipe, indent=2),
        transcript=transcript or "No transcript available",
    )
