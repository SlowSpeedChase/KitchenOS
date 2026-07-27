"""Tests for the Use-It-Up waste suggester."""

from datetime import date, timedelta

from lib.inventory import InventoryItem
from lib import use_it_up
from lib.use_it_up import _covers, _ingredient_phrase, _phrase


TODAY = date(2026, 6, 24)
SOON = (TODAY + timedelta(days=1)).isoformat()   # within the 3-day threshold
LATER = (TODAY + timedelta(days=30)).isoformat()
EXPIRED = (TODAY - timedelta(days=1)).isoformat()       # within the grace window
LONG_EXPIRED = (TODAY - timedelta(days=21)).isoformat()  # assumed already used

RECIPES = [
    {"name": "Strawberry Spinach Salad",
     "ingredient_items": ["strawberries", "spinach", "olive oil", "feta"]},
    {"name": "Banana Bread",
     "ingredient_items": ["bananas", "flour", "butter", "sugar"]},
    {"name": "Plain Toast",
     "ingredient_items": ["bread", "butter"]},
]


def _item(name, expires, category="produce"):
    return InventoryItem(name=name, quantity=1, unit="ct",
                         category=category, expires=expires)


class TestAtRisk:
    def test_only_expiring_or_expired(self):
        items = [_item("Strawberries", SOON), _item("Carrots", LATER)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Strawberries"]

    def test_excludes_staples(self):
        # Butter is a staple — even expiring, it must not be flagged.
        items = [_item("Salted Butter", SOON, category="dairy"),
                 _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]

    def test_expired_sorts_before_soon(self):
        items = [_item("Spinach", SOON), _item("Strawberries", EXPIRED)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [s for s, _ in flagged] == ["expired", "soon"]

    def test_long_expired_dropped(self):
        # Expired weeks ago — assumed already used; not actionable noise.
        items = [_item("Old Berries", LONG_EXPIRED), _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]

    def test_milk_is_a_staple_not_flagged(self):
        items = [_item("Whole Milk", SOON, category="dairy"), _item("Spinach", SOON)]
        flagged = use_it_up.at_risk_items(items, today=TODAY)
        assert [it.name for _, it in flagged] == ["Spinach"]


class TestSuggest:
    def test_ranks_by_at_risk_items_used(self):
        items = [_item("Strawberries", SOON), _item("Spinach", SOON),
                 _item("Bananas", SOON)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        names = [s["recipe"] for s in result["suggestions"]]
        # Salad uses 2 at-risk items (strawberries + spinach); banana bread uses 1.
        assert names[0] == "Strawberry Spinach Salad"
        assert "Banana Bread" in names

    def test_staple_assumed_available(self):
        # Banana bread needs flour/butter/sugar (staples) + bananas (at-risk).
        # It should still surface — staples don't block the suggestion.
        items = [_item("Bananas", SOON)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        assert any(s["recipe"] == "Banana Bread" for s in result["suggestions"])

    def test_empty_when_nothing_at_risk(self):
        items = [_item("Carrots", LATER)]
        result = use_it_up.suggest(items, RECIPES, today=TODAY)
        assert result == {"at_risk": [], "suggestions": []}


class TestMatchPrecision:
    """Token containment must not let a generic ingredient swallow a compound food.

    ``_matches``/``_is_staple`` used a bare bidirectional subset test, so any
    single-token ingredient matched every longer inventory name containing that
    word — "eggs" matched "Lo mein egg noodles", "butter" matched "Peanut
    butter". Containment into a *clean* name (inventory row, staple) now has to
    reach that name's head noun. Free-text ingredient strings stay on plain
    containment, since their trailing words are prep notes rather than food.
    """

    def _matches_name(self, item, ingredient):
        return use_it_up._matches(use_it_up._phrase(item),
                                  [use_it_up._ingredient_phrase(ingredient)])

    def _is_staple_name(self, item, staple):
        """`item` is a clean inventory name."""
        return use_it_up._is_staple(use_it_up._phrase(item),
                                    use_it_up._staple_phrases({staple}))

    def _ingredient_is_staple(self, text, staple):
        """`text` is free-form recipe ingredient text."""
        return use_it_up._is_staple(use_it_up._ingredient_phrase(text),
                                    use_it_up._staple_phrases({staple}))

    # --- false positives that must now be rejected ---

    def test_egg_does_not_match_egg_noodles(self):
        assert not self._matches_name("Lo mein egg noodles", "eggs")

    def test_corn_does_not_match_corn_tortilla_chips(self):
        assert not self._matches_name("yellow corn tortilla chips", "corn")

    def test_egg_noodles_are_not_an_egg_staple(self):
        assert not self._is_staple_name("Lo mein egg noodles", "egg")

    def test_peanut_butter_is_not_a_butter_staple(self):
        # Head noun is "butter", but peanut butter is its own food.
        assert not self._is_staple_name("Peanut butter", "butter")

    def test_coconut_milk_is_not_a_milk_staple(self):
        assert not self._is_staple_name("Canned coconut milk", "milk")

    # --- true positives that must keep working ---

    def test_descriptor_prefix_still_matches(self):
        assert self._matches_name("fresh strawberries", "strawberries")

    def test_salted_butter_is_still_a_butter_staple(self):
        assert self._is_staple_name("Salted Butter", "butter")

    def test_variant_still_matches_on_shared_head(self):
        assert self._matches_name("large curd cottage cheese", "cottage cheese")

    def test_exact_name_matches(self):
        assert self._matches_name("Okra", "okra")

    def test_cut_still_matches_its_animal(self):
        # "breast"/"thigh" name a cut, not a different food — the head noun to
        # match on is the protein itself.
        assert self._matches_name("Chicken", "boneless skinless chicken breasts")
        assert self._matches_name("Pork", "pork shoulder")

    def test_preparation_notes_in_ingredient_text_do_not_block_a_match(self):
        # Ingredient text is free-form; its trailing words are prep notes, not
        # a different food. These regressed when the head test was applied to
        # the noisy side as well as the clean one.
        assert self._ingredient_is_staple("unsalted butter, softened (112 g)", "butter")
        assert self._ingredient_is_staple("butter (melted)", "butter")
        assert self._ingredient_is_staple("egg yolks, at room temperature", "egg")
        assert self._matches_name("Beef broth",
                                  "beef broth  i use unsalted (or beef stock)")

    def test_ground_form_still_matches_the_spice(self):
        # "powder"/"weed" name the form, not a different food.
        assert self._matches_name("Coriander powder", "ground coriander")
        assert self._matches_name("Dried dill weed", "fresh dill")

    def test_a_compound_keeps_its_identity_through_a_form_word(self):
        # ...but stripping the form word must not expose "peanut butter powder"
        # as plain butter.
        assert not self._is_staple_name("peanut butter powder", "butter")

    def test_an_atomic_food_still_matches_itself_through_prep_notes(self):
        # Being atomic blocks the *base* staple, not the food's own variants.
        assert self._matches_name("Peanut butter",
                                  "creamy peanut butter jif or similar (128 g)")
        assert self._matches_name("Canned coconut milk", "coconut milk (chilled)")

    def test_ingredient_text_is_parsed_non_strict(self):
        assert use_it_up._ingredient_phrase("butter (melted)").strict is False
        assert use_it_up._phrase("Salted Butter").strict is True


class TestCompoundFoodsDoNotMatchTheirHeadNoun:
    """`_STOPWORDS` reduces 'shredded cheese' to {cheese} and 'Canned corn' to
    {corn}, so without an atomic entry every cheese and every corn product
    matches them. 436597d only closed the direction where the inventory name is
    the longer phrase."""

    def test_cream_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("cream cheese"))

    def test_cottage_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("cottage cheese"))

    def test_goat_cheese_is_not_shredded_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("goat cheese"))

    def test_corn_syrup_is_not_canned_corn(self):
        assert not _covers(_phrase("Canned corn"),
                           _ingredient_phrase("light corn syrup"))

    def test_corn_tortillas_are_not_canned_corn(self):
        assert not _covers(_phrase("Canned corn"),
                           _ingredient_phrase("corn tortillas"))


class TestCompoundExtensionKeepsTrueMatches:
    def test_cornstarch_still_matches_a_noisy_ingredient_line(self):
        assert _covers(_phrase("Cornstarch"),
                       _ingredient_phrase("potato starch or cornstarch"))

    def test_prep_note_variants_still_match(self):
        assert _covers(_phrase("Basil"), _ingredient_phrase("basil leaves"))

    def test_existing_atomic_foods_still_hold(self):
        assert not _covers(_phrase("butter"),
                           _ingredient_phrase("peanut butter"))
        assert _covers(_phrase("peanut butter"),
                       _ingredient_phrase("creamy peanut butter, softened"))


class TestAtomicBlockOnlyFiresWhenImplicated:
    """14fa2bc added cornmeal/cream cheese/cornstarch to `_ATOMIC_FOODS`, but
    `_covers` blocked on *any* atomic core found anywhere in the longer
    phrase, not just one the shorter phrase's tokens actually overlap. That
    produced false negatives: "chicken breast" stopped matching "cornmeal-
    crusted chicken breasts" because "cornmeal" happened to co-occur in the
    ingredient text, even though nothing about the match was claiming to be
    cornmeal. The atomic block must only fire when the atomic core shares a
    token with the shorter phrase — i.e. the core is part of what's being
    claimed, not incidental noise elsewhere in the text.
    """

    # --- regressions from 14fa2bc that must now match again ---

    def test_chicken_breast_matches_despite_unrelated_cornmeal(self):
        assert _covers(_phrase("chicken breast"),
                       _ingredient_phrase("cornmeal-crusted chicken breasts"))

    def test_chicken_breast_matches_despite_unrelated_cream_cheese(self):
        assert _covers(_phrase("chicken breast"),
                       _ingredient_phrase("cream cheese stuffed chicken breast"))

    def test_potato_starch_matches_despite_unrelated_cornstarch(self):
        assert _covers(_phrase("Potato starch"),
                       _ingredient_phrase("potato starch or cornstarch"))

    # --- must stay blocked: the atomic core IS what's being claimed ---

    def test_tortillas_still_does_not_match_corn_tortillas(self):
        assert not _covers(_phrase("tortillas"),
                           _ingredient_phrase("corn tortillas"))

    def test_butter_still_does_not_match_peanut_butter(self):
        assert not _covers(_phrase("butter"),
                           _ingredient_phrase("peanut butter"))

    def test_shredded_cheese_still_does_not_match_cream_cheese(self):
        assert not _covers(_phrase("shredded cheese"),
                           _ingredient_phrase("cream cheese"))

    # --- multi-core lines: several "___ butter"/"___ milk" alternatives at
    # once. A full-corpus measurement (every recipe x every inventory row)
    # caught these after the fix above shipped: checking only the first
    # structurally-present atomic core (via next()) let an irrelevant one
    # (peanut butter) shadow the one actually implicated (cashew butter), so
    # `_covers` now checks every core the longer phrase contains.

    def test_cashew_pieces_does_not_match_a_cashew_butter_alternative(self):
        # "cashew" only names a piece of the "cashew butter" alternative
        # listed here — it doesn't cover "butter" too, so it must stay
        # blocked even though "peanut butter" (irrelevant to "cashew") is
        # structurally the first atomic core found in the phrase.
        assert not _covers(
            _phrase("Cashew pieces"),
            _ingredient_phrase("almond butter (or peanut, walnut, or cashew butter, or tahini)"))

    def test_exact_alternative_still_matches_among_several_atomic_cores(self):
        # "Peanut butter" fully names one of the listed alternatives, so its
        # shared "butter" token with the *other* alternatives (almond butter,
        # cashew butter) is incidental vocabulary overlap, not an
        # under-claim — this must keep matching.
        assert _covers(
            _phrase("Peanut butter"),
            _ingredient_phrase("almond butter (or peanut, walnut, or cashew butter, or tahini)"))


class TestRender:
    def test_markdown_lists_at_risk_and_recipes(self):
        items = [_item("Strawberries", SOON)]
        md = use_it_up.render_markdown(use_it_up.suggest(items, RECIPES, today=TODAY))
        assert "# 🥗 Use It Up" in md
        assert "Strawberries" in md
        assert "[[Strawberry Spinach Salad]]" in md

    def test_markdown_all_clear(self):
        md = use_it_up.render_markdown({"at_risk": [], "suggestions": []})
        assert "good shape" in md
