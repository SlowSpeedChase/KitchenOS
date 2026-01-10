"""Markdown template for recipe output"""

from datetime import date
import re
from fractions import Fraction
from urllib.parse import quote

from lib.ingredient_parser import parse_ingredient

API_BASE_URL = "http://localhost:5001"

# Schema definition for recipe frontmatter
# Used by migration to add missing fields
RECIPE_SCHEMA = {
    "title": str,
    "source_url": str,
    "source_channel": str,
    "date_added": str,
    "video_title": str,
    "prep_time": str,
    "cook_time": str,
    "total_time": str,
    "servings": int,
    "difficulty": str,
    "cuisine": str,
    "protein": str,
    "dish_type": str,
    "dietary": list,
    "equipment": list,
    "needs_review": bool,
    "confidence_notes": str,
}

# Section renames for migration
SECTION_RENAMES = {
    # "Old Section Name": "New Section Name",
}


def convert_quantity_to_decimal(quantity_str):
    """Convert quantity string with fractions to decimal format.

    Examples:
        "1/2 cup" → "0.5 cup"
        "1 1/2 cups" → "1.5 cups"
        "2" → "2"
        "3/4" → "0.75"
        "1 /2 cup" → "0.5 cup" (handles space before slash)
    """
    if not quantity_str:
        return ""

    # Normalize spaces around slashes in fractions (e.g., "1 /2" → "1/2")
    normalized = re.sub(r'(\d)\s*/\s*(\d)', r'\1/\2', quantity_str.strip())

    # Try to match mixed number: "1 1/2 cups" -> whole=1, frac=1/2, rest=cups
    mixed_pattern = r'^(\d+)\s+(\d+/\d+)\s*(.*)$'
    mixed_match = re.match(mixed_pattern, normalized)

    if mixed_match:
        whole, frac, rest = mixed_match.groups()
        total = float(whole) + float(Fraction(frac))
    else:
        # Try to match simple fraction: "1/2 cup" -> frac=1/2, rest=cup
        frac_pattern = r'^(\d+/\d+)\s*(.*)$'
        frac_match = re.match(frac_pattern, normalized)

        if frac_match:
            frac, rest = frac_match.groups()
            total = float(Fraction(frac))
        else:
            # Try to match whole number: "2 cups" -> whole=2, rest=cups
            whole_pattern = r'^(\d+)\s*(.*)$'
            whole_match = re.match(whole_pattern, normalized)

            if whole_match:
                whole, rest = whole_match.groups()
                total = float(whole)
            else:
                # No numeric pattern found, return original
                return quantity_str

    # Format: remove trailing zeros, keep reasonable precision
    if total == int(total):
        decimal_str = str(int(total))
    else:
        decimal_str = f"{total:.2f}".rstrip('0').rstrip('.')

    rest = rest.strip() if rest else ""
    if not rest:
        return decimal_str
    # Don't add space before quote marks (inch/foot notation like 1" or 2')
    if rest.startswith('"') or rest.startswith("'"):
        return f"{decimal_str}{rest}"
    return f"{decimal_str} {rest}"


def generate_tools_callout(filename: str) -> str:
    """Generate the Tools callout block with reprocess buttons.

    Args:
        filename: The recipe filename (e.g., "Pasta Aglio E Olio.md")

    Returns:
        Markdown callout block with buttons
    """
    encoded_filename = quote(filename, safe='')
    return f'''> [!tools]- Tools
> ```button
> name Re-extract
> type link
> url {API_BASE_URL}/reprocess?file={encoded_filename}
> ```
> ```button
> name Refresh Template
> type link
> url {API_BASE_URL}/refresh?file={encoded_filename}
> ```

'''


RECIPE_TEMPLATE = '''---
title: "{title}"
source_url: "{source_url}"
source_channel: "{source_channel}"
date_added: {date_added}
video_title: "{video_title}"
recipe_source: "{recipe_source}"

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

{tools_callout}# {title}

> {description}

## Ingredients

{ingredients}

## Instructions

{instructions}

## Equipment

{equipment_list}
{video_tips_section}{notes_section}
## My Notes

<!-- Your personal notes, ratings, and modifications go here -->

---
*Extracted from [{video_title}]({source_url}) on {date_added}*
'''


