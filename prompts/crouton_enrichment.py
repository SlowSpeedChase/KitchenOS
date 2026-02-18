"""Prompt for enriching Crouton imports with AI-inferred metadata.

Used by import_crouton.py to classify recipes that Crouton exports
without metadata like cuisine, difficulty, or dish type.
"""


CROUTON_ENRICHMENT_PROMPT = """You are classifying a recipe that was imported from a recipe app.
The recipe already has ingredients and instructions. You need to infer the metadata.

Rules:
- Base your answers ONLY on the recipe name, ingredients, and instructions provided
- If a field cannot be determined, use null
- Be conservative — only classify what is clearly evident
- For meal_occasion, pick 1-3 that best fit from: weeknight-dinner, grab-and-go-breakfast, meal-prep, weekend-project, packed-lunch, afternoon-snack, date-night, post-workout, crowd-pleaser, lazy-sunday

Output valid JSON matching this schema:
{
  "description": "string (1-2 sentence summary of the dish)",
  "cuisine": "string or null (e.g., Italian, Mexican, Indian, American)",
  "protein": "string or null (main protein: chicken, beef, tofu, etc.)",
  "difficulty": "easy|medium|hard or null",
  "dish_type": "string or null (e.g., Main, Side, Dessert, Snack, Breakfast, Soup, Salad, Drink)",
  "meal_occasion": ["array of 1-3 strings"],
  "dietary": ["array of tags like vegetarian, vegan, gluten-free, dairy-free — empty if none"],
  "equipment": ["array of notable equipment like oven, blender, slow cooker — empty if basic"]
}"""


def build_enrichment_prompt(recipe_name: str, ingredients: list, instructions: list) -> str:
    """Build user prompt for Ollama enrichment."""
    ing_lines = []
    for ing in ingredients:
        amount = ing.get("amount", "")
        unit = ing.get("unit", "")
        item = ing.get("item", "")
        if amount and unit:
            ing_lines.append(f"- {amount} {unit} {item}")
        elif amount:
            ing_lines.append(f"- {amount} {item}")
        else:
            ing_lines.append(f"- {item}")

    step_lines = [
        f"{s.get('step', i+1)}. {s.get('text', '')}"
        for i, s in enumerate(instructions)
    ]

    return f"""Classify this recipe:

RECIPE: {recipe_name}

INGREDIENTS:
{chr(10).join(ing_lines)}

INSTRUCTIONS:
{chr(10).join(step_lines)}"""
