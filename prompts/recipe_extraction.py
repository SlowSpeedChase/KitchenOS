"""Prompt templates for AI recipe extraction"""

SYSTEM_PROMPT = """You are a recipe extraction assistant. Given a YouTube video transcript
and description about cooking, extract a structured recipe.

Rules:
- Extract ONLY what is shown/said in the video
- When inferring (timing, quantities, temperatures), mark with "(estimated)"
- If a field cannot be determined, use null
- Set needs_review: true if significant inference was required
- List confidence_notes explaining what was inferred vs explicit
- For ingredients: use standard unit abbreviations (tbsp, tsp, cup, oz, lb, g, ml)
- For informal amounts (a pinch, to taste), set amount to 1 and use the phrase as unit
- For unitless items (eggs, lemons), use "whole" as unit

Output valid JSON matching this schema:
{
  "recipe_name": "string",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
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
- Parse quantities and ingredients precisely
- Number the instructions in order
- Set needs_review: false (this is explicit text)
- For ingredients: use standard unit abbreviations (tbsp, tsp, cup, oz, lb, g, ml)
- For informal amounts (a pinch, to taste), set amount to 1 and use the phrase as unit
- For unitless items (eggs, lemons), use "whole" as unit

Output valid JSON matching this schema:
{
  "recipe_name": "string",
  "description": "string (1-2 sentences)",
  "prep_time": "string or null",
  "cook_time": "string or null",
  "servings": "number or null",
  "difficulty": "easy|medium|hard or null",
  "cuisine": "string or null",
  "protein": "string or null",
  "dish_type": "string or null",
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

Return a JSON array of 3-5 short tip strings. If no useful tips found, return [].

Example output:
["Watch for the garlic to turn golden, not brown - it burns quickly",
 "Reserve pasta water before draining - you'll need about 1/4 cup",
 "Let the pan cool slightly before adding the pasta to avoid splattering"]"""

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
