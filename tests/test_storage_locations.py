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
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    assert sl.resolve_location("weird", None) == "other"


def test_missing_table_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(tmp_path / "does_not_exist.json"))
    assert sl.resolve_location("bananas", "produce") == "pantry"


def test_save_item_override_roundtrips(monkeypatch, tmp_path):
    table = tmp_path / "storage_locations.json"
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    sl.save_item_override("Dragonfruit", "Fridge")
    # persisted, normalized, and resolvable
    assert sl.resolve_location("dragonfruit", "produce") == "fridge"
    data = json.loads(table.read_text())
    assert data["by_item"]["dragonfruit"] == "fridge"


@pytest.fixture
def fixture_table(monkeypatch, tmp_path):
    """A known table, independent of the real config.

    These assertions must not read `config/storage_locations.json`: since a move
    teaches, that file is now mutable production state. Moving bananas to the
    freezer on `/review` would otherwise break the unit suite.
    """
    table = tmp_path / "storage_locations.json"
    table.write_text(json.dumps({
        "by_item": {"bananas": "counter"},
        "by_category": {"dairy": "fridge", "produce": "fridge", "other": "pantry"},
    }))
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    return table


def test_place_item_reports_the_item_tier(fixture_table):
    p = sl.place_item("bananas", "produce")
    assert (p.location, p.source) == ("counter", "item")


def test_place_item_reports_the_category_tier(fixture_table):
    p = sl.place_item("whole milk", "dairy")
    assert (p.location, p.source) == ("fridge", "category")


def test_catch_all_category_is_not_an_answer(fixture_table):
    # `other` is where normalize_category sends anything it couldn't place, so
    # a location derived from it is a shrug, not a placement. The location it
    # yields is still pantry — only the confidence differs.
    p = sl.place_item("psyllium husk", "other")
    assert p.location == "pantry"
    assert p.source == "default"


def test_missing_category_is_default():
    assert sl.place_item("mystery item", None) == sl.Placement("pantry", "default")
    assert sl.place_item("", "") == sl.Placement("pantry", "default")


def test_longest_item_key_wins(monkeypatch, tmp_path):
    # Teaching grows by_item on every correction, so a short key must not
    # capture a longer, more specific one: "milk" must not swallow
    # "milk chocolate chips".
    table = tmp_path / "storage_locations.json"
    table.write_text(json.dumps({
        "by_item": {"milk": "fridge", "milk chocolate chips": "pantry"},
        "by_category": {},
    }))
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    assert sl.place_item("milk chocolate chips", None).location == "pantry"
    assert sl.place_item("whole milk", None).location == "fridge"


def test_resolve_location_still_returns_a_bare_string(fixture_table):
    # Four callers depend on this contract; place_item must not leak through.
    assert sl.resolve_location("whole milk", "dairy") == "fridge"
    assert sl.resolve_location("bananas", "produce") == "counter"
    assert isinstance(sl.resolve_location("mystery item", None), str)


def test_a_corrupt_table_is_never_overwritten(monkeypatch, tmp_path):
    """load_table degrades an unparseable file to empty tiers so reads keep
    working. save_table must not then write those empties back — the module
    docstring invites hand-editing, so one typo plus one move would destroy
    every curated override and category rule.
    """
    table = tmp_path / "storage_locations.json"
    original = json.dumps({"by_item": {"bananas": "counter"},
                           "by_category": {"produce": "fridge"}})
    table.write_text(original.replace('"by_item": {', '"by_item": {,', 1))
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    before = table.read_text()

    # Raises rather than returning quietly, so `_teach_location` surfaces it on
    # stderr — it already swallows OSError so the committed move still stands.
    with pytest.raises(OSError, match="does not parse"):
        sl.save_item_override("oat milk", "fridge")

    assert table.read_text() == before, "a corrupt table was overwritten"


def test_a_missing_table_is_still_created(monkeypatch, tmp_path):
    """Refusing to clobber a *corrupt* file must not stop a first write."""
    table = tmp_path / "sub" / "storage_locations.json"
    monkeypatch.setenv("KITCHENOS_STORAGE_TABLE", str(table))
    sl.save_item_override("oat milk", "fridge")
    assert json.loads(table.read_text())["by_item"] == {"oat milk": "fridge"}
