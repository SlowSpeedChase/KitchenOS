"""Meal plan template generation.

Creates weekly meal plan markdown files with blank slots for recipes.
"""

from datetime import date, timedelta


DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


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
        f"# Meal Plan - Week {week:02d} ({format_date_short(start_date)} - {format_date_short(end_date)}, {year})",
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
