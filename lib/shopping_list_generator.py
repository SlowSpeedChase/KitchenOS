"""Shopping list generation from meal plans.

Core logic extracted from shopping_list.py for API use.
"""

import re
from pathlib import Path

from lib.recipe_parser import parse_recipe_file, parse_ingredient_table
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"
RECIPES_PATH = OBSIDIAN_VAULT / "Recipes"
SHOPPING_LISTS_PATH = OBSIDIAN_VAULT / "Shopping Lists"


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


def extract_recipe_links(meal_plan_path: Path) -> list[str]:
    """Extract [[recipe]] links from meal plan."""
    content = meal_plan_path.read_text(encoding='utf-8')
    return re.findall(r'\[\[([^\]]+)\]\]', content)


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


def generate_shopping_list(week: str) -> dict:
    """Generate shopping list from meal plan.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Dict with keys:
            - success: bool
            - items: list of formatted ingredient strings
            - recipes: list of recipe names found
            - warnings: list of warning messages
            - error: error message (if success=False)
    """
    try:
        meal_plan_path = parse_week_string(week)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    recipe_names = extract_recipe_links(meal_plan_path)
    if not recipe_names:
        return {"success": False, "error": "No recipes found in meal plan"}

    all_ingredients = []
    loaded_recipes = []
    warnings = []

    for name in recipe_names:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(ingredients)
            loaded_recipes.append(name)

    if not all_ingredients:
        return {
            "success": False,
            "error": "No ingredients found in any recipes",
            "warnings": warnings
        }

    aggregated = aggregate_ingredients(all_ingredients)
    formatted = [format_ingredient(ing) for ing in aggregated]

    return {
        "success": True,
        "items": sorted(formatted),
        "recipes": loaded_recipes,
        "warnings": warnings
    }


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
