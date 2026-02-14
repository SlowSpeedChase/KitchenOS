"""Parse meal plan markdown files.

Extracts recipe links from weekly meal plan files for calendar generation.
"""

import re
from datetime import date, timedelta
from typing import NamedTuple


class MealEntry(NamedTuple):
    """A recipe reference in a meal plan with optional servings multiplier."""
    name: str
    servings: int = 1


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
            # Extract first [[recipe]] link with optional xN multiplier
            link_match = re.search(r'\[\[([^\]]+)\]\]\s*(?:x(\d+))?', content)
            if link_match:
                name = link_match.group(1)
                servings = int(link_match.group(2)) if link_match.group(2) else 1
                meals[meal_type] = MealEntry(name=name, servings=servings)

    return meals


def insert_recipe_into_meal_plan(content: str, day: str, meal: str, recipe_name: str) -> str:
    """Insert a recipe wikilink into a meal plan at the specified day and meal slot.

    Args:
        content: Full markdown content of meal plan file
        day: Day name (e.g. "Monday") - case insensitive
        meal: Meal type (e.g. "Dinner") - case insensitive
        recipe_name: Recipe name to insert as [[wikilink]]

    Returns:
        Updated markdown content

    Raises:
        ValueError: If day or meal section not found
    """
    day_title = day.strip().title()
    meal_title = meal.strip().title()

    # Find the day section
    day_pattern = rf'(## {day_title}\s+\([^)]+\))'
    day_match = re.search(day_pattern, content, re.IGNORECASE)
    if not day_match:
        raise ValueError(f"Day '{day_title}' not found in meal plan")

    # Find the meal subsection within the day section
    day_start = day_match.start()

    # Find the meal header after this day
    meal_pattern = rf'(### {meal_title})\s*\n'
    meal_match = re.search(meal_pattern, content[day_start:], re.IGNORECASE)
    if not meal_match:
        raise ValueError(f"Meal '{meal_title}' not found under {day_title}")

    # Position right after the meal header line (first \n after ### Meal)
    header_line_end = day_start + meal_match.start() + len(meal_match.group(1)) + 1
    insert_pos = header_line_end

    # Find the next section header (### or ##) after the meal header
    next_section = re.search(r'^###?\s', content[insert_pos:], re.MULTILINE)
    if next_section:
        section_end = insert_pos + next_section.start()
    else:
        section_end = len(content)

    # Get existing content in this slot
    existing = content[insert_pos:section_end].strip()

    # Build the new content for this slot
    if existing:
        new_slot = f"{existing}\n[[{recipe_name}]]\n"
    else:
        new_slot = f"[[{recipe_name}]]\n"

    # Replace the slot content
    return content[:insert_pos] + new_slot + content[section_end:]


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
