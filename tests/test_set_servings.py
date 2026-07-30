"""Tests for POST /api/recipes/<name>/servings.

The bug this endpoint exists to fix: the nutrition engine derives per-serving
macros as ``total / servings``, and when ``servings`` is missing it falls back to
1 and publishes the **whole-batch** total. The recipe page then showed that under
the same heading as every genuinely per-serving recipe — a tray of yogurt pops
read as a 1,339-calorie serving.
"""

import pytest

from api_server import app


RECIPE = """---
title: "Test Pops"
servings: null
servings_inferred: true
servings_needs_review: true
nutrition_calories: 1200
---
# Test Pops

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | cup | plain yogurt |
"""


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def recipe(tmp_path, monkeypatch):
    """A recipe file the endpoint is allowed to rewrite."""
    recipes = tmp_path / "Recipes"
    recipes.mkdir()
    path = recipes / "Test Pops.md"
    path.write_text(RECIPE, encoding="utf-8")
    monkeypatch.setattr("lib.paths.recipes_dir", lambda: recipes)
    monkeypatch.setattr("api_server.paths.recipes_dir", lambda: recipes)
    # Keep the nutrition engine out of these tests: they are about the write and
    # the validation, and a real recompute needs the food DB.
    monkeypatch.setattr("api_server._recompute_and_write",
                        lambda name: (None, "stubbed"))
    monkeypatch.setattr("api_server.create_backup", lambda p: None)
    return path


class TestValidation:
    @pytest.mark.parametrize("body", [
        {}, {"servings": None}, {"servings": "six"}, {"servings": ""},
    ])
    def test_non_numeric_is_rejected(self, client, recipe, body):
        r = client.post("/api/recipes/Test Pops/servings", json=body)
        assert r.status_code == 400
        assert "whole number" in r.get_json()["error"]

    @pytest.mark.parametrize("n", [0, -1, 201, 10_000])
    def test_out_of_range_is_rejected(self, client, recipe, n):
        r = client.post("/api/recipes/Test Pops/servings", json={"servings": n})
        assert r.status_code == 400
        assert "between 1 and 200" in r.get_json()["error"]

    def test_a_rejected_write_leaves_the_file_alone(self, client, recipe):
        before = recipe.read_text()
        client.post("/api/recipes/Test Pops/servings", json={"servings": 0})
        assert recipe.read_text() == before

    def test_unknown_recipe_is_404(self, client, recipe):
        r = client.post("/api/recipes/Nope/servings", json={"servings": 4})
        assert r.status_code == 404

    def test_path_traversal_is_refused(self, client, recipe):
        r = client.post("/api/recipes/..%2f..%2fetc%2fpasswd/servings",
                        json={"servings": 4})
        assert r.status_code == 404


class TestWrite:
    def test_servings_is_written(self, client, recipe):
        r = client.post("/api/recipes/Test Pops/servings", json={"servings": 6})
        assert r.status_code == 200
        assert r.get_json()["servings"] == 6
        assert "servings: 6" in recipe.read_text()

    def test_a_typed_count_clears_the_inference_flags(self, client, recipe):
        """A human typing the number is a measurement, not an estimate.

        backfill_servings.py leaves servings_inferred/servings_needs_review on a
        guess; leaving them after a human correction would keep the recipe
        flagged for review forever.
        """
        assert "servings_needs_review: true" in recipe.read_text()
        client.post("/api/recipes/Test Pops/servings", json={"servings": 6})
        after = recipe.read_text()
        assert "servings_inferred" not in after
        assert "servings_needs_review" not in after

    def test_float_input_is_coerced_to_a_whole_count(self, client, recipe):
        r = client.post("/api/recipes/Test Pops/servings", json={"servings": 6.0})
        assert r.status_code == 200
        assert r.get_json()["servings"] == 6

    def test_recompute_failure_still_reports_the_saved_count(self, client, recipe):
        """The count is saved even if macros can't be recomputed — say so."""
        body = client.post("/api/recipes/Test Pops/servings",
                           json={"servings": 6}).get_json()
        assert body["servings"] == 6
        assert body["warning"] == "stubbed"
        assert body["nutrition"] is None


class TestRecompute:
    def test_macros_are_recomputed_against_the_new_count(self, client, recipe,
                                                         monkeypatch):
        """Stored macros were computed against the OLD count, so they are wrong
        the instant it changes — the page must not show batch totals under a
        now-correct 'per serving' label."""
        calls = []

        class _Result:
            per_serving = type("N", (), {"to_dict": lambda s: {"calories": 200}})()
            coverage, confidence, unmatched = 1.0, 0.9, []
            needs_review, sanity_flags = False, []

        def fake(name):
            calls.append(name)
            return _Result(), None

        monkeypatch.setattr("api_server._recompute_and_write", fake)
        r = client.post("/api/recipes/Test Pops/servings", json={"servings": 6})

        assert calls == ["Test Pops"], "did not recompute after changing servings"
        assert r.get_json()["per_serving"] == {"calories": 200}

    def test_recompute_runs_after_the_write_not_before(self, client, recipe,
                                                       monkeypatch):
        """Order matters: the engine reads `servings` back off the file."""
        seen = {}

        def fake(name):
            seen["servings_on_disk"] = "servings: 6" in recipe.read_text()
            return None, "stubbed"

        monkeypatch.setattr("api_server._recompute_and_write", fake)
        client.post("/api/recipes/Test Pops/servings", json={"servings": 6})
        assert seen["servings_on_disk"] is True
