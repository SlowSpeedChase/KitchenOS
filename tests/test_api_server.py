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


def test_api_recipe_save_creates_file(client):
    """POST /api/recipes/save creates recipe markdown file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_path = Path(tmpdir)

        with patch('api_server.OBSIDIAN_RECIPES_PATH', recipes_path), \
             patch('api_server.validate_ingredients', side_effect=lambda x, **kw: x), \
             patch('api_server.match_ingredients_to_seasonal', return_value=[]), \
             patch('api_server.get_peak_months', return_value=[]), \
             patch('api_server.calculate_recipe_nutrition', return_value=None):

            response = client.post('/api/recipes/save', json={
                'recipe_name': 'Test Recipe',
                'description': 'A test recipe',
                'servings': 4,
                'cuisine': 'American',
                'ingredients': [
                    {'amount': '2', 'unit': 'cups', 'item': 'flour'},
                    {'amount': '1', 'unit': 'tsp', 'item': 'salt'},
                ],
                'instructions': [
                    {'step': 1, 'text': 'Mix flour and salt.', 'time': None},
                ],
            })

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'success'
            assert data['recipe_name'] == 'Test Recipe'

            # Verify file was created
            recipe_file = recipes_path / "Test Recipe.md"
            assert recipe_file.exists()


def test_api_recipe_save_missing_name(client):
    """POST /api/recipes/save returns 400 without recipe_name."""
    response = client.post('/api/recipes/save', json={
        'ingredients': [],
        'instructions': [],
    })
    assert response.status_code == 400


def test_api_recipe_detail_returns_full_recipe(client):
    """GET /api/recipes/<name> returns full recipe data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_path = Path(tmpdir)
        test_file = recipes_path / "Butter Chicken.md"
        test_file.write_text(
            '---\n'
            'title: "Butter Chicken"\n'
            'cuisine: "Indian"\n'
            'protein: "chicken"\n'
            'servings: 4\n'
            'prep_time: "15 min"\n'
            'cook_time: "30 min"\n'
            '---\n\n'
            '# Butter Chicken\n\n'
            '> A creamy Indian classic\n\n'
            '## Ingredients\n\n'
            '| Amount | Unit | Ingredient |\n'
            '|--------|------|------------|\n'
            '| 500 | g | chicken thighs |\n'
            '| 2 | tbsp | butter |\n\n'
            '## Instructions\n\n'
            '1. Cut the chicken into pieces.\n'
            '2. Cook in butter until done.\n\n'
            '## My Notes\n\n'
            '<!-- Your personal notes, ratings, and modifications go here -->\n',
            encoding='utf-8'
        )

        with patch('api_server.OBSIDIAN_RECIPES_PATH', recipes_path):
            response = client.get('/api/recipes/Butter%20Chicken')
            assert response.status_code == 200
            data = response.get_json()
            assert data['title'] == 'Butter Chicken'
            assert data['cuisine'] == 'Indian'
            assert data['servings'] == 4
            assert len(data['ingredients']) == 2
            assert data['ingredients'][0]['item'] == 'chicken thighs'
            assert len(data['instructions']) >= 1


