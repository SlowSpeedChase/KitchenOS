"""Tests for the Kitchen Today home-page state and the generated-note renderer.

The point of this page is *recall* — it exists so a feature can't be forgotten —
so the tests that matter most are the ones proving a card still says something
useful when its data is missing, empty, or broken. A home page that 500s is worse
than the canvas it replaced.
"""

from datetime import date

import pytest

from lib import kitchen_today as kt
from lib import note_view


TODAY = date(2026, 7, 30)


def _recipe(name, added, **kw):
    base = {"name": name, "added": added, "ingredient_items": [], "cuisine": None,
            "protein": None, "dish_type": None, "nutrition_calories": None}
    base.update(kw)
    return base


class TestPlural:
    def test_singular_and_plural(self):
        assert kt._plural(1, "recipe") == "1 recipe"
        assert kt._plural(6, "recipe") == "6 recipes"

    def test_zero_is_plural(self):
        assert kt._plural(0, "item") == "0 items"

    def test_explicit_plural_form(self):
        assert kt._plural(2, "is", "are") == "2 are"


class TestArrivalWord:
    @pytest.mark.parametrize("iso,expected", [
        ("2026-07-30", "Today"),
        ("2026-07-29", "Yesterday"),
        ("2026-07-27", "Monday"),      # 3 days back, inside the weekday window
        ("2026-07-24", "Friday"),      # 6 days back, still a weekday name
    ])
    def test_recent_days_read_as_words(self, iso, expected):
        assert kt.arrival_word(iso, TODAY) == expected

    def test_a_week_out_falls_back_to_a_date(self):
        # Past 6 days a weekday name is ambiguous — "Thursday" could be either one.
        assert kt.arrival_word("2026-07-23", TODAY) == "Jul 23, 2026"

    def test_garbage_does_not_raise(self):
        assert kt.arrival_word("not-a-date", TODAY) == "Undated"


class TestDayWord:
    def test_today_tomorrow_and_weekday(self):
        assert kt._day_word("2026-07-30", TODAY) == "today"
        assert kt._day_word("2026-07-31", TODAY) == "tomorrow"
        assert kt._day_word("2026-08-02", TODAY) == "Sunday"

    def test_already_expired_reads_as_today_not_a_negative(self):
        assert kt._day_word("2026-07-20", TODAY) == "today"

    def test_missing_date_degrades(self):
        assert kt._day_word(None, TODAY) == "soon"


class TestCookCard:
    def test_leads_with_the_zero_shopping_count(self, monkeypatch):
        monkeypatch.setattr("lib.cook_now.generate", lambda **k: {"recipes": [
            {"recipe": "A", "coverage": 1.0, "missing": []},
            {"recipe": "B", "coverage": 1.0, "missing": []},
            {"recipe": "C", "coverage": 0.5, "missing": ["x"]},
        ]})
        card = kt._cook_card([], [], TODAY)
        assert card.line == "2 recipes need nothing you don't have"
        assert card.href == "/cook-now"

    def test_nothing_fully_covered_names_the_closest(self, monkeypatch):
        # A bare "0 recipes" reads as a broken feature; the closest thing is the
        # honest and more useful answer.
        monkeypatch.setattr("lib.cook_now.generate", lambda **k: {"recipes": [
            {"recipe": "Chili", "coverage": 0.8, "missing": ["beans", "cumin"]},
        ]})
        assert kt._cook_card([], [], TODAY).line == "closest is Chili — 2 items short"

    def test_empty_library_still_gives_a_line(self, monkeypatch):
        monkeypatch.setattr("lib.cook_now.generate", lambda **k: {"recipes": []})
        assert kt._cook_card([], [], TODAY).line == "see what's closest to cookable"


class TestRecentCard:
    def test_counts_only_the_recent_window(self):
        idx = [
            _recipe("Fresh", "2026-07-29"),
            _recipe("Also fresh", "2026-07-30"),
            _recipe("Stale", "2026-06-01"),
        ]
        card = kt._recent_card(idx, TODAY)
        assert card.line == "2 recipes added — newest today"
        assert card.href == "/recent"

    def test_falls_back_to_library_size_when_nothing_is_new(self):
        idx = [_recipe("Old", "2026-01-01"), _recipe("Older", "2025-01-01")]
        assert kt._recent_card(idx, TODAY).line == "2 recipes in the library"

    def test_undated_recipes_are_not_counted_as_new(self):
        assert kt._recent_card([_recipe("Mystery", None)], TODAY).line == \
            "1 recipe in the library"


