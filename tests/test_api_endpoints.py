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
