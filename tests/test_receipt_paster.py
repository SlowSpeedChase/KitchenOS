"""Tests for the markdown receipt-paste parser."""

from lib.receipt_paster import parse_inventory_table, preview, commit

TABLE = """\
| Item | Qty | Unit | Category | Location | Expires | Notes |
|------|-----|------|----------|----------|---------|-------|
| Milk | 1 | gal | dairy | fridge | 2026-07-01 | organic |
| Bananas | 6 | ct | produce | | | |
| Black beans | 3 | can | pantry | | | bulk |
"""


class TestParse:
    def test_parses_rows(self):
        items = parse_inventory_table(TABLE)["items"]
        assert [i.name for i in items] == ["Milk", "Bananas", "Black beans"]

    def test_explicit_fields_preserved(self):
        milk = parse_inventory_table(TABLE)["items"][0]
        assert milk.quantity == 1.0
        assert milk.unit == "gal"
        assert milk.category == "dairy"
        assert milk.location == "fridge"
        assert milk.expires == "2026-07-01"
        assert milk.notes == "organic"

    def test_missing_location_auto_resolves(self):
        # Bananas have a by_item override (counter) in storage_locations.json
        bananas = parse_inventory_table(TABLE)["items"][1]
        assert bananas.location == "counter"

    def test_missing_expiry_auto_fills_for_known_window(self):
        bananas = parse_inventory_table(TABLE)["items"][1]
        assert bananas.expires is not None  # produce/bananas window

    def test_quantity_defaults_to_one(self):
        items = parse_inventory_table("| Item |\n|------|\n| Salt |\n")["items"]
        assert items[0].quantity == 1.0

    def test_header_aliases(self):
        md = "| Name | Amount | Units |\n|---|---|---|\n| Rice | 2 | lb |\n"
        item = parse_inventory_table(md)["items"][0]
        assert item.name == "Rice" and item.quantity == 2.0 and item.unit == "lb"

    def test_unknown_column_warns_but_parses(self):
        md = "| Item | Color |\n|---|---|\n| Apple | red |\n"
        result = parse_inventory_table(md)
        assert result["items"][0].name == "Apple"
        assert any("Color" in w for w in result["warnings"])

    def test_no_table_warns(self):
        result = parse_inventory_table("just some text")
        assert result["items"] == []
        assert result["warnings"]

    def test_missing_item_column_rejected(self):
        result = parse_inventory_table("| Qty | Unit |\n|---|---|\n| 1 | ct |\n")
        assert result["items"] == []
        assert any("Item" in w for w in result["warnings"])

    def test_blank_rows_skipped(self):
        md = "| Item | Qty |\n|---|---|\n| Eggs | 12 |\n|  |  |\n"
        items = parse_inventory_table(md)["items"]
        assert len(items) == 1


class TestPreviewCommit:
    def test_preview_does_not_write(self, tmp_vault, tmp_db):
        from lib.inventory import read_inventory
        out = preview(TABLE)
        assert out["count"] == 3
        assert read_inventory() == []  # nothing persisted

    def test_commit_persists(self, tmp_vault, tmp_db):
        from lib.inventory import read_inventory
        result = commit(TABLE)
        assert result["added"] == 3
        assert {i.name for i in read_inventory()} == {"Milk", "Bananas", "Black beans"}
