"""Markdown template for recipe output"""

import os
from datetime import date
import re
from fractions import Fraction
from urllib.parse import quote

from lib import frontmatter
from lib.ingredient_parser import parse_ingredient

# Base URL baked into recipe action buttons. Override with KITCHENOS_API_BASE.
# Pin this to the stable Tailscale *hostname* (not a raw 100.x IP): a raw IP
# drifts between extractions and produces near-identical recipe files that
# differ only by button host, which Obsidian Sync then forks into "X 2.md".
API_BASE_URL = os.environ.get(
    "KITCHENOS_API_BASE", "http://chases-mac-mini.taila69703.ts.net:5001"
).rstrip("/")

# Schema definition for recipe frontmatter
# Used by migration to add missing fields
RECIPE_SCHEMA = {
    "title": str,
    "banner": str,
    "source_url": str,
    "source_channel": str,
    "date_added": str,
    "video_title": str,
    "prep_time": str,
    "cook_time": str,
    "total_time": str,
    "servings": int,
    "serving_size": str,
    "difficulty": str,
    "nutrition_calories": int,
    "nutrition_protein": int,
    "nutrition_carbs": int,
    "nutrition_fat": int,
    "nutrition_source": str,
    "cuisine": str,
    "protein": str,
    "dish_type": str,
    "meal_occasion": list,
    "dietary": list,
    "seasonal_ingredients": list,
    "peak_months": list,
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
> action {API_BASE_URL}/reprocess?file={encoded_filename}
> ```
> ```button
> name Refresh Template
> type link
> action {API_BASE_URL}/refresh?file={encoded_filename}
> ```
> ```button
> name Add to Meal Plan
> type link
> action {API_BASE_URL}/add-to-meal-plan?recipe={encoded_filename}
> ```
> ```button
> name View Meal Plan
> type link
> action {API_BASE_URL}/current/meal-plan
> ```
> ```button
> name Shopping List
> type link
> action {API_BASE_URL}/current/shopping-list
> ```

'''


def generate_nutrition_section(recipe_data: dict) -> str:
    """Generate nutrition section if data available.

    Args:
        recipe_data: Recipe data dict with nutrition fields

    Returns:
        Markdown section with nutrition table, or empty string if no data
    """
    calories = recipe_data.get("nutrition_calories")
    if calories is None:
        return ""

    nutrition_protein = recipe_data.get("nutrition_protein", 0)
    carbs = recipe_data.get("nutrition_carbs", 0)
    fat = recipe_data.get("nutrition_fat", 0)
    serving_size = recipe_data.get("serving_size", "1 serving")
    source = recipe_data.get("nutrition_source", "unknown")
    confidence = recipe_data.get("nutrition_confidence")
    conf_str = f" • Confidence: {confidence}" if confidence is not None else ""

    # The heading has to follow the data. The engine derives per-serving macros as
    # total/servings, and with no `servings` it divides by 1 — so these become
    # whole-batch numbers. Printing "(per serving)" over them is not a vague label
    # but a false one: it read a 1,339-calorie tray of pops as a single serving.
    servings = recipe_data.get("servings")
    per_serving = bool(servings) and str(servings).strip().lower() not in ("none", "null")
    heading = "## Nutrition (per serving)" if per_serving else "## Nutrition (whole recipe)"
    footer = (f"*Serving size: {serving_size} • Source: {source.title()}{conf_str}*"
              if per_serving else
              f"*Whole-recipe totals — no servings count, so these can't be divided "
              f"yet • Source: {source.title()}{conf_str}*")

    return f"""{heading}

| Calories | Protein | Carbs | Fat |
|----------|---------|-------|-----|
| {calories}      | {nutrition_protein}g     | {carbs}g   | {fat}g |

{footer}

"""


RECIPE_TEMPLATE = '''---
title: {title_yaml}
source_url: {source_url_yaml}
source_channel: {source_channel_yaml}
date_added: {date_added}
video_title: {video_title_yaml}
recipe_source: {recipe_source_yaml}

prep_time: {prep_time}
cook_time: {cook_time}
total_time: {total_time}
servings: {servings}
serving_size: {serving_size}
difficulty: {difficulty}
freezes_well: {freezes_well}

nutrition_calories: {nutrition_calories}
nutrition_protein: {nutrition_protein}
nutrition_carbs: {nutrition_carbs}
nutrition_fat: {nutrition_fat}
nutrition_source: {nutrition_source}
nutrition_confidence: {nutrition_confidence}

cuisine: {cuisine}
protein: {protein}
dish_type: {dish_type}
meal_occasion: {meal_occasion}
dietary: {dietary}
seasonal_ingredients: {seasonal_ingredients}
peak_months: {peak_months}

equipment: {equipment}

tags:
{tags}

needs_review: {needs_review}
confidence_notes: {confidence_notes_yaml}
banner: {banner}
cssclasses:
  - recipe
---

{tools_callout}# {title}

{image_embed}> {description}

> [!abstract]- Jump to Section
> - [[#Ingredients]]
> - [[#Instructions]]
> - [[#Equipment]]
> - [[#My Notes]]

## Ingredients

{ingredients}

{nutrition_section}## Instructions

{instructions}

## Equipment

{equipment_list}
{video_tips_section}{notes_section}
## My Notes

<!-- Your personal notes, ratings, and modifications go here -->

---
*Extracted from [{video_title_label}]({source_url}) on {date_added}*
'''


def _escape_link_label(text):
    """Escape square brackets so a title can't open a wikilink in `[label](url)`.

    Escaped rather than stripped: the brackets are part of how the channel
    titled the video, and dropping them silently rewrites their content.
    """
    return str(text).replace("[", r"\[").replace("]", r"\]")


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

    # Format meal_occasion as YAML list
    meal_occasion = recipe_data.get('meal_occasion', [])
    meal_occasion_yaml = f"[{', '.join(quote + o.lower().replace(' ', '-') + quote for o in meal_occasion)}]" if meal_occasion else "[]"

    # Format seasonal fields as YAML lists
    seasonal_ings = recipe_data.get('seasonal_ingredients', [])
    seasonal_yaml = f"[{', '.join(quote + s + quote for s in seasonal_ings)}]" if seasonal_ings else "[]"

    peak_months = recipe_data.get('peak_months', [])
    peak_months_yaml = f"[{', '.join(str(m) for m in peak_months)}]" if peak_months else "[]"

    # Format tags
    tags = []
    if recipe_data.get('cuisine') and isinstance(recipe_data['cuisine'], str):
        tags.append(f"  - {recipe_data['cuisine'].lower().replace(' ', '-')}")
    if recipe_data.get('protein') and isinstance(recipe_data['protein'], str):
        tags.append(f"  - {recipe_data['protein'].lower().replace(' ', '-')}")
    if recipe_data.get('dish_type') and isinstance(recipe_data['dish_type'], str):
        tags.append(f"  - {recipe_data['dish_type'].lower().replace(' ', '-')}")
    for occasion in recipe_data.get('meal_occasion', []):
        if occasion:
            tags.append(f"  - {occasion.lower().replace(' ', '-')}")
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

    # Generate nutrition section
    nutrition_section = generate_nutrition_section(recipe_data)

    # Get time values
    prep = recipe_data.get('prep_time')
    cook = recipe_data.get('cook_time')
    total = recipe_data.get('total_time')

    # Format nullable fields
    def quote_or_null(val):
        """A quoted YAML scalar, or null. Escaping is frontmatter.scalar's job:
        these values are LLM-extracted, so `1 x 9" slice` used to break the file."""
        return frontmatter.scalar(val) if val else "null"

    def num_or_null(val):
        return val if val is not None else "null"

    def bool_or_null(val):
        """`true` / `false` / `null`, and nothing else.

        The value is LLM-extracted, so it arrives as "probably", "yes, but not
        the sauce", or a whole sentence. On a tri-state field whose unknown
        state is load-bearing, a truthy string must not become `true` —
        "freezes: probably?" would be recorded as a confident yes.
        """
        return frontmatter.scalar(val) if isinstance(val, bool) else "null"

    # Image support
    image_filename = recipe_data.get('image_filename')
    banner = f'"[[{image_filename}]]"' if image_filename else "null"
    image_embed = f"![[{image_filename}]]\n\n" if image_filename else ""

    # Every value below is untrusted: the title and channel come from the
    # YouTube API, the rest from an LLM extraction. Frontmatter fields therefore
    # go through frontmatter.scalar (which supplies its own quotes), while the
    # body keeps the raw text — the two contexts need different escaping, so
    # `title` / `video_title` each appear twice with different treatment.
    title = recipe_data.get('recipe_name', 'Untitled Recipe')
    video_title = video_title or "Unknown Video"

    return RECIPE_TEMPLATE.format(
        title=title,
        title_yaml=frontmatter.scalar(title),
        source_url_yaml=frontmatter.scalar(video_url),
        source_channel_yaml=frontmatter.scalar(channel or "Unknown"),
        date_added=date_added or date.today().isoformat(),
        video_title_yaml=frontmatter.scalar(video_title),
        # Escaped because it is interpolated as a markdown link *label*. Korean
        # and Japanese cooking channels routinely bracket their titles
        # ("[감자치즈빵] …"), and an unescaped "[" turns the attribution into a
        # wikilink to the bracketed fragment instead of a link to the video.
        video_title_label=_escape_link_label(video_title),
        source_url=video_url,
        recipe_source_yaml=frontmatter.scalar(recipe_source),
        tools_callout=tools_callout,
        prep_time=quote_or_null(prep),
        cook_time=quote_or_null(cook),
        total_time=quote_or_null(total or prep or cook),
        servings=num_or_null(recipe_data.get('servings')),
        serving_size=quote_or_null(recipe_data.get('serving_size')),
        difficulty=quote_or_null(recipe_data.get('difficulty')),
        freezes_well=bool_or_null(recipe_data.get('freezes_well')),
        nutrition_calories=num_or_null(recipe_data.get('nutrition_calories')),
        nutrition_protein=num_or_null(recipe_data.get('nutrition_protein')),
        nutrition_carbs=num_or_null(recipe_data.get('nutrition_carbs')),
        nutrition_fat=num_or_null(recipe_data.get('nutrition_fat')),
        nutrition_source=quote_or_null(recipe_data.get('nutrition_source')),
        nutrition_confidence=num_or_null(recipe_data.get('nutrition_confidence')),
        cuisine=quote_or_null(recipe_data.get('cuisine')),
        protein=quote_or_null(recipe_data.get('protein')),
        dish_type=quote_or_null(recipe_data.get('dish_type')),
        meal_occasion=meal_occasion_yaml,
        dietary=dietary_yaml,
        seasonal_ingredients=seasonal_yaml,
        peak_months=peak_months_yaml,
        equipment=equipment_yaml,
        tags=tags_yaml,
        needs_review=str(recipe_data.get('needs_review', True)).lower(),
        confidence_notes_yaml=frontmatter.scalar(recipe_data.get('confidence_notes', '')),
        banner=banner,
        image_embed=image_embed,
        description=recipe_data.get('description', ''),
        ingredients='\n'.join(ingredients_lines),
        nutrition_section=nutrition_section,
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
