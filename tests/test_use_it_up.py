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
    phrase, not just one implicated by what the shorter phrase claims to be.
    That produced false negatives: "chicken breast" stopped matching
    "cornmeal-crusted chicken breasts" because "cornmeal" happened to
    co-occur in the ingredient text, even though nothing about the match was
    claiming to be cornmeal.

    34c33b5 fixed that by firing the block whenever a core shared *any* token
    with the shorter phrase — but that also fires on a modifier-only overlap:
    "vanilla" (a bottle of extract) shares the token "vanilla" with "vanilla
    almond milk", so it wrongly matched a food it isn't. The block now fires
    on two independent tests instead: the compound's head noun is part of the
    core (the compound genuinely *is* this phrase's food, e.g. "corn
    tortillas"), or the shorter phrase's tokens overlap the core at all (the
    shorter name is an incomplete piece of the compound, e.g. "butter" for
    "peanut butter") — checked over every core the longer phrase contains, not
    just the first, since recipe lines can list several alternatives at once.

    That per-core check still needs one more exception: it fired whenever
    *any* implicated core wasn't fully named by the shorter phrase, even when
    a *different* implicated core was. That broke "Peanut butter" against
    "almond butter (or peanut, walnut, or cashew butter, or tahini)" — the
    shorter phrase fully names the "peanut butter" alternative, but "almond
    butter" and "cashew butter" are also implicated cores it doesn't fully
    name, so the naive per-core loop still blocked a legitimate match. The
    fix: skip the per-core loop entirely once the shorter phrase fully names
    *any* implicated core — at that point it's naming one of the line's
    alternatives, not under-claiming a different one.
    """

    # --- regressions from 14fa2bc that must stay fixed ---

    def test_chicken_breast_matches_despite_unrelated_cornmeal(self):
        assert _covers(_phrase("chicken breast"),
                       _ingredient_phrase("cornmeal-crusted chicken breasts"))

    def test_chicken_breast_matches_despite_unrelated_cream_cheese(self):
        assert _covers(_phrase("chicken breast"),
                       _ingredient_phrase("cream cheese stuffed chicken breast"))

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

    # --- must stay matching: shorter fully names the compound (or a
    # different, unimplicated compound is just noise in the line) ---

    def test_cornstarch_matches_despite_unrelated_potato_starch(self):
        assert _covers(_phrase("Cornstarch"),
                       _ingredient_phrase("potato starch or cornstarch"))

    def test_basil_matches_prep_note_variant(self):
        assert _covers(_phrase("Basil"), _ingredient_phrase("basil leaves"))

    def test_peanut_butter_matches_a_noisy_ingredient_line(self):
        assert _covers(_phrase("peanut butter"),
                       _ingredient_phrase("creamy peanut butter, softened"))

    # --- accepted loss: 34c33b5 fixed this same-line case by treating
    # "cornstarch" as merely incidental to "Potato starch", but that overlap
    # test can't tell "cornmeal is noise in a chicken breast line" apart from
    # "cornstarch is genuinely another named alternative in a starch line"
    # without reintroducing the false positives below. "Potato starch" no
    # longer matches this line directly, but the same ingredient line is
    # still covered via the "Cornstarch" inventory row above, so the recipe
    # itself is not lost — only this one inventory-row/ingredient pairing is.

    def test_potato_starch_no_longer_matches_the_cornstarch_alternative(self):
        assert not _covers(_phrase("Potato starch"),
                           _ingredient_phrase("potato starch or cornstarch"))

    # --- newly blocked: a modifier-only inventory name must not match a
    # compound food it merely happens to season. "vanilla" is a bottle of
    # extract; the ingredient's actual food is almond milk, an
    # `_ATOMIC_FOODS` entry — 34c33b5's any-token-overlap test let "vanilla"
    # match because it shares the "vanilla" token, even though the compound's
    # head noun ("milk") has nothing to do with what's in the inventory.

    def test_vanilla_does_not_match_vanilla_almond_milk(self):
        assert not _covers(_phrase("vanilla"),
                           _ingredient_phrase("vanilla almond milk"))

    def test_vanilla_does_not_match_unsweetened_vanilla_almond_milk(self):
        assert not _covers(_phrase("vanilla"),
                           _ingredient_phrase("unsweetened vanilla almond milk"))

    # --- regressions ea684f8 (this class's own fix) introduced: its
    # head-in-core test only fires when `_head_token` resolves to the
    # compound's real head noun, but `_head_token` takes the phrase's *last*
    # content word — so a trailing parenthetical or "of choice" clause
    # hijacks it, the block silently stops firing, and these go back to
    # matching. Both were correctly blocked before ea684f8 (and before this
    # branch entirely); fixed by resolving the atomic-block's head from a
    # version of the text with trailing clauses stripped.

    def test_vanilla_does_not_match_almond_milk_with_a_trailing_of_choice_clause(self):
        # Raw `_head_token` resolves to "choice", not "milk" — the
        # unstripped head-in-core check never fires here.
        assert not _covers(
            _phrase("vanilla"),
            _ingredient_phrase("unsweetened vanilla almond milk (or milk of choice)"))

    def test_cashew_pieces_does_not_match_nondairy_milk_listing_cashew_as_an_option(self):
        # Raw `_head_token` resolves to "hemp" (the last word in the
        # parenthetical list of milk options), not "milk" — same regression,
        # a parenthetical list rather than an "of choice" clause.
        assert not _covers(
            _phrase("Cashew pieces"),
            _ingredient_phrase("unsweetened nondairy milk (soy, almond, oat, cashew, hemp)"))

    # --- known, pre-existing limitation: left broken on purpose, not fixed
    # by the head-resolution change above ---

    def test_known_limitation_generic_row_matches_unlisted_compound(self):
        """"vanilla" (an extract) wrongly matches "vanilla nut milk of
        choice, unsweetened" — verified true at every version of this file,
        including pre-branch, so this is a pre-existing false positive of
        the single-generic-token inventory row ("vanilla" reduces to just
        {vanilla}), not a regression this branch introduced.

        It is NOT fixed by the trailing-clause head-resolution change above:
        "nut milk" has no `_ATOMIC_FOODS` entry (only "almond milk", "oat
        milk", "soy milk", and "coconut milk" do), so `implicated` is empty
        here and nothing in the atomic block can fire no matter what the
        head resolves to. Fixing this needs a different mechanism than the
        atomic list — out of scope here. This test documents the boundary
        so a future change doesn't assume it's already covered.
        """
        assert _covers(
            _phrase("vanilla"),
            _ingredient_phrase("vanilla nut milk of choice, unsweetened"))

    def test_known_limitation_sesame_paste_no_longer_matches_its_own_alternatives_line(self):
        """"Sesame paste" wrongly stops matching "sesame paste or peanut
        butter *(inferred)*" — an accepted loss traded for fixing the two
        regressions above, not a new bug in the trade-off's mechanism.

        The line is an explicit two-food disjunction ("sesame paste OR
        peanut butter"), not one food with a trailing substitution clause
        like the "milk (or milk of choice)" cases this fix targets. But
        `*(inferred)*` (an extraction-confidence marker, not a substitution
        note) is still a parenthetical, so stripping it exposes "butter" as
        `core_head` — and the head-in-core test then reads the whole line as
        "this ingredient IS peanut butter," blocking the "sesame paste"
        alternative even though the pantry item names it exactly.

        No other inventory row covers this line (`Sesame paste` was the only
        one that did), so this is a genuine under-report on this one recipe,
        accepted in exchange for closing the two false positives above: a
        false positive tells the user they can cook something they can't,
        which is the harm this matcher exists to prevent; a false negative
        only under-reports. Verified this was `True` at `HEAD` (`ea684f8`,
        the last committed state before this fix) and is `False` with this
        fix applied — a deliberate, accepted trade, not an oversight.
        """
        assert not _covers(
            _phrase("Sesame paste"),
            _ingredient_phrase("sesame paste or peanut butter *(inferred)*"))

    # --- must stay matching: shorter fully names one of several implicated
    # alternatives listed together in the same line ---

    def test_peanut_butter_matches_among_several_nut_butter_alternatives(self):
        # "Peanut butter" fully names one of the alternatives listed here
        # ("almond butter (or peanut, walnut, or cashew butter, or tahini)").
        # "almond butter" and "cashew butter" are also implicated cores
        # structurally present in the line, and neither is fully named by
        # "Peanut butter" — but a name that IS one of the compounds present
        # must still match; it's naming an alternative, not under-claiming a
        # different one.
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
