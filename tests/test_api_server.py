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
