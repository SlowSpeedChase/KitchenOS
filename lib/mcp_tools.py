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
    try:
        r = requests.post(f"{API_BASE}/extract", json={"url": url}, timeout=310)
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def save_recipe(recipe_data: dict) -> dict:
    """Save a recipe from structured data."""
    try:
        r = requests.post(f"{API_BASE}/api/recipes/save", json=recipe_data, timeout=60)
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def search_recipes(query: str = None, cuisine: str = None, protein: str = None) -> list:
    """Search recipe library. Filters client-side from cached index."""
    try:
        r = requests.get(f"{API_BASE}/api/recipes", timeout=10)
        recipes = r.json()
    except requests.exceptions.RequestException:
        return []

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
    try:
        r = requests.get(f"{API_BASE}/api/recipes/{quote(name)}", timeout=10)
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {e}"}


def get_meal_plan(week: str) -> dict:
    """Get meal plan for a given week (e.g., '2026-W11')."""
    try:
        r = requests.get(f"{API_BASE}/api/meal-plan/{week}", timeout=10)
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {e}"}


def update_meal_plan(week: str, days: list) -> dict:
    """Update meal plan for a given week."""
    try:
        r = requests.put(
            f"{API_BASE}/api/meal-plan/{week}",
            json={"days": days},
            timeout=10,
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def generate_shopping_list(week: str) -> dict:
    """Generate shopping list from meal plan."""
    try:
        r = requests.post(
            f"{API_BASE}/generate-shopping-list",
            json={"week": week},
            timeout=30,
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def send_to_reminders(week: str) -> dict:
    """Send shopping list to Apple Reminders."""
    try:
        r = requests.post(
            f"{API_BASE}/send-to-reminders",
            json={"week": week},
            timeout=30,
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def add_to_inventory(items: list) -> dict:
    """Add items to the kitchen inventory."""
    try:
        r = requests.post(
            f"{API_BASE}/api/inventory/add", json={"items": items}, timeout=15
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def list_inventory(category: str = None, location: str = None) -> list:
    """List inventory items with optional filters."""
    params = {}
    if category:
        params["category"] = category
    if location:
        params["location"] = location
    try:
        r = requests.get(f"{API_BASE}/api/inventory", params=params, timeout=10)
        return r.json()
    except requests.exceptions.RequestException:
        return []


def remove_from_inventory(name: str, location: str = None) -> dict:
    """Remove an item from inventory."""
    body = {"name": name}
    if location:
        body["location"] = location
    try:
        r = requests.post(
            f"{API_BASE}/api/inventory/remove", json=body, timeout=10
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def update_inventory_item(
    name: str, quantity: float, location: str = None
) -> dict:
    """Update an inventory item's quantity."""
    body = {"name": name, "quantity": quantity}
    if location:
        body["location"] = location
    try:
        r = requests.post(
            f"{API_BASE}/api/inventory/update", json=body, timeout=10
        )
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API request failed: {e}"}


def create_things_task(title: str, notes: str = None) -> dict:
    """Create a task in Things 3 via URL scheme."""
    params = [f"title={quote(title)}", "list=KitchenOS"]
    if notes:
        params.append(f"notes={quote(notes)}")

    url = f"things:///add?{'&'.join(params)}"
    subprocess.run(["open", url], check=True)
    return {"status": "created", "title": title}
