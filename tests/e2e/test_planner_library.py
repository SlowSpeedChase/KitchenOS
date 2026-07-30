"""Browsing the recipe library from the meal planner's sidebar.

The load-bearing property here isn't that the filters work — it's that they never
compare two different units. `nutrition_calories` is per-serving for most recipes
but the whole-batch total for any recipe with no servings count (the engine
divides by 1), so a naive calorie filter silently mixes the two.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def _visible(page) -> int:
    return page.locator(".recipe-card:not(.hidden)").count()


def _open(page, live_server):
    page.goto(live_server.url("/meal-planner"), wait_until="domcontentloaded")
    page.wait_for_selector(".recipe-card")


class TestParseServings:
    """`servings` is raw frontmatter and the extractor puts prose in it."""

    def test_matches_the_engine_on_every_real_form(self, live_server, page, page_errors):
        _open(page, live_server)
        got = page.evaluate("""() => ({
            plain:      parseServings(4),
            range:      parseServings('6-8'),
            rangeProse: parseServings('4-6 servings (estimated)'),
            trailing:   parseServings('6-8 as a side dish'),
            serves:     parseServings('serves 4'),
            none:       parseServings(null),
            empty:      parseServings(''),
            zero:       parseServings(0),
        })""")
        # Low end of a range, matching nutrition_engine._parse_servings.
        assert got == {"plain": 4, "range": 6, "rangeProse": 4, "trailing": 6,
                       "serves": 4, "none": 0, "empty": 0, "zero": 0}
        assert page_errors == []

    def test_a_prose_servings_recipe_is_not_mislabelled_whole_batch(
            self, live_server, page, page_errors):
        """Number('6-8') is NaN — that would have hidden real per-serving recipes."""
        _open(page, live_server)
        rows = page.evaluate("""() => allRecipes
            .filter(r => typeof r.servings === 'string' && /\\d/.test(r.servings))
            .map(r => [r.servings, parseServings(r.servings)])""")
        if not rows:
            pytest.skip("no prose servings values in the current library")
        for raw, parsed in rows:
            assert parsed >= 1, f"{raw!r} parsed to {parsed}"
        assert page_errors == []


class TestSort:
    def test_sort_control_offers_the_orderings(self, live_server, page, page_errors):
        _open(page, live_server)
        values = page.eval_on_selector_all(
            "#sort-select option", "els => els.map(e => e.value)")
        assert values == ["name", "added", "cal-asc", "cal-desc", "protein-desc"]
        assert page_errors == []

    def test_most_calories_excludes_implausible_figures(self, live_server, page,
                                                        page_errors):
        """42 recipes store a per-serving figure above the engine's 2500 ceiling,
        led by an 18,245-kcal 'serving'. Sorting without excluding them returns a
        leaderboard of data errors."""
        _open(page, live_server)
        page.select_option("#sort-select", "cal-desc")
        page.wait_for_timeout(200)

        top = page.evaluate("""() => [...document.querySelectorAll('.recipe-card:not(.hidden)')]
            .slice(0, 5)
            .map(e => (allRecipes.find(r => r.name === e.dataset.name) || {}).nutrition_calories)""")
        assert top, "nothing rendered"
        for cal in top:
            assert cal is None or cal <= 2500, f"implausible {cal} kcal sorted to the top"
        assert page_errors == []

    def test_recently_added_is_newest_first(self, live_server, page, page_errors):
        _open(page, live_server)
        page.select_option("#sort-select", "added")
        page.wait_for_timeout(200)

        dates = page.evaluate("""() => [...document.querySelectorAll('.recipe-card:not(.hidden)')]
            .slice(0, 12)
            .map(e => (allRecipes.find(r => r.name === e.dataset.name) || {}).added)
            .filter(Boolean)""")
        assert dates == sorted(dates, reverse=True), "not newest-first"
        assert page_errors == []


class TestFilters:
    def test_meal_type_chips_cover_the_taxonomy(self, live_server, page, page_errors):
        _open(page, live_server)
        labels = page.eval_on_selector_all(
            ".chip.meal-type", "els => els.map(e => e.textContent.trim())")
        assert labels == ["Mains", "Breakfast", "Sides", "Snacks", "Desserts", "Drinks"]
        assert page_errors == []

    def test_a_meal_type_chip_narrows_the_list(self, live_server, page, page_errors):
        _open(page, live_server)
        before = _visible(page)
        page.locator(".chip.meal-type", has_text="Desserts").click()
        page.wait_for_timeout(200)
        after = _visible(page)
        assert 0 < after < before
        assert page_errors == []

    def test_macro_chips_compose_as_AND(self, live_server, page, page_errors):
        _open(page, live_server)
        page.locator(".chip.macro", has_text="kcal ≤ 400").click()
        page.wait_for_timeout(200)
        one = _visible(page)
        page.locator(".chip.macro", has_text="protein 30g+").click()
        page.wait_for_timeout(200)
        two = _visible(page)
        assert two <= one, "adding a second macro chip widened the results"
        assert page_errors == []

    def test_macro_filter_never_compares_batch_totals(self, live_server, page,
                                                      page_errors):
        """The whole point: a recipe with no servings carries whole-batch macros,
        so it must be excluded rather than judged against the wrong unit."""
        _open(page, live_server)
        page.locator(".chip.macro", has_text="kcal ≤ 400").click()
        page.wait_for_timeout(200)

        shown = page.evaluate("""() => [...document.querySelectorAll('.recipe-card:not(.hidden)')]
            .map(e => allRecipes.find(r => r.name === e.dataset.name))
            .filter(Boolean)
            .map(r => [r.name, parseServings(r.servings), r.nutrition_calories])""")
        assert shown, "filter hid everything"
        for name, servings, cal in shown:
            assert servings >= 1, f"{name} has no servings but passed a macro filter"
            assert cal is not None and cal <= 400, f"{name} at {cal} kcal passed 'kcal <= 400'"
        assert page_errors == []

    def test_excluded_recipes_are_reported_not_silently_dropped(
            self, live_server, page, page_errors):
        """"0 results" must never be an unexplained mystery."""
        _open(page, live_server)
        assert page.locator("#filter-note").inner_text().strip() == ""

        page.locator(".chip.macro", has_text="kcal ≤ 400").click()
        page.wait_for_timeout(200)
        note = page.locator("#filter-note").inner_text()
        assert "hidden" in note and "servings" in note
        assert page_errors == []

    def test_clearing_a_chip_restores_the_full_list(self, live_server, page,
                                                    page_errors):
        _open(page, live_server)
        before = _visible(page)
        chip = page.locator(".chip.macro", has_text="kcal ≤ 400")
        chip.click()
        page.wait_for_timeout(200)
        assert _visible(page) < before
        chip.click()
        page.wait_for_timeout(200)
        assert _visible(page) == before
        assert page.locator("#filter-note").inner_text().strip() == ""
        assert page_errors == []


class TestPreview:
    """Looking up what a recipe is must not cost you the week on screen."""

    def _first_with(self, page, predicate):
        """A recipe name from the live library matching a JS predicate."""
        return page.evaluate(
            f"() => (allRecipes.filter(r => {predicate})[0] || {{}}).name")

    def test_backdrop_is_hidden_until_asked_for(self, live_server, page, page_errors):
        _open(page, live_server)
        assert page.locator("#preview-backdrop").is_hidden()
        assert page_errors == []

    def test_info_button_opens_the_preview_without_navigating(
            self, live_server, page, page_errors):
        _open(page, live_server)
        before = page.url
        page.locator(".recipe-card:not(.hidden) .recipe-info-link").first.click()
        page.wait_for_selector("#preview-title")

        assert page.url == before, "the preview navigated away instead of overlaying"
        assert page.locator(".recipe-card").count() > 0, "planner unmounted"
        assert page_errors == []

    def test_preview_shows_ingredients_and_a_way_to_the_full_recipe(
            self, live_server, page, page_errors):
        _open(page, live_server)
        name = self._first_with(page, "r.servings")
        page.evaluate(f"openPreview({name!r})")
        page.wait_for_selector("#preview-title")

        assert page.locator(".preview-ing li").count() > 0
        href = page.locator("a.preview-open").get_attribute("href")
        assert href.startswith("/recipe/")
        assert page_errors == []

    def test_a_recipe_with_servings_reads_per_serving(self, live_server, page,
                                                      page_errors):
        _open(page, live_server)
        name = self._first_with(
            page,
            "parseServings(r.servings) >= 1 && plausibleCalories(r.nutrition_calories)")
        page.evaluate(f"openPreview({name!r})")
        page.wait_for_selector(".preview-basis")

        basis = page.locator(".preview-basis").inner_text()
        assert "per serving" in basis and "makes" in basis
        assert page_errors == []

    def test_a_recipe_without_servings_says_whole_recipe(self, live_server, page,
                                                         page_errors):
        """The same honesty rule as the sidebar — these are batch totals."""
        _open(page, live_server)
        name = self._first_with(
            page, "!parseServings(r.servings) && r.nutrition_calories != null")
        if not name:
            pytest.skip("every recipe has a servings count in the current library")
        page.evaluate(f"openPreview({name!r})")
        page.wait_for_selector(".preview-basis")

        basis = page.locator(".preview-basis").inner_text()
        assert "whole recipe" in basis
        assert "per serving" not in basis
        assert page_errors == []

    def test_escape_closes(self, live_server, page, page_errors):
        _open(page, live_server)
        page.locator(".recipe-card:not(.hidden) .recipe-info-link").first.click()
        page.wait_for_selector("#preview-title")
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)

        assert page.locator("#preview-backdrop").is_hidden()
        assert page_errors == []

    def test_backdrop_closes_but_the_card_itself_does_not(self, live_server, page,
                                                          page_errors):
        _open(page, live_server)
        page.locator(".recipe-card:not(.hidden) .recipe-info-link").first.click()
        page.wait_for_selector("#preview-title")

        # A click inside the card must not dismiss what you're reading.
        page.locator("#preview-title").click()
        page.wait_for_timeout(150)
        assert page.locator("#preview-backdrop").is_visible()

        page.locator("#preview-backdrop").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(150)
        assert page.locator("#preview-backdrop").is_hidden()
        assert page_errors == []

    def test_closing_restores_page_scrolling(self, live_server, page, page_errors):
        """The overlay locks body scroll; failing to release it strands the page."""
        _open(page, live_server)
        page.locator(".recipe-card:not(.hidden) .recipe-info-link").first.click()
        page.wait_for_selector("#preview-title")
        assert page.evaluate("document.body.style.overflow") == "hidden"

        page.locator("#preview-close").click()
        page.wait_for_timeout(150)
        assert page.evaluate("document.body.style.overflow") == ""
        assert page_errors == []

    def test_a_failed_load_offers_the_full_page_instead(self, live_server, page,
                                                        page_errors):
        _open(page, live_server)
        page.route("**/api/recipes/*", lambda r: r.fulfill(status=500, body="nope"))
        page.evaluate("openPreview('Anything At All')")
        page.wait_for_selector(".preview-error")

        err = page.locator(".preview-error")
        assert "Could not load" in err.inner_text()
        assert err.locator("a").get_attribute("href").startswith("/recipe/")


class TestDragStillWorks:
    """The preview shares the sidebar with SortableJS; it must not disarm it."""

    def test_sortable_is_live_and_still_excludes_the_info_button(
            self, live_server, page, page_errors):
        _open(page, live_server)
        assert page.evaluate("typeof sidebarSortable !== 'undefined' && !!sidebarSortable")
        # If the info button ever stopped being filtered, tapping it would start a
        # drag instead of opening the preview.
        assert page.evaluate(
            "sidebarSortable.option('filter').includes('recipe-info-link')")
        assert page_errors == []


class TestCardMacros:
    def test_every_card_states_its_basis(self, live_server, page, page_errors):
        """A per-serving figure, a whole-batch total, and an implausible one must
        not look alike."""
        _open(page, live_server)
        rows = page.evaluate("""() => [...document.querySelectorAll('.recipe-card')]
            .map(e => {
                const r = allRecipes.find(x => x.name === e.dataset.name) || {};
                const m = e.querySelector('.recipe-macros');
                return [r.name, parseServings(r.servings), r.nutrition_calories,
                        m ? m.innerText : null];
            })""")
        seen_batch = False
        for name, servings, cal, text in rows:
            if cal is None:
                assert text is None, f"{name} has no calories but rendered {text!r}"
                continue
            assert text, f"{name} has calories but no macro line"
            if servings < 1:
                assert "whole batch" in text, f"{name}: {text!r} hides that it's a batch"
                seen_batch = True
            elif not (50 <= cal <= 2500):
                assert "implausible" in text, f"{name}: {text!r} presents {cal} as fact"
            else:
                assert "srv" in text
        assert seen_batch, "no whole-batch recipe present — this assertion went vacuous"
        assert page_errors == []