class TestUseItUpCard:
    def test_expired_is_urgent_and_names_the_next_to_go(self, monkeypatch):
        monkeypatch.setattr("lib.use_it_up.generate", lambda **k: {"at_risk": [
            {"name": "ham", "status": "expired", "expires": "2026-07-29"},
            {"name": "lime", "status": "soon", "expires": "2026-07-31"},
        ]})
        card = kt._use_it_up_card([], [], TODAY)
        assert card.tone == "urgent"
        assert card.line == "1 item expired · lime goes tomorrow"

    def test_only_soon_is_not_urgent(self, monkeypatch):
        monkeypatch.setattr("lib.use_it_up.generate", lambda **k: {"at_risk": [
            {"name": "lime", "status": "soon", "expires": "2026-07-31"},
        ]})
        card = kt._use_it_up_card([], [], TODAY)
        assert card.tone == "normal"
        assert card.line == "lime goes tomorrow"

    def test_nothing_at_risk(self, monkeypatch):
        monkeypatch.setattr("lib.use_it_up.generate", lambda **k: {"at_risk": []})
        assert kt._use_it_up_card([], [], TODAY).line == "nothing expiring soon"


# Cook now · New recipes · Use it up · Today's prep · Plan the week.
# Asserted exactly, because the failure this guards against is a card
# silently vanishing from the page rather than degrading to a link.
HOME_CARDS = 5


class TestGatherIsFailSafe:
    """Every card degrades alone; none can take the page down."""

    def test_a_raising_builder_falls_back_to_a_tappable_link(self, monkeypatch):
        def boom(**k):
            raise RuntimeError("db is on fire")
        monkeypatch.setattr("lib.cook_now.generate", boom)
        monkeypatch.setattr("lib.use_it_up.generate", lambda **k: {"at_risk": []})

        cards = kt.gather(items=[], recipe_index=[], today=TODAY)
        cook = next(c for c in cards if c.href == "/cook-now")
        assert cook.line == "ranked by what's on hand"      # the fallback
        assert len(cards) == HOME_CARDS                     # page is intact

    def test_every_card_always_renders(self, monkeypatch):
        def boom(**k):
            raise RuntimeError("everything is broken")
        monkeypatch.setattr("lib.cook_now.generate", boom)
        monkeypatch.setattr("lib.use_it_up.generate", boom)
        monkeypatch.setattr("lib.serving_ledger.cooks_for_week", boom)

        cards = kt.gather(items=[], recipe_index=[], today=TODAY)
        assert len(cards) == HOME_CARDS
        assert all(c.href and c.title and c.line for c in cards)


class TestRenderHtml:
    def test_escapes_card_text(self):
        html = kt.render_html([kt.Card("🍳", "T", '<script>alert(1)</script>', "/x")])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_urgent_tone_reaches_the_markup(self):
        assert "today-card urgent" in kt.render_html(
            [kt.Card("⏳", "T", "gone off", "/review", tone="urgent")])
        assert "urgent" not in kt.render_html([kt.Card("🍳", "T", "fine", "/x")])


class TestRecentRecipes:
    def test_sorted_newest_first_and_undated_dropped(self):
        idx = [
            _recipe("Old", "2026-07-01"),
            _recipe("New", "2026-07-29"),
            _recipe("Undated", None),
        ]
        got = kt.recent_recipes(recipe_index=idx)
        assert [r["name"] for r in got] == ["New", "Old"]

    def test_limit_is_honoured(self):
        idx = [_recipe(f"R{i}", f"2026-07-{i:02d}") for i in range(1, 20)]
        assert len(kt.recent_recipes(recipe_index=idx, limit=5)) == 5

    def test_render_groups_by_day_and_escapes(self):
        html = kt.render_recent_html(
            [_recipe("Fish & <b>Chips</b>", "2026-07-29")], today=TODAY)
        assert "<h2>Yesterday</h2>" in html
        assert "&lt;b&gt;" in html
        assert "/recipe/Fish%20%26%20%3Cb%3EChips%3C/b%3E" in html

    def test_empty_says_so(self):
        assert "No recipes yet" in kt.render_recent_html([], today=TODAY)


