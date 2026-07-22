"""The one recurring cue: "how did that go?"

Cooking gets remembered; judging it does not. The Meal System note is explicit
that a habit needs a *timed trigger* — that is why the 3-4pm snack defuses the
evening and a vague intention doesn't. This is that idea pointed at the ledger.

Three deliberate restraints, all downstream of "additive, never a chore":

- **Silent when there is nothing to ask.** A cue that fires into an empty week
  trains you to dismiss it, and a dismissed cue takes the real ones with it.
- **One question, never a backlog.** Extra pending cooks are a count in the
  message, not a list of tasks. A queue of five is a chore; "and 2 more" is a
  fact you can ignore.
- **Nothing older than a few days.** Being asked about last month's dinner is
  both unanswerable and slightly accusing.

Delivered through Apple Reminders rather than a macOS notification on purpose:
the mini is headless and the answer happens on a phone, on a couch, after
dinner. A notification on a machine nobody is looking at is not a cue.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from lib import inventory_db

# How far back to ask. Beyond this the memory is gone and the question is noise.
RECENT_DAYS = 4
REMINDER_LIST = "KitchenOS"


def pending(today: Optional[date] = None, recent_days: int = RECENT_DAYS) -> list[dict]:
    """Cooks that have happened but carry no verdict, most recent first.

    A NULL ``make_again`` is the only thing that counts as unanswered — False is
    a real answer. A cook dated in the future hasn't been eaten yet.
    """
    today = today or date.today()
    earliest = (today - timedelta(days=recent_days)).isoformat()
    cutoff = today.isoformat()

    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT id, recipe, date, cooked_at FROM cooks"
            " WHERE make_again IS NULL"
            "   AND COALESCE(date, substr(cooked_at, 1, 10)) BETWEEN ? AND ?"
            " ORDER BY COALESCE(date, cooked_at) DESC, id DESC",
            (earliest, cutoff),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def message(items: list[dict]) -> str:
    """One line, one question. Extra items are a count, never a list."""
    if not items:
        return ""
    head = items[0]["recipe"]
    if len(items) == 1:
        return f"How was {head}? Open the planner, tap ⋮ → Make again"
    return (f"How was {head}? Open the planner, tap ⋮ → Make again "
            f"(and {len(items) - 1} more waiting)")


def _deliver(text: str, list_name: str = REMINDER_LIST) -> None:
    """Put the question where it will actually be seen — the phone."""
    from lib.reminders import add_to_reminders, create_reminders_list
    create_reminders_list(list_name)
    add_to_reminders([text], list_name=list_name)


def run(today: Optional[date] = None) -> bool:
    """Deliver at most one nudge. True if something was sent.

    Never raises: this runs unattended from a LaunchAgent, and a crash loop over
    a missing Reminders list would be a worse outcome than a missed question.
    """
    items = pending(today=today)
    if not items:
        return False
    try:
        _deliver(message(items))
        return True
    except Exception as e:  # noqa: BLE001 - unattended; log and move on
        print(f"Warning: verdict nudge delivery failed: {e}")
        return False
