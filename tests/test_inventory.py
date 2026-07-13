"""Tests for the inventory module."""

from lib.inventory import (
    InventoryItem,
    add_items,
    extend_expiry,
    inventory_path,
    normalize_category,
    normalize_location,
    normalize_source,
    parse_inventory_markdown,
    read_inventory,
    remove_item,
    update_quantity,
    write_inventory,
)


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
    def test_read_empty_when_no_data(self, tmp_vault, tmp_db):
        assert read_inventory() == []

    def test_write_then_read_preserves_items(self, tmp_vault, tmp_db):
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

    def test_fractional_quantity_preserved(self, tmp_vault, tmp_db):
        write_inventory([InventoryItem(name="Olive oil", quantity=0.5, unit="L")])
        loaded = read_inventory()
        assert loaded[0].quantity == 0.5

    def test_inventory_file_lives_at_vault_root(self, tmp_vault, tmp_db):
        write_inventory([InventoryItem(name="Salt", quantity=1, unit="lb")])
        assert (tmp_vault / "Inventory.md").exists()


class TestAddItems:
    def test_add_into_empty_inventory(self, tmp_vault, tmp_db):
        result = add_items([
            InventoryItem(name="Eggs", quantity=12, unit="ct", category="dairy"),
        ])
        assert result == {"added": 1, "merged": 0, "total": 1}
        assert read_inventory()[0].name == "Eggs"

    def test_merge_same_name_unit_location_sums_quantity(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge")])
        result = add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal", location="fridge"),
        ])
        assert result == {"added": 0, "merged": 1, "total": 1}
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 2.0

    def test_different_unit_keeps_separate_rows(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal")])
        add_items([InventoryItem(name="Milk", quantity=8, unit="oz")])
        items = read_inventory()
        assert len(items) == 2

    def test_different_location_keeps_separate_rows(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry")])
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer")])
        items = read_inventory()
        assert len(items) == 2

    def test_merge_is_case_insensitive(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Eggs", quantity=12, unit="ct")])
        result = add_items([InventoryItem(name="EGGS", quantity=6, unit="CT")])
        assert result["merged"] == 1
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 18.0

    def test_merge_updates_purchased_date(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-01"),
        ])
        add_items([
            InventoryItem(name="Yogurt", quantity=1, unit="ct", purchased="2026-04-30"),
        ])
        assert read_inventory()[0].purchased == "2026-04-30"


class TestRemove:
    def test_remove_existing_item(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Cheese", quantity=1, unit="lb"),
            InventoryItem(name="Bread", quantity=1, unit="loaf"),
        ])
        assert remove_item("Cheese") is True
        names = [i.name for i in read_inventory()]
        assert "Cheese" not in names
        assert "Bread" in names

    def test_remove_missing_item_returns_false(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Bread", quantity=1, unit="loaf")])
        assert remove_item("Cheese") is False
        assert len(read_inventory()) == 1

    def test_remove_filters_by_location(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="pantry"),
            InventoryItem(name="Bread", quantity=1, unit="loaf", location="freezer"),
        ])
        assert remove_item("Bread", location="freezer") is True
        items = read_inventory()
        assert len(items) == 1
        assert items[0].location == "pantry"


