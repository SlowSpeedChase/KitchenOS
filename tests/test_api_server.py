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


class TestApiRecipes:
    """Tests for GET /api/recipes endpoint."""

    def test_returns_recipe_list(self, tmp_path):
        """Should return JSON list of recipe metadata."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        recipes_path.mkdir()
        (recipes_path / "Pasta.md").write_text(
            '---\ntitle: "Pasta"\ncuisine: "Italian"\nprotein: null\n'
            'difficulty: "easy"\nmeal_occasion: ["weeknight-dinner"]\n---\n\n# Pasta'
        )

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path), \
             patch.object(api_server, '_recipe_cache', {"data": None, "timestamp": 0}):
            with app.test_client() as c:
                response = c.get('/api/recipes')

        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "Pasta"
        assert data[0]["cuisine"] == "Italian"

    def test_returns_empty_list_for_no_recipes(self, tmp_path):
        """Should return empty list if no recipe files."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        recipes_path.mkdir()

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path), \
             patch.object(api_server, '_recipe_cache', {"data": None, "timestamp": 0}):
            with app.test_client() as c:
                response = c.get('/api/recipes')

        assert response.status_code == 200
        assert response.get_json() == []


class TestApiMealPlanGet:
    """Tests for GET /api/meal-plan/<week> endpoint."""

    def test_returns_parsed_meal_plan(self, tmp_path):
        """Should return structured JSON from existing meal plan."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        plan_file = meal_plans_path / "2026-W09.md"
        content = generate_meal_plan_markdown(2026, 9)
        content = content.replace("## Monday (Feb 23)\n### Breakfast\n",
                                  "## Monday (Feb 23)\n### Breakfast\n[[Pancakes]] x2\n")
        plan_file.write_text(content)

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.get('/api/meal-plan/2026-W09')

        assert response.status_code == 200
        data = response.get_json()
        assert data["week"] == "2026-W09"
        assert len(data["days"]) == 7
        assert data["days"][0]["day"] == "Monday"
        assert data["days"][0]["breakfast"]["name"] == "Pancakes"
        assert data["days"][0]["breakfast"]["servings"] == 2
        assert data["days"][0]["lunch"] is None

    def test_creates_plan_if_missing(self, tmp_path):
        """Should auto-create meal plan file and return empty plan."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.get('/api/meal-plan/2026-W09')

        assert response.status_code == 200
        data = response.get_json()
        assert data["week"] == "2026-W09"
        assert all(d["breakfast"] is None for d in data["days"])
        assert (meal_plans_path / "2026-W09.md").exists()

    def test_invalid_week_format(self, client):
        """Should return 400 for invalid week format."""
        response = client.get('/api/meal-plan/bad-format')
        assert response.status_code == 400


class TestApiMealPlanPut:
    """Tests for PUT /api/meal-plan/<week> endpoint."""

    def test_saves_meal_plan(self, tmp_path):
        """Should write meal plan markdown from JSON."""
        from templates.meal_plan_template import generate_meal_plan_markdown

        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()
        plan_file = meal_plans_path / "2026-W09.md"
        plan_file.write_text(generate_meal_plan_markdown(2026, 9))

        payload = {
            "week": "2026-W09",
            "days": [
                {"day": "Monday", "date": "2026-02-23",
                 "breakfast": {"name": "Pancakes", "servings": 2},
                 "lunch": None,
                 "dinner": {"name": "Butter Chicken", "servings": 1}},
                {"day": "Tuesday", "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01", "breakfast": None, "lunch": None, "dinner": None},
            ]
        }

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.put('/api/meal-plan/2026-W09', json=payload, content_type='application/json')

        assert response.status_code == 200
        content = plan_file.read_text()
        assert "[[Pancakes]] x2" in content
        assert "[[Butter Chicken]]" in content

    def test_creates_file_if_missing(self, tmp_path):
        """Should create meal plan file if it doesn't exist."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        payload = {
            "week": "2026-W09",
            "days": [
                {"day": "Monday", "date": "2026-02-23",
                 "breakfast": {"name": "Toast", "servings": 1},
                 "lunch": None, "dinner": None},
                {"day": "Tuesday", "date": "2026-02-24", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28", "breakfast": None, "lunch": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01", "breakfast": None, "lunch": None, "dinner": None},
            ]
        }

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                response = c.put('/api/meal-plan/2026-W09', json=payload, content_type='application/json')

        assert response.status_code == 200
        assert (meal_plans_path / "2026-W09.md").exists()
        content = (meal_plans_path / "2026-W09.md").read_text()
        assert "[[Toast]]" in content

    def test_invalid_week_format(self, client):
        """Should return 400 for invalid week format."""
        response = client.put('/api/meal-plan/bad', json={"days": []}, content_type='application/json')
        assert response.status_code == 400

    def test_roundtrip_get_put_get(self, tmp_path):
        """GET -> PUT -> GET should preserve data."""
        meal_plans_path = tmp_path / "Meal Plans"
        meal_plans_path.mkdir()

        with patch('api_server.MEAL_PLANS_PATH', meal_plans_path):
            with app.test_client() as c:
                r1 = c.get('/api/meal-plan/2026-W09')
                data = r1.get_json()
                data["days"][0]["dinner"] = {"name": "Steak", "servings": 1}
                c.put('/api/meal-plan/2026-W09', json=data, content_type='application/json')
                r2 = c.get('/api/meal-plan/2026-W09')
                data2 = r2.get_json()

        assert data2["days"][0]["dinner"]["name"] == "Steak"
        assert data2["days"][0]["dinner"]["servings"] == 1
        assert data2["days"][0]["breakfast"] is None
