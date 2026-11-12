"""Contract for the kitchen block Selene's morning briefing fetches."""
from datetime import date

import pytest

from api_server import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class TestKitchenBriefingEndpoint:
    def test_returns_the_documented_shape(self, client, monkeypatch):
        from lib import kitchen_briefing
        monkeypatch.setattr(kitchen_briefing, "build", lambda today=None: {
            "date": "2026-08-22", "week": "2026-W34", "plate": [],
            "next": None, "at_risk": [], "look": [], "degraded": [],
        })
        response = client.get("/api/briefing/kitchen")
        assert response.status_code == 200
        assert set(response.get_json()) == {
            "date", "week", "plate", "next", "at_risk", "look", "degraded"}

    def test_date_param_is_passed_through(self, client, monkeypatch):
        from lib import kitchen_briefing
        seen = {}

        def fake_build(today=None):
            seen["today"] = today
            return {"date": "x", "week": "x", "plate": [], "next": None,
                    "at_risk": [], "look": [], "degraded": []}

        monkeypatch.setattr(kitchen_briefing, "build", fake_build)
        client.get("/api/briefing/kitchen?date=2026-08-22")
        assert seen["today"] == date(2026, 8, 22)

    def test_a_bad_date_is_rejected(self, client):
        response = client.get("/api/briefing/kitchen?date=not-a-date")
        assert response.status_code == 400

    def test_never_calls_the_regenerating_extractor(self, client, monkeypatch):
        """The 6am digest cannot block on an LLM classification pass.

        A raising fake is useless here: kitchen_briefing._safe catches bare
        Exception, so an AssertionError from inside a seam becomes a quiet
        `degraded` entry and a 200. Record instead, and assert nothing degraded.
        """
        from lib import task_extractor

        calls = []
        monkeypatch.setattr(task_extractor, "extract_tasks",
                            lambda *a, **kw: calls.append(1))

        response = client.get("/api/briefing/kitchen")
        assert response.status_code == 200
        assert calls == []
        assert response.get_json()["degraded"] == []
