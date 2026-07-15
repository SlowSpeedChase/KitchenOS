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
