"""Tests for API endpoints."""

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
