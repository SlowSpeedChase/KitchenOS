"""The one-tap verdict ask.

`make_again` was empty on 14 of 16 cooks not because the user had no opinion but
because recording one cost five gestures: reopen the planner, find the card,
tap it (touch-only), tap the verdict in the sheet. Meanwhile a nightly agent
sent Reminders saying "Open the planner, tap ⋮ → Make again" — a pointer to the
chore rather than a way out of it.

The whole apparatus downstream (`make_again_count`, suggestion ranking) is
waiting on this one field.
"""

from datetime import date

import pytest

from lib import kitchen_today, serving_ledger as sl

TODAY = date(2026, 7, 10)


def _cooked(recipe="Chili", when="2026-07-09"):
    row = sl.create_cook(recipe=recipe, week="2026-W28", servings_produced=4.0,
                         date=when, meal="dinner")
    return sl.update_cook(row["id"], cooked_at=f"{when}T18:00:00Z")


class TestVerdictPrompt:
    def test_nothing_cooked_asks_nothing(self, tmp_db):
        assert kitchen_today.verdict_prompt(TODAY) is None

    def test_it_asks_about_a_cook_with_no_verdict(self, tmp_db):
        row = _cooked()
        prompt = kitchen_today.verdict_prompt(TODAY)
        assert prompt["cook_id"] == row["id"]
        assert prompt["recipe"] == "Chili"

    def test_an_answered_cook_is_not_asked_about_again(self, tmp_db):
        row = _cooked()
        sl.update_cook(row["id"], make_again=True)
        assert kitchen_today.verdict_prompt(TODAY) is None

    def test_a_thumbs_down_also_counts_as_answered(self, tmp_db):
        """False is a real answer; only NULL is unanswered."""
        row = _cooked()
        sl.update_cook(row["id"], make_again=False)
        assert kitchen_today.verdict_prompt(TODAY) is None

    def test_it_asks_about_one_thing_at_a_time(self, tmp_db):
        """A queue of six is the chore this replaces."""
        _cooked("Chili", "2026-07-08")
        _cooked("Tacos", "2026-07-09")
        prompt = kitchen_today.verdict_prompt(TODAY)
        assert prompt["recipe"] == "Tacos"          # most recent first

    def test_answering_reveals_the_next_one(self, tmp_db):
        older = _cooked("Chili", "2026-07-08")
        newer = _cooked("Tacos", "2026-07-09")
        sl.update_cook(newer["id"], make_again=True)
        assert kitchen_today.verdict_prompt(TODAY)["cook_id"] == older["id"]


class TestRenderVerdictHtml:
    def test_nothing_pending_renders_nothing(self):
        assert kitchen_today.render_verdict_html(None) == ""

    def test_it_carries_the_cook_id_for_the_patch(self):
        html = kitchen_today.render_verdict_html(
            {"cook_id": 42, "recipe": "Chili", "when": "yesterday"})
        assert 'data-cook-id="42"' in html

    def test_it_offers_both_answers(self):
        html = kitchen_today.render_verdict_html(
            {"cook_id": 1, "recipe": "Chili", "when": ""})
        assert 'data-verdict="1"' in html
        assert 'data-verdict="0"' in html

    def test_the_recipe_name_is_escaped(self):
        """Recipe names are LLM-extracted from arbitrary pages."""
        html = kitchen_today.render_verdict_html(
            {"cook_id": 1, "recipe": '<img src=x onerror=alert(1)>', "when": ""})
        assert "<img" not in html
        assert "&lt;img" in html

    @pytest.mark.parametrize("when", ["", None, "yesterday"])
    def test_a_missing_day_word_does_not_break_the_sentence(self, when):
        html = kitchen_today.render_verdict_html(
            {"cook_id": 1, "recipe": "Chili", "when": when})
        assert "How was <strong>Chili</strong>" in html
        assert "  " not in html, "double space where the day word would go"
