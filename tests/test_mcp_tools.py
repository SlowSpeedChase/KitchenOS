"""Tests for MCP tool implementations."""
import json
from unittest.mock import patch, MagicMock

import pytest

from lib.mcp_tools import (
    extract_recipe,
    save_recipe,
    search_recipes,
    get_recipe,
    get_meal_plan,
    update_meal_plan,
    generate_shopping_list,
    send_to_reminders,
    create_things_task,
)

API_BASE = "http://localhost:5001"


class TestExtractRecipe:
    @patch('lib.mcp_tools.requests.post')
    def test_extract_recipe_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "success", "recipe": "Butter Chicken"}
        )
        result = extract_recipe("https://www.youtube.com/watch?v=abc123")
        assert result["status"] == "success"
        assert result["recipe"] == "Butter Chicken"
        mock_post.assert_called_once_with(
            f"{API_BASE}/extract",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
            timeout=310,
        )

    @patch('lib.mcp_tools.requests.post')
    def test_extract_recipe_api_error(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=500,
            json=lambda: {"status": "error", "message": "Ollama down"}
        )
        result = extract_recipe("https://www.youtube.com/watch?v=abc123")
        assert result["status"] == "error"


class TestSearchRecipes:
    @patch('lib.mcp_tools.requests.get')
    def test_search_recipes_filters_by_query(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"name": "Butter Chicken", "cuisine": "Indian", "protein": "chicken"},
                {"name": "Pasta Aglio", "cuisine": "Italian", "protein": None},
            ]
        )
        result = search_recipes(query="butter")
        assert len(result) == 1
        assert result[0]["name"] == "Butter Chicken"

    @patch('lib.mcp_tools.requests.get')
    def test_search_recipes_no_query_returns_all(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"name": "Butter Chicken"},
                {"name": "Pasta Aglio"},
            ]
        )
        result = search_recipes()
        assert len(result) == 2


class TestGetRecipe:
    @patch('lib.mcp_tools.requests.get')
    def test_get_recipe_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"title": "Butter Chicken", "servings": 4}
        )
        result = get_recipe("Butter Chicken")
        assert result["title"] == "Butter Chicken"


class TestGetMealPlan:
    @patch('lib.mcp_tools.requests.get')
    def test_get_meal_plan_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"week": "2026-W11", "days": []}
        )
        result = get_meal_plan("2026-W11")
        assert result["week"] == "2026-W11"


class TestUpdateMealPlan:
    @patch('lib.mcp_tools.requests.put')
    def test_update_meal_plan_success(self, mock_put):
        mock_put.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "saved", "week": "2026-W11"}
        )
        days = [{"day": "Monday", "date": "2026-03-09", "breakfast": None, "lunch": None, "dinner": {"name": "Pasta", "servings": 1}}]
        result = update_meal_plan("2026-W11", days)
        assert result["status"] == "saved"


class TestGenerateShoppingList:
    @patch('lib.mcp_tools.requests.post')
    def test_generate_shopping_list_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"success": True, "item_count": 12, "recipes": ["Pasta", "Chicken"]}
        )
        result = generate_shopping_list("2026-W11")
        assert result["success"] is True
        assert result["item_count"] == 12


class TestSendToReminders:
    @patch('lib.mcp_tools.requests.post')
    def test_send_to_reminders_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"success": True, "items_sent": 10, "items_skipped": 2}
        )
        result = send_to_reminders("2026-W11")
        assert result["success"] is True
        assert result["items_sent"] == 10


class TestCreateThingsTask:
    @patch('lib.mcp_tools.subprocess.run')
    def test_create_things_task(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = create_things_task("Review Butter Chicken", notes="Check seasoning")
        assert result["status"] == "created"
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "open"
        assert "things:///add" in call_args[1]
