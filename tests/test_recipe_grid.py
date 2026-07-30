"""Tests for the grid (Cooking-for-Engineers matrix) recipe card."""

import tempfile
from pathlib import Path

from lib import recipe_grid


def _write_recipe(recipes_dir, name, ingredients, steps, extra_fm=""):
    rows = "".join(f"| {a} | {u} | {it} |\n" for a, u, it in ingredients)
    numbered = "".join(f"{n}. {s}\n" for n, s in enumerate(steps, 1))
    content = (
        f'---\ntitle: "{name}"\n{extra_fm}---\n\n# {name}\n\n'
        f"## Ingredients\n\n| Amount | Unit | Ingredient |\n"
        f"|--------|------|------------|\n{rows}\n"
        f"## Instructions\n\n{numbered}"
    )
    (recipes_dir / f"{name}.md").write_text(content)


class TestIngredientDisplay:
    def test_mass_unit_resolves_grams(self):
        out = recipe_grid._ingredient_display({"amount": "4", "unit": "oz", "item": "butter"})
        assert "butter" in out
        assert "113 g" in out  # 4 oz ~= 113 g

    def test_unresolvable_unit_omits_grams(self):
        # A "whole" count of an item with no known piece weight can't resolve.
        out = recipe_grid._ingredient_display(
            {"amount": "1", "unit": "whole", "item": "mystery widget"})
        assert "mystery widget" in out
        assert "g)" not in out
        assert out.startswith("1")


class TestRenderGridHtml:
    def test_renders_matrix_with_actions_and_finish(self):
        spec = {
            "prep": ["Preheat oven to 350F"],
            "groups": [
                {"action": "melt", "ingredients": ["butter"]},
                {"action": "mix", "ingredients": ["sugar", "vanilla"]},
            ],
            "finish": "bake 350F, 30-40 min",
            "ingredient_rows": ["4 oz butter", "1 cup sugar", "1 tsp vanilla"],
        }
        ingredients = [{"item": "butter"}, {"item": "sugar"}, {"item": "vanilla"}]
        html = recipe_grid.render_grid_html(spec, ingredients)
        assert "recipe-grid" in html
        assert "melt" in html and "mix" in html
        assert "bake 350F, 30-40 min" in html
        assert "Preheat oven to 350F" in html
        # staircase: the finish spans all three ingredient rows
        assert "rowspan='3'" in html
        for row in spec["ingredient_rows"]:
            assert row in html

    def test_fallback_lists_steps_when_no_groups(self):
        spec = {
            "prep": [], "groups": [], "finish": "",
            "steps": ["Combine everything", "Cook until done"],
            "ingredient_rows": ["1 cup flour", "2 eggs"],
        }
        html = recipe_grid.render_grid_html(spec, [{"item": "flour"}, {"item": "eggs"}])
        assert "grid-steps" in html
        assert "Combine everything" in html and "Cook until done" in html
        assert "1 cup flour" in html and "2 eggs" in html

    def test_unmatched_ingredients_are_never_dropped(self):
        spec = {
            "prep": [], "groups": [{"action": "mix", "ingredients": ["sugar"]}],
            "finish": "", "ingredient_rows": ["1 cup sugar", "1 pinch mystery"],
        }
        html = recipe_grid.render_grid_html(spec, [{"item": "sugar"}, {"item": "mystery"}])
        assert "mystery" in html  # surfaced in the leading unassigned group


class TestBuildGrid:
    def test_missing_recipe_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert recipe_grid.build_grid("Nope", Path(tmp)) is None

    def test_heuristic_when_no_llm(self, monkeypatch):
        """No Claude + no Ollama -> heuristic spec, sidecar written, needs_review."""
        monkeypatch.setattr(recipe_grid, "_anthropic_client", None)
        monkeypatch.setattr(recipe_grid, "_group_with_ollama", lambda prompt: None)
        with tempfile.TemporaryDirectory() as tmp:
            recipes_dir = Path(tmp)
            _write_recipe(recipes_dir, "Test Cake",
                          [("4", "oz", "butter"), ("1", "cup", "sugar")],
                          ["Melt butter", "Stir in sugar", "Bake"])
            spec = recipe_grid.build_grid("Test Cake", recipes_dir)
            assert spec["source"] == "heuristic"
            assert spec["needs_review"] is True
            assert spec["steps"] == ["Melt butter", "Stir in sugar", "Bake"]
            assert spec["ingredient_rows"]  # display rows present
            assert (recipes_dir / "Test Cake.grid.json").exists()

    def test_claude_spec_is_normalized_and_cached(self, monkeypatch):
        fake = {
            "prep": ["Preheat 350F"],
            "groups": [
                {"action": "melt", "ingredients": ["butter"]},
                {"action": "mix", "ingredients": ["sugar"]},
                {"action": "", "ingredients": []},  # empty -> dropped
            ],
            "finish": "bake",
        }
        monkeypatch.setattr(recipe_grid, "_group_with_claude", lambda prompt: fake)
        with tempfile.TemporaryDirectory() as tmp:
            recipes_dir = Path(tmp)
            _write_recipe(recipes_dir, "Cake",
                          [("4", "oz", "butter"), ("1", "cup", "sugar")],
                          ["Melt", "Mix", "Bake"])
            spec = recipe_grid.build_grid("Cake", recipes_dir)
            assert spec["source"] == "claude"
            assert len(spec["groups"]) == 2  # empty group dropped
            assert spec["finish"] == "bake"
            # cached: a second call with the LLM disabled returns the sidecar
            monkeypatch.setattr(recipe_grid, "_group_with_claude", lambda prompt: None)
            monkeypatch.setattr(recipe_grid, "_group_with_ollama", lambda prompt: None)
            spec2 = recipe_grid.build_grid("Cake", recipes_dir)
            assert spec2["source"] == "claude"  # from sidecar, not heuristic
