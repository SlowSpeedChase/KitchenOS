"""Shopping list generation from meal plans.

Core logic extracted from shopping_list.py for API use.
"""

import re
from pathlib import Path
from typing import Optional

from lib.recipe_parser import parse_recipe_file, parse_ingredient_table
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient, parse_amount_to_float, format_amount
from lib import meal_loader, paths

# Configuration
OBSIDIAN_VAULT = paths.vault_root()
MEAL_PLANS_PATH = paths.meal_plans_dir()
RECIPES_PATH = paths.recipes_dir()
SHOPPING_LISTS_PATH = paths.shopping_lists_dir()


def parse_week_string(week_str: str) -> Path:
    """Parse a week string like '2026-W04' into a meal plan path.

    Raises:
        ValueError: If format is invalid or file doesn't exist.
    """
    match = re.match(r'^(\d{4})-W(\d{2})$', week_str)
    if not match:
        raise ValueError(f"Invalid week format: {week_str}. Expected: YYYY-WNN")

    filepath = MEAL_PLANS_PATH / f"{week_str}.md"
    if not filepath.exists():
        raise ValueError(f"Meal plan not found: {week_str}")

    return filepath


def extract_recipe_links(meal_plan_path: Path) -> list[tuple[str, int]]:
    """Extract recipe references from a meal plan, expanding any meals.

    Recognizes both `[[Recipe Name]]` and `[[Meal: Bundle Name]]` (the latter
    is resolved to its sub-recipes via lib.meal_loader). Outer `xN`
    multipliers propagate through to each sub-recipe and stack with the
    sub-recipe's own per-bundle servings override.

    Returns:
        List of (recipe_name, servings) tuples. Unknown meals are emitted
        as-is so the caller can surface a "Recipe not found" warning.
    """
    content = meal_plan_path.read_text(encoding='utf-8')
    matches = re.findall(r'\[\[(Meal:\s*)?([^\]]+)\]\]\s*(?:x(\d+))?', content)
    out: list[tuple[str, int]] = []
    for prefix, name, mult in matches:
        servings = int(mult) if mult else 1
        name = name.strip()
        if prefix:
            meal = meal_loader.load_meal(name)
            if meal and meal.sub_recipes:
                for sub in meal.sub_recipes:
                    out.append((sub.recipe, servings * max(1, int(sub.servings or 1))))
                continue
        out.append((name, servings))
    return out


