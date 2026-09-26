"""Validate a cook's timed session without changing ledger state."""
from __future__ import annotations

import re
from datetime import date as _date, datetime, time, timedelta, timezone as _timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate(date: str, start: str, timezone: str, duration_minutes: int) -> str:
    """Return a canonical offset-aware start, or reject an invalid session.

    The written wall time and offset must both describe a real instant in the
    supplied IANA zone. This also rejects nonexistent times at a DST jump while
    allowing either explicit offset during the repeated hour in autumn.
    """
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        day = _date.fromisoformat(date)
    except ValueError:
        raise ValueError("date must be a valid YYYY-MM-DD") from None
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("timezone must be an IANA timezone")
    try:
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("timezone must be an IANA timezone") from None
    if not isinstance(start, str):
        raise ValueError("start must be an offset-aware ISO timestamp")
    try:
        stamp = datetime.fromisoformat(start)
    except ValueError:
        raise ValueError("start must be an offset-aware ISO timestamp") from None
    if stamp.utcoffset() is None:
        raise ValueError("start must be an offset-aware ISO timestamp")
    local = stamp.astimezone(zone)
    if (local.replace(tzinfo=None) != stamp.replace(tzinfo=None)
            or local.utcoffset() != stamp.utcoffset()):
        raise ValueError("start time and offset must match timezone")
    if local.date() != day:
        raise ValueError("start must match the local date")
    if local.minute % 15 or local.second or local.microsecond:
        raise ValueError("start must be on a 15-minute boundary")
    if (type(duration_minutes) is not int or not 15 <= duration_minutes <= 360
            or duration_minutes % 15):
        raise ValueError("duration_minutes must be 15..360 in 15-minute increments")
    # Durations measure elapsed minutes even across daylight-saving changes.
    finish = local.astimezone(_timezone.utc) + timedelta(minutes=duration_minutes)
    midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    if finish > midnight.astimezone(_timezone.utc):
        raise ValueError("session must finish by midnight")
    return local.isoformat()
