"""Tests for the inventory module."""

import os
import tempfile
from pathlib import Path

import pytest

from lib import inventory
from lib.inventory import (
    InventoryItem,
    add_items,
    normalize_category,
    normalize_location,
    normalize_source,
    read_inventory,
    remove_item,
    update_quantity,
    write_inventory,
)


@pytest.fixture
def tmp_vault(monkeypatch):
    """Point the vault at a temp dir for the duration of a test."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("KITCHENOS_VAULT", tmp)
        yield Path(tmp)


class TestNormalizers:
    def test_normalize_category_known(self):
        assert normalize_category("Dairy") == "dairy"
        assert normalize_category("PRODUCE") == "produce"

    def test_normalize_category_unknown_falls_back_to_other(self):
        assert normalize_category("widgets") == "other"
        assert normalize_category(None) == "other"
        assert normalize_category("") == "other"

    def test_normalize_location_default_is_pantry(self):
        assert normalize_location(None) == "pantry"
        assert normalize_location("") == "pantry"

    def test_normalize_location_known(self):
        assert normalize_location("Fridge") == "fridge"
        assert normalize_location("FREEZER") == "freezer"

    def test_normalize_location_unknown_falls_back_to_other(self):
        assert normalize_location("garage") == "other"

    def test_normalize_source(self):
        assert normalize_source("receipt") == "receipt"
        assert normalize_source("RANDOM") == "manual"
        assert normalize_source(None) == "manual"


class TestRoundtrip:
    def test_read_empty_when_no_file(self, tmp_vault):
        assert read_inventory() == []

    def test_write_then_read_preserves_items(self, tmp_vault):
        items = [
            InventoryItem(
                name="Whole milk", quantity=1, unit="gal",
                category="dairy", location="fridge",
                purchased="2026-04-30", source="receipt",
                notes="GV WHL MLK 1G",
            ),
            InventoryItem(
                name="Bananas", quantity=6, unit="ct",
                category="produce", location="counter",
            ),
        ]
        write_inventory(items)
        loaded = read_inventory()

        assert len(loaded) == 2
        by_name = {i.name: i for i in loaded}
        assert by_name["Whole milk"].quantity == 1.0
        assert by_name["Whole milk"].unit == "gal"
        assert by_name["Whole milk"].category == "dairy"
        assert by_name["Whole milk"].location == "fridge"
        assert by_name["Whole milk"].purchased == "2026-04-30"
        assert by_name["Whole milk"].source == "receipt"
        assert by_name["Whole milk"].notes == "GV WHL MLK 1G"
        assert by_name["Bananas"].quantity == 6.0
        assert by_name["Bananas"].location == "counter"

    def test_fractional_quantity_preserved(self, tmp_vault):
        write_inventory([InventoryItem(name="Olive oil", quantity=0.5, unit="L")])
        loaded = read_inventory()
        assert loaded[0].quantity == 0.5

    def test_inventory_file_lives_at_vault_root(self, tmp_vault):
        write_inventory([InventoryItem(name="Salt", quantity=1, unit="lb")])
        assert (tmp_vault / "Inventory.md").exists()


class TestAddItems:
    def test_add_into_empty_inventory(self, tmp_vault):
        result = add_items([
            InventoryItem(name="Eggs", quantity=12, unit="ct", category="dairy"),
        ])
        assert result == {"added": 1, "merged": 0, "total": 1}
        assert read_inventory()[0].name == "Eggs"

    def test_merge_same_name_unit_location_sums_quantity(self, tmp_vault):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge")])
        result = add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge"),
        ])
        assert result == {"added": 0, "merged": 1, "total": 1}
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 2.0

    def test_different_unit_keeps_separate_rows(self, tmp_vault):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal")])
        add_items([InventoryItem(name="Milk", quantity=8, unit="oz")])
        items = read_inventory()
        assert len(items) == 2

    def test_different_location_keeps_separate_rows(self, tmp_vault):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry")])
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer")])
        items = read_inventory()
        assert len(items) == 2

    def test_merge_is_case_insensitive(self, tmp_vault):
        add_items([InventoryItem(name="Eggs", quantity=12, unit="ct")])
        result = add_items([InventoryItem(name="EGGS", quantity=6, unit="CT")])
        assert result["merged"] == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 18.0

    def test_merge_updates_purchased_date(self, tmp_vault):
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-01"),
        ])
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-30"),
        ])
        assert read_inventory()[0].purchased == "2026-04-30"


class TestRemove:
    def test_remove_existing_item(self, tmp_vault):
        add_items([
            InventoryItem(name="Cheese", quantity=1, unit="lb"),
            InventoryItem(name="Bread", quantity=1, unit="loaf"),
        ])
        assert remove_item("Cheese") is True
        names = [i.name for i in read_inventory()]
        assert "Cheese" not in names
        assert "Bread" in names

    def test_remove_missing_item_returns_false(self, tmp_vault):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf")])
        assert remove_item("Cheese") is False
        assert len(read_inventory()) == 1

    def test_remove_filters_by_location(self, tmp_vault):
        add_items([
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry"),
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer"),
        ])
        assert remove_item("Bread", location="freezer") is True
        items = read_inventory()
        assert len(items) == 1
        assert items[0].location == "pantry"


class TestUpdateQuantity:
    def test_update_existing_item(self, tmp_vault):
        add_items([InventoryItem(name="Flour", quantity=5, unit="lb")])
        assert update_quantity("Flour", 2.5) is True
        assert read_inventory()[0].quantity == 2.5

    def test_update_missing_item_returns_false(self, tmp_vault):
        assert update_quantity("Flour", 1) is False


class TestParsing:
    def test_skips_malformed_rows(self, tmp_vault):
        content = (
            "---\n"
            "type: inventory\n"
            "---\n\n"
            "# Pantry Inventory\n\n"
            "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |\n"
            "|------|----------|------|----------|----------|-----------|--------|-------|\n"
            "| Milk | 1 | gal | dairy | fridge | 2026-04-30 | receipt |  |\n"
            "|  |  |  |  |  |  |  |  |\n"
            "| Eggs | 12 | ct | dairy | fridge |  | manual |  |\n"
        )
        (tmp_vault / "Inventory.md").write_text(content, encoding="utf-8")
        items = read_inventory()
        assert len(items) == 2
        names = sorted(i.name for i in items)
        assert names == ["Eggs", "Milk"]
