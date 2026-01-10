"""Generate ICS calendar files from meal plan data.

Creates standard iCalendar format for Obsidian Full Calendar and Apple Calendar.
"""

from datetime import date
from icalendar import Calendar, Event


def format_day_summary(breakfast: str | None, lunch: str | None, dinner: str | None) -> str:
    """Format meals into a compact summary string.

    Args:
        breakfast: Recipe name or None
        lunch: Recipe name or None
        dinner: Recipe name or None

    Returns:
        String like "B: Pancakes | L: — | D: Pasta"
    """
    b = breakfast or '—'
    l = lunch or '—'
    d = dinner or '—'
    return f'B: {b} | L: {l} | D: {d}'


def create_meal_event(
    day_date: date,
    breakfast: str | None,
    lunch: str | None,
    dinner: str | None
) -> Event | None:
    """Create an all-day calendar event for a day's meals.

    Args:
        day_date: The date for this event
        breakfast: Recipe name or None
        lunch: Recipe name or None
        dinner: Recipe name or None

    Returns:
        Event object, or None if no meals planned
    """
    # Skip days with no meals
    if not any([breakfast, lunch, dinner]):
        return None

    event = Event()
    event.add('summary', format_day_summary(breakfast, lunch, dinner))
    event.add('dtstart', day_date)
    event.add('uid', f'{day_date.isoformat()}@kitchenos')

    return event


def generate_ics(days: list[dict]) -> bytes:
    """Generate ICS calendar content from parsed meal plan days.

    Args:
        days: List of day dicts from parse_meal_plan()

    Returns:
        ICS file content as bytes
    """
    cal = Calendar()
    cal.add('prodid', '-//KitchenOS//Meal Plans//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', 'Meal Plans')

    for day in days:
        event = create_meal_event(
            day['date'],
            day.get('breakfast'),
            day.get('lunch'),
            day.get('dinner')
        )
        if event:
            cal.add_component(event)

    return cal.to_ical()
