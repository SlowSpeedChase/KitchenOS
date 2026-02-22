"""Tests for keyword-based seasonal matching fallback in seasonality module."""

from lib.seasonality import (
    keyword_match_seasonal,
    _is_pantry_item,
    _keyword_in_text,
)


class TestIsPantryItem:
    def test_oil_is_pantry(self):
        assert _is_pantry_item("olive oil") is True

    def test_flour_is_pantry(self):
        assert _is_pantry_item("all-purpose flour") is True

    def test_salt_is_pantry(self):
        assert _is_pantry_item("kosher salt") is True

    def test_tomato_is_not_pantry(self):
        assert _is_pantry_item("tomato") is False

    def test_corn_is_not_pantry(self):
        assert _is_pantry_item("fresh corn") is False

    def test_soy_sauce_is_pantry(self):
        assert _is_pantry_item("soy sauce") is True

    def test_pasta_is_pantry(self):
        assert _is_pantry_item("spaghetti pasta") is True

    def test_sugar_is_pantry(self):
        assert _is_pantry_item("brown sugar") is True

    def test_case_insensitive(self):
        assert _is_pantry_item("Olive Oil") is True


class TestKeywordInText:
    def test_direct_match(self):
        assert _keyword_in_text("corn", "fresh corn", set()) is True

    def test_plural_s_match(self):
        assert _keyword_in_text("peach", "large peaches", set()) is True

    def test_plural_es_match(self):
        assert _keyword_in_text("tomato", "cherry tomatoes", set()) is True

    def test_no_match(self):
        assert _keyword_in_text("corn", "olive oil", set()) is False

    def test_claimed_longer_name_blocks(self):
        """If 'sweet potato' is already claimed, 'potato' should not match."""
        claimed = {"sweet potato"}
        assert _keyword_in_text("potato", "sweet potatoes", claimed) is False

    def test_unclaimed_still_matches(self):
        """If nothing is claimed, 'potato' can match 'sweet potatoes'."""
        assert _keyword_in_text("potato", "sweet potatoes", set()) is True

    def test_substring_in_longer_word(self):
        """'corn' should match in 'ears fresh corn'."""
        assert _keyword_in_text("corn", "ears fresh corn", set()) is True


class TestKeywordMatchSeasonal:
    def test_exact_match(self):
        """'corn' -> matches 'corn'"""
        ingredients = [{"item": "corn"}]
        result = keyword_match_seasonal(ingredients)
        assert "corn" in result

    def test_substring_match(self):
        """'cherry tomatoes' -> matches 'tomato'"""
        ingredients = [{"item": "cherry tomatoes"}]
        result = keyword_match_seasonal(ingredients)
        assert "tomato" in result

    def test_compound_ingredient(self):
        """'ears fresh corn' -> matches 'corn'"""
        ingredients = [{"item": "ears fresh corn"}]
        result = keyword_match_seasonal(ingredients)
        assert "corn" in result

    def test_plural_match(self):
        """'large firm-but-ripe peaches' -> matches 'peach'"""
        ingredients = [{"item": "large firm-but-ripe peaches"}]
        result = keyword_match_seasonal(ingredients)
        assert "peach" in result

    def test_skips_pantry_staples(self):
        """'olive oil', 'flour', 'salt' -> 0 matches"""
        ingredients = [
            {"item": "olive oil"},
            {"item": "all-purpose flour"},
            {"item": "kosher salt"},
        ]
        result = keyword_match_seasonal(ingredients)
        assert result == []

    def test_deduplicates(self):
        """'tomatoes' + 'cherry tomatoes' -> one 'tomato'"""
        ingredients = [
            {"item": "tomatoes"},
            {"item": "cherry tomatoes"},
        ]
        result = keyword_match_seasonal(ingredients)
        assert result.count("tomato") == 1
        assert "tomato" in result

    def test_multi_word_seasonal(self):
        """'sweet potatoes' -> 'sweet potato', NOT also 'potato'"""
        ingredients = [{"item": "sweet potatoes"}]
        result = keyword_match_seasonal(ingredients)
        assert "sweet potato" in result
        assert "potato" not in result

    def test_green_bean_match(self):
        """'fresh green beans' -> 'green bean'"""
        ingredients = [{"item": "fresh green beans"}]
        result = keyword_match_seasonal(ingredients)
        assert "green bean" in result

    def test_empty_ingredients(self):
        """[] -> []"""
        result = keyword_match_seasonal([])
        assert result == []

    def test_bell_pepper_match(self):
        """'red bell pepper' -> 'bell pepper'"""
        ingredients = [{"item": "red bell pepper"}]
        result = keyword_match_seasonal(ingredients)
        assert "bell pepper" in result

    def test_mixed_produce_and_pantry(self):
        """Only produce should match, pantry items skipped."""
        ingredients = [
            {"item": "olive oil"},
            {"item": "fresh spinach"},
            {"item": "all-purpose flour"},
            {"item": "cherry tomatoes"},
            {"item": "salt"},
        ]
        result = keyword_match_seasonal(ingredients)
        assert "spinach" in result
        assert "tomato" in result
        assert len(result) == 2

    def test_missing_item_key_skipped(self):
        """Ingredients without 'item' key are safely skipped."""
        ingredients = [{"amount": "1", "unit": "cup"}, {"item": "corn"}]
        result = keyword_match_seasonal(ingredients)
        assert "corn" in result

    def test_butternut_squash_vs_squash(self):
        """'butternut squash' should match 'butternut squash', not just 'squash'."""
        ingredients = [{"item": "butternut squash"}]
        result = keyword_match_seasonal(ingredients)
        assert "butternut squash" in result
        # squash should not also match since butternut squash was already claimed
        assert "squash" not in result

    def test_collard_greens_match(self):
        """'collard greens' should match the multi-word seasonal name."""
        ingredients = [{"item": "bunch of collard greens"}]
        result = keyword_match_seasonal(ingredients)
        assert "collard greens" in result

    def test_brussels_sprout_plural(self):
        """'brussels sprouts' -> 'brussels sprout'"""
        ingredients = [{"item": "brussels sprouts"}]
        result = keyword_match_seasonal(ingredients)
        assert "brussels sprout" in result
