#!/usr/bin/env python3
"""KitchenOS MCP Server — Claude Desktop integration."""

from mcp.server.fastmcp import FastMCP

from lib.mcp_tools import (
    check_api_health,
    extract_recipe as _extract_recipe,
    save_recipe as _save_recipe,
    search_recipes as _search_recipes,
    get_recipe as _get_recipe,
    get_meal_plan as _get_meal_plan,
    update_meal_plan as _update_meal_plan,
    generate_shopping_list as _generate_shopping_list,
    send_to_reminders as _send_to_reminders,
    create_things_task as _create_things_task,
)

mcp = FastMCP("KitchenOS")

API_DOWN_MSG = (
    "ERROR: KitchenOS API server is not running at localhost:5001. "
    "Nothing was saved. Start it with: launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist"
)


def _require_api() -> str | None:
    """Return error message if API is down, None if healthy."""
    if not check_api_health():
        return API_DOWN_MSG
    return None


@mcp.tool()
def extract_recipe(url: str) -> str:
    """Extract a recipe from a YouTube URL and save it to the Obsidian vault.

    Args:
        url: YouTube video URL (e.g., https://www.youtube.com/watch?v=abc123)
    """
    if err := _require_api():
        return err
    result = _extract_recipe(url)
    if result.get("status") == "success":
        return f"Recipe saved: {result['recipe']}"
    return f"Error: {result.get('message', 'Unknown error')}"


@mcp.tool()
def save_recipe(
    recipe_name: str,
    ingredients: list[dict],
    instructions: list[dict],
    description: str = "",
    servings: int = 4,
    cuisine: str = None,
    protein: str = None,
    dish_type: str = None,
    difficulty: str = None,
    prep_time: str = None,
    cook_time: str = None,
) -> str:
    """Save a recipe to KitchenOS from structured data.

    Use this when a recipe comes up in conversation (not from YouTube).

    Args:
        recipe_name: Name of the recipe
        ingredients: List of ingredients, each with keys: amount, unit, item
        instructions: List of steps, each with keys: step (number), text, time (optional)
        description: Brief description of the dish
        servings: Number of servings
        cuisine: Cuisine type (e.g., Italian, Mexican)
        protein: Main protein (e.g., chicken, beef, tofu)
        dish_type: Type of dish (e.g., main, side, dessert)
        difficulty: easy, medium, or hard
        prep_time: Prep time string (e.g., "15 min")
        cook_time: Cook time string (e.g., "30 min")
    """
    if err := _require_api():
        return err
    data = {
        "recipe_name": recipe_name,
        "description": description,
        "servings": servings,
        "cuisine": cuisine,
        "protein": protein,
        "dish_type": dish_type,
        "difficulty": difficulty,
        "prep_time": prep_time,
        "cook_time": cook_time,
        "ingredients": ingredients,
        "instructions": instructions,
    }
    result = _save_recipe(data)
    if result.get("status") == "success":
        return f"Recipe saved: {result['recipe_name']}"
    return f"Error: {result.get('error', 'Unknown error')}"


@mcp.tool()
def search_recipes(
    query: str = None,
    cuisine: str = None,
    protein: str = None,
) -> str:
    """Search the KitchenOS recipe library.

    Args:
        query: Search term to match against recipe names
        cuisine: Filter by cuisine (e.g., Italian, Indian)
        protein: Filter by protein (e.g., chicken, beef)
    """
    if err := _require_api():
        return err
    import json
    results = _search_recipes(query=query, cuisine=cuisine, protein=protein)
    if not results:
        return "No recipes found matching your criteria."
    names = [r["name"] for r in results]
    return f"Found {len(names)} recipes:\n" + "\n".join(f"- {n}" for n in names)


@mcp.tool()
def get_recipe(name: str) -> str:
    """Get full details of a specific recipe.

    Args:
        name: Recipe name (e.g., "Butter Chicken")
    """
    if err := _require_api():
        return err
    import json
    result = _get_recipe(name)
    if "error" in result:
        return f"Error: {result['error']}"
    return json.dumps(result, indent=2)


@mcp.tool()
def get_meal_plan(week: str) -> str:
    """View the meal plan for a given week.

    Args:
        week: Week identifier (e.g., "2026-W11")
    """
    if err := _require_api():
        return err
    import json
    result = _get_meal_plan(week)
    if "error" in result:
        return f"Error: {result['error']}"
    return json.dumps(result, indent=2)


@mcp.tool()
def update_meal_plan(week: str, days: list[dict]) -> str:
    """Update the meal plan for a given week.

    Each day should have: day, date, breakfast, lunch, dinner.
    Each meal is either null or {name: "Recipe Name", servings: 1}.

    Args:
        week: Week identifier (e.g., "2026-W11")
        days: List of day objects with meal assignments
    """
    if err := _require_api():
        return err
    result = _update_meal_plan(week, days)
    if result.get("status") == "saved":
        return f"Meal plan saved for {week}"
    return f"Error: {result.get('error', 'Unknown error')}"


@mcp.tool()
def generate_shopping_list(week: str) -> str:
    """Generate a shopping list from the meal plan for a given week.

    Args:
        week: Week identifier (e.g., "2026-W11")
    """
    if err := _require_api():
        return err
    result = _generate_shopping_list(week)
    if result.get("success"):
        return f"Shopping list generated: {result['item_count']} items from {len(result.get('recipes', []))} recipes"
    return f"Error: {result.get('error', 'Unknown error')}"


@mcp.tool()
def send_to_reminders(week: str) -> str:
    """Send the shopping list for a week to Apple Reminders.

    Args:
        week: Week identifier (e.g., "2026-W11")
    """
    if err := _require_api():
        return err
    result = _send_to_reminders(week)
    if result.get("success"):
        return f"Sent {result['items_sent']} items to Reminders (skipped {result['items_skipped']} already checked)"
    return f"Error: {result.get('error', 'Unknown error')}"


@mcp.tool()
def create_things_task(title: str, notes: str = None) -> str:
    """Create a task in Things 3 for KitchenOS follow-up.

    Use this for reminders like "Review new recipe", "Meal plan next week", etc.

    Args:
        title: Task title
        notes: Optional notes (can include links)
    """
    result = _create_things_task(title, notes=notes)
    return f"Things task created: {result['title']}"


if __name__ == "__main__":
    if not check_api_health():
        import sys
        print("Warning: KitchenOS API server is not running at localhost:5001", file=sys.stderr)
        print("Start it with: launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist", file=sys.stderr)
    mcp.run()