class TestNoteView:
    def test_dead_kitchenos_button_becomes_an_http_button(self):
        """The single reason no shopping list existed between W27 and W31."""
        md = ("# Meal Plan\n\n```button\nname Generate Shopping List\ntype link\n"
              "action kitchenos://generate-shopping-list?week=2026-W31\n```\n")
        html = note_view.render(md, week="2026-W31")
        assert "kitchenos://" not in html
        assert '<button class="gen" data-week="2026-W31">' in html

    def test_dead_send_to_reminders_button_becomes_an_http_button(self):
        md = ("```button\nname Send to Reminders\ntype link\n"
              "action kitchenos://send-to-reminders?week=2026-W31\n```\n")
        html = note_view.render(md, week="2026-W31")
        assert "kitchenos://" not in html
        assert '<button class="remind" data-week="2026-W31">' in html

    def test_obsidian_only_button_renders_as_nothing(self):
        # A QuickAdd command has no web equivalent; a dead control is worse than
        # an absent one.
        md = ("```button\nname Add Ingredients\ntype command\n"
              "action QuickAdd: Add Ingredients to Shopping List\n```\n")
        assert note_view.render(md, week="2026-W31").strip() == ""

    def test_each_button_keeps_its_own_action(self):
        """Regression: all three buttons once rendered as 'Generate shopping list'.

        Dispatch used to fall back to the *page's* week whenever it couldn't parse
        an action, so every button in a note collapsed into the same one.
        """
        md = ("```button\nname Add Ingredients\ntype command\n"
              "action QuickAdd: Add Ingredients to Shopping List\n```\n\n"
              "```button\nname Send to Reminders\ntype link\n"
              "action kitchenos://send-to-reminders?week=2026-W31\n```\n")
        html = note_view.render(md, week="2026-W31")
        assert html.count("<button") == 1
        assert 'class="remind"' in html
        assert "Generate shopping list" not in html

    def test_unknown_kitchenos_action_is_dropped(self):
        md = "```button\naction kitchenos://self-destruct?week=2026-W31\n```\n"
        assert note_view.render(md, week="2026-W31").strip() == ""

    def test_button_week_comes_from_the_action_not_the_page(self):
        md = ("```button\naction kitchenos://send-to-reminders?week=2026-W25\n```\n")
        html = note_view.render(md, week="2026-W31")
        assert 'data-week="2026-W25"' in html

    def test_wikilinks_become_recipe_links(self):
        html = note_view.render("[[Chili Garlic Noodles]] x1")
        assert 'href="/recipe/Chili%20Garlic%20Noodles"' in html
        assert ">Chili Garlic Noodles<" in html

    def test_wikilink_alias_uses_the_label(self):
        html = note_view.render("[[2026-W27|Meal Plan]]")
        assert 'href="/recipe/2026-W27"' in html
        assert ">Meal Plan<" in html

    def test_task_state_is_rendered_faithfully(self):
        html = note_view.render("- [ ] milk\n- [x] eggs\n")
        assert '<li><span class="box">☐</span><span>milk</span></li>' in html
        assert '<li class="done"><span class="box">☑</span><span>eggs</span></li>' in html

    def test_h1_is_dropped_but_deeper_headings_survive(self):
        # The page supplies its own title; two competing H1s waste the first screen.
        html = note_view.render("# Shopping List\n## Items\n### Produce\n")
        assert "Shopping List" not in html
        assert "<h2>Items</h2>" in html
        assert "<h3>Produce</h3>" in html

    def test_note_content_cannot_inject_markup(self):
        html = note_view.render("- [ ] <img src=x onerror=alert(1)>")
        assert "<img" not in html
        assert "&lt;img" in html

    def test_unterminated_fence_still_renders(self):
        html = note_view.render("```button\naction kitchenos://"
                                "generate-shopping-list?week=2026-W31\n")
        assert 'data-week="2026-W31"' in html

    def test_unknown_syntax_survives_as_visible_text(self):
        # Falling through as a paragraph beats silently swallowing content.
        assert "<p>| a | b |</p>" in note_view.render("| a | b |")

    def test_blockquote_and_bullets(self):
        html = note_view.render("> Unassigned: 7\n- plain bullet\n")
        assert "<blockquote>Unassigned: 7</blockquote>" in html
        assert "<span>plain bullet</span>" in html


