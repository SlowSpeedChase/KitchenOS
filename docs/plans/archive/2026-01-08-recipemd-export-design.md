# RecipeMD Export Design

Date: 2026-01-08
Status: Approved
Priority: Medium

## Problem

KitchenOS uses a custom format (YAML frontmatter + markdown) optimized for Obsidian Dataview. This format isn't portable to other recipe tools that expect standard formats like RecipeMD.

## Solution

**Dual output**: Save both formats on every extraction.

- `recipe-name.md` - Current KitchenOS format (Dataview, tips, full metadata)
- `recipe-name.recipe.md` - RecipeMD format (portable, interoperable)

## RecipeMD Format

Specification: https://recipemd.org/specification.html

```markdown
# Recipe Title

Optional description paragraph.

*tag1, tag2, tag3*
**4 servings**

---

- *1 cup* flour
- *2* eggs
- *1/2 tsp* salt
- butter

## For the Sauce

- *200 ml* cream
- *1 clove* garlic, minced

---

1. Mix dry ingredients
2. Add wet ingredients
3. Cook until done

*Source: [Video Title](url) by Channel*
```

## Design

### 1. New Template File

Create `templates/recipemd_template.py`:

```python
"""RecipeMD format template for recipe export."""


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
    """Format single ingredient for RecipeMD.

    RecipeMD format: amount in italics, then ingredient name.

    Examples:
        {'amount': '1', 'unit': 'cup', 'item': 'flour'} -> '- *1 cup* flour'
        {'amount': '2', 'unit': '', 'item': 'eggs'} -> '- *2* eggs'
        {'amount': '', 'unit': '', 'item': 'butter'} -> '- butter'

    Args:
        ing: Dict with amount, unit, item keys

    Returns:
        str: Formatted ingredient line
    """
    amount = ing.get('amount', '')
    unit = ing.get('unit', '')
    item = ing.get('item', '')

    # Convert amount to string if numeric
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
    """Build tag list from recipe metadata.

    Combines cuisine, dish_type, protein, and dietary into a flat tag list.

    Args:
        recipe_data: Dict with recipe metadata

    Returns:
        list: Tag strings, lowercased
    """
    tags = []

    if recipe_data.get('cuisine'):
        tags.append(recipe_data['cuisine'].lower())

    if recipe_data.get('dish_type'):
        tags.append(recipe_data['dish_type'].lower())

    if recipe_data.get('protein'):
        tags.append(recipe_data['protein'].lower())

    # Dietary tags (already a list)
    for dietary in recipe_data.get('dietary', []):
        if dietary:
            tags.append(dietary.lower())

    return tags
```

### 2. Update extract_recipe.py

Modify `save_recipe_to_obsidian()`:

```python
from templates.recipemd_template import format_recipemd

def save_recipe_to_obsidian(recipe_data, video_url, video_title, channel, video_id):
    # ... existing logic for main file ...

    # Write main file
    filepath.write_text(markdown, encoding='utf-8')

    # Generate and save RecipeMD version
    recipemd_content = format_recipemd(recipe_data, video_url, video_title, channel)
    recipemd_path = filepath.with_suffix('.recipe.md')
    recipemd_path.write_text(recipemd_content, encoding='utf-8')

    return filepath  # Return main file path
```

### 3. Update templates/__init__.py

```python
from .recipe_template import format_recipe_markdown, generate_filename
from .recipemd_template import format_recipemd
```

## Edge Cases

| Case | Handling |
|------|----------|
| Missing amount/unit | Just output item name: `- butter` |
| Fractional amounts (`1/2`, `1 1/2`) | Pass through as-is (RecipeMD supports) |
| Informal amounts ("a pinch") | Treat as amount: `- *a pinch* salt` |
| No servings | Omit yield line entirely |
| No description | Skip straight to tags |
| `inferred: true` ingredients | Include without marking |
| Video tips | **Omit** - RecipeMD is portable format, tips stay in main file |
| Empty tags | Omit tags line |

## File Structure

After extraction:
```
Recipes/
  pasta-aglio-e-olio.md          # KitchenOS format (Dataview, tips, metadata)
  pasta-aglio-e-olio.recipe.md   # RecipeMD format (portable)
```

## Files to Create/Modify

| File | Action |
|------|--------|
| `templates/recipemd_template.py` | **Create** |
| `templates/__init__.py` | Update exports |
| `extract_recipe.py` | Add RecipeMD save call |

## What's NOT Included in RecipeMD

These fields exist in main file but are omitted from RecipeMD:

- `video_tips` - KitchenOS-specific
- `confidence_notes` - KitchenOS-specific
- `needs_review` - KitchenOS-specific
- `source` / `source_url` - Replaced with footer attribution
- `equipment` - No RecipeMD equivalent
- `storage` - No RecipeMD equivalent
- `variations` - No RecipeMD equivalent
- `prep_time` / `cook_time` - RecipeMD doesn't have standard fields

## Test Cases

**Input recipe_data:**
```json
{
  "recipe_name": "Pasta Aglio e Olio",
  "description": "A simple Italian pasta dish.",
  "cuisine": "Italian",
  "dish_type": "Main",
  "protein": "None",
  "dietary": ["vegetarian"],
  "servings": 4,
  "ingredients": [
    {"amount": "1", "unit": "lb", "item": "spaghetti"},
    {"amount": "6", "unit": "cloves", "item": "garlic, sliced"},
    {"amount": "1/2", "unit": "cup", "item": "olive oil"},
    {"amount": "", "unit": "", "item": "red pepper flakes"}
  ],
  "instructions": [
    {"step": 1, "text": "Cook pasta according to package directions."},
    {"step": 2, "text": "Sauté garlic in olive oil until golden."},
    {"step": 3, "text": "Toss pasta with garlic oil and pepper flakes."}
  ]
}
```

**Expected RecipeMD output:**
```markdown
# Pasta Aglio e Olio

A simple Italian pasta dish.

*italian, main, vegetarian*
**4 servings**

---

- *1 lb* spaghetti
- *6 cloves* garlic, sliced
- *1/2 cup* olive oil
- red pepper flakes

---

1. Cook pasta according to package directions.
2. Sauté garlic in olive oil until golden.
3. Toss pasta with garlic oil and pepper flakes.

*Source: [Video Title](https://youtube.com/watch?v=xxx) by Channel Name*
```

## Future Considerations

- Could add `--no-recipemd` flag to skip dual output
- Could add standalone export script for existing recipes
- CookLang export could follow same pattern
