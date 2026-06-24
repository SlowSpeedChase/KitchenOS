"""Tests for lib/recipe_matcher.py — purchase → meal-plan recipe matching."""
from lib import recipe_matcher as rm
from lib.recipe_matcher import PlanIndex, _content_tokens, assign_recipes


def _idx():
    return PlanIndex({
        "Garlic Butter Chicken": [
            _content_tokens("boneless skinless chicken breasts"),
            _content_tokens("4 cloves garlic, minced"),
        ],
        "Tomato Soup": [
            _content_tokens("2 lbs roma tomatoes"),
            _content_tokens("1 yellow onion, diced"),
        ],
    })


class TestMatch:
    def test_exact_and_subset(self):
        idx = _idx()
        assert idx.match("chicken breast") == ["Garlic Butter Chicken"]
        # buying just "chicken" still matches the chicken-breast recipe
        assert idx.match("chicken") == ["Garlic Butter Chicken"]

    def test_singularization(self):
        # "tomatoes" purchase matches an ingredient written "tomatoes"/"tomato"
        assert _idx().match("tomato") == ["Tomato Soup"]
        assert _idx().match("onions") == ["Tomato Soup"]

    def test_no_match_returns_empty(self):
        assert _idx().match("salmon fillet") == []
        assert _idx().match("paper towels") == []

    def test_staple_can_match_multiple(self):
        idx = PlanIndex({
            "A": [_content_tokens("2 tbsp butter")],
            "B": [_content_tokens("1 stick butter, softened")],
        })
        assert idx.match("butter") == ["A", "B"]


class TestAssignRecipes:
    def test_sets_for_recipe_and_skips_fees(self):
        purchases = [
            {"canonical_name": "chicken breast", "category": "meat"},
            {"canonical_name": "roma tomatoes", "category": "produce"},
            {"canonical_name": "sales tax", "category": "fee"},
            {"canonical_name": "potato chips", "category": "pantry"},
        ]
        assign_recipes(purchases, index=_idx())
        assert purchases[0]["for_recipe"] == "Garlic Butter Chicken"
        assert purchases[1]["for_recipe"] == "Tomato Soup"
        assert "for_recipe" not in purchases[2]  # fee untouched
        assert purchases[3]["for_recipe"] is None  # no plan match


def test_current_week_window_format():
    weeks = rm.current_week_window()
    assert len(weeks) == 2
    for w in weeks:
        assert len(w) == 8 and w[4:6] == "-W"


def test_build_plan_index_reads_vault(tmp_vault):
    """End-to-end: a meal plan + recipe file produce a working index."""
    (tmp_vault / "Meal Plans").mkdir()
    (tmp_vault / "Recipes").mkdir()
    (tmp_vault / "Recipes" / "Sheet Pan Chicken.md").write_text(
        "---\ntitle: Sheet Pan Chicken\n---\n\n"
        "# Sheet Pan Chicken\n\n"
        "## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n"
        "|--------|------|------------|\n"
        "| 2 | lb | chicken thighs |\n"
        "| 3 | clove | garlic |\n\n"
        "## Instructions\n\n1. Cook it.\n",
        encoding="utf-8",
    )
    weeks = rm.current_week_window()
    (tmp_vault / "Meal Plans" / f"{weeks[0]}.md").write_text(
        f"# Meal Plan\n\n## Monday (Jan 1)\n"
        "### Breakfast\n\n### Lunch\n\n### Snack\n\n"
        "### Dinner\n[[Sheet Pan Chicken]]\n### Notes\n",
        encoding="utf-8",
    )
    index = rm.build_plan_index()
    assert "Sheet Pan Chicken" in index.recipe_names
    assert index.match("chicken thigh") == ["Sheet Pan Chicken"]
    assert index.match("garlic") == ["Sheet Pan Chicken"]
    assert index.match("orange juice") == []