def test_api_recipe_detail_not_found(client):
    """GET /api/recipes/<name> returns 404 for missing recipe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('api_server.OBSIDIAN_RECIPES_PATH', Path(tmpdir)):
            response = client.get('/api/recipes/Nonexistent')
            assert response.status_code == 404


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
                {"day": "Tuesday", "date": "2026-02-24", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
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
                {"day": "Tuesday", "date": "2026-02-24", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Wednesday", "date": "2026-02-25", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Thursday", "date": "2026-02-26", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Friday", "date": "2026-02-27", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Saturday", "date": "2026-02-28", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
                {"day": "Sunday", "date": "2026-03-01", "breakfast": None, "lunch": None, "snack": None, "dinner": None},
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


class TestServeImages:
    """Tests for GET /images/<filename> endpoint."""

    def test_serves_existing_image(self, tmp_path):
        """Should serve image file from Recipes/Images/ directory."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        images_path = recipes_path / "Images"
        images_path.mkdir(parents=True)
        (images_path / "Test Recipe.jpg").write_bytes(b'\xff\xd8\xff\xe0fake-jpeg')

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/Test%20Recipe.jpg')

        assert response.status_code == 200
        assert response.content_type.startswith('image/')

    def test_returns_404_for_missing_image(self, tmp_path):
        """Should return 404 when image doesn't exist."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        images_path = recipes_path / "Images"
        images_path.mkdir(parents=True)

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/Missing.jpg')

        assert response.status_code == 404

    def test_blocks_path_traversal(self, tmp_path):
        """Should reject filenames with path traversal."""
        import api_server

        recipes_path = tmp_path / "Recipes"
        (recipes_path / "Images").mkdir(parents=True)

        with patch.object(api_server, 'OBSIDIAN_RECIPES_PATH', recipes_path):
            with app.test_client() as c:
                response = c.get('/images/..%2F..%2Fetc%2Fpasswd')

        assert response.status_code == 404


class TestAddToMealPlanDirect:
    """Regression guard for the existing direct schedule flow."""

    def test_direct_schedules_recipe(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'direct',
            'week': '2026-W18',
            'day': 'Monday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data
        plan_file = plans_dir / "2026-W18.md"
        assert plan_file.exists()
        assert '[[Pan-Seared Salmon]]' in plan_file.read_text()

    def test_direct_without_mode_param_still_works(self, client, tmp_path, monkeypatch):
        """Backwards compat: forms posted without 'mode' default to direct."""
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'week': '2026-W18',
            'day': 'Monday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data


class TestAddToMealPlanExisting:
    """mode=existing — append a recipe to an existing meal."""

    def test_appends_recipe_to_existing_meal(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon", servings=1)]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'existing',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 200
        assert b'Schedule it now?' in response.data
        loaded = ml.load_meal('Salmon Dinner', meals_dir=meals_dir)
        assert [s.recipe for s in loaded.sub_recipes] == ['Pan-Seared Salmon', 'Lemon Asparagus']

    def test_idempotent_when_recipe_already_in_meal(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon", servings=1)]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'existing',
            'meal_name': 'Dinner',
        })

        assert response.status_code == 200
        assert b'already in' in response.data.lower()
        loaded = ml.load_meal('Dinner', meals_dir=meals_dir)
        assert len(loaded.sub_recipes) == 1

    def test_meal_not_found_re_renders_form_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'existing',
            'meal_name': 'Does Not Exist',
        })

        assert b'Add to Meal Plan' in response.data
        assert b'Meal not found' in response.data


class TestAddToMealPlanNew:
    """mode=new — create a new meal seeded with the current recipe."""

    def test_creates_new_meal_with_seed_recipe(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 200
        assert b'Schedule it now?' in response.data
        from lib import meal_loader as ml
        loaded = ml.load_meal('Salmon Dinner', meals_dir=meals_dir)
        assert loaded is not None
        assert [s.recipe for s in loaded.sub_recipes] == ['Pan-Seared Salmon']

    def test_empty_meal_name_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': '   ',
        })

        assert b'Meal name is required' in response.data
        assert response.status_code == 400

    def test_collision_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon")]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Lemon Asparagus',
            'mode': 'new',
            'meal_name': 'Salmon Dinner',
        })

        assert response.status_code == 409
        assert b'already exists' in response.data

    def test_filesystem_unsafe_name_re_renders_with_error(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',
            'mode': 'new',
            'meal_name': 'Bad/Name',
        })

        assert response.status_code == 400
        assert b"can't contain" in response.data or b'can&#39;t contain' in response.data


class TestScheduleMeal:
    """mode=schedule_meal — Screen 2 submit. Inserts [[Meal: X]] into the plan."""

    def test_inserts_meal_token_into_plan(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'Pan-Seared Salmon',  # carried through, not used here
            'mode': 'schedule_meal',
            'meal_name': 'Salmon Dinner',
            'week': '2026-W19',
            'day': 'Tuesday',
            'meal': 'Dinner',
        })

        assert response.status_code == 200
        assert b'Added!' in response.data
        plan_text = (plans_dir / "2026-W19.md").read_text()
        assert '[[Meal: Salmon Dinner]]' in plan_text
        # The wikilink is NOT a plain recipe link.
        assert '[[Pan-Seared Salmon]]' not in plan_text

    def test_invalid_week_returns_error(self, client, tmp_path, monkeypatch):
        plans_dir = tmp_path / "Meal Plans"
        plans_dir.mkdir()
        monkeypatch.setattr('api_server.MEAL_PLANS_PATH', plans_dir)

        response = client.post('/add-to-meal-plan', data={
            'recipe': 'X',
            'mode': 'schedule_meal',
            'meal_name': 'Salmon Dinner',
            'week': 'not-a-week',
            'day': 'Tuesday',
            'meal': 'Dinner',
        })

        assert response.status_code == 400
        assert b'Invalid week format' in response.data


class TestAddToMealPlanFormRender:
    """GET /add-to-meal-plan — branch picker form."""

    def test_form_lists_three_radios(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=Pan-Seared%20Salmon')
        body = response.data
        assert response.status_code == 200
        assert b'Pan-Seared Salmon' in body
        assert b'value="direct"' in body
        assert b'value="existing"' in body
        assert b'value="new"' in body
        # Default selection
        assert b'value="direct" checked' in body

    def test_existing_disabled_when_no_meals(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=X')
        # The existing radio is rendered with `disabled`.
        assert b'value="existing" disabled' in response.data
        assert b'(none yet)' in response.data

    def test_existing_enabled_when_meals_exist(self, client, tmp_path, monkeypatch):
        meals_dir = tmp_path / "Meals"
        meals_dir.mkdir()
        from lib import meal_loader as ml
        ml.save_meal(
            ml.Meal(name="Salmon Dinner",
                    sub_recipes=[ml.SubRecipe(recipe="Pan-Seared Salmon")]),
            meals_dir=meals_dir,
        )
        monkeypatch.setattr('lib.meal_loader.paths.meals_dir', lambda: meals_dir)

        response = client.get('/add-to-meal-plan?recipe=X')
        assert b'value="existing" disabled' not in response.data
        assert b'<option value="Salmon Dinner">' in response.data


# ---------------------------------------------------------------------------
# /api/inventory/add — optional trip + prices (price ledger)
# ---------------------------------------------------------------------------

def test_inventory_add_with_trip_records_purchases(client, tmp_vault, tmp_db):
    payload = {
        "items": [
            {"name": "chicken breast", "quantity": 2, "unit": "lb",
             "category": "meat", "location": "fridge",
             "purchased": "2026-06-09", "source": "receipt",
             "unit_price": 5.49, "line_total": 10.98},
        ],
        "trip": {"date": "2026-06-09", "store": "HEB", "total": 10.98,
                 "source_id": "photo-abc123"},
    }
    resp = client.post("/api/inventory/add", json=payload)
    assert resp.status_code == 200
    from lib import inventory_db as idb
    assert idb.trip_exists("photo-abc123")
    conn = idb.connect()
    row = conn.execute("SELECT canonical_name, total_cents FROM purchases").fetchone()
    conn.close()
    assert row[0] == "chicken breast"
    assert row[1] == 1098


def test_inventory_add_fee_items_skip_inventory(client, tmp_vault, tmp_db):
    payload = {
        "items": [
            {"name": "chicken breast", "quantity": 2, "unit": "lb",
             "category": "meat", "location": "fridge",
             "unit_price": 5.49, "line_total": 10.98},
            {"name": "sales tax", "quantity": 1, "unit": "ct",
             "category": "fee", "line_total": 0.91},
        ],
        "trip": {"date": "2026-06-09", "store": "HEB", "total": 11.89,
                 "source_id": "photo-fee-test"},
    }
    resp = client.post("/api/inventory/add", json=payload)
    assert resp.status_code == 200

    from lib.inventory import read_inventory
    names = [it.name for it in read_inventory()]
    assert "chicken breast" in names
    assert "sales tax" not in names

    from lib import inventory_db as idb
    conn = idb.connect()
    rows = conn.execute(
        "SELECT canonical_name, category FROM purchases ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 2
    assert ("sales tax", "fee") in [(r[0], r[1]) for r in rows]


def test_inventory_add_without_trip_unchanged(client, tmp_vault, tmp_db):
    resp = client.post("/api/inventory/add", json={
        "items": [{"name": "rice", "quantity": 2, "unit": "lb"}]})
    assert resp.status_code == 200
    from lib import inventory_db as idb
    conn = idb.connect()
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# /api/inventory — computed expiry_status field (additive)
# ---------------------------------------------------------------------------

def test_inventory_list_includes_expiry_status(client, tmp_vault, tmp_db):
    # An always-expired perishable, and a no-expiry household item.
    client.post("/api/inventory/add", json={"items": [
        {"name": "old milk", "quantity": 1, "unit": "gal", "category": "dairy",
         "location": "fridge", "expires": "2020-01-01"},
        {"name": "dish soap", "quantity": 1, "unit": "ct", "category": "household",
         "location": "pantry"},
    ]})

    resp = client.get("/api/inventory")
    assert resp.status_code == 200
    by_name = {i["name"]: i for i in resp.get_json()}

    assert by_name["old milk"]["expiry_status"] == "expired"
    # No expiry configured for household → null/None, but the key is present.
    assert "expiry_status" in by_name["dish soap"]
    assert by_name["dish soap"]["expiry_status"] is None
    # Field is additive — existing keys still present.
    assert by_name["old milk"]["expires"] == "2020-01-01"
    assert by_name["old milk"]["purchased"] is not None or "purchased" in by_name["old milk"]
