"""MCP tool implementations — wraps KitchenOS Flask API and Things 3."""

import subprocess
from urllib.parse import quote

import requests

API_BASE = "http://localhost:5001"


def check_api_health() -> bool:
    """Check if the KitchenOS API server is running."""
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def extract_recipe(url: str) -> dict:
    """Extract recipe from a YouTube URL via the API."""
    r = requests.post(f"{API_BASE}/extract", json={"url": url}, timeout=310)
    return r.json()


def save_recipe(recipe_data: dict) -> dict:
    """Save a recipe from structured data."""
    r = requests.post(f"{API_BASE}/api/recipes/save", json=recipe_data, timeout=60)
    return r.json()


def search_recipes(query: str = None, cuisine: str = None, protein: str = None) -> list:
    """Search recipe library. Filters client-side from cached index."""
    r = requests.get(f"{API_BASE}/api/recipes", timeout=10)
    recipes = r.json()

    if query:
        q = query.lower()
        recipes = [rec for rec in recipes if q in rec.get("name", "").lower()]
    if cuisine:
        c = cuisine.lower()
        recipes = [rec for rec in recipes if (rec.get("cuisine") or "").lower() == c]
    if protein:
        p = protein.lower()
        recipes = [rec for rec in recipes if (rec.get("protein") or "").lower() == p]

    return recipes


def get_recipe(name: str) -> dict:
    """Get full recipe details by name."""
    r = requests.get(f"{API_BASE}/api/recipes/{quote(name)}", timeout=10)
    return r.json()


def get_meal_plan(week: str) -> dict:
    """Get meal plan for a given week (e.g., '2026-W11')."""
    r = requests.get(f"{API_BASE}/api/meal-plan/{week}", timeout=10)
    return r.json()


def update_meal_plan(week: str, days: list) -> dict:
    """Update meal plan for a given week."""
    r = requests.put(
        f"{API_BASE}/api/meal-plan/{week}",
        json={"days": days},
        timeout=10,
    )
    return r.json()


def generate_shopping_list(week: str) -> dict:
    """Generate shopping list from meal plan."""
    r = requests.post(
        f"{API_BASE}/generate-shopping-list",
        json={"week": week},
        timeout=30,
    )
    return r.json()


def send_to_reminders(week: str) -> dict:
    """Send shopping list to Apple Reminders."""
    r = requests.post(
        f"{API_BASE}/send-to-reminders",
        json={"week": week},
        timeout=30,
    )
    return r.json()


def create_things_task(title: str, notes: str = None) -> dict:
    """Create a task in Things 3 via URL scheme."""
    params = [f"title={quote(title)}", "list=KitchenOS"]
    if notes:
        params.append(f"notes={quote(notes)}")

    url = f"things:///add?{'&'.join(params)}"
    subprocess.run(["open", url], check=True)
    return {"status": "created", "title": title}
