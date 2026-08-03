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

    def test_strips_template_display_annotation(self):
        """get_recipe_index reads rendered cells back as data, so the template's
        "*(inferred)*" marker arrives attached to the name. Left in place it stops
        staples matching and manufactures false overlap."""
        assert normalize_ingredient("water *(inferred)*") == "water"
        assert normalize_ingredient("pumpkin seeds *(inferred)*") == "pumpkin seeds"
        assert normalize_ingredient("Diced Tomatoes *(inferred)*") == "tomatoes"
        assert normalize_ingredient("soy sauce") == "soy sauce"

    def test_strips_parenthetical_asides(self):
        """Cookbook lines carry metric conversions and cross-references."""
        assert normalize_ingredient("(455 g) white beans") == "white beans"
        assert normalize_ingredient("cashew cheese (this page)") == "cashew cheese"

    def test_drops_clause_after_first_comma(self):
        """Prep and variety clauses are not part of an ingredient's identity."""
        assert normalize_ingredient("large yellow onion , diced") == "yellow onion"
        assert normalize_ingredient("garlic cloves , peeled") == "garlic cloves"
        assert normalize_ingredient(
            "white beans , such as great northern") == "white beans"

    def test_messy_and_clean_spellings_collapse_together(self):
        """The whole point: both forms must resolve to the same ingredient."""
        assert normalize_ingredient("(8 g) basil leaves, slivered") == \
            normalize_ingredient("basil leaves")


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
                at_risk=[],
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
                at_risk=[],
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
                                 day="Tue", meal="dinner", skip_index=0, at_risk=[])
            second = suggest_meal(recipes_dir=recipes_dir, planned_meals=planned,
                                  day="Tue", meal="dinner", skip_index=1, at_risk=[])
            assert first is not None
            assert second is not None
            assert first["name"] != second["name"]


from lib.recipe_matcher import _content_tokens


def _at_risk(*names):
    """Build at-risk (name, token_set) pairs as load_at_risk_index() would."""
    return [(n, _content_tokens(n)) for n in names]


class TestWasteAwareRanking:
    """Layer 3: rank_candidates boosts recipes that use expiring inventory."""

    def test_waste_outranks_higher_overlap(self):
        """A recipe using at-risk food beats a higher-overlap one that doesn't."""
        candidates = [
            {"name": "Overlap King", "ingredient_items": ["chicken", "rice"]},
            {"name": "Buttermilk Bake", "ingredient_items": ["buttermilk", "berries"]},
        ]
        planned_items = {"chicken", "rice"}  # Overlap King = 1.0 overlap
        ranked = rank_candidates(candidates, planned_items, set(),
                                 at_risk=_at_risk("buttermilk"))
        assert ranked[0]["name"] == "Buttermilk Bake"
        assert ranked[0]["waste_uses"] == ["buttermilk"]
        # Overlap score is preserved separately from the waste-boosted rank_score.
        assert ranked[1]["name"] == "Overlap King"
        assert ranked[1]["score"] == 1.0

    def test_no_at_risk_preserves_overlap_order(self):
        """Without at-risk items, ordering matches the old score-based ranking."""
        candidates = [
            {"name": "A", "ingredient_items": ["chicken", "yogurt"]},
            {"name": "B", "ingredient_items": ["chicken", "rice", "soy sauce"]},
        ]
        ranked = rank_candidates(candidates, {"chicken", "yogurt"}, set(), at_risk=[])
        assert [r["name"] for r in ranked] == ["A", "B"]
        assert all(r["waste_uses"] == [] for r in ranked)

    def test_singularized_token_match(self):
        """'strawberries' in the fridge matches a 'strawberry' ingredient."""
        candidates = [{"name": "Tart", "ingredient_items": ["fresh strawberry", "sugar"]}]
        ranked = rank_candidates(candidates, set(), set(),
                                 at_risk=_at_risk("strawberries"))
        assert ranked[0]["waste_uses"] == ["strawberries"]


