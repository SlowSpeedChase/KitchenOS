"""Recovering an author-supplied weight from an ingredient name."""

import pytest

from lib.gram_equivalent import extract


class TestRecovers:
    @pytest.mark.parametrize("item,name,grams", [
        ("light brown sugar (165 g)", "light brown sugar", 165.0),
        ("unsalted butter (28.5 g)", "unsalted butter", 28.5),
        ("oyster sauce (30 g)", "oyster sauce", 30.0),
        ("liquid egg whites (90 grams)", "liquid egg whites", 90.0),
        ("shredded mozzarella cheese (84 grams)", "shredded mozzarella cheese", 84.0),
        ("agave nectar  or maple syrup (42g)", "agave nectar or maple syrup", 42.0),
    ])
    def test_plain_metric_asides(self, item, name, grams):
        assert extract(item) == (name, grams)

    def test_approximations_are_still_exact_enough(self):
        assert extract("eggplants (about 450 grams)") == ("eggplants", 450.0)

    @pytest.mark.parametrize("item,grams", [
        ("cheddar (2 oz)", 56.7),
        ("chicken thighs (1.5 lb)", 680.39),
        ("flour (1 kg)", 1000.0),
    ])
    def test_imperial_is_converted(self, item, grams):
        assert extract(item)[1] == pytest.approx(grams, rel=1e-3)


class TestRefusesWhenAmbiguous:
    """Silently wrong weights corrupt nutrition, so doubt means decline."""

    @pytest.mark.parametrize("item", [
        "ears of corn (about 600-650g of corn kernels)",   # a range, and of kernels
        "block of extra-firm tofu, drained (14-ounce/400g)",  # two systems
        "cannellini beans (15-ounce/440g)",
        "chicken (about 2 to 3 lb)",
        "water (1 1/2 cups)",
        "rice (250 g cooked)",                             # weighed after cooking
        "sauce (30 g per serving)",
        "unsalted stock of any kind or water (300 ml)",    # volume is not a weight
        "carrot (1/4-inch)",
        "cream cheese, softened ($1.89)",
        "chives (chopped fresh)",
        "soft tofu (or silken tofu)",
    ])
    def test_left_for_the_estimator(self, item):
        assert extract(item) == (item, None)

    def test_absurd_weights_are_refused(self):
        assert extract("salt (99999 g)")[1] is None
        assert extract("salt (0 g)")[1] is None


class TestEdges:
    def test_no_parenthetical(self):
        assert extract("greek yogurt") == ("greek yogurt", None)

    def test_empty(self):
        assert extract("") == ("", None)

    def test_trailing_punctuation_is_tidied(self):
        assert extract("butter, (28 g)")[0] == "butter"

    def test_the_weight_is_absolute_not_per_unit(self):
        """0.75 cup sugar (165 g) totals 165 g - the aside restates the whole
        line in metric, it is not a per-cup rate."""
        assert extract("light brown sugar (165 g)")[1] == 165.0


class TestPriceNoise:
    """Scraped pages leave prices in the same aside as the weight."""

    def test_a_price_riding_along_does_not_block_recovery(self):
        assert extract("frozen blueberries (130g, $0.82)") == ("frozen blueberries", 130.0)

    def test_two_weights_still_decline(self):
        assert extract("mushrooms (7 ounces, 200 grams)")[1] is None

    def test_a_non_price_companion_still_declines(self):
        assert extract("pear (120g, chopped fine)")[1] is None
