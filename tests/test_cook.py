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
        # spinach is qty 1 — a container. The gate use-stamps it, never
        # decrements it, because in the real inventory 188 of 198 count rows
        # sit at exactly 1.0 and mean "one package".
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
        # spinach is qty 1 — a container, so it is stamped rather than emptied.
        assert "spinach" not in consumed
        assert any(u["item"] == "spinach" for u in result["use_recorded"])

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
        # spinach survives: a qty-1 row is one package, and the recipe using it
        # does not empty it. It is stamped as used instead of being deleted.
        assert by_name["spinach"].quantity == 1
        assert by_name["spinach"].last_used is not None

    def test_servings_multiplier(self, tmp_vault, tmp_db):
        _write_recipe()
        _seed_inventory()
        # 2x batch uses 0.5 cup buttermilk → 3.5 left, and 2 cucumbers → 1 left
        cook.consume_recipe("Test Bake", servings=2)
        by_name = {i.name: i for i in read_inventory()}
        assert round(by_name["buttermilk"].quantity, 2) == 3.5
        assert by_name["cucumber"].quantity == 1


CONTAINER_RECIPE_MD = """\
---
recipe_name: Container Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | tbsp | mirin |
| 3 | whole | bay leaves |
| 2 | whole | limes |
| 1 | whole | table spoon bacon drippings |
"""


def _write_container_recipe():
    rd = paths.recipes_dir()
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "Container Test.md").write_text(CONTAINER_RECIPE_MD, encoding="utf-8")


def _seed_containers():
    add_items([
        InventoryItem(name="Mirin", quantity=1, unit="ct", category="pantry"),
        InventoryItem(name="Bay leaves", quantity=1, unit="ct", category="pantry"),
        InventoryItem(name="lime", quantity=5, unit="ct", category="produce"),
        InventoryItem(name="bacon", quantity=1, unit="oz", category="meat"),
    ])


class TestContainerGate:
    def test_container_quantity_is_never_changed(self, tmp_vault, tmp_db):
        """`1 ct Mirin` used for `2 tbsp` keeps its quantity."""
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test")

        rows = {i.name: i for i in read_inventory()}
        assert rows["Mirin"].quantity == 1

    def test_container_use_is_stamped(self, tmp_vault, tmp_db):
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test", now="2026-07-26T10:00:00")

        rows = {i.name: i for i in read_inventory()}
        assert rows["Mirin"].last_used == "2026-07-26T10:00:00"
        assert rows["Mirin"].use_count == 1

    def test_a_qty_one_jar_is_not_deleted_by_a_count_recipe_line(self, tmp_vault, tmp_db):
        """Without the gate, `3 whole bay leaves` deletes the whole jar."""
        _write_container_recipe()
        _seed_containers()
        cook.consume_recipe("Container Test")

        rows = {i.name: i for i in read_inventory()}
        assert "Bay leaves" in rows
        assert rows["Bay leaves"].quantity == 1

    def test_a_real_count_still_decrements(self, tmp_vault, tmp_db):
        """5 ct lime, recipe wants 2 whole limes → 3 left. The reported bug."""
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")

        consumed = {c["item"]: c for c in result["consumed"]}
        assert consumed["lime"]["after"] == 3
        assert consumed["lime"]["depleted"] is False

    def test_garbage_unit_becomes_a_use_record(self, tmp_vault, tmp_db):
        """"1 whole table spoon bacon drippings" vs `1 oz bacon` — the biscuits case."""
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")

        assert any(u["item"] == "bacon" for u in result["use_recorded"])
        rows = {i.name: i for i in read_inventory()}
        assert rows["bacon"].quantity == 1

    def test_response_has_no_unconvertible_key(self, tmp_vault, tmp_db):
        _write_container_recipe()
        _seed_containers()
        result = cook.consume_recipe("Container Test")
        assert "unconvertible" not in result
        assert set(result) == {
            "recipe", "consumed", "skipped_staples", "not_tracked", "use_recorded"}


WEIGHT_RECIPE_MD = """\
---
recipe_name: Weight Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 250 | g | pumpkin puree |
"""


DUPE_RECIPE_MD = """\
---
recipe_name: Dupe Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | whole | cucumber |
"""


def _write_raw_recipe(name, body):
    rd = paths.recipes_dir()
    rd.mkdir(parents=True, exist_ok=True)
    (rd / f"{name}.md").write_text(body, encoding="utf-8")


