"""Tests for API server endpoints"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from api_server import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_refresh_endpoint_missing_file_param(client):
    """Refresh should return error if file param missing"""
    response = client.get('/refresh')
    assert response.status_code == 400
    assert b'file parameter required' in response.data


def test_refresh_endpoint_file_not_found(client):
    """Refresh should return error if file doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('api_server.OBSIDIAN_RECIPES_PATH', Path(tmpdir)):
            response = client.get('/refresh?file=missing.md')
            assert response.status_code == 404
            assert b'not found' in response.data.lower()


def test_reprocess_endpoint_missing_file_param(client):
    """Reprocess should return error if file param missing"""
    response = client.get('/reprocess')
    assert response.status_code == 400
    assert b'file parameter required' in response.data


def test_reprocess_endpoint_no_source_url(client):
    """Reprocess should return error if recipe has no source_url"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_path = Path(tmpdir)
        test_file = recipes_path / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\n# Test")

        with patch('api_server.OBSIDIAN_RECIPES_PATH', recipes_path):
            response = client.get('/reprocess?file=test.md')
            assert response.status_code == 400
            assert b'no source url' in response.data.lower()


class TestGenerateShoppingListMerge:
    """Tests for shopping list regeneration with manual item preservation."""

    def test_preserves_manual_items_on_regeneration(self, tmp_path):
        """Manual items are preserved when regenerating shopping list."""
        import api_server
        import lib.shopping_list_generator

        # Create test shopping list with a manual item
        test_shopping_list = tmp_path / "Shopping Lists"
        test_shopping_list.mkdir()
        existing_file = test_shopping_list / "2026-W99.md"
        existing_file.write_text(
            "# Shopping List - Week 99\n\n"
            "## Items\n\n"
            "- [ ] 2 cups flour\n"
            "- [ ] 1 tsp salt\n"
            "- [ ] organic eggs (manual item)\n"
        )

        # Mock the paths
        with patch.object(api_server, 'SHOPPING_LISTS_PATH', test_shopping_list), \
             patch.object(lib.shopping_list_generator, 'SHOPPING_LISTS_PATH', test_shopping_list):

            # Mock generate_shopping_list to return known items
            def mock_generate(week):
                return {
                    'success': True,
                    'items': ['2 cups flour', '1 tsp salt'],
                    'recipes': ['Test Recipe'],
                    'warnings': []
                }

            with patch.object(api_server, 'generate_shopping_list', mock_generate):
                # Call the endpoint
                with api_server.app.test_client() as client:
                    response = client.post('/generate-shopping-list',
                                           json={'week': '2026-W99'})

                # Verify manual item is preserved
                result_content = existing_file.read_text()
                assert 'organic eggs (manual item)' in result_content
                assert '2 cups flour' in result_content

    def test_returns_manual_count_in_response(self, tmp_path):
        """Response includes count of manual items preserved."""
        import api_server
        import lib.shopping_list_generator

        # Create test shopping list with manual items
        test_shopping_list = tmp_path / "Shopping Lists"
        test_shopping_list.mkdir()
        existing_file = test_shopping_list / "2026-W98.md"
        existing_file.write_text(
            "# Shopping List - Week 98\n\n"
            "## Items\n\n"
            "- [ ] 2 cups flour\n"
            "- [ ] manual item 1\n"
            "- [ ] manual item 2\n"
        )

        with patch.object(api_server, 'SHOPPING_LISTS_PATH', test_shopping_list), \
             patch.object(lib.shopping_list_generator, 'SHOPPING_LISTS_PATH', test_shopping_list):

            def mock_generate(week):
                return {
                    'success': True,
                    'items': ['2 cups flour'],
                    'recipes': ['Test Recipe'],
                    'warnings': []
                }

            with patch.object(api_server, 'generate_shopping_list', mock_generate):
                with api_server.app.test_client() as client:
                    response = client.post('/generate-shopping-list',
                                           json={'week': '2026-W98'})

                data = response.get_json()
                assert data['success'] is True
                assert data['manual_count'] == 2
                assert data['generated_count'] == 1
                assert data['item_count'] == 3

    def test_works_without_existing_file(self, tmp_path):
        """Endpoint works when no existing file (no manual items to preserve)."""
        import api_server
        import lib.shopping_list_generator

        test_shopping_list = tmp_path / "Shopping Lists"
        test_shopping_list.mkdir()

        with patch.object(api_server, 'SHOPPING_LISTS_PATH', test_shopping_list), \
             patch.object(lib.shopping_list_generator, 'SHOPPING_LISTS_PATH', test_shopping_list):

            def mock_generate(week):
                return {
                    'success': True,
                    'items': ['2 cups flour', '1 tsp salt'],
                    'recipes': ['Test Recipe'],
                    'warnings': []
                }

            with patch.object(api_server, 'generate_shopping_list', mock_generate):
                with api_server.app.test_client() as client:
                    response = client.post('/generate-shopping-list',
                                           json={'week': '2026-W97'})

                data = response.get_json()
                assert data['success'] is True
                assert data['manual_count'] == 0
                assert data['generated_count'] == 2


class TestAddToMealPlan:
    """Tests for the add-to-meal-plan endpoint."""

    def test_get_returns_form_html(self, client):
        """GET should return an HTML form."""
        response = client.get('/add-to-meal-plan?recipe=Test%20Recipe.md')
        assert response.status_code == 200
        assert b'Test Recipe' in response.data
        assert b'<form' in response.data
        assert b'Breakfast' in response.data

    def test_get_missing_recipe_returns_error(self, client):
        """GET without recipe param should return 400."""
        response = client.get('/add-to-meal-plan')
        assert response.status_code == 400

    def test_post_adds_recipe_to_meal_plan(self, tmp_path):
        """POST should append recipe wikilink to meal plan file."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        plan_file = meal_plans_path / "2026-W07.md"
        plan_file.write_text(generate_meal_plan_markdown(2026, 7))

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as client:
                response = client.post('/add-to-meal-plan', data={
                    'recipe': 'Pasta Aglio E Olio',
                    'week': '2026-W07',
                    'day': 'Monday',
                    'meal': 'Dinner'
                })

        assert response.status_code == 200
        assert b'Added!' in response.data
        content = plan_file.read_text()
        assert '[[Pasta Aglio E Olio]]' in content

    def test_post_creates_meal_plan_if_missing(self, tmp_path):
        """POST should create meal plan file if it doesn't exist."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as client:
                response = client.post('/add-to-meal-plan', data={
                    'recipe': 'Test Recipe',
                    'week': '2026-W07',
                    'day': 'Wednesday',
                    'meal': 'Lunch'
                })

        assert response.status_code == 200
        plan_file = meal_plans_path / "2026-W07.md"
        assert plan_file.exists()
        content = plan_file.read_text()
        assert '[[Test Recipe]]' in content

    def test_post_missing_fields_returns_error(self, client):
        """POST without required fields should return 400."""
        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Test',
            # missing week, day, meal
        })
        assert response.status_code == 400
