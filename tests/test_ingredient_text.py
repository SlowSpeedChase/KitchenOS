import lib.ingredient_text as ingredient_text
from lib.ingredient_text import clean_for_matching, apply_aliases


def test_strips_parentheticals():
    assert clean_for_matching(
        "blanched almond flour (spooned and leveled)") == "blanched almond flour"


def test_strips_inferred_marker():
    assert clean_for_matching("olive oil *(inferred)*") == "olive oil"


def test_strips_prep_phrases():
    assert clean_for_matching("extra-virgin olive oil, plus more for serving") \
        == "extra-virgin olive oil"
    assert clean_for_matching("fresh cilantro, finely chopped") == "fresh cilantro"


def test_collapses_doubled_words():
    assert clean_for_matching("garlic garlic cloves") == "garlic cloves"


def test_alias_lookup():
    assert apply_aliases("evoo") == "olive oil"


def test_alias_passthrough():
    assert apply_aliases("ground beef") == "ground beef"


def test_prep_tail_leaves_non_prep_trailing_word():
    # "nuts" is food identity, not prep — the whole tail must survive.
    assert clean_for_matching("salt, chopped nuts") == "salt, chopped nuts"


def test_prep_tail_strips_pure_prep_segment():
    # A trailing segment that is entirely prep vocabulary strips away, even
    # when that leaves just the base food — matching favors the base food.
    assert clean_for_matching("tomatoes, diced") == "tomatoes"


def test_prep_tail_covers_toasted():
    assert clean_for_matching("walnuts, toasted") == "walnuts"


def test_prep_tail_strips_multiple_pure_prep_segments():
    assert clean_for_matching("chicken, cooked, shredded") == "chicken"


def test_aliases_malformed_yaml_passthrough(tmp_path, monkeypatch):
    bad = tmp_path / "food_aliases.yml"
    bad.write_text("evoo: [unterminated\n", encoding="utf-8")
    monkeypatch.setattr(ingredient_text, "_ALIASES_PATH", bad)
    assert apply_aliases("evoo") == "evoo"


def test_aliases_non_dict_yaml_passthrough(tmp_path, monkeypatch):
    bad = tmp_path / "food_aliases.yml"
    bad.write_text("- one\n- two\n", encoding="utf-8")
    monkeypatch.setattr(ingredient_text, "_ALIASES_PATH", bad)
    assert apply_aliases("evoo") == "evoo"


class TestRecoverRangeRemnant:
    """A split range leaves the real unit stranded in the ingredient name.

    "1 1/2 to 2 teaspoons dijon mustard" is stored as:

        | 1.5 | whole | to 2 teaspoons dijon mustard |

    The amount kept the low end, the unit was *fabricated* — `whole` is
    `ingredient_parser`'s default for anything it can't read — and the real unit
    is sitting in the name. So `to_grams(1.5, "whole", "to 2 teaspoons dijon
    mustard")` has nothing to work with, and the food match sees a name beginning
    with a number. 132 rows across 76 recipes look like this.

    Recovery is gated on the unit being exactly the fabricated `whole`: if the
    row carries a real unit, the row is not this defect and must not be rewritten.
    The midpoint matches `units.parse_amount_to_float`, which already averages
    "3-4" to 3.5 — this is the same range, split across two columns.
    """

    def _recover(self, amount, unit, item):
        from lib.ingredient_text import recover_range_remnant
        return recover_range_remnant(amount, unit, item)

    def test_the_unit_is_recovered_and_the_amount_becomes_the_midpoint(self):
        assert self._recover("1.5", "whole", "to 2 teaspoons dijon mustard") == (
            "1.75", "teaspoons", "dijon mustard")

    def test_a_mixed_fraction_high_end_is_read(self):
        assert self._recover("1", "whole", "to 1 1/2 cups brown rice") == (
            "1.25", "cups", "brown rice")

    def test_the_rest_of_the_name_is_preserved(self):
        amount, unit, item = self._recover(
            "2", "whole", "to 3 tablespoons extra-virgin olive oil , or oil of choice")
        assert (amount, unit) == ("2.5", "tablespoons")
        assert item == "extra-virgin olive oil , or oil of choice"

    def test_a_row_with_a_real_unit_is_left_alone(self):
        """Not this defect — don't rewrite a row that parsed correctly."""
        assert self._recover("1", "cup", "to 2 cups rice") == ("1", "cup", "to 2 cups rice")

    def test_an_ordinary_row_is_untouched(self):
        assert self._recover("2", "tbsp", "olive oil") == ("2", "tbsp", "olive oil")

    def test_an_unreadable_amount_is_left_alone(self):
        assert self._recover("", "whole", "to 2 teaspoons dijon") == (
            "", "whole", "to 2 teaspoons dijon")

    def test_a_trailing_word_that_is_not_a_unit_is_left_alone(self):
        """"to 2 chipotle peppers" is a count range, not a stranded unit."""
        assert self._recover("1", "whole", "to 2 chipotle peppers in adobo") == (
            "1", "whole", "to 2 chipotle peppers in adobo")
