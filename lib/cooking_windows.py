"""Deterministic, local-time cooking openings. Flexible blocks are context."""

from datetime import datetime, timedelta
import math
import re
from zoneinfo import ZoneInfo


def valid_duration(value):
    if type(value) is not int or not 15 <= value <= 360 or value % 15:
        raise ValueError("Duration must be 15–360 minutes in 15-minute steps")
    return value


def recipe_duration(metadata):
    def positive(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0

    def minutes(value):
        if positive(value):
            return value
        # Accept literal durations already present in the corpus, not arbitrary
        # recipe prose (which can mention only one part of the preparation).
        if isinstance(value, str) and re.fullmatch(
            r"\s*(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m)\s*)+",
            value,
            re.I,
        ):
            from lib.recipe_time import parse_minutes

            return parse_minutes(value)
        return None

    total = minutes(metadata.get("total_time"))
    if not positive(total):
        prep, cook = (
            minutes(metadata.get("prep_time")),
            minutes(metadata.get("cook_time")),
        )
        total = prep + cook if positive(prep) and positive(cook) else None
    if not positive(total):
        return {"minutes": 90, "source": "estimate"}
    return {
        "minutes": max(15, min(360, math.ceil(total / 15) * 15)),
        "source": "recipe",
    }


def overlaps(start, end, other_start, other_end):
    return start < other_end and end > other_start


def suggest_windows(day, timezone_name, events, choices, schedules, duration_minutes):
    valid_duration(duration_minutes)
    zone = ZoneInfo(timezone_name)
    start_day = datetime.fromisoformat(day).replace(tzinfo=zone)
    noon = start_day + timedelta(hours=12)
    midnight = start_day + timedelta(days=1)
    parsed = [
        (e, datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]))
        for e in events
    ]
    relevant = [(e, s, t) for e, s, t in parsed if overlaps(noon, midnight, s, t)]
    all_day = [e for e, s, t in relevant if e["all_day"]]
    if any(choices.get(e["id"]) == "blocking" for e in all_day):
        return []
    unresolved = sorted(e["id"] for e in all_day if e["id"] not in choices)
    firm = [(s, t) for e, s, t in relevant if not e["all_day"] and e["role"] == "firm"]
    flex = [
        (s, t) for e, s, t in relevant if not e["all_day"] and e["role"] == "flexible"
    ]
    for block in schedules:
        s = datetime.fromisoformat(block["start"])
        firm.append((s, s + timedelta(minutes=block["duration_minutes"])))
    # Merge intervals so an overlapping set of commitments is one occupied span.
    merged = []
    for s, t in sorted(firm):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(t, merged[-1][1]))
        else:
            merged.append((s, t))
    result = []
    start = noon
    while start + timedelta(minutes=duration_minutes) <= midnight:
        end = start + timedelta(minutes=duration_minutes)
        if not any(overlaps(start, end, s, t) for s, t in merged):
            before = [
                (t, e["id"])
                for e, s, t in parsed
                if not e["all_day"] and start_day <= t <= start
            ]
            after = [
                (s, e["id"])
                for e, s, t in parsed
                if not e["all_day"] and end <= s <= midnight
            ]
            adjacent = ([max(before)[1]] if before else []) + (
                [min(after)[1]] if after else []
            )
            result.append(
                dict(
                    start=start.isoformat(),
                    end=end.isoformat(),
                    overlaps_flexible=any(overlaps(start, end, s, t) for s, t in flex),
                    unresolved_all_day_ids=unresolved,
                    adjacent_event_ids=adjacent,
                )
            )
        start += timedelta(minutes=15)
    return sorted(result, key=lambda w: (w["overlaps_flexible"], w["start"]))
