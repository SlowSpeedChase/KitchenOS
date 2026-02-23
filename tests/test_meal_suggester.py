"""Tests for meal suggestion engine."""

import json
from pathlib import Path

from lib.meal_suggester import normalize_ingredient, score_overlap, rank_candidates


class TestPantryStaples:
    """Test pantry staples config loading."""

    def test_loads_pantry_staples(self):
        """Pantry staples config loads as a list of strings."""
        config_path = Path(__file__).parent.parent / "config" / "pantry_staples.json"
        with open(config_path) as f:
            staples = json.load(f)
        assert isinstance(staples, list)
        assert "salt" in staples
        assert "olive oil" in staples
        assert len(staples) >= 10


class TestNormalizeIngredient:
    """Test ingredient normalization for matching."""

    def test_lowercase(self):
        assert normalize_ingredient("Chicken Thighs") == "chicken thighs"

    def test_strips_preparation(self):
        assert normalize_ingredient("diced tomatoes") == "tomatoes"
        assert normalize_ingredient("minced garlic") == "garlic"
        assert normalize_ingredient("finely chopped onion") == "onion"

    def test_strips_adjectives(self):
        assert normalize_ingredient("fresh basil") == "basil"
        assert normalize_ingredient("large eggs") == "eggs"
        assert normalize_ingredient("boneless skinless chicken thighs") == "chicken thighs"

    def test_passthrough_simple(self):
        assert normalize_ingredient("rice") == "rice"
        assert normalize_ingredient("soy sauce") == "soy sauce"


class TestScoreOverlap:
    """Test ingredient overlap scoring."""

    def test_full_overlap(self):
        """Recipe using only planned ingredients scores 1.0."""
        recipe_items = ["chicken", "rice"]
        planned_items = {"chicken", "rice", "broccoli"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 1.0
        assert shared == {"chicken", "rice"}

    def test_no_overlap(self):
        """Recipe sharing nothing scores 0.0."""
        recipe_items = ["salmon", "asparagus"]
        planned_items = {"chicken", "rice"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.0
        assert shared == set()

    def test_partial_overlap(self):
        """Score proportional to shared ingredients."""
        recipe_items = ["chicken", "rice", "soy sauce", "ginger"]
        planned_items = {"chicken", "rice"}
        pantry = set()
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.5
        assert shared == {"chicken", "rice"}

    def test_pantry_staples_excluded(self):
        """Pantry staples don't count toward total."""
        recipe_items = ["chicken", "salt", "pepper", "olive oil"]
        planned_items = {"chicken"}
        pantry = {"salt", "pepper", "olive oil"}
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 1.0
        assert shared == {"chicken"}

    def test_all_pantry_returns_zero(self):
        """Recipe with only pantry items scores 0.0."""
        recipe_items = ["salt", "pepper", "water"]
        planned_items = {"chicken"}
        pantry = {"salt", "pepper", "water"}
        score, shared = score_overlap(recipe_items, planned_items, pantry)
        assert score == 0.0


class TestRankCandidates:
    """Test ranking recipes by overlap with planned meals."""

    def test_ranks_by_score_descending(self):
        """Highest overlap first."""
        candidates = [
            {"name": "A", "ingredient_items": ["salmon", "lemon"]},
            {"name": "B", "ingredient_items": ["chicken", "rice", "soy sauce"]},
            {"name": "C", "ingredient_items": ["chicken", "yogurt"]},
        ]
        planned_items = {"chicken", "yogurt", "rice"}
        pantry = set()
        ranked = rank_candidates(candidates, planned_items, pantry, limit=10)
        assert ranked[0]["name"] == "C"  # 2/2 = 1.0
        assert ranked[1]["name"] == "B"  # 2/3 = 0.67
        assert ranked[2]["name"] == "A"  # 0/2 = 0.0

    def test_excludes_already_planned(self):
        """Recipes already in the meal plan are not suggested."""
        candidates = [
            {"name": "Chicken Shawarma", "ingredient_items": ["chicken", "yogurt"]},
            {"name": "Chicken Gyros", "ingredient_items": ["chicken", "yogurt", "pita"]},
        ]
        planned_items = {"chicken", "yogurt"}
        pantry = set()
        planned_names = {"Chicken Shawarma"}
        ranked = rank_candidates(candidates, planned_items, pantry, limit=10, exclude_names=planned_names)
        assert len(ranked) == 1
        assert ranked[0]["name"] == "Chicken Gyros"

    def test_respects_limit(self):
        """Only returns top N candidates."""
        candidates = [
            {"name": f"Recipe {i}", "ingredient_items": ["chicken"]}
            for i in range(20)
        ]
        planned_items = {"chicken"}
        pantry = set()
        ranked = rank_candidates(candidates, planned_items, pantry, limit=5)
        assert len(ranked) == 5


from unittest.mock import patch, MagicMock
import requests


class TestOllamaNormalize:
    """Test Ollama-based ingredient normalization."""

    @patch("lib.meal_suggester.requests.post")
    def test_normalizes_via_ollama(self, mock_post):
        """Ollama returns normalized ingredient names."""
        from lib.meal_suggester import normalize_ingredients_ollama

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": '["chicken", "tomato", "greek yogurt"]'
        }
        mock_post.return_value = mock_response

        result = normalize_ingredients_ollama(
            ["boneless skinless chicken thighs", "fresh diced tomatoes", "low-fat Greek yogurt"]
        )
        assert result == ["chicken", "tomato", "greek yogurt"]

    @patch("lib.meal_suggester.requests.post")
    def test_falls_back_on_ollama_error(self, mock_post):
        """On Ollama failure, falls back to simple normalization."""
        from lib.meal_suggester import normalize_ingredients_ollama

        mock_post.side_effect = requests.exceptions.ConnectionError("Ollama down")

        result = normalize_ingredients_ollama(["fresh diced tomatoes", "large eggs"])
        assert result == ["tomatoes", "eggs"]


class TestClaudeSuggest:
    """Test Claude API suggestion call."""

    @patch("lib.meal_suggester.anthropic_client")
    def test_returns_suggestion_from_claude(self, mock_client):
        """Claude returns a recipe suggestion with reason."""
        from lib.meal_suggester import suggest_with_claude

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"name": "Chicken Fried Rice", "reason": "Uses leftover chicken from Monday", "is_new_idea": false, "new_ingredients_needed": ["rice", "soy sauce", "eggs"]}')]
        mock_client.messages.create.return_value = mock_message

        result = suggest_with_claude(
            planned_meals=[
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ],
            candidates=[
                {"name": "Chicken Fried Rice", "score": 0.4,
                 "shared_ingredients": ["chicken"],
                 "ingredient_items": ["chicken", "rice", "soy sauce", "eggs"]},
            ],
            day="Tuesday",
            meal="dinner",
        )
        assert result["name"] == "Chicken Fried Rice"
        assert result["is_new_idea"] is False

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_returns_none_when_no_api_key(self):
        """Returns None if no Anthropic API key configured."""
        from lib.meal_suggester import suggest_with_claude

        result = suggest_with_claude(
            planned_meals=[{"day": "Monday", "meal": "dinner", "name": "X", "ingredients": ["a"]}],
            candidates=[{"name": "Y", "score": 0.3, "shared_ingredients": ["a"], "ingredient_items": ["a", "b"]}],
            day="Tuesday",
            meal="dinner",
        )
        assert result is None


