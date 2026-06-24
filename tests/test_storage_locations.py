"""Tests for lib/storage_locations.py — the storage-location lookup table."""
import json

import pytest

from lib import storage_locations as sl


def test_item_override_beats_category():
    # bananas are produce, but the item table sends them to the counter
    assert sl.resolve_location("bananas", "produce") == "counter"
    assert sl.resolve_location("yellow onions", "produce") == "pantry"


def test_word_subset_match():
    # "roma tomatoes" isn't a literal key, but "tomatoes" is contained
    assert sl.resolve_location("roma tomatoes", "produce") == "counter"
    assert sl.resolve_location("organic sweet potatoes", "produce") == "pantry"


def test_category_fallback():
    assert sl.resolve_location("whole milk", "dairy") == "fridge"
    assert sl.resolve_location("ground beef", "meat") == "fridge"
    assert sl.resolve_location("frozen peas", "frozen") == "freezer"
    assert sl.resolve_location("paper towels", "household") == "other"


def test_unknown_defaults_to_pantry():
    assert sl.resolve_location("mystery item", None) == "pantry"
    assert sl.resolve_location("", "") == "pantry"


def test_always_valid_vocab(monkeypatch, tmp_path):
    # A corrupt location in the table is normalized to valid vocab
    table = tmp_path / "storage_locations.json"
    table.write_text(json.dumps({
        "by_item": {"weird": "garage"},
        "by_category": {},
    }))
    monkeypatch.setattr(sl, "TABLE_PATH", table)
    assert sl.resolve_location("weird", None) == "other"


def test_missing_table_is_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "TABLE_PATH", tmp_path / "does_not_exist.json")
    assert sl.resolve_location("bananas", "produce") == "pantry"


def test_save_item_override_roundtrips(monkeypatch, tmp_path):
    table = tmp_path / "storage_locations.json"
    monkeypatch.setattr(sl, "TABLE_PATH", table)
    sl.save_item_override("Dragonfruit", "Fridge")
    # persisted, normalized, and resolvable
    assert sl.resolve_location("dragonfruit", "produce") == "fridge"
    data = json.loads(table.read_text())
    assert data["by_item"]["dragonfruit"] == "fridge"
