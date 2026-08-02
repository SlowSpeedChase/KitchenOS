"""Tests for API endpoints."""

import os

import pytest
from api_server import app


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_generate_shopping_list_requires_week(client):
    """Endpoint requires week parameter."""
    response = client.post('/generate-shopping-list', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "week" in data.get("error", "").lower()


def test_generate_shopping_list_invalid_week(client):
    """Invalid week format returns error."""
    response = client.post('/generate-shopping-list', json={'week': 'invalid'})
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False


def test_send_to_reminders_requires_week(client):
    """Endpoint requires week parameter."""
    response = client.post('/send-to-reminders', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "week" in data.get("error", "").lower()


def test_suggest_meal_requires_fields(client):
    """Suggest endpoint requires week, day, meal fields."""
    response = client.post('/api/suggest-meal', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_home_page_lists_every_registered_page(client):
    from html import escape

    from lib import web_dashboard as wd

    response = client.get('/')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for _section, items in wd.SECTIONS:
        for _emoji, title, path, _desc in items:
            assert escape(title) in body
            assert f'href="{path}"' in body


def test_home_page_has_no_unsubstituted_placeholder(client):
    body = client.get('/').get_data(as_text=True)
    assert "<!--SECTIONS-->" not in body


def test_suggest_meal_invalid_week(client):
    """Invalid week format returns 400."""
    response = client.post('/api/suggest-meal', json={
        "week": "invalid", "day": "Monday", "meal": "dinner"
    })
    assert response.status_code == 400


def test_create_meal_rejects_subs_without_recipe_key(client):
    """Sub_recipes entries missing the 'recipe' key must 400, not silently save empty."""
    response = client.post('/api/meals', json={
        "name": "Test Meal Bad Subs",
        "sub_recipes": [{"name": "Salmon Onigiri"}, {"recipe": ""}],
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "recipe" in data.get("error", "").lower()


def test_inventory_extend_requires_name_and_days(client):
    response = client.post('/api/inventory/extend', json={})
    assert response.status_code == 400


def test_inventory_extend_not_found(client):
    response = client.post('/api/inventory/extend',
                           json={'name': 'ZzzNope', 'days': 3})
    assert response.status_code == 404
    assert response.get_json()['status'] == 'not_found'


def test_inventory_extend_success(client):
    client.post('/api/inventory/add', json={'items': [
        {'name': 'ExtendTestKale', 'quantity': 1, 'unit': 'ct',
         'category': 'produce', 'location': 'fridge'}]})
    response = client.post('/api/inventory/extend',
                           json={'name': 'ExtendTestKale', 'days': 7,
                                 'location': 'fridge'})
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'extended'
    assert body['item']['name'] == 'ExtendTestKale'
    assert body['item']['expires']  # a date string is now set
    assert 'expiry_status' in body['item']
    # cleanup
    client.post('/api/inventory/remove',
                json={'name': 'ExtendTestKale', 'location': 'fridge'})


def test_review_page_served(client):
    response = client.get('/review')
    assert response.status_code == 200
    assert b'Inventory Review' in response.data


def test_claude_notes_get_empty(client, tmp_vault):
    """GET /api/claude-notes on a fresh vault returns empty notes."""
    response = client.get('/api/claude-notes')
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"notes": ""}


def test_claude_notes_save_and_get(client, tmp_vault):
    """POST /api/claude-notes saves, returns normalized body, then GET retrieves it."""
    from lib.paths import claude_notes_path

    # Save notes
    response = client.post('/api/claude-notes', json={"notes": "buy milk"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "saved"
    assert data["notes"] == "buy milk\n"

    # Verify file exists with correct content
    assert claude_notes_path().exists()
    assert claude_notes_path().read_text(encoding="utf-8") == "buy milk\n"

    # Verify GET retrieves it
    response = client.get('/api/claude-notes')
    assert response.status_code == 200
    data = response.get_json()
    assert data["notes"] == "buy milk\n"


def test_claude_notes_post_missing_key(client, tmp_vault):
    """POST /api/claude-notes without 'notes' key returns 400."""
    response = client.post('/api/claude-notes', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "notes" in data.get("error", "").lower()


def test_claude_notes_post_non_string(client, tmp_vault):
    """POST /api/claude-notes with non-string 'notes' value returns 400."""
    response = client.post('/api/claude-notes', json={"notes": 123})
    assert response.status_code == 400
    data = response.get_json()
    assert "string" in data.get("error", "").lower()


def test_claude_notes_post_empty_clears(client, tmp_vault):
    """Saving empty string clears the notes."""
    from lib.paths import claude_notes_path

    # Save some notes
    client.post('/api/claude-notes', json={"notes": "hello"})
    assert claude_notes_path().read_text(encoding="utf-8") == "hello\n"

    # Clear with empty string
    response = client.post('/api/claude-notes', json={"notes": ""})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "saved"
    assert data["notes"] == ""

    # Verify it's cleared
    response = client.get('/api/claude-notes')
    assert response.status_code == 200
    data = response.get_json()
    assert data["notes"] == ""


def _bulk_seed(client, name, unit, location, category="produce"):
    client.post('/api/inventory/add', json={'items': [
        {'name': name, 'quantity': 1, 'unit': unit,
         'category': category, 'location': location}]})


def _bulk_cleanup(client, name, location):
    client.post('/api/inventory/remove', json={'name': name, 'location': location})


def test_inventory_bulk_requires_action(client):
    response = client.post('/api/inventory/bulk',
                           json={'refs': [{'name': 'X', 'unit': 'ct',
                                           'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'action' in response.get_json()['error'].lower()


def test_inventory_bulk_requires_non_empty_refs(client):
    response = client.post('/api/inventory/bulk',
                           json={'action': 'remove', 'refs': []})
    assert response.status_code == 400
    assert 'refs' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_unknown_action(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'detonate',
        'refs': [{'name': 'X', 'unit': 'ct', 'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'unknown action' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_ref_missing_unit(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'X', 'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'unit' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_ref_missing_location(client):
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'X', 'unit': 'ct'}]})
    assert response.status_code == 400
    assert 'location' in response.get_json()['error'].lower()


def test_inventory_bulk_rejects_missing_action_param(client):
    _bulk_seed(client, 'BulkParamKale', 'bunch', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend',
        'refs': [{'name': 'BulkParamKale', 'unit': 'bunch',
                  'location': 'fridge'}]})
    assert response.status_code == 400
    assert 'days' in response.get_json()['error'].lower()
    _bulk_cleanup(client, 'BulkParamKale', 'fridge')


def test_inventory_bulk_extend_applies_to_all(client):
    _bulk_seed(client, 'BulkKale', 'bunch', 'fridge')
    _bulk_seed(client, 'BulkRice', 'lb', 'pantry', category='pantry')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend', 'days': 7,
        'refs': [
            {'name': 'BulkKale', 'unit': 'bunch', 'location': 'fridge'},
            {'name': 'BulkRice', 'unit': 'lb', 'location': 'pantry'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'applied'
    assert body['applied'] == 2
    assert body['removed'] == []
    assert body['not_found'] == []
    assert len(body['items']) == 2
    for item in body['items']:
        assert item['expires']
        assert 'expiry_status' in item      # same shape as the single routes
    _bulk_cleanup(client, 'BulkKale', 'fridge')
    _bulk_cleanup(client, 'BulkRice', 'pantry')


def test_inventory_bulk_remove_returns_rows_for_undo(client):
    _bulk_seed(client, 'BulkGone', 'ct', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'remove',
        'refs': [{'name': 'BulkGone', 'unit': 'ct', 'location': 'fridge'}]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 1
    assert body['items'] == []
    assert body['removed'][0]['name'] == 'BulkGone'
    assert body['removed'][0]['quantity'] == 1
    assert body['removed'][0]['unit'] == 'ct'


def test_inventory_bulk_partial_not_found_is_not_a_404(client):
    _bulk_seed(client, 'BulkHalf', 'ct', 'fridge')
    response = client.post('/api/inventory/bulk', json={
        'action': 'extend', 'days': 3,
        'refs': [
            {'name': 'BulkHalf', 'unit': 'ct', 'location': 'fridge'},
            {'name': 'BulkGhostZzz', 'unit': 'ct', 'location': 'fridge'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 1
    assert len(body['not_found']) == 1
    assert body['not_found'][0]['name'] == 'BulkGhostZzz'
    _bulk_cleanup(client, 'BulkHalf', 'fridge')


def test_inventory_bulk_set_expiry_clears_with_null(client):
    """'expires': null is a legal value (clear the expiry), not an omitted param.

    The route collects bulk params by key presence (`k in data`), not
    truthiness — if that ever regressed to a truthiness filter, a null
    expires would silently vanish from **params and 400 with "requires
    'expires'". Guard the whole round trip end to end.
    """
    _bulk_seed(client, 'BulkExpiryClear', 'ct', 'fridge')
    # Give it a real expiry first, so clearing it is an observable change.
    client.post('/api/inventory/extend', json={
        'name': 'BulkExpiryClear', 'location': 'fridge', 'days': 5})
    response = client.post('/api/inventory/bulk', json={
        'action': 'set-expiry', 'expires': None,
        'refs': [{'name': 'BulkExpiryClear', 'unit': 'ct', 'location': 'fridge'}]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'applied'
    assert body['applied'] == 1
    assert body['not_found'] == []
    assert body['removed'] == []
    assert len(body['items']) == 1
    assert body['items'][0]['expires'] is None
    _bulk_cleanup(client, 'BulkExpiryClear', 'fridge')


def test_inventory_bulk_set_category_applies_to_all(client):
    _bulk_seed(client, 'BulkCatKale', 'bunch', 'fridge')
    _bulk_seed(client, 'BulkCatRice', 'lb', 'pantry', category='pantry')
    response = client.post('/api/inventory/bulk', json={
        'action': 'set-category', 'category': 'frozen',
        'refs': [
            {'name': 'BulkCatKale', 'unit': 'bunch', 'location': 'fridge'},
            {'name': 'BulkCatRice', 'unit': 'lb', 'location': 'pantry'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 2
    assert body['not_found'] == []
    assert len(body['items']) == 2
    for item in body['items']:
        assert item['category'] == 'frozen'
    _bulk_cleanup(client, 'BulkCatKale', 'fridge')
    _bulk_cleanup(client, 'BulkCatRice', 'pantry')


def test_inventory_bulk_move_applies_to_all(client):
    _bulk_seed(client, 'BulkMoveKale', 'bunch', 'fridge')
    _bulk_seed(client, 'BulkMoveRice', 'lb', 'pantry', category='pantry')
    response = client.post('/api/inventory/bulk', json={
        'action': 'move', 'to_location': 'counter',
        'refs': [
            {'name': 'BulkMoveKale', 'unit': 'bunch', 'location': 'fridge'},
            {'name': 'BulkMoveRice', 'unit': 'lb', 'location': 'pantry'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 2
    assert body['not_found'] == []
    assert len(body['items']) == 2
    for item in body['items']:
        assert item['location'] == 'counter'
    _bulk_cleanup(client, 'BulkMoveKale', 'counter')
    _bulk_cleanup(client, 'BulkMoveRice', 'counter')


def test_inventory_bulk_freeze_applies_to_all(client):
    _bulk_seed(client, 'BulkFreezeKale', 'bunch', 'fridge')
    _bulk_seed(client, 'BulkFreezeRice', 'lb', 'pantry', category='pantry')
    response = client.post('/api/inventory/bulk', json={
        'action': 'freeze',
        'refs': [
            {'name': 'BulkFreezeKale', 'unit': 'bunch', 'location': 'fridge'},
            {'name': 'BulkFreezeRice', 'unit': 'lb', 'location': 'pantry'},
        ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body['applied'] == 2
    assert body['not_found'] == []
    assert len(body['items']) == 2
    for item in body['items']:
        assert item['location'] == 'freezer'
        assert item['category'] == 'frozen'
        assert item['expires'] is None
    _bulk_cleanup(client, 'BulkFreezeKale', 'freezer')
    _bulk_cleanup(client, 'BulkFreezeRice', 'freezer')


def test_review_page_has_bulk_selection_ui(client):
    """The bulk bar, select-all, and per-row checkbox ship in the page."""
    response = client.get('/review')
    assert response.status_code == 200
    html = response.data
    assert b'id="bulkbar"' in html
    assert b'id="selall"' in html
    assert b'class="pick"' in html
    assert b'/api/inventory/bulk' in html


def test_review_page_has_a_sort_control(client):
    """Expiry/Added ordering ships in the page."""
    html = client.get('/review').data
    assert b'id="sortby"' in html
    assert b'value="expiry"' in html
    assert b'value="added"' in html


# ---- Macro-aware suggest-meal (Stage 3) ----

def _write_recipe(recipes_dir, name, *, cal, protein, coverage, servings, items):
    rows = "".join(f"| 1 | whole | {it} |\n" for it in items)
    content = (
        f'---\ntitle: "{name}"\ncuisine: "test"\nprotein: "test"\n'
        f'nutrition_calories: {cal}\nnutrition_protein: {protein}\n'
        f'nutrition_carbs: 20\nnutrition_fat: 10\n'
        f'nutrition_coverage: {coverage}\nservings: {servings}\n---\n\n'
        f"# {name}\n\n## Ingredients\n\n"
        f"| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}"
    )
    (recipes_dir / f"{name}.md").write_text(content)


def test_suggest_meal_includes_macro_context(client, tmp_vault, tmp_path, monkeypatch):
    """With My Macros.md + a planned day, the response carries macro_context and
    the suggestion carries per-serving nutrition."""
    (tmp_vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n\n# My Macros\n"
    )
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    _write_recipe(recipes_dir, "Small Salad", cal=200, protein=6,
                  coverage=0.95, servings=4, items=["lettuce", "cucumber"])
    _write_recipe(recipes_dir, "Beef Power Bowl", cal=650, protein=48,
                  coverage=0.95, servings=3, items=["beef", "quinoa"])
    plans_dir = tmp_path / "Meal Plans"
    plans_dir.mkdir()
    (plans_dir / "2026-W31.md").write_text(
        "## Thursday (Jul 31)\n\n### lunch\n[[Small Salad]]\n\n### dinner\n\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server.MEAL_PLANS_PATH", plans_dir)

    response = client.post('/api/suggest-meal', json={
        "week": "2026-W31", "day": "Thursday", "meal": "dinner",
    })
    assert response.status_code == 200
    data = response.get_json()
    ctx = data["macro_context"]
    assert ctx is not None
    assert ctx["target"]["protein"] == 190
    assert ctx["current"]["protein"] == 6          # Small Salad, 1 serving
    assert ctx["remaining"]["protein"] == 184
    # A suggestion was made and it carries per-serving nutrition.
    assert data["suggestion"] is not None
    assert data["suggestion"]["nutrition"]["protein"] == 48
    assert data["suggestion"]["name"] == "Beef Power Bowl"


def test_suggest_meal_no_targets_null_macro_context(client, tmp_vault, tmp_path, monkeypatch):
    """No My Macros.md → macro_context null; endpoint still responds 200."""
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    plans_dir = tmp_path / "Meal Plans"
    plans_dir.mkdir()
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server.MEAL_PLANS_PATH", plans_dir)

    response = client.post('/api/suggest-meal', json={
        "week": "2026-W31", "day": "Thursday", "meal": "dinner",
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["macro_context"] is None


# ---- Grid recipe card (Phase 2a) ----

def test_recipe_card_renders_grid(client, tmp_vault, monkeypatch):
    """The card page renders the recipe's grid matrix; heuristic path (no LLM)."""
    from lib import recipe_grid
    # `_anthropic_resolved` matters as much as the client itself: the client is
    # built lazily now, so blanking only the slot lets `_client()` rebuild one
    # from a real ANTHROPIC_API_KEY and dial out. That is what "no LLM" in this
    # docstring is supposed to mean, and without the second line this test was
    # making a live API call.
    monkeypatch.setattr(recipe_grid, "_anthropic_client", None)
    monkeypatch.setattr(recipe_grid, "_anthropic_resolved", True)
    monkeypatch.setattr(recipe_grid, "_group_with_ollama", lambda prompt: None)

    recipes_dir = tmp_vault / "Recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    (recipes_dir / "Brownies.md").write_text(
        '---\ntitle: "Brownies"\nservings: 9\n'
        'nutrition_calories: 180\nnutrition_protein: 3\n'
        'nutrition_carbs: 24\nnutrition_fat: 9\nnutrition_coverage: 0.9\n---\n\n'
        "# Brownies\n\n## Ingredients\n\n| Amount | Unit | Ingredient |\n"
        "|--------|------|------------|\n| 4 | oz | butter |\n| 1 | cup | sugar |\n\n"
        "## Instructions\n\n1. Melt butter\n2. Stir in sugar\n3. Bake\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)

    response = client.get('/recipe-card/Brownies')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Brownies" in body
    assert "recipe-grid" in body            # the matrix table rendered
    assert "Serves" in body and "protein" in body  # macro/servings header
    assert "AI-suggested" in body           # honest review banner


def test_recipe_card_missing_returns_404(client, tmp_path, monkeypatch):
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    response = client.get('/recipe-card/DoesNotExist')
    assert response.status_code == 404


# ---- Print my week (Phase 2b) ----

def test_print_week_page_renders(client, tmp_vault):
    """GET /print/week renders the packet: grid + shopping + prep, for a week."""
    (tmp_vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n\n# My Macros\n")
    recipes = tmp_vault / "Recipes"; recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "Beef Bowl.md").write_text(
        '---\ntitle: "Beef Bowl"\nnutrition_calories: 650\nnutrition_protein: 48\n'
        'nutrition_carbs: 30\nnutrition_fat: 12\nnutrition_coverage: 0.95\nservings: 2\n---\n# Beef Bowl\n')
    plans = tmp_vault / "Meal Plans"; plans.mkdir(parents=True, exist_ok=True)
    (plans / "2026-W31.md").write_text("## Monday (Jul 27)\n\n### dinner\n[[Beef Bowl]]\n\n")

    response = client.get('/print/week?week=2026-W31')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "week-grid" in body
    assert "Shopping list" in body and "Get ahead" in body
    assert "Print this week" in body  # the on-screen print button


def test_print_week_invalid_week_400(client):
    response = client.get('/print/week?week=nope')
    assert response.status_code == 400


def test_print_week_missing_plan_404(client, tmp_vault):
    (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
    response = client.get('/print/week?week=2099-W01')
    assert response.status_code == 404


# ---- Plan-week command center (Sunday shortcut) ----

def test_plan_week_page_planned(client, tmp_vault):
    (tmp_vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n# My Macros\n")
    recipes = tmp_vault / "Recipes"; recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "Beef Bowl.md").write_text(
        '---\ntitle: "Beef Bowl"\nnutrition_calories: 650\nnutrition_protein: 48\n'
        'nutrition_carbs: 30\nnutrition_fat: 12\nnutrition_coverage: 0.95\nservings: 2\n---\n# Beef Bowl\n')
    plans = tmp_vault / "Meal Plans"; plans.mkdir(parents=True, exist_ok=True)
    (plans / "2026-W31.md").write_text("## Monday (Jul 27)\n\n### dinner\n[[Beef Bowl]]\n\n")

    response = client.get('/plan-week?week=2026-W31')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Plan your week" in body
    assert "/meal-planner?week=2026-W31" in body
    assert "/print/week?week=2026-W31" in body


def test_plan_week_unplanned_is_empty_state_not_404(client, tmp_vault):
    (tmp_vault / "Recipes").mkdir(parents=True, exist_ok=True)
    response = client.get('/plan-week?week=2099-W05')
    assert response.status_code == 200  # empty state, not an error
    assert "Plan your week" in response.get_data(as_text=True)


def test_plan_week_invalid_week_400(client):
    assert client.get('/plan-week?week=bogus').status_code == 400


def test_add_records_the_resolved_placement(client, tmp_db, tmp_vault):
    """A resolved location carries its tier; an explicit one is the caller's call."""
    client.post('/api/inventory/add', json={'items': [
        {'name': 'PlacementTestMilk', 'quantity': 1, 'category': 'dairy'},
        {'name': 'PlacementTestHusk', 'quantity': 1, 'category': 'other'},
        {'name': 'PlacementTestPick', 'quantity': 1, 'category': 'dairy',
         'location': 'counter'},
    ], 'match_plan': False})

    rows = {i['name']: i for i in client.get('/api/inventory').get_json()}
    assert rows['PlacementTestMilk']['location_source'] == 'category'
    assert rows['PlacementTestHusk']['location_source'] == 'default'
    assert rows['PlacementTestPick']['location_source'] == 'manual'
    assert rows['PlacementTestPick']['location'] == 'counter'


def test_review_page_shows_storage_location(client):
    """The location, its glyphs, and the unsure marker ship in the page."""
    html = client.get('/review').data
    assert b'LOC_EMOJI' in html
    assert b'locationLabel' in html
    assert b'location_source' in html
    # The freezer glyph must not be the category emoji for `frozen`.
    assert '🥶'.encode() in html


def test_review_page_shows_the_last_used_stamp(client):
    """consume-on-cook writes last_used/use_count; this is the only view that
    reads them. Without this the columns are write-only."""
    html = client.get('/review').data
    assert b'usedLabel' in html
    assert b'last_used' in html


def test_review_page_has_a_location_sort_mode(client):
    """Location ordering and its group headers ship in the page."""
    html = client.get('/review').data
    assert b'value="location"' in html
    assert b'groupHeader' in html
    assert b'placeRows' in html
    assert b'li.group' in html


# ---- Meal macros + fractional serving splits ----

def test_create_meal_accepts_fractional_servings_and_slot(client, tmp_vault, tmp_path, monkeypatch):
    """A 1.5-serving sub-recipe round-trips, and the rollup comes back with it."""
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    _write_recipe(recipes_dir, "Turkey Chili", cal=300, protein=32,
                  coverage=0.95, servings=4, items=["turkey", "beans"])
    _write_recipe(recipes_dir, "Cornbread", cal=200, protein=6,
                  coverage=0.95, servings=8, items=["cornmeal"])
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)

    response = client.post('/api/meals', json={
        "name": "Chili Bowl Lunch",
        "slot": "lunch",
        "sub_recipes": [
            {"recipe": "Turkey Chili", "servings": 1.5},
            {"recipe": "Cornbread", "servings": 0.5},
        ],
    })
    assert response.status_code == 201
    created = response.get_json()
    assert created["slot"] == "lunch"
    assert [s["servings"] for s in created["sub_recipes"]] == [1.5, 0.5]
    assert created["nutrition"]["calories"] == pytest.approx(300 * 1.5 + 200 * 0.5)
    assert created["nutrition"]["incomplete"] is False

    # ...and survives the round trip through the .meal.md file
    fetched = client.get('/api/meals/Chili Bowl Lunch').get_json()
    assert [s["servings"] for s in fetched["sub_recipes"]] == [1.5, 0.5]
    assert fetched["slot"] == "lunch"
    assert fetched["nutrition"]["protein"] == pytest.approx(32 * 1.5 + 6 * 0.5)


def test_meal_nutrition_names_untrusted_sub_recipes(client, tmp_vault, tmp_path, monkeypatch):
    """An untrusted sub-recipe is excluded and named, not counted as zero."""
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    _write_recipe(recipes_dir, "Turkey Chili", cal=300, protein=32,
                  coverage=0.95, servings=4, items=["turkey"])
    (recipes_dir / "Greek Yogurt.md").write_text(
        '---\ntitle: "Greek Yogurt"\nnutrition_calories: 8000\n'
        'nutrition_protein: 900\nnutrition_coverage: 0.95\n---\n\n# Greek Yogurt\n'
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)

    client.post('/api/meals', json={
        "name": "Sketchy Bowl",
        "sub_recipes": [
            {"recipe": "Turkey Chili"},
            {"recipe": "Greek Yogurt", "servings": 1.5},
        ],
    })
    nutrition = client.get('/api/meals/Sketchy Bowl').get_json()["nutrition"]
    assert nutrition["calories"] == 300
    assert nutrition["incomplete"] is True
    assert nutrition["excluded"] == ["Greek Yogurt"]


def test_create_meal_rejects_non_positive_servings(client, tmp_vault):
    response = client.post('/api/meals', json={
        "name": "Zero Meal",
        "sub_recipes": [{"recipe": "Turkey Chili", "servings": 0}],
    })
    assert response.status_code == 400
    assert "servings" in response.get_json()["error"].lower()


def test_create_meal_rejects_unparseable_servings(client, tmp_vault):
    response = client.post('/api/meals', json={
        "name": "Wordy Meal",
        "sub_recipes": [{"recipe": "Turkey Chili", "servings": "lots"}],
    })
    assert response.status_code == 400
    assert "servings" in response.get_json()["error"].lower()


def test_create_meal_rejects_unknown_slot(client, tmp_vault):
    response = client.post('/api/meals', json={
        "name": "Brunchy Meal",
        "slot": "brunch",
        "sub_recipes": [{"recipe": "Turkey Chili"}],
    })
    assert response.status_code == 400
    assert "slot" in response.get_json()["error"].lower()


def test_meal_defaults_to_dinner_slot(client, tmp_vault, tmp_path, monkeypatch):
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", tmp_path)
    response = client.post('/api/meals', json={
        "name": "Slotless Meal",
        "sub_recipes": [{"recipe": "Turkey Chili"}],
    })
    assert response.status_code == 201
    assert response.get_json()["slot"] == "dinner"


def test_update_meal_rejection_does_not_delete_the_meal(client, tmp_vault, tmp_path, monkeypatch):
    """A 400 on a rename must not take the existing file with it.

    The rename used to delete the old file before validating the payload, so an
    invalid body destroyed the meal and saved nothing in its place.
    """
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", tmp_path)
    client.post('/api/meals', json={
        "name": "Keeper", "sub_recipes": [{"recipe": "Turkey Chili"}],
    })

    response = client.put('/api/meals/Keeper', json={
        "name": "Renamed", "sub_recipes": [{"recipe": "Turkey Chili", "servings": -1}],
    })
    assert response.status_code == 400
    assert client.get('/api/meals/Keeper').status_code == 200


def test_update_meal_preserves_slot_when_omitted(client, tmp_vault, tmp_path, monkeypatch):
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", tmp_path)
    client.post('/api/meals', json={
        "name": "Lunchy", "slot": "lunch",
        "sub_recipes": [{"recipe": "Turkey Chili"}],
    })
    updated = client.put('/api/meals/Lunchy', json={
        "description": "now with a description",
    }).get_json()
    assert updated["slot"] == "lunch"


def test_macro_targets_endpoint_defaults(client, tmp_vault):
    """No My Macros.md → null daily target, default shares, no normalisation."""
    body = client.get('/api/macro-targets').get_json()
    assert body["daily"] is None
    assert body["slot_shares"] == {
        "breakfast": 0.25, "lunch": 0.3, "dinner": 0.35, "snack": 0.1,
    }
    assert body["slot_shares_normalized"] is False


def test_macro_targets_endpoint_reads_shares(client, tmp_vault):
    (tmp_vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n"
        "share_breakfast: 25\nshare_lunch: 30\nshare_dinner: 35\nshare_snack: 10\n---\n"
    )
    body = client.get('/api/macro-targets').get_json()
    assert body["daily"]["protein"] == 190
    assert body["slot_shares"]["lunch"] == pytest.approx(0.30)
    assert body["slot_shares_normalized"] is True, "percentages were rescaled — say so"


def test_meal_plan_get_ships_slot_and_nutrition_for_meal_entries(
        client, tmp_vault, tmp_path, monkeypatch):
    """The planner loads meals and the plan concurrently, so the plan must carry
    a meal's macros itself rather than relying on the meal index being ready."""
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    _write_recipe(recipes_dir, "Turkey Chili", cal=300, protein=32,
                  coverage=0.95, servings=4, items=["turkey"])
    plans_dir = tmp_path / "Meal Plans"
    plans_dir.mkdir()
    (plans_dir / "2026-W31.md").write_text(
        "## Thursday (Jul 31)\n\n### Lunch\n[[Meal: Chili Bowl Lunch]]\n\n### Dinner\n\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server.MEAL_PLANS_PATH", plans_dir)
    client.post('/api/meals', json={
        "name": "Chili Bowl Lunch", "slot": "lunch",
        "sub_recipes": [{"recipe": "Turkey Chili", "servings": 1.5}],
    })

    days = client.get('/api/meal-plan/2026-W31').get_json()["days"]
    thursday = next(d for d in days if d["day"] == "Thursday")
    assert thursday["lunch"]["kind"] == "meal"
    assert thursday["lunch"]["slot"] == "lunch"
    assert thursday["lunch"]["nutrition"]["calories"] == pytest.approx(450)
    assert thursday["lunch"]["sub_recipes"] == [
        {"recipe": "Turkey Chili", "servings": 1.5}
    ]


def test_suggest_meal_counts_a_planned_meal_bundle(client, tmp_vault, tmp_path, monkeypatch):
    """REGRESSION: a `[[Meal: X]]` entry contributed zero kcal to the day.

    day_macro_gap resolves each planned name against Recipes/, where a meal
    bundle has no file — so the suggester saw an empty day and steered every
    macro-aware suggestion wrong by a whole meal. The endpoint now flattens meal
    entries to their sub-recipes before building planned_meals.
    """
    (tmp_vault / "My Macros.md").write_text(
        "---\ncalories: 2300\nprotein: 190\ncarbs: 228\nfat: 70\n---\n"
    )
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir()
    _write_recipe(recipes_dir, "Turkey Chili", cal=300, protein=32,
                  coverage=0.95, servings=4, items=["turkey", "beans"])
    _write_recipe(recipes_dir, "Beef Power Bowl", cal=650, protein=48,
                  coverage=0.95, servings=3, items=["beef", "quinoa"])
    plans_dir = tmp_path / "Meal Plans"
    plans_dir.mkdir()
    (plans_dir / "2026-W31.md").write_text(
        "## Thursday (Jul 31)\n\n### Lunch\n[[Meal: Chili Bowl Lunch]]\n\n### Dinner\n\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server.MEAL_PLANS_PATH", plans_dir)
    client.post('/api/meals', json={
        "name": "Chili Bowl Lunch", "slot": "lunch",
        "sub_recipes": [{"recipe": "Turkey Chili", "servings": 1.5}],
    })

    response = client.post('/api/suggest-meal', json={
        "week": "2026-W31", "day": "Thursday", "meal": "dinner",
    })
    assert response.status_code == 200
    current = response.get_json()["macro_context"]["current"]
    assert current["protein"] == pytest.approx(32 * 1.5)
    assert current["calories"] == pytest.approx(300 * 1.5)


# ---- Shopping list credits inventory on the one-shot trigger ----

def _plan_and_recipe(tmp_path, monkeypatch, ingredients):
    """A one-recipe week wired into both the API and the generator."""
    import lib.shopping_list_generator as slg

    plans = tmp_path / "Meal Plans"
    plans.mkdir(exist_ok=True)
    (plans / "2026-W31.md").write_text("## Monday (Jul 27)\n### Dinner\n[[Test Bake]]\n")
    lists = tmp_path / "Shopping Lists"
    lists.mkdir(exist_ok=True)
    monkeypatch.setattr(slg, "MEAL_PLANS_PATH", plans)
    monkeypatch.setattr(slg, "SHOPPING_LISTS_PATH", lists)
    monkeypatch.setattr("api_server.SHOPPING_LISTS_PATH", lists)
    monkeypatch.setattr(slg, "load_recipe_ingredients", lambda name: (ingredients, None))
    return lists


def test_generate_shopping_list_omits_what_you_already_have(
        client, tmp_vault, tmp_path, monkeypatch):
    """REGRESSION: the phone trigger passed no pantry, so it bought what you owned.

    The reported symptom was garlic salt, eggs and brown sugar on the list when
    all three were in the kitchen.
    """
    from lib import pantry as pantry_module

    lists = _plan_and_recipe(tmp_path, monkeypatch, [
        {"amount": "1", "unit": "tsp", "item": "garlic salt"},
        {"amount": "2", "unit": "cup", "item": "flour"},
    ])
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "garlic salt", "amount": "3", "unit": "tsp"}])

    response = client.post('/generate-shopping-list', json={"week": "2026-W31"})
    assert response.status_code == 200

    written = (lists / "2026-W31.md").read_text()
    buy_lines = [ln for ln in written.split("\n") if ln.startswith("- [ ] ")]
    assert any("flour" in ln for ln in buy_lines)
    assert not any("garlic salt" in ln for ln in buy_lines), \
        "you own the garlic salt — it must not be on the buy list"


def test_generate_shopping_list_annotates_what_it_credited(
        client, tmp_vault, tmp_path, monkeypatch):
    """Credited stock is named under 'Already have' — omitted, not silently vanished."""
    from lib import pantry as pantry_module

    lists = _plan_and_recipe(tmp_path, monkeypatch, [
        {"amount": "1", "unit": "cup", "item": "brown sugar"},
    ])
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "brown sugar", "amount": "5", "unit": "cup"}])

    client.post('/generate-shopping-list', json={"week": "2026-W31"})
    written = (lists / "2026-W31.md").read_text()

    assert "## Already have" in written
    assert "brown sugar — in stock, 1 cup needed" in written


def test_credited_items_are_not_checkboxes(client, tmp_vault, tmp_path, monkeypatch):
    """The 'Already have' notes must never be `- [ ]` lines.

    parse_shopping_list_file collects every unchecked box in the file regardless
    of section, so a checkbox here would be sent to Reminders as something to buy
    and would return as a phantom "manual item" on the next regeneration.
    """
    from lib import pantry as pantry_module
    from lib.shopping_list_generator import parse_shopping_list_file

    lists = _plan_and_recipe(tmp_path, monkeypatch, [
        {"amount": "1", "unit": "cup", "item": "brown sugar"},
        {"amount": "2", "unit": "cup", "item": "flour"},
    ])
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "brown sugar", "amount": "5", "unit": "cup"}])

    client.post('/generate-shopping-list', json={"week": "2026-W31"})

    unchecked = parse_shopping_list_file("2026-W31")["items"]
    assert any("flour" in i for i in unchecked)
    assert not any("brown sugar" in i for i in unchecked), \
        "a credited note must not read as an item to buy"

    # ...and regenerating must not resurrect it as a manual addition
    client.post('/generate-shopping-list', json={"week": "2026-W31"})
    written = (lists / "2026-W31.md").read_text()
    assert written.count("brown sugar") == 1


def test_generate_shopping_list_never_decrements_inventory(
        client, tmp_vault, tmp_path, monkeypatch):
    """Annotate, don't decrement — this trigger has no confirmation step.

    Stock is only ever spent through /api/shopping-list/confirm's decisions.
    """
    from lib import pantry as pantry_module

    _plan_and_recipe(tmp_path, monkeypatch, [
        {"amount": "1", "unit": "cup", "item": "brown sugar"},
    ])
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "brown sugar", "amount": "5", "unit": "cup"}])

    def explode(*args, **kwargs):
        raise AssertionError("generate must not apply pantry decisions")

    monkeypatch.setattr(pantry_module, "apply_decisions", explode)
    monkeypatch.setattr(pantry_module, "save_pantry", explode)

    assert client.post('/generate-shopping-list',
                       json={"week": "2026-W31"}).status_code == 200


def test_generate_shopping_list_use_pantry_false_keeps_raw_demand(
        client, tmp_vault, tmp_path, monkeypatch):
    """The opt-out returns the pre-fix behaviour: every ingredient, no notes."""
    from lib import pantry as pantry_module

    lists = _plan_and_recipe(tmp_path, monkeypatch, [
        {"amount": "1", "unit": "cup", "item": "brown sugar"},
    ])
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "brown sugar", "amount": "5", "unit": "cup"}])

    client.post('/generate-shopping-list',
                json={"week": "2026-W31", "use_pantry": False})
    written = (lists / "2026-W31.md").read_text()

    assert "- [ ] 1 cup brown sugar" in written
    assert "## Already have" not in written


# ---- Discoverability: the board and the review page explain themselves ----

def _outside_style(body: str, needle: str) -> bool:
    """Is `needle` in real markup, not buried inside an open <style> block?

    Same check as tests/test_claude_bar.py: a string assertion alone passed for
    months while /meal-planner rendered nothing, because the snippet had been
    spliced inside <style>.
    """
    at = body.index(needle)
    return body.rfind('<style', 0, at) <= body.rfind('</style>', 0, at)


def test_planner_explains_what_a_serving_chip_is(client):
    """The board's core object had no on-screen explanation at all."""
    body = client.get('/meal-planner').get_data(as_text=True)
    assert 'id="board-help"' in body
    assert 'chips are servings' in body
    assert _outside_style(body, 'chips are servings')


def test_planner_board_help_is_board_mode_only(client):
    """A legend for chips that don't exist yet is noise on a legacy week."""
    body = client.get('/meal-planner').get_data(as_text=True)
    assert 'body.board-mode .board-help' in body, 'help must be gated on board mode'
    assert '.board-help {' in body and 'display: none;' in body


def test_planner_names_all_three_chip_destinations(client):
    """Day, freezer, bin — the freezer was the one nobody could find."""
    body = client.get('/meal-planner').get_data(as_text=True)
    help_text = body[body.index('id="board-help"'):body.index('id="board-help"') + 600]
    assert 'Freezer' in help_text
    assert '🗑' in help_text
    assert 'another day' in help_text


def test_freezer_empty_state_says_how_to_fill_it(client):
    """'Freezer is empty' was true and useless — dragging a chip isn't guessable."""
    body = client.get('/meal-planner').get_data(as_text=True)
    assert 'Freezer is empty.' in body
    assert 'freezer-empty-how' in body
    assert 'drag a leftover' in body


def test_nutrition_review_states_the_job_and_the_stakes(client):
    """The page ranked untrustworthy recipes and never said what to do or why."""
    body = client.get('/nutrition-review').get_data(as_text=True)
    assert 'class="page-lead"' in body
    assert _outside_style(body, 'class="page-lead"')
    # what the flag costs you, and that a row is the way in
    assert 'skipped' in body
    assert 'click a row to fix it' in body


def test_nutrition_review_explains_negligible(client):
    """'Negligible' is jargon for 'count this as zero calories, forever'."""
    body = client.get('/nutrition-review').get_data(as_text=True)
    assert 'no meaningful calories' in body
    assert 'Remembered for every recipe' in body


# ---- Recipe page marks what you don't have in stock ----

def _stock_recipe(tmp_path, monkeypatch, rows="| 2 | lb | chicken thighs |\n| 1 | tsp | saffron |\n"):
    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir(exist_ok=True)
    (recipes_dir / "Stock Test.md").write_text(
        '---\ntitle: "Stock Test"\nservings: 4\n---\n\n# Stock Test\n\n## Ingredients\n\n'
        "| Amount | Unit | Ingredient |\n|---|---|---|\n" + rows +
        "\n## Instructions\n\n1. Cook.\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server._RECIPES_ENV_AT_IMPORT", os.environ.get("KITCHENOS_VAULT"))
    return recipes_dir


def test_recipe_detail_marks_ingredients_you_do_not_have(client, tmp_path, monkeypatch):
    from lib import pantry as pantry_module

    _stock_recipe(tmp_path, monkeypatch)
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "Chicken thighs", "amount": "3", "unit": "lb"}])

    data = client.get('/api/recipes/Stock Test').get_json()
    by_item = {i["item"]: i for i in data["ingredients"]}

    assert by_item["chicken thighs"]["in_stock"] is True
    assert by_item["chicken thighs"]["have"] == "3 lb"
    assert by_item["saffron"]["in_stock"] is False
    assert by_item["saffron"]["have"] is None


def test_empty_inventory_leaves_ingredients_unmarked(client, tmp_path, monkeypatch):
    """None, not False — an empty inventory says nothing about your kitchen.

    Marking everything "not in stock" would read as a claim about the kitchen
    rather than about the absence of data.
    """
    from lib import pantry as pantry_module

    _stock_recipe(tmp_path, monkeypatch)
    monkeypatch.setattr(pantry_module, "load_pantry", lambda: [])

    data = client.get('/api/recipes/Stock Test').get_json()
    assert all(i["in_stock"] is None for i in data["ingredients"])


def test_stock_check_failure_does_not_break_the_recipe(client, tmp_path, monkeypatch):
    """A DB that won't open degrades to an uncoloured list, not a 500."""
    from lib import pantry as pantry_module

    _stock_recipe(tmp_path, monkeypatch)

    def boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(pantry_module, "load_pantry", boom)

    response = client.get('/api/recipes/Stock Test')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["ingredients"]) == 2
    assert all(i["in_stock"] is None for i in data["ingredients"])


def test_stock_annotation_preserves_the_original_ingredient_fields(client, tmp_path, monkeypatch):
    from lib import pantry as pantry_module

    _stock_recipe(tmp_path, monkeypatch)
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "Chicken thighs", "amount": "3", "unit": "lb"}])

    first = client.get('/api/recipes/Stock Test').get_json()["ingredients"][0]
    assert first["item"] == "chicken thighs"
    assert first["amount"] == "2"
    assert first["unit"] == "lb"


def test_grouped_ingredient_sections_are_stock_checked_too(client, tmp_path, monkeypatch):
    """The sub-heading fix and this feature have to compose."""
    from lib import pantry as pantry_module

    recipes_dir = tmp_path / "Recipes"
    recipes_dir.mkdir(exist_ok=True)
    (recipes_dir / "Stock Test.md").write_text(
        '---\ntitle: "Stock Test"\n---\n\n## Ingredients\n\n'
        "| Amount | Unit | Ingredient |\n|---|---|---|\n| 2 | lb | chicken thighs |\n\n"
        "### For the rub\n\n"
        "| Amount | Unit | Ingredient |\n|---|---|---|\n| 1 | tsp | saffron |\n\n"
        "## Instructions\n\n1. Cook.\n"
    )
    monkeypatch.setattr("api_server.OBSIDIAN_RECIPES_PATH", recipes_dir)
    monkeypatch.setattr("api_server._RECIPES_ENV_AT_IMPORT", os.environ.get("KITCHENOS_VAULT"))
    monkeypatch.setattr(pantry_module, "load_pantry",
                        lambda: [{"item": "Chicken thighs", "amount": "3", "unit": "lb"}])

    items = {i["item"]: i["in_stock"]
             for i in client.get('/api/recipes/Stock Test').get_json()["ingredients"]}
    assert items == {"chicken thighs": True, "saffron": False}
