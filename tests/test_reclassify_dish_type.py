"""Diff and apply logic for the one-off dish_type repair. No network."""

import pytest

from lib import paths
from scripts import reclassify_dish_type as rc


RECIPES = [
    {"name": "Butter Biscuits", "dish_type": "dessert",
     "ingredient_items": ["flour", "butter", "buttermilk"]},
    {"name": "Chili Garlic Noodles", "dish_type": "main",
     "ingredient_items": ["noodles", "chili crisp", "garlic"]},
    {"name": "Green Shakshuka", "dish_type": "Shakshuka",
     "ingredient_items": ["eggs", "spinach", "feta"]},
]


class TestDiff:
    def test_splits_change_keep_and_unresolved(self):
        results = {"r0": "bread", "r1": "main"}  # r2 missing -> unresolved
        out = rc.diff(RECIPES, results)
        assert out["change"] == [("Butter Biscuits", "dessert", "bread")]
        assert out["keep"] == [("Chili Garlic Noodles", "main")]
        assert out["unresolved"] == [("Green Shakshuka", "Shakshuka")]

    def test_every_recipe_lands_in_exactly_one_bucket(self):
        """A silently dropped recipe would read as 'nothing to do'."""
        results = {"r0": "bread"}
        out = rc.diff(RECIPES, results)
        total = len(out["change"]) + len(out["keep"]) + len(out["unresolved"])
        assert total == len(RECIPES)

    def test_results_are_keyed_by_custom_id_not_order(self):
        """Batch results come back in arbitrary order — position must not matter."""
        forward = rc.diff(RECIPES, {"r0": "bread", "r1": "main", "r2": "main"})
        shuffled = rc.diff(RECIPES, {"r2": "main", "r1": "main", "r0": "bread"})
        assert forward == shuffled

    def test_unknown_custom_id_is_ignored(self):
        out = rc.diff(RECIPES, {"r99": "dessert"})
        assert out["change"] == []
        assert len(out["unresolved"]) == 3


class TestApplyChanges:
    def test_writes_frontmatter_and_backs_up(self, tmp_vault):
        recipes_dir = paths.recipes_dir()
        recipes_dir.mkdir(parents=True, exist_ok=True)
        path = recipes_dir / "Butter Biscuits.md"
        path.write_text(
            "---\ntitle: Butter Biscuits\ndish_type: dessert\n---\n\n## Ingredients\n- flour\n",
            encoding="utf-8",
        )

        written, skipped = rc.apply_changes([("Butter Biscuits", "dessert", "bread")])

        assert written == 1 and skipped == []
        assert "dish_type: bread" in path.read_text(encoding="utf-8")
        assert list((recipes_dir / ".history").glob("Butter Biscuits*")), "no backup written"

    def test_leaves_other_frontmatter_untouched(self, tmp_vault):
        recipes_dir = paths.recipes_dir()
        recipes_dir.mkdir(parents=True, exist_ok=True)
        path = recipes_dir / "Butter Biscuits.md"
        path.write_text(
            "---\ntitle: Butter Biscuits\ndish_type: dessert\ncuisine: American\n---\n\nbody\n",
            encoding="utf-8",
        )

        rc.apply_changes([("Butter Biscuits", "dessert", "bread")])

        text = path.read_text(encoding="utf-8")
        assert "cuisine: American" in text
        assert "title: Butter Biscuits" in text
        assert "body" in text

    def test_missing_file_is_reported_not_crashed(self, tmp_vault):
        paths.recipes_dir().mkdir(parents=True, exist_ok=True)
        written, skipped = rc.apply_changes([("Nonexistent Recipe", "main", "side")])
        assert written == 0
        assert skipped == ["Nonexistent Recipe"]


class TestPrompt:
    def test_prompt_carries_name_ingredients_and_current_value(self):
        prompt = rc.build_prompt(RECIPES[0])
        assert "Butter Biscuits" in prompt
        assert "buttermilk" in prompt
        assert "dessert" in prompt
