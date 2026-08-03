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
    """Silently wrong weights corrupt nutrition, so doubt means decline.

    Two cases moved OUT of this list on 2026-08-02, deliberately reversing an
    earlier decision: "(14-ounce/400g)" and "(15-ounce/440g)" were refused as
    "two systems". They are not two systems — they are one quantity glossed in
    both, which is the imported cookbook's house style across 58 rows. They are
    now recovered *when the halves agree*, and their coverage is pinned by
    TestCorroboratedDualUnitPackage below. A pair that disagrees is still refused
    here, so the module's posture is unchanged: doubt still declines.
    """

    @pytest.mark.parametrize("item", [
        "ears of corn (about 600-650g of corn kernels)",   # a range, and of kernels
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


class TestCorroboratedDualUnitPackage:
    """A US/metric pair states one weight twice, so the halves can check each other.

    This module deliberately rejected "(15-ounce/440g)" as "mixing two systems",
    and that was right for the corpus it was written against. The EPUB import
    changed the input: the cookbook's house style glosses every package in both
    systems — "(15-ounce/425 g) cans chickpeas" — 58 rows across 49 recipes. That
    is not two systems in conflict, it is one quantity written twice, and 15 oz
    really is 425 g.

    So the pair is recovered only when the two halves AGREE, which is a stronger
    guarantee than the single-figure case this module already trusts: two
    independent statements corroborating each other, rather than one taken on
    faith. A pair that disagrees is a typo or a referent shift, and is still
    refused.
    """

    def test_an_agreeing_pair_yields_the_metric_figure(self):
        from lib.gram_equivalent import extract
        _, grams = extract("(15-ounce/425 g) cans chickpeas, drained")
        assert grams == 425.0

    def test_rounding_in_the_book_still_agrees(self):
        """14 oz is 396.9 g; the book prints 400 g. Well within tolerance."""
        from lib.gram_equivalent import extract
        _, grams = extract("(14-ounce/400 g) block extra-firm tofu")
        assert grams == 400.0

    def test_a_disagreeing_pair_is_refused(self):
        from lib.gram_equivalent import extract
        _, grams = extract("(15-ounce/900 g) cans chickpeas")
        assert grams is None

    def test_a_pound_gram_pair_agrees(self):
        from lib.gram_equivalent import extract
        _, grams = extract("(1-pound/455 g) white beans")
        assert grams == 455.0

    def test_a_lone_figure_still_works(self):
        """The existing single-quantity path must be untouched."""
        from lib.gram_equivalent import extract
        _, grams = extract("light brown sugar (165 g)")
        assert grams == 165.0

    def test_a_span_is_still_refused(self):
        """"(about 600-650g of corn kernels)" is a range AND a referent shift."""
        from lib.gram_equivalent import extract
        _, grams = extract("6 ears corn (about 600-650g of corn kernels)")
        assert grams is None

    def test_a_referent_shift_inside_a_pair_is_still_refused(self):
        """The module checks for a shifted referent *within* the aside, and a pair
        is held to the same rule — "(15-ounce/425 g drained)" weighs something
        other than what the line calls for.

        Note what this deliberately does NOT cover: "(15-ounce/425 g) cans
        chickpeas , drained and rinsed" is still recovered at 425 g, even though
        draining sheds liquid. That is the same known gap the audit files under
        "frying medium counted as eaten", not something this change should decide.
        """
        from lib.gram_equivalent import extract
        _, grams = extract("(15-ounce/425 g drained) can chickpeas")
        assert grams is None