class TestPrepCard:
    """Today's prep, moved off the meal planner onto the home page.

    The load-bearing property is *speed*: `task_extractor.extract_tasks`
    regenerates a stale sidecar with an LLM classification pass, and this card
    runs on every home-page load. It reads the sidecar only when already fresh.
    """

    def _card(self, monkeypatch, cached, fresh=True):
        from lib import kitchen_today, task_extractor
        monkeypatch.setattr(task_extractor, "load_cached_tasks", lambda w: cached)
        monkeypatch.setattr(task_extractor, "_is_cache_fresh", lambda w, c: fresh)
        # Fails the test loudly rather than silently costing seconds.
        monkeypatch.setattr(task_extractor, "extract_tasks",
                            lambda *a, **k: pytest.fail(
                                "the home page must never regenerate the task sidecar"))
        return kitchen_today._prep_card(date(2026, 7, 31))   # a Friday

    def test_never_regenerates_the_sidecar(self, monkeypatch):
        """The whole reason this reads the cache directly."""
        card = self._card(monkeypatch, {"tasks": [
            {"day": "Friday", "text": "chop", "done": False},
        ]})
        assert "1 step today" in card.line

    def test_counts_today_and_get_ahead_separately(self, monkeypatch):
        card = self._card(monkeypatch, {"tasks": [
            {"day": "Friday", "text": "a", "done": False},
            {"day": "Friday", "text": "b", "done": False},
            {"day": "Sunday", "text": "c", "can_do_ahead": True, "done": False},
        ]})
        assert "2 steps today" in card.line
        assert "1 can be done ahead" in card.line

    def test_done_steps_do_not_count(self, monkeypatch):
        card = self._card(monkeypatch, {"tasks": [
            {"day": "Friday", "text": "a", "done": True},
            {"day": "Friday", "text": "b", "done": False},
        ]})
        assert "1 step today" in card.line

    def test_a_future_step_that_cannot_be_done_ahead_is_not_offered(self, monkeypatch):
        card = self._card(monkeypatch, {"tasks": [
            {"day": "Sunday", "text": "sear the steak", "can_do_ahead": False, "done": False},
        ]})
        assert card.line == "nothing to prep today"

    def test_a_stale_sidecar_says_so_rather_than_lying(self, monkeypatch):
        card = self._card(monkeypatch, {"tasks": [
            {"day": "Friday", "text": "a", "done": False},
        ]}, fresh=False)
        assert "refresh" in card.line
        assert card.href == "/prep"

    def test_no_sidecar_at_all(self, monkeypatch):
        card = self._card(monkeypatch, None)
        assert card.line == "nothing planned yet"

    def test_today_with_work_is_urgent_but_get_ahead_alone_is_not(self, monkeypatch):
        todays = self._card(monkeypatch, {"tasks": [
            {"day": "Friday", "text": "a", "done": False}]})
        ahead = self._card(monkeypatch, {"tasks": [
            {"day": "Sunday", "text": "b", "can_do_ahead": True, "done": False}]})
        assert todays.tone == "urgent"
        assert ahead.tone == "normal", "'you could' is not 'you must'"

    def test_the_card_is_on_the_home_page(self):
        from lib import kitchen_today
        cards = kitchen_today.gather(items=[], recipe_index=[], today=date(2026, 7, 31))
        prep = [c for c in cards if c.href == "/prep"]
        assert len(prep) == 1, "exactly one prep card"


class TestRenderPrepHtml:
    def _html(self, today=(), ahead=()):
        from lib import kitchen_today
        return kitchen_today.render_prep_html(
            {"day": "Friday", "week": "2026-W31", "today": list(today), "ahead": list(ahead)})

    def test_empty_says_so(self):
        assert "Nothing to prep" in self._html()

    def test_a_step_carries_its_recipe_so_it_is_attributable(self):
        """"Chill until ready to serve" is meaningless on its own."""
        html = self._html(today=[{"id": "x1", "text": "Chill until ready",
                                  "recipe": "Beef Kabobs", "day": "Friday"}])
        assert "Chill until ready" in html
        assert "Beef Kabobs" in html
        assert 'data-task-id="x1"' in html

    def test_step_text_is_escaped(self):
        html = self._html(today=[{"id": "x", "text": "<script>alert(1)</script>",
                                  "recipe": "R", "day": "Friday"}])
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_done_steps_render_ticked(self):
        html = self._html(today=[{"id": "x", "text": "t", "recipe": "R",
                                  "day": "Friday", "done": True}])
        assert "task done" in html and "checked" in html

    def test_get_ahead_alone_still_offers_reminders(self):
        """Gating the button on today's steps left a dead end on exactly the day
        the get-ahead work is what you'd want queued."""
        html = self._html(ahead=[{"id": "a", "text": "t", "recipe": "R", "day": "Sunday"}])
        assert 'id="send-reminders"' in html
        assert 'data-scope="ahead"' in html
        assert "Send get-ahead" in html

    def test_today_takes_precedence_over_get_ahead(self):
        html = self._html(today=[{"id": "t", "text": "t", "recipe": "R", "day": "Friday"}],
                          ahead=[{"id": "a", "text": "a", "recipe": "R", "day": "Sunday"}])
        assert 'data-scope="today"' in html
        assert "Send today" in html
