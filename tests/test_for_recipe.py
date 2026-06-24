"""Tests for the for_recipe column: model merge, view render, DB migration."""
import sqlite3

from lib import inventory_db as idb
from lib.inventory import (
    InventoryItem,
    _merge_recipes,
    add_items,
    read_inventory,
    render_inventory_md,
)


class TestMergeRecipes:
    def test_union_preserves_order_and_dedups(self):
        assert _merge_recipes("A", "B") == "A, B"
        assert _merge_recipes("A, B", "B") == "A, B"
        assert _merge_recipes("A, B", "C") == "A, B, C"

    def test_none_and_empty(self):
        assert _merge_recipes(None, None) is None
        assert _merge_recipes("A", None) == "A"
        assert _merge_recipes(None, "A") == "A"
        assert _merge_recipes("", "") is None


class TestAddItemsUnionsRecipes:
    def test_same_item_two_recipes_combines(self, tmp_vault, tmp_db):
        add_items([InventoryItem(
            name="chicken breast", quantity=2, unit="lb",
            category="meat", location="fridge", for_recipe="Recipe A",
        )])
        add_items([InventoryItem(
            name="chicken breast", quantity=1, unit="lb",
            category="meat", location="fridge", for_recipe="Recipe B",
        )])
        items = read_inventory()
        assert len(items) == 1
        assert items[0].quantity == 3
        assert items[0].for_recipe == "Recipe A, Recipe B"


def test_render_includes_for_recipe_column(tmp_vault):
    md = render_inventory_md([InventoryItem(
        name="milk", quantity=1, unit="gal", category="dairy",
        location="fridge", for_recipe="Pancakes",
    )])
    assert "For Recipe" in md
    assert "Pancakes" in md


def test_for_recipe_persists_through_db(tmp_db):
    idb.replace_inventory_rows([{
        "name": "garlic", "quantity": 3, "unit": "ct", "category": "produce",
        "location": "pantry", "purchased": None, "source": "receipt",
        "notes": "", "for_recipe": "Garlic Bread",
    }])
    rows = idb.fetch_inventory_rows()
    assert rows[0]["for_recipe"] == "Garlic Bread"


def test_migration_adds_column_to_legacy_db(tmp_db):
    """A pre-existing DB without for_recipe gets the column on connect()."""
    # Build a legacy inventory/purchases schema (no for_recipe), with a row.
    raw = sqlite3.connect(tmp_db)
    raw.executescript(
        "CREATE TABLE inventory (id INTEGER PRIMARY KEY, name TEXT,"
        " quantity REAL, unit TEXT, category TEXT, location TEXT,"
        " purchased TEXT, source TEXT, notes TEXT);"
        "CREATE TABLE purchases (id INTEGER PRIMARY KEY, trip_id INTEGER,"
        " raw_name TEXT, canonical_name TEXT, quantity REAL, unit TEXT,"
        " unit_price_cents INTEGER, total_cents INTEGER, category TEXT);"
        "CREATE TABLE trips (id INTEGER PRIMARY KEY, date TEXT, store TEXT,"
        " source TEXT, source_id TEXT, total_cents INTEGER,"
        " needs_review INTEGER, raw_text TEXT, created_at TEXT);"
        "INSERT INTO inventory (name, quantity, unit) VALUES ('eggs', 12, 'ct');"
    )
    raw.commit()
    raw.close()

    conn = idb.connect()
    inv_cols = {r["name"] for r in conn.execute("PRAGMA table_info(inventory)")}
    pur_cols = {r["name"] for r in conn.execute("PRAGMA table_info(purchases)")}
    # existing data survives the migration
    eggs = conn.execute("SELECT for_recipe FROM inventory WHERE name='eggs'").fetchone()
    conn.close()
    assert "for_recipe" in inv_cols
    assert "for_recipe" in pur_cols
    assert eggs["for_recipe"] is None
