"""Markdown template for recipe output"""

from datetime import date
import re

RECIPE_TEMPLATE = '''---
title: "{title}"
source_url: "{source_url}"
source_channel: "{source_channel}"
date_added: {date_added}
video_title: "{video_title}"

prep_time: {prep_time}
cook_time: {cook_time}
total_time: {total_time}
servings: {servings}
difficulty: {difficulty}

cuisine: {cuisine}
protein: {protein}
dish_type: {dish_type}
dietary: {dietary}

equipment: {equipment}

tags:
{tags}

needs_review: {needs_review}
confidence_notes: "{confidence_notes}"
---

# {title}

> {description}

## Ingredients

{ingredients}

## Instructions

{instructions}

## Equipment

{equipment_list}
{notes_section}
---
*Extracted from [{video_title}]({source_url}) on {date_added}*
'''


def format_recipe_markdown(recipe_data, video_url, video_title, channel):
    """Format recipe data into markdown string"""

    # Format ingredients
    ingredients_lines = []
    for ing in recipe_data.get('ingredients', []):
        inferred = " *(inferred)*" if ing.get('inferred') else ""
        ingredients_lines.append(f"- {ing.get('quantity', '')} {ing.get('item', '')}{inferred}")

    # Format instructions
    instructions_lines = []
    for inst in recipe_data.get('instructions', []):
        time_note = f" ({inst['time']})" if inst.get('time') else ""
        instructions_lines.append(f"{inst.get('step', '')}. {inst.get('text', '')}{time_note}")

    # Format equipment list
    equipment_list = '\n'.join(f"- {e}" for e in recipe_data.get('equipment', []))

    # Format dietary as YAML list
    dietary = recipe_data.get('dietary', [])
    dietary_yaml = f"[{', '.join(dietary)}]" if dietary else "[]"

    # Format equipment as YAML list
    equipment = recipe_data.get('equipment', [])
    equipment_yaml = f"[{', '.join(f'\"' + e + '\"' for e in equipment)}]" if equipment else "[]"

    # Format tags
    tags = []
    if recipe_data.get('cuisine'):
        tags.append(f"  - {recipe_data['cuisine'].lower().replace(' ', '-')}")
    if recipe_data.get('protein'):
        tags.append(f"  - {recipe_data['protein'].lower().replace(' ', '-')}")
    if recipe_data.get('dish_type'):
        tags.append(f"  - {recipe_data['dish_type'].lower().replace(' ', '-')}")
    tags_yaml = '\n'.join(tags) if tags else "  - recipe"

    # Build notes section
    notes_parts = []
    if recipe_data.get('storage'):
        notes_parts.append(f"### Storage\n{recipe_data['storage']}")
    if recipe_data.get('variations'):
        variations = '\n'.join(f"- {v}" for v in recipe_data['variations'])
        notes_parts.append(f"### Variations\n{variations}")
    if recipe_data.get('nutritional_info'):
        notes_parts.append(f"### Nutritional Info\n{recipe_data['nutritional_info']}")

    notes_section = "\n\n## Notes\n\n" + "\n\n".join(notes_parts) + "\n" if notes_parts else ""

    # Get time values
    prep = recipe_data.get('prep_time')
    cook = recipe_data.get('cook_time')
    total = recipe_data.get('total_time')

    # Format nullable fields
    def quote_or_null(val):
        return f'"{val}"' if val else "null"

    def num_or_null(val):
        return val if val is not None else "null"

    return RECIPE_TEMPLATE.format(
        title=recipe_data.get('recipe_name', 'Untitled Recipe'),
        source_url=video_url,
        source_channel=channel or "Unknown",
        date_added=date.today().isoformat(),
        video_title=video_title or "Unknown Video",
        prep_time=quote_or_null(prep),
        cook_time=quote_or_null(cook),
        total_time=quote_or_null(total or prep or cook),
        servings=num_or_null(recipe_data.get('servings')),
        difficulty=quote_or_null(recipe_data.get('difficulty')),
        cuisine=quote_or_null(recipe_data.get('cuisine')),
        protein=quote_or_null(recipe_data.get('protein')),
        dish_type=quote_or_null(recipe_data.get('dish_type')),
        dietary=dietary_yaml,
        equipment=equipment_yaml,
        tags=tags_yaml,
        needs_review=str(recipe_data.get('needs_review', True)).lower(),
        confidence_notes=recipe_data.get('confidence_notes', ''),
        description=recipe_data.get('description', ''),
        ingredients='\n'.join(ingredients_lines),
        instructions='\n'.join(instructions_lines),
        equipment_list=equipment_list,
        notes_section=notes_section
    )


def generate_filename(recipe_name):
    """Generate filename from recipe name"""
    slug = re.sub(r'[^a-z0-9]+', '-', recipe_name.lower()).strip('-')
    return f"{date.today().isoformat()}-{slug}.md"
