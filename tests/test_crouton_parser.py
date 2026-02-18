"""Tests for Crouton .crumb file parser"""

import pytest
from lib.crouton_parser import map_quantity_type


class TestMapQuantityType:
    """Maps Crouton quantityType enum to KitchenOS unit strings"""

    def test_cup(self):
        assert map_quantity_type("CUP") == "cup"

    def test_tablespoon(self):
        assert map_quantity_type("TABLESPOON") == "tbsp"

    def test_teaspoon(self):
        assert map_quantity_type("TEASPOON") == "tsp"

    def test_grams(self):
        assert map_quantity_type("GRAMS") == "g"

    def test_ounce(self):
        assert map_quantity_type("OUNCE") == "oz"

    def test_pound(self):
        assert map_quantity_type("POUND") == "lb"

    def test_fluid_ounce(self):
        assert map_quantity_type("FLUID_OUNCE") == "fl oz"

    def test_mills(self):
        assert map_quantity_type("MILLS") == "ml"

    def test_kgs(self):
        assert map_quantity_type("KGS") == "kg"

    def test_can(self):
        assert map_quantity_type("CAN") == "can"

    def test_bunch(self):
        assert map_quantity_type("BUNCH") == "bunch"

    def test_packet(self):
        assert map_quantity_type("PACKET") == "packet"

    def test_pinch(self):
        assert map_quantity_type("PINCH") == "pinch"

    def test_item(self):
        assert map_quantity_type("ITEM") == "whole"

    def test_unknown_returns_whole(self):
        assert map_quantity_type("UNKNOWN_UNIT") == "whole"

    def test_none_returns_whole(self):
        assert map_quantity_type(None) == "whole"
