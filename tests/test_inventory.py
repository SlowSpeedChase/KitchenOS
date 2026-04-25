"""Tests for the kitchen inventory module."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lib.inventory import (
    INVENTORY_FILENAME,
    InventoryRow,
    append_rows,
    apply_default_expiry,
    load_layout,
    lookup_group,
    parse_inventory_md,
    render_inventory_md,
    route_item,
)
from lib.receipt_paster import parse_paste, parse_table
from templates.inventory_template import render_skeleton
from templates.labels_template import render_labels


@pytest.fixture(scope="module")
def layout():
    return load_layout()


class TestLoadLayout:
    def test_loads_groups_and_shelves(self, layout):
        assert "dairy" in layout.groups
        assert layout.groups["dairy"].default_expiry_days == 14
        assert any(s.location_id == "fridge/middle" for s in layout.shelves)

    def test_unique_shelf_ids_within_space(self, layout):
        seen = set()
        for shelf in layout.shelves:
            assert shelf.location_id not in seen
            seen.add(shelf.location_id)

    def test_every_shelf_group_is_defined(self, layout):
        for shelf in layout.shelves:
            for gid in shelf.groups:
                assert gid in layout.groups, f"shelf {shelf.location_id} has unknown group {gid}"


class TestRouting:
    def test_known_item_routes_to_expected_group(self, layout):
        group, location, _ = route_item("chicken breast", layout)
        assert group == "proteins-fresh"
        assert location.startswith("fridge/")

    def test_plural_item_still_matches(self, layout):
        # singularized lookup: "kidney beans" -> canned
        group, _, _ = route_item("kidney beans", layout)
        assert group == "canned"

    def test_unknown_item_falls_back_with_warning(self, layout):
        group, _, warnings = route_item("zzz unknown widget", layout)
        assert group == "dry-goods"
        assert any("no group match" in w for w in warnings)

    def test_lookup_group_handles_substring(self, layout):
        # "frozen broccoli" → frozen-veg via substring
        assert lookup_group("frozen broccoli") == "frozen-veg"

    def test_group_override_wins(self, layout):
        group, location, _ = route_item("salmon", layout, group_override="proteins-frozen")
        assert group == "proteins-frozen"
        assert location.startswith("freezer/")

    def test_location_override_wins(self, layout):
        group, location, _ = route_item("milk", layout, location_override="fridge/door")
        assert location == "fridge/door"


class TestDefaultExpiry:
    def test_fills_when_blank(self, layout):
        row = InventoryRow(
            item="chicken breast", qty="2", unit="lb",
            group="proteins-fresh", location="fridge/middle",
            added="2026-04-25",
        )
        apply_default_expiry(row, layout, today=date(2026, 4, 25))
        assert row.expires == "2026-04-29"

    def test_skips_when_already_set(self, layout):
        row = InventoryRow(
            item="x", qty="1", unit="each", group="dairy",
            location="fridge/top", added="2026-04-25",
            expires="2026-12-31",
        )
        apply_default_expiry(row, layout, today=date(2026, 4, 25))
        assert row.expires == "2026-12-31"

    def test_no_default_for_pantry_groups(self, layout):
        row = InventoryRow(
            item="rice", qty="1", unit="lb", group="dry-goods",
            location="main-pantry/middle", added="2026-04-25",
        )
        apply_default_expiry(row, layout, today=date(2026, 4, 25))
        assert row.expires == ""


class TestPasteParsing:
    def test_minimal_table(self, layout):
        md = """| Item | Qty | Unit |
|---|---|---|
| chicken breast | 2 | lb |
| eggs | 12 | each |
"""
        rows, warnings = parse_paste(md, layout, today=date(2026, 4, 25))
        assert len(rows) == 2
        assert rows[0].item == "chicken breast"
        assert rows[0].location.startswith("fridge/")
        assert rows[1].item == "eggs"
        assert warnings == []

    def test_extra_columns_for_overrides(self, layout):
        md = """| Item | Qty | Unit | Group | Location |
