"""The one recurring cue: "how did that go?"

The Meal System note is explicit that a habit needs a *timed trigger* — that's
why the 3-4pm snack works and the 9pm scramble doesn't. This is the same idea
pointed at the ledger: cooking is remembered, judging it is not.

The design constraint that drives every test here is the project's
"additive, never a chore" principle. A cue that fires when there is nothing to
answer is a chore, and a chore gets muted — at which point the real cue is
muted too. So: silent by default, one item at a time, never a backlog.
"""
from datetime import date, timedelta

import pytest

from lib import serving_ledger as sl, verdict_nudge


def _cook(recipe, days_ago=1, produced=2, week="2026-W28"):
    when = (date(2026, 7, 8) - timedelta(days=days_ago)).isoformat()
    return sl.create_cook(recipe=recipe, week=week, servings_produced=produced,
                          date=when, meal="dinner")


TODAY = date(2026, 7, 8)


def test_says_nothing_when_there_are_no_cooks(tmp_db):
    assert verdict_nudge.pending(today=TODAY) == []


def test_says_nothing_when_every_cook_is_judged(tmp_db):
    cook = _cook("Chili")
    sl.update_cook(cook["id"], make_again=True)
    assert verdict_nudge.pending(today=TODAY) == []


def test_asks_about_an_unjudged_cook(tmp_db):
    _cook("Chili")
    pend = verdict_nudge.pending(today=TODAY)
    assert [p["recipe"] for p in pend] == ["Chili"]


def test_ignores_a_cook_scheduled_for_the_future(tmp_db):
    """A meal planned for Friday hasn't been eaten yet — nothing to judge."""
    _cook("Chili", days_ago=-3)
    assert verdict_nudge.pending(today=TODAY) == []


def test_ignores_stale_cooks(tmp_db):
    """Asking about last month's dinner is a backlog, and backlogs get muted."""
    _cook("Chili", days_ago=30)
    assert verdict_nudge.pending(today=TODAY) == []


def test_a_note_without_a_verdict_still_counts_as_unjudged(tmp_db):
    cook = _cook("Chili")
    sl.update_cook(cook["id"], cook_note="rushed it")
    assert len(verdict_nudge.pending(today=TODAY)) == 1


def test_a_negative_verdict_counts_as_judged(tmp_db):
    """False is an answer; only NULL is unanswered."""
    cook = _cook("Chili")
    sl.update_cook(cook["id"], make_again=False)
    assert verdict_nudge.pending(today=TODAY) == []


def test_asks_about_the_most_recent_first(tmp_db):
    _cook("Older", days_ago=3)
    _cook("Newer", days_ago=1)
    assert verdict_nudge.pending(today=TODAY)[0]["recipe"] == "Newer"


def test_message_names_the_dish(tmp_db):
    _cook("Chili")
    msg = verdict_nudge.message(verdict_nudge.pending(today=TODAY))
    assert "Chili" in msg


def test_message_mentions_the_others_without_listing_them(tmp_db):
    """One question, not a to-do list — the backlog is a count, not a queue."""
    for n in ("A", "B", "C"):
        _cook(n)
    msg = verdict_nudge.message(verdict_nudge.pending(today=TODAY))
    assert msg.count("\n") == 0
    assert "2 more" in msg


def test_run_is_a_silent_noop_with_nothing_pending(tmp_db, monkeypatch):
    """The whole point: no cook, no interruption."""
    sent = []
    monkeypatch.setattr(verdict_nudge, "_deliver", lambda *a, **k: sent.append(a))
    assert verdict_nudge.run(today=TODAY) is False
    assert sent == []


def test_run_delivers_once_when_something_is_pending(tmp_db, monkeypatch):
    sent = []
    monkeypatch.setattr(verdict_nudge, "_deliver", lambda *a, **k: sent.append(a))
    _cook("Chili")
    assert verdict_nudge.run(today=TODAY) is True
    assert len(sent) == 1


def test_delivery_failure_does_not_raise(tmp_db, monkeypatch):
    """A cron job that crashes on a missing Reminders list is worse than silence."""
    def boom(*a, **k):
        raise RuntimeError("no Reminders")
    monkeypatch.setattr(verdict_nudge, "_deliver", boom)
    _cook("Chili")
    assert verdict_nudge.run(today=TODAY) is False
