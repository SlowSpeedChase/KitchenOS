"""The dish_type controlled vocabulary, and the biscuit rule that corrupted it."""

from lib import normalizer


def test_vocabulary_has_thirteen_values():
    assert len(normalizer.VALID_DISH_TYPES) == 13


def test_biscuit_no_longer_maps_to_dessert():
    """'biscuit' -> 'dessert' filed savory biscuits as desserts.

    Left in place, it re-corrupts the data on the next extraction, so the
    one-off repair would silently rot.
    """
    assert "biscuit" not in normalizer.DISH_TYPE_MAP


def test_savory_biscuit_is_not_normalized_to_dessert():
    assert normalizer.normalize_field("dish_type", "biscuit") != "dessert"