class TestClaudeSuggestEmptyWeek:
    """Test Claude suggestion when no meals planned yet."""

    @patch("lib.meal_suggester.anthropic_client")
    def test_suggests_starting_recipe(self, mock_client):
        """When week is empty, suggests a good starting recipe."""
        from lib.meal_suggester import suggest_for_empty_week

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"name": "Chicken Shawarma", "reason": "Versatile chicken and yogurt base for multiple meals", "is_new_idea": false, "new_ingredients_needed": []}')]
        mock_client.messages.create.return_value = mock_message

        result = suggest_for_empty_week(
            recipe_summaries=[
                {"name": "Chicken Shawarma", "cuisine": "Middle Eastern", "protein": "chicken"},
                {"name": "Pasta Aglio", "cuisine": "Italian", "protein": "none"},
            ],
            day="Monday",
            meal="dinner",
        )
        assert result["name"] == "Chicken Shawarma"
        assert result["is_new_idea"] is False


import tempfile


class TestSuggestMeal:
    """Test the top-level suggest_meal orchestrator."""

    def _make_recipes_dir(self, tmpdir, recipes):
        """Helper: write recipe files to a temp dir and return Path."""
        recipes_dir = Path(tmpdir)
        for name, ingredients in recipes.items():
            rows = "".join(
                f"| 1 | whole | {item} |\n" for item in ingredients
            )
            content = (
                f'---\ntitle: "{name}"\ncuisine: "test"\nprotein: "test"\n---\n\n'
                f"# {name}\n\n## Ingredients\n\n"
                f"| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}"
            )
            (recipes_dir / f"{name}.md").write_text(content)
        return recipes_dir

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_high_overlap_skips_claude(self):
        """When top candidate has >= 0.5 overlap, returns it without Claude."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Chicken Gyros": ["chicken", "yogurt", "pita", "cucumber"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir,
                planned_meals=planned,
                day="Tuesday",
                meal="dinner",
                skip_index=0,
            )
            assert result is not None
            assert result["name"] == "Chicken Gyros"
            assert result["score"] >= 0.5

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_excludes_planned_recipes(self):
        """Already-planned recipes are not suggested."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Chicken Shawarma": ["chicken", "yogurt", "cumin"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Chicken Shawarma",
                 "ingredients": ["chicken", "yogurt", "cumin"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir,
                planned_meals=planned,
                day="Tuesday",
                meal="dinner",
                skip_index=0,
            )
            assert result is None or result["name"] != "Chicken Shawarma"

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_skip_index_cycles_candidates(self):
        """skip_index=1 returns second candidate."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "A": ["chicken", "yogurt"],
                "B": ["chicken", "rice"],
                "C": ["salmon", "rice"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Shawarma",
                 "ingredients": ["chicken", "yogurt"]},
            ]
            first = suggest_meal(recipes_dir=recipes_dir, planned_meals=planned,
                                 day="Tue", meal="dinner", skip_index=0)
            second = suggest_meal(recipes_dir=recipes_dir, planned_meals=planned,
                                  day="Tue", meal="dinner", skip_index=1)
            assert first is not None
            assert second is not None
            assert first["name"] != second["name"]
