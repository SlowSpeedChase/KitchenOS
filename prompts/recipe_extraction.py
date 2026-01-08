"""Prompt templates for AI recipe extraction"""

SYSTEM_PROMPT = """You are a recipe extraction assistant. Given a YouTube video transcript
and description about cooking, extract a structured recipe.

Rules:
- Extract ONLY what is shown/said in the video
- When inferring (timing, quantities, temperatures), mark with "(estimated)"
- If a field cannot be determined, use null
- Set needs_review: true if significant inference was required
- List confidence_notes explaining what was inferred vs explicit

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
    {"quantity": "string", "item": "string", "inferred": boolean}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
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

TRANSCRIPT:
{transcript}"""


def build_user_prompt(title, channel, description, transcript):
    """Build the user prompt with video data"""
    return USER_PROMPT_TEMPLATE.format(
        title=title or "Unknown",
        channel=channel or "Unknown",
        description=description or "No description",
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
    {"quantity": "string", "item": "string", "inferred": false}
  ],
  "instructions": [
    {"step": number, "text": "string", "time": "string or null"}
  ],
  "storage": "string or null",
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
