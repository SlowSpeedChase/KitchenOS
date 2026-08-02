"""Tests for scripts/enrich_recipes.py — which fields get asked, and how a
genuinely uncooked recipe settles.

Background: cook_time missed 3-for-3 on a sample because every honest way of
saying "this isn't cooked" ("0 minutes", "none", "n/a") is a junk placeholder
from the old extractor, so the field stayed empty and was re-asked on every
run — a recipe with no cook step could never reach `complete`.
"""

import importlib

import pytest

enrich_recipes = importlib.import_module("scripts.enrich_recipes")

fields_to_ask = enrich_recipes.fields_to_ask
clean_value = enrich_recipes.clean_value
is_missing = enrich_recipes.is_missing
NO_COOK = enrich_recipes.NO_COOK


def test_no_cook_types_are_real_dish_types():
    """A typo here fails silently — the value simply never matches a recipe.

    dish_type is a closed vocabulary (see CLAUDE.md); anything outside it is
    unreachable, so pin the set to normalizer's own list rather than trusting
    the spelling.
    """
    from lib import normalizer
    unknown = enrich_recipes.NO_COOK_DISH_TYPES - set(normalizer.VALID_DISH_TYPES)
    assert not unknown, f"not real dish types: {sorted(unknown)}"


class TestNoCookDishTypes:
    """cook_time is not asked for dish types that are essentially never cooked."""

    @pytest.mark.parametrize("dish_type", ["drink", "snack"])
    def test_cook_time_not_asked(self, dish_type):
        asked = fields_to_ask({"dish_type": dish_type})
        assert "cook_time" not in asked

    def test_other_fields_still_asked_for_those_types(self):
        asked = fields_to_ask({"dish_type": "drink"})
        assert "servings" in asked and "cuisine" in asked

    @pytest.mark.parametrize("dish_type", ["main", "dip", "sauce", "dessert",
                                           "salad", "bread", "soup"])
    def test_cook_time_still_asked_for_cooked_types(self, dish_type):
        """A baked queso is a dip and a marinara is a sauce — those keep asking."""
        assert "cook_time" in fields_to_ask({"dish_type": dish_type})

    def test_unset_dish_type_still_asks(self):
        """dish_type is itself inferable, so it may not be known yet."""
        assert "cook_time" in fields_to_ask({})

    def test_dish_type_is_matched_case_insensitively(self):
        assert "cook_time" not in fields_to_ask({"dish_type": "Drink"})

    def test_dish_type_as_a_list_is_tolerated(self):
        assert "cook_time" not in fields_to_ask({"dish_type": ["snack"]})

    def test_present_fields_are_never_asked(self):
        asked = fields_to_ask({"dish_type": "main", "servings": 4})
        assert "servings" not in asked

    def test_only_servings_mode_asks_just_servings(self):
        assert fields_to_ask({"dish_type": "main"}, only_servings=True) == ["servings"]


class TestNoCookSettles:
    """Any dish type can be uncooked; an explicit no-cook answer must stick."""

    def test_sentinel_is_accepted(self):
        assert clean_value("cook_time", NO_COOK) == NO_COOK

    def test_sentinel_is_case_insensitive(self):
        assert clean_value("cook_time", NO_COOK.upper()) == NO_COOK

    def test_sentinel_reads_as_present_so_it_is_never_reasked(self):
        """The whole point: once written, the field stops being missing."""
        assert not is_missing(NO_COOK)
        assert "cook_time" not in fields_to_ask({"dish_type": "main",
                                                 "cook_time": NO_COOK})

    @pytest.mark.parametrize("junk", ["none", "n/a", "null", "0 minutes",
                                      "0 seconds", "unknown", ""])
    def test_vague_answers_are_still_rejected(self, junk):
        """"I don't know" must not be recorded as "there is no cooking".

        Only the exact sentinel counts, so absence stays distinguishable from
        a positive claim that the recipe is uncooked.
        """
        assert clean_value("cook_time", junk) is None

    def test_real_durations_are_unaffected(self):
        assert clean_value("cook_time", "25 minutes") == "25 minutes"

    def test_sentinel_is_not_accepted_for_other_time_fields(self):
        """Every recipe has prep; "no cooking" is meaningless there."""
        assert clean_value("prep_time", NO_COOK) is None


