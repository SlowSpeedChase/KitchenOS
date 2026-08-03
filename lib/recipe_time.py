"""Read a cook time out of `total_time`'s free text.

The field is LLM-extracted prose, not a number. Measured across the corpus: 147
of 254 recipes have none at all, and the remainder include "5 minutes",
"(estimated) 1 hour", "15 minutes (estimated)", "2.5 hours" and
"(estimated) 10-15 minutes for the meatballs, additional time for sides if
needed".

So this parses leniently and refuses confidently: anything it cannot read comes
back ``None`` rather than 0, because a zero would read as "instant" and win
every ranking that sorts on speed. With most of the corpus unknown, the caller
must treat absence as neutral — see ``cook_now._speed_factor``.
"""

from __future__ import annotations

import re
from typing import Optional

#: Longer than this and it isn't a weeknight signal — a multi-day ferment or a
#: value that parsed wrong. Saying nothing beats saying something misleading.
MAX_PLAUSIBLE_MINUTES = 8 * 60

# Seconds are matched only so they can be *discarded*: "2 minutes 15 seconds"
# must not read as 17. Ordered longest-unit-first so "hr" can't shadow "hour".
_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)?\b",
    re.I,
)

_HOURS = {"hour", "hours", "hr", "hrs", "h"}
_SECONDS = {"second", "seconds", "sec", "secs", "s"}


def parse_minutes(value) -> Optional[int]:
    """Total minutes from a `total_time` string, or None when unreadable.

    A range takes its **longer** end: on a week with no time, promising the
    optimistic number is the failure that matters.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or text == "null":
        return None

    total = 0.0
    found = False
    # A range ("10-15 minutes") is two numbers sharing one unit; taking the max
    # of the values carrying each unit gives the longer end without needing to
    # detect the hyphen specially.
    by_unit: dict[str, float] = {}

    for raw, unit in _UNIT_RE.findall(text):
        try:
            amount = float(raw)
        except ValueError:
            continue
        unit = (unit or "").strip()
        if unit in _SECONDS:
            continue                      # discarded, never added
        key = "hour" if unit in _HOURS else "minute"
        by_unit[key] = max(by_unit.get(key, 0.0), amount)
        found = True

    if not found:
        return None

    total = by_unit.get("hour", 0.0) * 60 + by_unit.get("minute", 0.0)
    if total <= 0 or total > MAX_PLAUSIBLE_MINUTES:
        return None
    return int(round(total))