class TestUpdateQuantity:
    def test_update_existing_item(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Flour", quantity=5, unit="lb")])
        assert update_quantity("Flour", 2.5) is True
        assert read_inventory()[0].quantity == 2.5

    def test_update_missing_item_returns_false(self, tmp_vault, tmp_db):
        assert update_quantity("Flour", 1) is False


class TestGeneratedView:
    def test_inventory_md_is_generated_view(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 category="dairy", location="fridge")])
        content = inventory_path().read_text(encoding="utf-8")
        assert "| Milk | 1 | gal | dairy | fridge |" in content
        assert "generated" in content.lower()  # view banner present

    def test_hand_edits_to_md_are_invisible(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal")])
        # simulate a user hand-editing the generated view
        inventory_path().write_text("| Item |...| Beer | 99 | ct |", encoding="utf-8")
        items = read_inventory()
        assert [it.name for it in items] == ["Milk"]


class TestParsing:
    def test_parse_inventory_markdown_still_works(self, tmp_vault, tmp_db):
        md = (
            "| Item | Quantity | Unit | Category | Location | Purchased | Source | Notes |\n"
            "|------|----------|------|----------|----------|-----------|--------|-------|\n"
            "| Eggs | 12 | ct | dairy | fridge | 2026-06-01 | receipt |  |\n"
        )
        items = parse_inventory_markdown(md)
        assert items[0].name == "Eggs"
        assert items[0].quantity == 12.0

    def test_skips_malformed_rows(self, tmp_vault, tmp_db):
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
        items = parse_inventory_markdown(content)
        assert len(items) == 2
        names = sorted(i.name for i in items)
        assert names == ["Eggs", "Milk"]


class TestExpiry:
    def test_add_autofills_expires_from_window(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal",
                          category="dairy", purchased="2026-06-01"),
        ])
        item = read_inventory()[0]
        assert item.expires == "2026-06-11"  # milk window = 10 days

    def test_null_window_leaves_expires_none(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Dish soap", quantity=1, unit="ct",
                          category="household", purchased="2026-06-01"),
        ])
        assert read_inventory()[0].expires is None

    def test_explicit_expires_is_respected(self, tmp_vault, tmp_db):
        add_items([
            InventoryItem(name="Milk", quantity=1, unit="gal", category="dairy",
                          purchased="2026-06-01", expires="2026-06-05"),
        ])
        assert read_inventory()[0].expires == "2026-06-05"

    def test_merge_keeps_earliest_expiry(self, tmp_vault, tmp_db):
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 location="fridge", category="dairy",
                                 expires="2026-06-20")])
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal",
                                 location="fridge", category="dairy",
                                 expires="2026-06-10")])
        items = read_inventory()
        assert len(items) == 1
        assert items[0].expires == "2026-06-10"

    def test_render_includes_expiry_warning_section(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import render_inventory_md
        soon = (date.today() + timedelta(days=1)).isoformat()
        items = [InventoryItem(name="Yogurt", quantity=1, unit="ct",
                               category="dairy", expires=soon)]
        md = render_inventory_md(items)
        assert "## ⚠️ Expiring Soon" in md
        assert "Yogurt" in md
        assert "Expires" in md  # table column header


class TestPruneExpired:
    def test_drops_long_expired_perishables(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import add_items, prune_expired, read_inventory
        today = date(2026, 6, 24)
        add_items([
            InventoryItem(name="Old Spinach", quantity=1, unit="ct", category="produce",
                          expires=(today - timedelta(days=10)).isoformat()),
            InventoryItem(name="Fresh Spinach", quantity=1, unit="ct", category="produce",
                          expires=(today - timedelta(days=1)).isoformat()),  # within grace
            InventoryItem(name="Canned Beans", quantity=1, unit="can", category="pantry",
                          expires=(today + timedelta(days=300)).isoformat()),
            InventoryItem(name="Dish Soap", quantity=1, unit="ct", category="household"),  # no expiry
        ])
        removed = prune_expired(today=today)
        assert removed == 1
        names = {i.name for i in read_inventory()}
        assert "Old Spinach" not in names
        assert {"Fresh Spinach", "Canned Beans", "Dish Soap"} <= names

    def test_noop_when_nothing_stale(self, tmp_vault, tmp_db):
        from datetime import date, timedelta
        from lib.inventory import add_items, prune_expired
        today = date(2026, 6, 24)
        add_items([InventoryItem(name="Milk", quantity=1, unit="gal", category="dairy",
                                 expires=(today + timedelta(days=5)).isoformat())])
        assert prune_expired(today=today) == 0


class TestExtendExpiry:
    def test_extends_from_today_not_old_date(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Milk", quantity=1, unit="ct",
                                 category="dairy", location="fridge",
                                 expires="2026-07-15")])
        item = extend_expiry("Milk", days=3, location="fridge",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-15"  # today(07-12) + 3 days

    def test_sets_fresh_expiry_on_no_expiry_item(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Rice", quantity=1, unit="lb",
                                 category="pantry", location="pantry",
                                 expires=None)])
        item = extend_expiry("Rice", days=7, location="pantry",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-19"

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert extend_expiry("Nonexistent", days=3) is None

    def test_preserves_other_fields(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Yogurt", quantity=2, unit="ct",
                                 category="dairy", location="fridge",
                                 for_recipe="Smoothie", expires="2026-07-14")])
        item = extend_expiry("Yogurt", days=5, location="fridge",
                             today=date(2026, 7, 12))
        assert item.quantity == 2
        assert item.unit == "ct"
        assert item.for_recipe == "Smoothie"