def format_recipe_markdown(recipe_data, video_url, video_title, channel, date_added=None):
    """Format recipe data into markdown string"""

    # Format ingredients as 3-column table
    ingredients_lines = ["| Amount | Unit | Ingredient |", "|--------|------|------------|"]
    for ing in recipe_data.get('ingredients', []):
        # Handle new format (amount, unit, item)
        if 'amount' in ing and 'unit' in ing:
            amount = ing.get('amount', '1')
            unit = ing.get('unit', 'whole')
            item = ing.get('item', '')
        # Handle old format (quantity, item) - parse it
        elif 'quantity' in ing:
            quantity = ing.get('quantity', '')
            item_raw = ing.get('item', '')
            # Combine and re-parse
            combined = f"{quantity} {item_raw}".strip()
            parsed = parse_ingredient(combined)
            amount = parsed['amount']
            unit = parsed['unit']
            item = parsed['item']
        else:
            amount = '1'
            unit = 'whole'
            item = str(ing.get('item', ''))

        if ing.get('inferred'):
            item = f"{item} *(inferred)*"
        ingredients_lines.append(f"| {amount} | {unit} | {item} |")

    # Format instructions
    # Multi-paragraph steps need continuation paragraphs indented for proper markdown
    instruction_blocks = []
    for inst in recipe_data.get('instructions', []):
        time_note = f" ({inst['time']})" if inst.get('time') else ""
        text = inst.get('text', '').strip()

        # Split into paragraphs and format for markdown numbered list
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if paragraphs:
            # First paragraph gets the step number
            step_lines = [f"{inst.get('step', '')}. {paragraphs[0]}{time_note}"]
            # Continuation paragraphs get indented (3 spaces for alignment)
            for para in paragraphs[1:]:
                step_lines.append(f"   {para}")
            # Join paragraphs within a step with single newline
            instruction_blocks.append('\n\n'.join(step_lines))
        else:
            instruction_blocks.append(f"{inst.get('step', '')}. {text}{time_note}")

    # Format equipment list
    equipment_list = '\n'.join(f"- {e}" for e in recipe_data.get('equipment', []))

    # Format dietary as YAML list
    dietary = recipe_data.get('dietary', [])
    dietary_yaml = f"[{', '.join(dietary)}]" if dietary else "[]"

    # Format equipment as YAML list
    equipment = recipe_data.get('equipment', [])
    quote = '"'
    equipment_yaml = f"[{', '.join(quote + e + quote for e in equipment)}]" if equipment else "[]"

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

    # Format video tips section
    video_tips = recipe_data.get('video_tips', [])
    if video_tips:
        tips_lines = ["## Tips from the Video", ""]
        tips_lines.extend(f"- {tip}" for tip in video_tips)
        video_tips_section = "\n".join(tips_lines) + "\n\n"
    else:
        video_tips_section = ""

    # Get recipe source
    recipe_source = recipe_data.get('source', 'ai_extraction')

    # Generate tools callout
    filename = generate_filename(recipe_data.get('recipe_name', 'Untitled Recipe'))
    tools_callout = generate_tools_callout(filename)

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
        date_added=date_added or date.today().isoformat(),
        video_title=video_title or "Unknown Video",
        recipe_source=recipe_source,
        tools_callout=tools_callout,
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
        # Join instructions with extra blank line between steps for better readability
        instructions='\n\n\n'.join(instruction_blocks),
        equipment_list=equipment_list,
        video_tips_section=video_tips_section,
        notes_section=notes_section
    )


def generate_filename(recipe_name):
    """Generate filename from recipe name using title case with spaces."""
    # Remove characters that are problematic in filenames
    clean = re.sub(r'[<>:"/\\|?*]', '', recipe_name)
    # Normalize whitespace
    clean = ' '.join(clean.split())
    # Title case
    title = clean.title()
    return f"{title}.md"