|---|---|---|---|---|
| salmon | 1 | lb | proteins-frozen | freezer/middle |
"""
        rows, _ = parse_paste(md, layout, today=date(2026, 4, 25))
        assert len(rows) == 1
        assert rows[0].group == "proteins-frozen"
        assert rows[0].location == "freezer/middle"

    def test_qty_unit_fallbacks(self, layout):
        md = """| Item |
|---|
| garlic |
"""
        rows, _ = parse_paste(md, layout)
        assert len(rows) == 1
        assert rows[0].qty == "1"
        assert rows[0].unit == "each"

    def test_no_table_returns_warning(self, layout):
        rows, warnings = parse_paste("just some prose", layout)
        assert rows == []
        assert warnings

    def test_missing_item_column_errors(self, layout):
        md = "| Qty | Unit |\n|---|---|\n| 2 | lb |"
        rows, warnings = parse_paste(md, layout)
        assert rows == []
        assert any("Item" in w for w in warnings)

    def test_header_aliases(self, layout):
        md = """| Name | Amount | UoM |
|---|---|---|
| eggs | 6 | each |
"""
        rows, _ = parse_paste(md, layout)
        assert len(rows) == 1
        assert rows[0].item == "eggs"
        assert rows[0].qty == "6"


class TestRoundTrip:
    def test_parse_render_is_stable(self, layout):
        md = """| Item | Qty | Unit |
|---|---|---|
| chicken breast | 2 | lb |
| eggs | 12 | each |
| black beans | 4 | can |
"""
        rows, _ = parse_paste(md, layout, today=date(2026, 4, 25))
        rendered = render_inventory_md(rows, layout, updated=date(2026, 4, 25))
        parsed = parse_inventory_md(rendered, layout)
        rerendered = render_inventory_md(parsed, layout, updated=date(2026, 4, 25))
        assert rendered == rerendered

    def test_append_merges_same_key(self, layout, tmp_path: Path):
        md = """| Item | Qty | Unit |
|---|---|---|
| eggs | 6 | each |
"""
        rows, _ = parse_paste(md, layout, today=date(2026, 4, 25))
        append_rows(rows, layout, tmp_path, today=date(2026, 4, 25))
        rows2, _ = parse_paste(md, layout, today=date(2026, 4, 25))
        append_rows(rows2, layout, tmp_path, today=date(2026, 4, 25))

        content = (tmp_path / INVENTORY_FILENAME).read_text(encoding="utf-8")
        # both pastes coalesced into a single 12-egg row
        egg_lines = [ln for ln in content.splitlines() if "eggs" in ln and "|" in ln]
        assert len(egg_lines) == 1
        assert " 12 " in egg_lines[0]

    def test_append_creates_inventory_file(self, layout, tmp_path: Path):
        rows = [InventoryRow(
            item="rice", qty="2", unit="lb", group="dry-goods",
            location="main-pantry/middle", added="2026-04-25",
        )]
        target = append_rows(rows, layout, tmp_path)
        assert target.exists()
        assert target.name == INVENTORY_FILENAME
        assert "rice" in target.read_text(encoding="utf-8")


class TestSkeletonAndLabels:
    def test_skeleton_has_one_section_per_shelf(self, layout):
        out = render_skeleton(layout, updated=date(2026, 4, 25))
        for shelf in layout.shelves:
            assert f"## {shelf.section_heading}" in out

    def test_labels_groups_by_space(self, layout):
        out = render_labels(layout, generated=date(2026, 4, 25))
        assert "## Main Pantry" in out
        assert "## Fridge" in out
        # one card per shelf with the right groups listed
        for shelf in layout.shelves:
            for gid in shelf.groups:
                assert layout.groups[gid].label in out


class TestParseTable:
    def test_first_table_only(self, layout):
        md = """preamble
| Item | Qty | Unit |
|---|---|---|
| eggs | 12 | each |

other prose

| Item | Qty |
|---|---|
| later | 1 |
"""
        rows, _ = parse_table(md)
        assert len(rows) == 1
        assert rows[0]["item"] == "eggs"
