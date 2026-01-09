"""RecipeMD format template for recipe export.

RecipeMD is a portable markdown recipe format that works with various
recipe management tools. This module exports recipes in RecipeMD format
alongside the main KitchenOS format.

Specification: https://recipemd.org/specification.html
"""

import re




def format_recipemd(recipe_data, video_url, video_title, channel):
    """Format recipe data as RecipeMD markdown.

    RecipeMD spec: https://recipemd.org/specification.html

    Args:
        recipe_data: Dict with recipe_name, description, ingredients, instructions, etc.
        video_url: Source YouTube URL
        video_title: Original video title
        channel: YouTube channel name

    Returns:
        str: RecipeMD formatted markdown
    """
    lines = []

    # Title (required)
    recipe_name = recipe_data.get('recipe_name', 'Untitled Recipe')
    lines.append(f"# {recipe_name}")
    lines.append("")

    # Description (optional)
    description = recipe_data.get('description', '')
    if description:
        lines.append(description)
        lines.append("")

    # Tags in italics (optional)
    tags = build_tags(recipe_data)
    if tags:
        lines.append(f"*{', '.join(tags)}*")

    # Yield in bold (optional)
    servings = recipe_data.get('servings')
    if servings:
        lines.append(f"**{servings} servings**")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Ingredients
    for ing in recipe_data.get('ingredients', []):
        lines.append(format_ingredient_recipemd(ing))

    lines.append("")
    lines.append("---")
    lines.append("")

    # Instructions
    for i, step in enumerate(recipe_data.get('instructions', []), 1):
        text = step.get('text', step) if isinstance(step, dict) else step
        lines.append(f"{i}. {text}")

    # Source attribution
    lines.append("")
    lines.append(f"*Source: [{video_title}]({video_url}) by {channel}*")

    return '\n'.join(lines)





def format_ingredient_recipemd(ing):
    """Format single ingredient for RecipeMD."""
    amount = ing.get('amount', '')
    unit = ing.get('unit', '')
    item = ing.get('item', '')
    if amount is not None:
        amount = str(amount).strip()
    else:
        amount = ''
    unit = (unit or '').strip()
    item = (item or '').strip()
    if amount and unit:
        return f"- *{amount} {unit}* {item}"
    elif amount:
        return f"- *{amount}* {item}"
    else:
        return f"- {item}"



def build_tags(recipe_data):
    """Build tag list from recipe metadata."""
    tags = []
    cuisine = recipe_data.get('cuisine')
    if cuisine and cuisine.lower() != 'none':
        tags.append(cuisine.lower())
    dish_type = recipe_data.get('dish_type')
    if dish_type and dish_type.lower() != 'none':
        tags.append(dish_type.lower())
    protein = recipe_data.get('protein')
    if protein and protein.lower() != 'none':
        tags.append(protein.lower())
    for dietary in recipe_data.get('dietary', []):
        if dietary and dietary.lower() != 'none':
            tags.append(dietary.lower())
    return tags


def generate_recipemd_filename(recipe_name):
    slug = re.sub(r'[^a-z0-9]+', '-', recipe_name.lower()).strip('-')
    return f"{slug}.recipe.md"