def slugify(text: str) -> str:
    """Convert text to slug format."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def find_recipe_file(recipe_name: str) -> Path | None:
    """Find recipe file by name."""
    exact = RECIPES_PATH / f"{recipe_name}.md"
    if exact.exists():
        return exact

    slug = slugify(recipe_name)
    for file in RECIPES_PATH.glob("*.md"):
        if slugify(file.stem) == slug:
            return file
    return None


def extract_ingredient_table(body: str) -> str:
    """Extract ingredient table from recipe body."""
    pattern = r'##\s+Ingredients\s*\n(.*?)(?=\n##|\Z)'
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def multiply_ingredients(ingredients: list[dict], multiplier: int) -> list[dict]:
    """Scale ingredient amounts by a multiplier.

    Args:
        ingredients: List of ingredient dicts with 'amount', 'unit', 'item' keys
        multiplier: Number to multiply amounts by

    Returns:
        New list of ingredient dicts with scaled amounts
    """
    if multiplier == 1:
        return ingredients

    scaled = []
    for ing in ingredients:
        new_ing = ing.copy()
        amount = parse_amount_to_float(ing.get('amount'))
        if amount is not None:
            new_ing['amount'] = format_amount(amount * multiplier)
        scaled.append(new_ing)
    return scaled


def load_recipe_ingredients(recipe_name: str) -> tuple[list[dict], str | None]:
    """Load ingredients from a recipe file.

    Returns:
        Tuple of (ingredients list, warning message or None)
    """
    recipe_file = find_recipe_file(recipe_name)
    if not recipe_file:
        return [], f"Recipe not found: {recipe_name}"

    try:
        content = recipe_file.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        table_text = extract_ingredient_table(parsed['body'])
        if not table_text:
            return [], f"No ingredients table in: {recipe_name}"

        ingredients = parse_ingredient_table(table_text)
        return ingredients, None
    except Exception as e:
        return [], f"Could not parse {recipe_name}: {e}"


def compute_lines(aggregated: list[dict], pantry: Optional[list[dict]] = None) -> list[dict]:
    """Build per-line shopping records, optionally split against pantry inventory.

    Each record has the shape:
        {
            "item": str,                            # normalized item name
            "needed": {amount, unit},               # what the recipes call for
            "from_pantry": {amount, unit} | None,   # what to take from pantry
            "to_buy": {amount, unit} | None,        # what still needs purchasing
            "display": str,                         # full formatted ingredient
            "warning": str | None,                  # cross-family mismatch, etc.
        }

    When `pantry` is None, every line has `from_pantry=None` and
    `to_buy=needed`. When `pantry` is provided, lib.pantry.split_against_pantry()
    is consulted to subtract.
    """
    splitter = None
    if pantry is not None:
        from lib import pantry as pantry_module  # local import to avoid cycle
        splitter = pantry_module.split_against_pantry

    lines: list[dict] = []
    for ing in aggregated:
        amount = ing.get("amount", "")
        unit = ing.get("unit", "")
        item = ing.get("item", "")
        needed = {"amount": amount, "unit": unit}
        from_pantry: Optional[dict] = None
        to_buy: Optional[dict] = needed
        warning: Optional[str] = None

        if splitter is not None:
            split = splitter(item, amount, unit, pantry)
            from_pantry = split.get("from_pantry")
            to_buy = split.get("to_buy")
            warning = split.get("warning")

        lines.append({
            "item": item,
            "needed": needed,
            "from_pantry": from_pantry,
            "to_buy": to_buy,
            "display": format_ingredient(ing),
            "warning": warning,
        })
    return lines


def generate_shopping_list_from_path(meal_plan_path: Path, pantry: Optional[list[dict]] = None) -> dict:
    """Same contract as `generate_shopping_list` but operates on a path.

    Used by the CLI which supports `--plan custom.md` in addition to weeks.
    """
    if not meal_plan_path.exists():
        return {"success": False, "error": f"Meal plan not found: {meal_plan_path}"}

    recipe_links = extract_recipe_links(meal_plan_path)
    if not recipe_links:
        return {"success": False, "error": "No recipes found in meal plan"}

    all_ingredients = []
    loaded_recipes = []
    warnings = []

    for name, servings in recipe_links:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(multiply_ingredients(ingredients, servings))
            loaded_recipes.append(name)

    if not all_ingredients:
        return {
            "success": False,
            "error": "No ingredients found in any recipes",
            "warnings": warnings
        }

    aggregated = aggregate_ingredients(all_ingredients)
    lines = compute_lines(aggregated, pantry=pantry)

    if pantry is None:
        formatted = [line["display"] for line in lines]
    else:
        formatted = []
        for line in lines:
            tb = line.get("to_buy")
            if tb is None:
                continue
            buy_ing = {"amount": tb.get("amount", ""), "unit": tb.get("unit", ""), "item": line["item"]}
            formatted.append(format_ingredient(buy_ing))

    return {
        "success": True,
        "items": sorted(formatted),
        "lines": lines,
        "recipes": loaded_recipes,
        "warnings": warnings
    }


def generate_shopping_list(week: str, pantry: Optional[list[dict]] = None) -> dict:
    """Generate shopping list from a week's meal plan.

    Args:
        week: Week identifier like '2026-W04'
        pantry: Optional pantry inventory (list of {item, amount, unit} dicts).
            When supplied, each returned line is split into `from_pantry` and
            `to_buy` portions and the top-level `items` reflects only what
            still needs purchasing.

    Returns:
        Dict with keys: success, items, lines, recipes, warnings, error.
    """
    try:
        meal_plan_path = parse_week_string(week)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return generate_shopping_list_from_path(meal_plan_path, pantry=pantry)


def parse_shopping_list_file(week: str) -> dict:
    """Parse shopping list file and extract unchecked items.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Dict with keys:
            - success: bool
            - items: list of unchecked item strings
            - skipped: count of checked items
            - error: error message (if success=False)
    """
    filepath = SHOPPING_LISTS_PATH / f"{week}.md"

    if not filepath.exists():
        return {"success": False, "error": f"Shopping list not found: {week}. Generate it first."}

    content = filepath.read_text(encoding='utf-8')

    unchecked = []
    checked_count = 0

    for line in content.split('\n'):
        # Match unchecked: - [ ] item
        if re.match(r'^- \[ \] ', line):
            item = line[6:].strip()  # Remove "- [ ] " prefix
            if item:
                unchecked.append(item)
        # Match checked: - [x] item
        elif re.match(r'^- \[x\] ', line, re.IGNORECASE):
            checked_count += 1

    return {
        "success": True,
        "items": unchecked,
        "skipped": checked_count
    }


def extract_manual_items(existing_items: list[str], generated_items: list[str]) -> list[str]:
    """Find items that were manually added (not from generation).

    Args:
        existing_items: Items currently in the shopping list
        generated_items: Items freshly generated from meal plan

    Returns:
        List of items that exist but weren't generated (manual additions)
    """
    generated_set = set(generated_items)
    return [item for item in existing_items if item not in generated_set]
