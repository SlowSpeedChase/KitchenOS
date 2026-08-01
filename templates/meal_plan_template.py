"""Meal plan template generation.

Creates weekly meal plan markdown files with blank slots for recipes.
"""

import re
from datetime import date, timedelta
from typing import Optional


DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

WEEK_ID_RE = re.compile(r'^\s*(\d{4})-W(\d{2})\s*$')


def parse_week_id(week_id: str) -> tuple[int, int]:
    """Parse a 'YYYY-Www' identifier into (year, week).

    Raises ValueError on anything that isn't a well-formed week id.
    """
    match = WEEK_ID_RE.match(week_id or '')
    if not match:
        raise ValueError(f"Invalid week id: {week_id!r} (expected 'YYYY-Www')")
    return int(match.group(1)), int(match.group(2))


def get_week_start(year: int, week: int) -> date:
    """Get the Monday of a given ISO week."""
    jan_4 = date(year, 1, 4)
    week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
    return week_1_monday + timedelta(weeks=week - 1)


def format_date_short(d: date) -> str:
    """Format date as 'Jan 13'."""
    return d.strftime('%b %-d')


def get_week_date_range(year: int, week: int) -> tuple[date, date]:
    """Get the start (Monday) and end (Sunday) dates of a week."""
    start = get_week_start(year, week)
    end = start + timedelta(days=6)
    return start, end


def format_week_range(week_id: str, *, with_year: bool = True) -> str:
    """Human date range for a 'YYYY-Www' id, e.g. 'Jun 22 - Jun 28, 2026'.

    Pass with_year=False for the bare 'Jun 22 - Jun 28' form (e.g. dropdowns).

    **This is what a surface shows.** A week id is a key — it names files
    (`Meal Plans/2026-W26.md`), API paths, task sidecars and wikilinks — but
    "2026-W26" tells a human nothing about when it is, and neither does "Week
    26". Render the range; keep the id for the link.
    """
    year, week = parse_week_id(week_id)
    start, end = get_week_date_range(year, week)
    rng = f"{format_date_short(start)} - {format_date_short(end)}"
    return f"{rng}, {year}" if with_year else rng


def week_relative_label(week_id: str, today: Optional[date] = None) -> str:
    """'This week' / 'Next week' / 'Last week', or '' for anything further out.

    The orientation a week number was really being used for — "which week am I
    looking at?" — answered in words instead of arithmetic. Empty for distant
    weeks, where the date range is the only honest answer.
    """
    try:
        year, week = parse_week_id(week_id)
    except ValueError:
        return ""
    today = today or date.today()
    start, _ = get_week_date_range(year, week)
    this_monday = today - timedelta(days=today.weekday())
    delta_weeks = (start - this_monday).days // 7
    return {0: "This week", 1: "Next week", -1: "Last week"}.get(delta_weeks, "")


def format_week_heading(week_id: str, *, with_year: bool = True,
                        today: Optional[date] = None) -> str:
    """The full human label: 'This week · Jun 22 - Jun 28, 2026'.

    Falls back to the bare range when the week isn't adjacent to today.
    """
    rng = format_week_range(week_id, with_year=with_year)
    relative = week_relative_label(week_id, today)
    return f"{relative} · {rng}" if relative else rng


def generate_meal_plan_markdown(year: int, week: int) -> str:
    """Generate a meal plan markdown file for a given week.

    Args:
        year: ISO year
        week: ISO week number

    Returns:
        Formatted markdown string
    """
    start_date, end_date = get_week_date_range(year, week)
    week_id = f"{year}-W{week:02d}"

    lines = [
        f"# Meal Plan - {format_week_range(week_id)}",
        "",
        "```button",
        "name Generate Shopping List",
        "type link",
        f"action kitchenos://generate-shopping-list?week={week_id}",
        "```",
        "",
    ]

    for i, day in enumerate(DAYS_OF_WEEK):
        day_date = start_date + timedelta(days=i)
        lines.extend([
            f"## {day} ({format_date_short(day_date)})",
            "### Breakfast",
            "",
            "### Lunch",
            "",
            "### Snack",
            "",
            "### Dinner",
            "",
            "### Notes",
            "",
            "",
        ])

    return '\n'.join(lines)


def generate_filename(year: int, week: int) -> str:
    """Generate the filename for a meal plan.

    Args:
        year: ISO year
        week: ISO week number

    Returns:
        Filename like '2026-W03.md'
    """
    return f"{year}-W{week:02d}.md"