class TestFieldsWithNoValue:
    """protein and dietary have the same "no way to say none" problem as
    cook_time — but their answer cannot be written into the field.

    protein feeds recipe_index.FILTER_FIELDS and is rendered as an Obsidian
    tag, so a sentinel there becomes a "none" filter chip and a #none tag.
    dietary is a tag vocabulary with the same issue. Both are recorded in a
    separate key instead.
    """

    apply_response = staticmethod(enrich_recipes.apply_response)
    KEY = enrich_recipes.ENRICH_NONE_KEY

    def test_protein_none_is_recorded_out_of_band(self):
        updates, none_fields = self.apply_response(
            ["protein"], {"protein": "no main protein"})
        assert "protein" not in updates, "must not pollute the filter/tag field"
        assert none_fields == ["protein"]

    def test_dietary_none_is_recorded_out_of_band(self):
        updates, none_fields = self.apply_response(
            ["dietary"], {"dietary": "no dietary tags"})
        assert "dietary" not in updates
        assert none_fields == ["dietary"]

    def test_a_real_answer_still_writes_the_field(self):
        updates, none_fields = self.apply_response(["protein"], {"protein": "chicken"})
        assert updates["protein"] == "chicken"
        assert none_fields == []

    def test_recorded_fields_are_not_reasked(self):
        assert "protein" not in fields_to_ask({self.KEY: ["protein"]})
        assert "dietary" not in fields_to_ask({self.KEY: ["dietary"]})

    def test_other_fields_unaffected_by_the_marker(self):
        assert "cuisine" in fields_to_ask({self.KEY: ["protein"]})

    def test_template_default_empty_dietary_is_still_asked(self):
        """The recipe template writes `dietary: []` for every new recipe, so an
        empty list cannot mean "already answered" — only the marker can."""
        assert "dietary" in fields_to_ask({"dietary": []})

    def test_vague_answers_do_not_count_as_a_none_claim(self):
        for junk in ["none", "n/a", "unknown", ""]:
            updates, none_fields = self.apply_response(["protein"], {"protein": junk})
            assert none_fields == [], f"{junk!r} must not assert 'no protein'"
            assert "protein" not in updates

    def test_sentinel_is_not_honoured_for_an_unrelated_field(self):
        updates, none_fields = self.apply_response(
            ["cuisine"], {"cuisine": "no main protein"})
        assert none_fields == []

    def test_marker_key_is_managed_so_it_can_be_written(self):
        assert self.KEY in enrich_recipes.MANAGED_KEYS


class TestEnrichWritesEscapedScalars:
    """The enricher writes LLM output straight into frontmatter.

    Its local yaml_scalar was f'"{v}"' for strings and
    '[' + ', '.join(f'"{x}"') + ']' for lists — so a cuisine or dietary tag
    containing a double quote broke the file. It now delegates to the one
    authority in lib.frontmatter.
    """

    def test_it_delegates_to_the_shared_helper(self):
        from lib import frontmatter
        from scripts import enrich_recipes
        assert enrich_recipes.yaml_scalar is frontmatter.scalar

    def test_a_quote_in_a_string_value_round_trips(self):
        import yaml
        from scripts.enrich_recipes import yaml_scalar
        value = 'the 9" style'
        assert yaml.safe_load(f"cuisine: {yaml_scalar(value)}\n")["cuisine"] == value

    def test_a_quote_in_a_list_item_round_trips(self):
        import yaml
        from scripts.enrich_recipes import yaml_scalar
        items = ["gluten-free", 'has a " quote']
        out = yaml.safe_load(f"dietary: {yaml_scalar(items)}\n")
        assert out["dietary"] == items

    def test_booleans_and_ints_keep_their_yaml_type(self):
        import yaml
        from scripts.enrich_recipes import yaml_scalar
        assert yaml.safe_load(f"needs_review: {yaml_scalar(True)}\n")["needs_review"] is True
        assert yaml.safe_load(f"servings: {yaml_scalar(4)}\n")["servings"] == 4
