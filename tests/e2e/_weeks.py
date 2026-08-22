"""Far-future weeks a browser test can own outright.

The e2e server runs against a *copy of the developer's real vault and DB*, so
any test that opens "this week" is coupled to whatever was actually planned
and bought this week. Such a test passes on an empty week and fails the moment
the app is used for its purpose — observed: one real Thursday dinner broke the
tap-to-assign test, which assumed that slot was empty.

Tests that need a week they control claim one here. Offsets are a single
namespace across *all* of ``tests/e2e`` (the server is session-scoped, so two
files sharing a week collide exactly like two tests in one file). Claims are
checked at run time: a second caller asking for an offset already held by a
different test fails loudly, instead of flipping the first test's week into
board mode and deleting the legacy cards it asserts on — which is how two
tests in ``test_weekly_loop.py`` silently collided before.
"""
from __future__ import annotations

import inspect
from datetime import date

#: offset -> "file::function" of the test that owns it.
_CLAIMS: dict[int, str] = {}


def unique_week(offset: int) -> tuple[str, str]:
    """A far-future week no real plan occupies, so a test owns its own state.

    Returns ``(week, date_inside_it)``. Derive the date rather than hardcoding
    one: a cook whose ``date`` falls outside its ``week`` is filed correctly
    but never rendered on that week's board, which reads as an app bug and is
    not. ``offset`` 0 is 2099-W01; the date is that week's Wednesday.
    """
    caller = inspect.stack()[1]
    owner = f"{caller.filename.rsplit('/', 1)[-1]}::{caller.function}"
    prior = _CLAIMS.setdefault(offset, owner)
    if prior != owner:
        raise RuntimeError(
            f"unique_week({offset}) is already owned by {prior}; {owner} must "
            f"claim a different offset (grep 'unique_week(' under tests/e2e)")
    week_no = offset + 1
    return f"2099-W{week_no:02d}", date.fromisocalendar(2099, week_no, 3).isoformat()
