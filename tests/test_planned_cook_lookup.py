"""AppEntity exact lookup: isolated ledger, authenticated, no regeneration."""
import pytest
import api_server
from lib import serving_ledger as sl

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('KITCHENOS_API_TOKEN', 'test-secret')
    monkeypatch.setattr(api_server, '_regen_weeks', lambda *a: pytest.fail('GET regenerated week'))
    return api_server.app.test_client()

def test_lookup_uses_exact_id_with_duplicate_recipe_names(client):
    a=sl.create_cook(recipe='Same recipe',week='2026-W41',servings_produced=4)
    b=sl.create_cook(recipe='Same recipe',week='2026-W42',servings_produced=2)
    for cook in [a,b]:
        response=client.get(f"/api/cooks/{cook['id']}")
        assert response.status_code==200
        assert response.json==sl.get_cook(cook['id'])
    assert a['id']!=b['id']

def test_missing_is_404_and_remote_lookup_requires_token(client):
    remote={'environ_base': {'REMOTE_ADDR':'100.64.0.5'}}
    assert client.get('/api/cooks/999999').status_code==404
    assert client.get('/api/cooks/999999',**remote).status_code==401
    assert client.get('/api/cooks/999999',headers={'Authorization':'Bearer test-secret'},**remote).status_code==404

def test_lookup_exposes_current_cooked_and_bundle_status_without_mutation(client):
    from lib import inventory_db
    cook=sl.create_cook(recipe='Same recipe',week='2026-W41',servings_produced=4)
    with inventory_db.write_transaction() as conn:
        conn.execute("UPDATE cooks SET cooked_at='2026-10-09',bundle_id='plate' WHERE id=?",(cook['id'],))
    before=sl.get_cook(cook['id'])
    response=client.get(f"/api/cooks/{cook['id']}")
    assert response.status_code==200
    assert response.json==before
    assert sl.get_cook(cook['id'])==before