class TestSuggestMealWaste:
    """suggest_meal surfaces waste-using recipes with an explanatory reason."""

    def _make_recipes_dir(self, tmpdir, recipes):
        recipes_dir = Path(tmpdir)
        for name, ingredients in recipes.items():
            rows = "".join(f"| 1 | whole | {item} |\n" for item in ingredients)
            content = (
                f'---\ntitle: "{name}"\ncuisine: "test"\nprotein: "test"\n---\n\n'
                f"# {name}\n\n## Ingredients\n\n"
                f"| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}"
            )
            (recipes_dir / f"{name}.md").write_text(content)
        return recipes_dir

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_waste_recipe_returned_with_reason(self):
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Buttermilk Pancakes": ["buttermilk", "flour", "egg"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            planned = [
                {"day": "Monday", "meal": "dinner", "name": "Tacos",
                 "ingredients": ["salmon", "rice"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir, planned_meals=planned,
                day="Tuesday", meal="dinner", skip_index=0,
                at_risk=_at_risk("buttermilk"),
            )
            assert result["name"] == "Buttermilk Pancakes"
            assert result["waste_uses"] == ["buttermilk"]
            assert "expiring buttermilk" in result["reason"]
            assert result["is_new_idea"] is False

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_empty_week_leads_with_waste(self):
        """Even with nothing planned, an expiring item drives the first pick."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Buttermilk Pancakes": ["buttermilk", "flour", "egg"],
                "Salmon Bowl": ["salmon", "rice", "avocado"],
            })
            result = suggest_meal(
                recipes_dir=recipes_dir, planned_meals=[],
                day="Monday", meal="dinner", skip_index=0,
                at_risk=_at_risk("buttermilk"),
            )
            assert result is not None
            assert result["name"] == "Buttermilk Pancakes"
            assert "expiring buttermilk" in result["reason"]


class TestProfileInjection:
    """The personal food profile must actually reach the model.

    This wiring is easy to break silently: the prompt still renders, the
    suggestion still returns, and nothing fails — the model just never learns
    the user is trying to lower LDL. Hence an explicit test.
    """

    def test_profile_block_is_empty_without_a_profile(self, tmp_vault):
        from lib import meal_suggester
        assert meal_suggester._profile_block() == ""

    def test_profile_block_carries_the_prose(self, tmp_vault):
        from lib import meal_suggester
        (tmp_vault / "My Meal System.md").write_text(
            "---\n---\n# My Meal System\n\nLowering LDL. Loves sweet food.\n",
            encoding="utf-8")
        block = meal_suggester._profile_block()
        assert "Lowering LDL" in block
        assert "personal profile" in block.lower()

    def test_suggest_prompt_renders_with_the_profile(self, tmp_vault):
        """Guards the format() contract — a missing key raises at call time."""
        from prompts.meal_suggestion import SUGGEST_PROMPT
        rendered = SUGGEST_PROMPT.format(
            profile="## Their food system\nLowering LDL.\n",
            planned_meals="- Mon dinner: Chili",
            macro_block="",
            candidates="- Tacos",
            day="Tuesday", meal="dinner")
        assert "Lowering LDL" in rendered

    def test_empty_week_prompt_renders_with_the_profile(self, tmp_vault):
        from prompts.meal_suggestion import SUGGEST_EMPTY_WEEK_PROMPT
        rendered = SUGGEST_EMPTY_WEEK_PROMPT.format(
            profile="## Their food system\nLowering LDL.\n",
            recipe_summaries="- Chili", day="Monday", meal="dinner")
        assert "Lowering LDL" in rendered

    def test_profile_block_survives_an_unreadable_vault(self, monkeypatch):
        """A broken profile must never take down meal suggestions."""
        from lib import meal_suggester, profile as profile_mod
        monkeypatch.setattr(profile_mod, "load_profile",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        assert meal_suggester._profile_block() == ""


class TestMacroRanking:
    """Macro-aware ranking in rank_candidates (Stage 1)."""

    def _cand(self, name, items, *, cal=None, protein=0, carbs=0, fat=0,
              coverage=None, servings=None):
        return {
            "name": name,
            "ingredient_items": items,
            "nutrition_calories": cal,
            "nutrition_protein": protein,
            "nutrition_carbs": carbs,
            "nutrition_fat": fat,
            "nutrition_coverage": coverage,
            "servings": servings,
        }

    def test_macro_fit_prefers_gap_filler(self):
        """With a protein gap, the high-protein eligible recipe wins even when a
        rival has higher ingredient overlap."""
        candidates = [
            # higher overlap with the plan, but low protein
            self._cand("Overlap Salad", ["chicken", "rice"],
                       cal=300, protein=8, coverage=0.95, servings=2),
            # lower overlap, but closes the protein gap
            self._cand("Protein Bowl", ["beef", "quinoa"],
                       cal=650, protein=48, coverage=0.95, servings=3),
        ]
        planned_items = {"chicken", "rice"}
        ranked = rank_candidates(
            candidates, planned_items, set(),
            macro_gap={"protein": 50, "calories": 700},
        )
        assert ranked[0]["name"] == "Protein Bowl"
        assert ranked[0]["macro_fit"] > ranked[1]["macro_fit"]
        assert ranked[0]["nutrition"]["protein"] == 48

    def test_ineligible_recipe_scores_zero_but_stays(self):
        """Low coverage / missing servings → macro_fit 0, nutrition_unknown, still present."""
        candidates = [
            self._cand("Low Coverage", ["beef"],
                       cal=600, protein=45, coverage=0.4, servings=3),
            self._cand("No Servings", ["pork"],
                       cal=600, protein=45, coverage=0.95, servings=None),
        ]
        ranked = rank_candidates(
            candidates, set(), set(),
            macro_gap={"protein": 50, "calories": 700},
        )
        names = {r["name"] for r in ranked}
        assert names == {"Low Coverage", "No Servings"}
        for r in ranked:
            assert r["macro_fit"] == 0.0
            assert r["nutrition_unknown"] is True

    def test_degradation_identity_no_gap(self):
        """macro_gap=None ranks identically to the pre-macro (waste, overlap) order,
        even with nutrition present on the candidates."""
        candidates = [
            self._cand("A", ["salmon", "lemon"], cal=700, protein=50, coverage=0.95, servings=2),
            self._cand("B", ["chicken", "rice", "soy sauce"], cal=200, protein=5, coverage=0.95, servings=2),
            self._cand("C", ["chicken", "yogurt"], cal=200, protein=5, coverage=0.95, servings=2),
        ]
        planned_items = {"chicken", "yogurt", "rice"}
        ranked = rank_candidates(candidates, planned_items, set(), macro_gap=None)
        # Pure overlap order: C (1.0) > B (0.67) > A (0.0)
        assert [r["name"] for r in ranked] == ["C", "B", "A"]
        assert all(r["macro_fit"] == 0.0 for r in ranked)

    def test_waste_still_wins_over_macro_fit(self):
        """A waste-using recipe outranks a better macro fit — never waste food."""
        from lib.recipe_matcher import _content_tokens

        candidates = [
            self._cand("Great Macros", ["beef", "quinoa"],
                       cal=650, protein=48, coverage=0.95, servings=3),
            self._cand("Uses Spinach", ["spinach", "eggs"],
                       cal=200, protein=12, coverage=0.95, servings=2),
        ]
        at_risk = [("spinach", _content_tokens("spinach"))]
        ranked = rank_candidates(
            candidates, set(), set(),
            at_risk=at_risk, macro_gap={"protein": 50, "calories": 700},
        )
        assert ranked[0]["name"] == "Uses Spinach"
        assert ranked[0]["waste_uses"] == ["spinach"]


class TestMacroTier:
    """The macro tier in suggest_meal (Stage 2)."""

    def _make_recipes_dir(self, tmpdir, recipes):
        """Write recipe files carrying nutrition frontmatter.

        recipes: {name: {"items": [...], "cal", "protein", "coverage", "servings"}}
        """
        recipes_dir = Path(tmpdir)
        for name, spec in recipes.items():
            rows = "".join(f"| 1 | whole | {item} |\n" for item in spec["items"])
            fm = (
                f'---\ntitle: "{name}"\ncuisine: "test"\nprotein: "test"\n'
                f'nutrition_calories: {spec["cal"]}\n'
                f'nutrition_protein: {spec["protein"]}\n'
                f'nutrition_carbs: 20\nnutrition_fat: 10\n'
                f'nutrition_coverage: {spec["coverage"]}\n'
                f'servings: {spec["servings"]}\n---\n\n'
            )
            content = (
                fm + f"# {name}\n\n## Ingredients\n\n"
                f"| Amount | Unit | Ingredient |\n|--------|------|------------|\n{rows}"
            )
            (recipes_dir / f"{name}.md").write_text(content)
        return recipes_dir

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_macro_tier_picks_protein_filler(self):
        """With a protein gap, a high-protein eligible recipe is surfaced with a
        macro reason, beating a higher-overlap low-protein recipe."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Overlap Rice Bowl": {"items": ["chicken", "rice"],
                                      "cal": 300, "protein": 6,
                                      "coverage": 0.95, "servings": 2},
                "Beef Protein Bowl": {"items": ["beef", "quinoa"],
                                      "cal": 650, "protein": 48,
                                      "coverage": 0.95, "servings": 3},
            })
            planned = [
                {"day": "Tuesday", "meal": "lunch", "name": "Salad",
                 "ingredients": ["chicken", "rice"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir, planned_meals=planned,
                day="Tuesday", meal="dinner", at_risk=[],
                macro_gap={"protein": 50, "calories": 700},
            )
            assert result is not None
            assert result["name"] == "Beef Protein Bowl"
            assert "protein" in result["reason"].lower()
            assert result["nutrition"]["protein"] == 48
            assert result["nutrition_unknown"] is False

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_no_macro_gap_uses_overlap_tier(self):
        """macro_gap=None → the old overlap tier wins (high-overlap pick),
        unchanged from pre-macro behaviour."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Overlap Rice Bowl": {"items": ["chicken", "rice"],
                                      "cal": 300, "protein": 6,
                                      "coverage": 0.95, "servings": 2},
                "Beef Protein Bowl": {"items": ["beef", "quinoa"],
                                      "cal": 650, "protein": 48,
                                      "coverage": 0.95, "servings": 3},
            })
            planned = [
                {"day": "Tuesday", "meal": "lunch", "name": "Salad",
                 "ingredients": ["chicken", "rice"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir, planned_meals=planned,
                day="Tuesday", meal="dinner", at_risk=[], macro_gap=None,
            )
            assert result is not None
            assert result["name"] == "Overlap Rice Bowl"  # 1.0 overlap wins

    @patch("lib.meal_suggester.anthropic_client", None)
    def test_ineligible_top_does_not_trigger_macro_tier(self):
        """A high-protein but low-coverage recipe must not be surfaced by the
        macro tier (nutrition_unknown guard)."""
        from lib.meal_suggester import suggest_meal

        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Untrusted Protein": {"items": ["beef", "quinoa"],
                                      "cal": 650, "protein": 48,
                                      "coverage": 0.3, "servings": 3},
                "Overlap Rice Bowl": {"items": ["chicken", "rice"],
                                      "cal": 300, "protein": 6,
                                      "coverage": 0.95, "servings": 2},
            })
            planned = [
                {"day": "Tuesday", "meal": "lunch", "name": "Salad",
                 "ingredients": ["chicken", "rice"]},
            ]
            result = suggest_meal(
                recipes_dir=recipes_dir, planned_meals=planned,
                day="Tuesday", meal="dinner", at_risk=[],
                macro_gap={"protein": 50, "calories": 700},
            )
            # Falls through to the overlap tier, not the untrusted protein bomb.
            assert result["name"] == "Overlap Rice Bowl"


class TestDayMacroGap:
    """day_macro_gap() — summing the planned day against targets (Stage 3)."""

    def _make_recipes_dir(self, tmpdir, recipes):
        recipes_dir = Path(tmpdir)
        for name, spec in recipes.items():
            content = (
                f'---\ntitle: "{name}"\n'
                f'nutrition_calories: {spec["cal"]}\n'
                f'nutrition_protein: {spec["protein"]}\n'
                f'nutrition_carbs: {spec.get("carbs", 0)}\n'
                f'nutrition_fat: {spec.get("fat", 0)}\n'
                f'nutrition_coverage: 0.95\nservings: 2\n---\n\n# {name}\n'
            )
            (recipes_dir / f"{name}.md").write_text(content)
        return recipes_dir

    def test_none_targets_returns_none(self):
        from lib.meal_suggester import day_macro_gap
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {})
            assert day_macro_gap([], "Monday", None, recipes_dir) is None

    def test_sums_only_target_day_and_clamps(self):
        from lib.meal_suggester import day_macro_gap
        from lib.nutrition import NutritionData
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Mon Meal": {"cal": 500, "protein": 40},
                "Tue Meal": {"cal": 900, "protein": 70},
            })
            planned = [
                {"day": "Monday", "name": "Mon Meal", "servings": 1},
                {"day": "Tuesday", "name": "Tue Meal", "servings": 1},
            ]
            targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)
            gap = day_macro_gap(planned, "Monday", targets, recipes_dir)
            assert gap["current"]["protein"] == 40      # only Monday counted
            assert gap["remaining"]["protein"] == 110    # 150 - 40
            assert gap["remaining"]["calories"] == 1500  # 2000 - 500
            assert gap["target"]["protein"] == 150

    def test_servings_multiplier_scales_current(self):
        from lib.meal_suggester import day_macro_gap
        from lib.nutrition import NutritionData
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Big Batch": {"cal": 400, "protein": 30},
            })
            planned = [{"day": "Monday", "name": "Big Batch", "servings": 2}]
            targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)
            gap = day_macro_gap(planned, "Monday", targets, recipes_dir)
            assert gap["current"]["protein"] == 60   # 30 * 2
            assert gap["remaining"]["protein"] == 90  # 150 - 60

    def test_overshoot_clamps_to_zero(self):
        from lib.meal_suggester import day_macro_gap
        from lib.nutrition import NutritionData
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = self._make_recipes_dir(tmpdir, {
                "Huge": {"cal": 3000, "protein": 200},
            })
            planned = [{"day": "Monday", "name": "Huge", "servings": 1}]
            targets = NutritionData(calories=2000, protein=150, carbs=200, fat=65)
            gap = day_macro_gap(planned, "Monday", targets, recipes_dir)
            assert gap["remaining"]["protein"] == 0
            assert gap["remaining"]["calories"] == 0


class TestClaudeMacroPrompt:
    """Stage 4: the low-overlap Claude tier reasons about macros."""

    def test_macro_block_present_when_gap(self):
        from lib.meal_suggester import _macro_block
        block = _macro_block({"protein": 40, "calories": 500})
        assert "40 g" in block and "500 kcal" in block
        assert "protein first" in block

    def test_macro_block_empty_without_gap(self):
        from lib.meal_suggester import _macro_block
        assert _macro_block(None) == ""
        assert _macro_block({"protein": 0, "calories": 0}) == ""

    def test_candidate_line_includes_macros_when_known(self):
        from lib.meal_suggester import _candidate_line
        line = _candidate_line({
            "name": "X", "score": 0.5, "shared_ingredients": ["a"],
            "nutrition": {"protein": 30, "calories": 400}, "nutrition_unknown": False,
        })
        assert "30g protein" in line and "400 kcal" in line

    def test_candidate_line_omits_macros_when_unknown(self):
        from lib.meal_suggester import _candidate_line
        line = _candidate_line({
            "name": "X", "score": 0.5, "shared_ingredients": ["a"],
            "nutrition": None, "nutrition_unknown": True,
        })
        assert "protein" not in line

    def test_suggest_with_claude_sends_macro_gap(self):
        from lib import meal_suggester
        mock_client = MagicMock()
        msg = MagicMock()
        msg.content = [MagicMock(text='{"name":"Beef Bowl","reason":"protein","is_new_idea":false,"new_ingredients_needed":[]}')]
        mock_client.messages.create.return_value = msg
        with patch("lib.meal_suggester.anthropic_client", mock_client):
            candidates = [{
                "name": "Beef Bowl", "score": 0.2, "shared_ingredients": [],
                "nutrition": {"protein": 48, "calories": 650}, "nutrition_unknown": False,
            }]
            res = meal_suggester.suggest_with_claude(
                [{"day": "Mon", "meal": "dinner", "name": "X", "ingredients": ["a"]}],
                candidates, "Tue", "dinner",
                macro_gap={"protein": 50, "calories": 700},
            )
        assert res["name"] == "Beef Bowl"
        sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Remaining macro gap" in sent
        assert "48g protein" in sent


class TestQualifiedStapleOnEitherSide:
    """A staple stays a staple when the qualifier follows it, not just precedes it.

    `_is_pantry` matched a staple exactly or as a *suffix* — "kosher salt".endswith
    (" salt") — which fixed the prefix-qualified case. The mirror case was left
    open: "garlic cloves" is `garlic` plus a form noun, so it slipped the filter
    and counted as genuine shared shopping. Measured on the live library it drove
    **77 of 144** plate pairings and every one of Jammy Zucchini's 31, and it
    inflates `use_it_up`, `cook_now` and POST /api/recipes/by-ingredients the same
    way, since all four share this scorer.

    The distinction that matters: a *form* of the staple is the staple, but a
    *transformation* of it is a different food. Garlic powder is not garlic — that
    is the compound-food trap the audit files under Phase 4.
    """

    PANTRY = {"garlic", "onion", "salt", "olive oil", "butter"}

    def _is(self, name):
        from lib.meal_suggester import _is_pantry
        return _is_pantry(name, self.PANTRY)

    def test_a_form_noun_after_the_staple_is_still_the_staple(self):
        assert self._is("garlic cloves")
        assert self._is("garlic clove")

    def test_other_form_nouns(self):
        assert self._is("garlic head")
        assert self._is("onion bulb")

    def test_the_prefix_qualified_case_still_works(self):
        assert self._is("kosher salt")
        assert self._is("extra-virgin olive oil")

    def test_a_transformation_is_a_different_food(self):
        """garlic powder != garlic — this is the whole reason the rule is narrow.

        Note "garlic salt" is deliberately NOT asserted here: it already matches
        the staple `salt` through the pre-existing suffix rule, which is defensible
        for a salt-based seasoning and is not what this change is about.
        """
        assert not self._is("garlic powder")
        assert not self._is("onion powder")

    def test_an_unrelated_food_is_not_a_staple(self):
        assert not self._is("garlic bread")
        assert not self._is("chicken thighs")

    def test_the_bare_staple_still_matches(self):
        assert self._is("garlic")
