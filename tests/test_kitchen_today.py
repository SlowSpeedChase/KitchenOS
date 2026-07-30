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
        assert len(cards) == 4                              # page is intact

    def test_all_four_cards_always_render(self, monkeypatch):
        def boom(**k):
            raise RuntimeError("everything is broken")
        monkeypatch.setattr("lib.cook_now.generate", boom)
        monkeypatch.setattr("lib.use_it_up.generate", boom)
        monkeypatch.setattr("lib.serving_ledger.cooks_for_week", boom)

        cards = kt.gather(items=[], recipe_index=[], today=TODAY)
        assert len(cards) == 4
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
