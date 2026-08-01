"""Phase B: making an ingredient line read the way a cook would write it."""

import pytest

from lib.ingredient_presentation import (
    collapse_repeats,
    drop_unit_echo,
    rejoin_percentage,
    repair,
    strip_source_noise,
    unit_column_holds_the_ingredient,
)


class TestPercentage:
    """"2% milk" is one name; the extractor eats the 2 as an amount."""

    @pytest.mark.parametrize("amount,item,out_amount,out_item", [
        ("2", "% milk", "1", "2% milk"),
        ("93", "% beef", "1", "93% beef"),
        ("1", "% greek yogurt", "1", "1% greek yogurt"),
        ("2.0", "% milk", "1", "2% milk"),
    ])
    def test_rejoined(self, amount, item, out_amount, out_item):
        a, i, notes = rejoin_percentage(amount, item)
        assert (a, i) == (out_amount, out_item)
        assert notes

    def test_the_amount_becomes_one_because_none_was_stated(self):
        """"2% milk" says nothing about how much milk — 2 was never a quantity."""
        assert rejoin_percentage("2", "% milk")[0] == "1"

    @pytest.mark.parametrize("amount,item", [
        ("", "% milk"), ("two", "% milk"), ("2", "milk"), ("2", "%"),
    ])
    def test_left_alone_when_not_this_shape(self, amount, item):
        assert rejoin_percentage(amount, item)[:2] == (amount, item)


class TestSourceNoise:
    @pytest.mark.parametrize("item,expected", [
        ("cream cheese, softened ($1.89)", "cream cheese, softened"),
        ("vanilla extract ($1.00)", "vanilla extract"),
        ("frozen blueberries (130g, $0.82)", "frozen blueberries (130g)"),
        ("vinegar (see note 5 for subs)", "vinegar"),
        ("@fit.flour (code:shredz)", "@fit.flour"),
    ])
    def test_stripped(self, item, expected):
        assert strip_source_noise(item)[0] == expected

    def test_a_real_weight_aside_survives(self):
        """gram_equivalent reads these later — stripping them would destroy the
        most accurate weight the recipe has."""
        assert strip_source_noise("light brown sugar (165 g)")[0] == "light brown sugar (165 g)"

    def test_prep_notes_survive(self):
        assert strip_source_noise("chives (chopped fresh)")[0] == "chives (chopped fresh)"

    def test_never_empties_the_name(self):
        assert strip_source_noise("($1.89)")[0] == "($1.89)"


class TestRepeats:
    @pytest.mark.parametrize("item,expected", [
        ("salt salt", "salt"),
        ("water water", "water"),
        ("egg whites egg whites", "egg whites"),
        ("whole egg whites egg whites", "whole egg whites"),
        ("mediterranean marinade marinade", "mediterranean marinade"),
    ])
    def test_collapsed(self, item, expected):
        assert collapse_repeats(item)[0] == expected

    @pytest.mark.parametrize("item", [
        "salt and pepper", "black bean burger", "chicken chicken-style seasoning",
    ])
    def test_distinct_words_untouched(self, item):
        assert collapse_repeats(item)[0] == item


class TestUnitEcho:
    @pytest.mark.parametrize("item,expected", [
        ("whole lemons", "lemons"),
        ("whole dark chocolate", "dark chocolate"),
        ("whole avocado", "avocado"),
        ("whole egg yolks", "egg yolks"),
    ])
    def test_echo_dropped(self, item, expected):
        assert drop_unit_echo("whole", item)[0] == expected

    @pytest.mark.parametrize("item", ["whole milk", "whole wheat flour", "whole grain bread"])
    def test_product_names_survive(self, item):
        """whole milk is not milk. Dropping the word changes the food."""
        assert drop_unit_echo("whole", item)[0] == item

    def test_bare_echo_is_kept(self):
        assert drop_unit_echo("whole", "whole")[0] == "whole"

    def test_unrelated_unit_untouched(self):
        assert drop_unit_echo("cup", "flour")[0] == "flour"


class TestUnitColumnHoldsIngredient:
    @pytest.mark.parametrize("unit,item", [("lemon", "lemon"), ("onion", "onion"),
                                           ("avocado", "avocado"), ("flax egg", "flax egg")])
    def test_duplicated_across_columns(self, unit, item):
        u, i, notes = unit_column_holds_the_ingredient(unit, item)
        assert (u, i) == ("whole", item)
        assert notes

    def test_a_name_split_across_columns_is_left_for_a_human(self):
        """Rejoining needs a food vocabulary: "corn"+"tortillas" is right but
        "blorp"+"flour" would invent a plausible-looking ingredient out of junk.
        A3 already flags these needs_review, so they reach a human anyway."""
        assert unit_column_holds_the_ingredient("corn", "tortillas") [:2] == ("corn", "tortillas")
        assert unit_column_holds_the_ingredient("blorp", "flour")[:2] == ("blorp", "flour")

    @pytest.mark.parametrize("unit", ["handful", "pinch", "clove", "can", "bunch", "stick"])
    def test_informal_units_are_real_units(self, unit):
        """"1 handful | fresh cilantro" must not become "handful fresh cilantro"."""
        u, i, _ = unit_column_holds_the_ingredient(unit, "fresh cilantro")
        assert (u, i) == (unit, "fresh cilantro")

    @pytest.mark.parametrize("unit", ["cup", "tbsp", "g", "oz", "whole"])
    def test_canonical_units_untouched(self, unit):
        u, i, _ = unit_column_holds_the_ingredient(unit, "flour")
        assert (u, i) == (unit, "flour")


class TestRepairEndToEnd:
    @pytest.mark.parametrize("amount,unit,item,expected", [
        ("2", "whole", "% milk", ("1", "whole", "2% milk")),
        ("1", "whole", "whole dark chocolate", ("1", "whole", "dark chocolate")),
        ("1", "whole", "salt salt", ("1", "whole", "salt")),
        ("3", "whole", "whole egg whites egg whites", ("3", "whole", "egg whites")),
        ("1", "lemon", "lemon", ("1", "whole", "lemon")),
        ("8", "oz", "cream cheese, softened ($1.89)", ("8", "oz", "cream cheese, softened")),
    ])
    def test_reported_defects(self, amount, unit, item, expected):
        assert repair(amount, unit, item)[:3] == expected

    def test_a_clean_line_is_returned_unchanged(self):
        assert repair("0.5", "cup", "greek yogurt")[:3] == ("0.5", "cup", "greek yogurt")

    def test_a_stated_weight_survives_the_whole_pipeline(self):
        """Phase B runs before nutrition reads the weight, so it must not eat it."""
        assert repair("0.75", "cup", "light brown sugar (165 g)")[:3] == (
            "0.75", "cup", "light brown sugar (165 g)")
