"""Tests for consume-on-cook (Layer 2)."""

from lib.inventory import InventoryItem, add_items, read_inventory
from lib import paths, cook


RECIPE_MD = """\
---
recipe_name: Test Bake
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 0.25 | cup | buttermilk |
| 2 | cup | flour |
| 1 | ct | cucumber |
| 1 | ct | spinach |
| 1 | ct | dragon fruit |
"""


def _write_recipe(name="Test Bake"):
    rd = paths.recipes_dir()
    rd.mkdir(parents=True, exist_ok=True)
    (rd / f"{name}.md").write_text(RECIPE_MD, encoding="utf-8")


def _seed_inventory():
    add_items([
        InventoryItem(name="buttermilk", quantity=4, unit="cup", category="dairy"),
        InventoryItem(name="cucumber", quantity=3, unit="ct", category="produce"),
        InventoryItem(name="spinach", quantity=1, unit="ct", category="produce"),
        # flour intentionally absent (it's a staple); dragon fruit absent (untracked)
    ])


class TestConsumeRecipe:
    def test_missing_recipe(self, tmp_vault, tmp_db):
        result = cook.consume_recipe("Nope")
        assert result["error"] == "recipe not found"

    def test_decrements_tracked_non_staples(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        result = cook.consume_recipe("Test Bake")

        consumed = {c["item"]: c for c in result["consumed"]}
        # buttermilk: 4 cup - 0.25 = 3.75 left
        assert round(consumed["buttermilk"]["after"], 2) == 3.75
        assert consumed["buttermilk"]["depleted"] is False
        # cucumber: 3 - 1 = 2
        assert consumed["cucumber"]["after"] == 2
        # spinach: 1 - 1 = 0 → used up
        assert consumed["spinach"]["depleted"] is True

    def test_skips_staples_and_untracked(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        result = cook.consume_recipe("Test Bake")
        assert "flour" in result["skipped_staples"]
        assert "dragon fruit" in result["not_tracked"]

    def test_persists_to_inventory(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        cook.consume_recipe("Test Bake")
        by_name = {i.name: i for i in read_inventory()}
        assert round(by_name["buttermilk"].quantity, 2) == 3.75
        assert by_name["cucumber"].quantity == 2
        assert "spinach" not in by_name  # used up → removed

    def test_servings_multiplier(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        # 2x batch uses 0.5 cup buttermilk → 3.5 left, and 2 cucumbers → 1 left
        cook.consume_recipe("Test Bake", servings=2)
        by_name = {i.name: i for i in read_inventory()}
        assert round(by_name["buttermilk"].quantity, 2) == 3.5
        assert by_name["cucumber"].quantity == 1
