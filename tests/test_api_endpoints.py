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