class TestACookNeverDeletesARow:
    """A cook may reduce a row; it must never remove one.

    Inventory rows are packages. A `5 oz` row matched by a `250 g` recipe line
    is a unit-of-sale mismatch, not five ounces about to run out — and the
    real library contains exactly that pair (pumpkin). A missed depletion
    self-heals through the expiry prune; a deleted row does not.
    """

    def test_a_weight_package_is_not_emptied_by_a_larger_line(self, tmp_vault, tmp_db):
        _write_raw_recipe("Weight Test", WEIGHT_RECIPE_MD)
        add_items([
            InventoryItem(name="pumpkin", quantity=5, unit="oz", category="produce"),
        ])
        result = cook.consume_recipe("Weight Test")

        rows = {i.name: i for i in read_inventory()}
        assert "pumpkin" in rows, "the row was deleted — the gate under-fired"
        assert rows["pumpkin"].quantity == 5
        assert any(u["item"] == "pumpkin" for u in result["use_recorded"])

    def test_two_lines_cannot_jointly_empty_a_row(self, tmp_vault, tmp_db):
        """apply_decisions subtracts cumulatively, so a guard that checks each
        line against the *original* quantity lets two passing lines combine to
        delete the row. 5 oz ≈ 141.7 g, so 100 g twice would zero it."""
        _write_raw_recipe("Accum Test", """\
---
recipe_name: Accum Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 100 | g | pumpkin puree |
| 100 | g | pumpkin puree for the glaze |
""")
        add_items([
            InventoryItem(name="pumpkin", quantity=5, unit="oz", category="produce"),
        ])
        cook.consume_recipe("Accum Test")

        rows = {i.name: i for i in read_inventory()}
        assert "pumpkin" in rows, "two lines combined to delete the row"

    def test_a_weight_package_still_decrements_when_stock_survives(
        self, tmp_vault, tmp_db
    ):
        """The guard must not freeze every weight row: 900 g - 250 g still spends."""
        _write_raw_recipe("Weight Test", WEIGHT_RECIPE_MD)
        add_items([
            InventoryItem(name="pumpkin", quantity=900, unit="g", category="produce"),
        ])
        result = cook.consume_recipe("Weight Test")

        consumed = {c["item"]: c for c in result["consumed"]}
        assert consumed["pumpkin"]["after"] == 650
        assert consumed["pumpkin"]["depleted"] is False


class TestRowsSummedAcrossLocations:
    """load_pantry sums (name, unit) across locations, so two qty-1 rows read as
    2.0 and the container gate never sees the parts. save_pantry's duplicate
    collapse then drops the second row outright — along with its stamps."""

    def test_two_container_rows_are_both_preserved(self, tmp_vault, tmp_db):
        _write_raw_recipe("Dupe Test", DUPE_RECIPE_MD)
        add_items([
            InventoryItem(name="cucumber", quantity=1, unit="ct",
                          category="produce", location="fridge"),
            InventoryItem(name="cucumber", quantity=1, unit="ct",
                          category="produce", location="pantry"),
        ])
        assert len(read_inventory()) == 2

        result = cook.consume_recipe("Dupe Test")

        rows = read_inventory()
        assert len(rows) == 2, "a row was dropped by the cook"
        assert all(r.quantity == 1 for r in rows)
        assert any(u["item"].lower() == "cucumber" for u in result["use_recorded"])


class TestOneCookStampsARowOnce:
    def test_a_row_in_both_buckets_increments_once(self, tmp_vault, tmp_db):
        """A row can be decremented by one line and merely used by another. That
        is one cook touching one row, so use_count must move by exactly 1."""
        _write_raw_recipe("Both Test", """\
---
recipe_name: Both Test
---

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | whole | limes |
| 1 | pinch | lime |
""")
        add_items([
            InventoryItem(name="lime", quantity=5, unit="ct", category="produce"),
        ])
        result = cook.consume_recipe("Both Test", now="2026-07-27T10:00:00")

        rows = {i.name: i for i in read_inventory()}
        assert rows["lime"].use_count == 1
        # And the row is reported once, not in two buckets at odds with each other.
        in_consumed = {c["item"].lower() for c in result["consumed"]}
        in_used = {u["item"].lower() for u in result["use_recorded"]}
        assert not (in_consumed & in_used), "same row reported in two buckets"


class TestNoOpCookDoesNotRewriteInventory:
    def test_no_decisions_means_no_save_pantry(self, tmp_vault, tmp_db, monkeypatch):
        """234 of 236 recipes decrement nothing. Each one used to trigger a full
        DELETE+INSERT of every row plus two vault-note regenerations."""
        _write_container_recipe()
        add_items([InventoryItem(name="Mirin", quantity=1, unit="ct")])

        calls = []
        monkeypatch.setattr(cook, "save_pantry", lambda items: calls.append(items))
        cook.consume_recipe("Container Test")
        assert calls == []
