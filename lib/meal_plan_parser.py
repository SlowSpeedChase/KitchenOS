"""Parse meal plan markdown files.

Extracts recipe links from weekly meal plan files for calendar generation.
"""

import re
from datetime import date, timedelta


def get_week_start_date(year: int, week: int) -> date:
    """Get the Monday of a given ISO week."""
    # ISO week 1 contains Jan 4
    jan4 = date(year, 1, 4)
    # Find Monday of week 1
    week1_monday = jan4 - timedelta(days=jan4.weekday())
    # Add weeks
    return week1_monday + timedelta(weeks=week - 1)


def extract_meals_for_day(section: str) -> dict:
    """Extract breakfast, lunch, dinner from a day section.

    Args:
        section: Markdown section for a single day

    Returns:
        Dict with 'breakfast', 'lunch', 'dinner' keys (None if empty)
    """
    meals = {'breakfast': None, 'lunch': None, 'dinner': None}

    for meal_type in ['breakfast', 'lunch', 'dinner']:
        pattern = rf'###\s+{meal_type}\s*\n(.*?)(?=###|\Z)'
        match = re.search(pattern, section, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).strip()
            # Extract first [[recipe]] link
            link_match = re.search(r'\[\[([^\]]+)\]\]', content)
            if link_match:
                meals[meal_type] = link_match.group(1)

    return meals


def parse_meal_plan(content: str, year: int, week: int) -> list[dict]:
    """Parse meal plan markdown into structured day data.

    Args:
        content: Full markdown content of meal plan file
        year: ISO year
        week: ISO week number

    Returns:
        List of 7 dicts, one per day, with keys:
            - date: datetime.date
            - day: str (Monday, Tuesday, etc.)
            - breakfast: str or None
            - lunch: str or None
            - dinner: str or None
    """
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    week_start = get_week_start_date(year, week)
    result = []

    for i, day_name in enumerate(days):
        day_date = week_start + timedelta(days=i)

        # Find this day's section
        pattern = rf'##\s+{day_name}\s+\([^)]+\)(.*?)(?=##\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|\Z)'
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

        meals = {'breakfast': None, 'lunch': None, 'dinner': None}
        if match:
            meals = extract_meals_for_day(match.group(0))

        result.append({
            'date': day_date,
            'day': day_name,
            **meals
        })

    return result
