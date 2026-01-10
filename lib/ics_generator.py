"""Generate ICS calendar files from meal plan data.

Creates timed events for each meal (Breakfast, Lunch, Snack, Dinner).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event


# Meal times: (hour, minute) in local time
MEAL_TIMES = {
    'breakfast': (8, 0),
    'lunch': (12, 0),
    'snack': (15, 0),
    'dinner': (19, 30),
}

# Event duration in minutes
EVENT_DURATION = 30

# Local timezone
LOCAL_TZ = ZoneInfo('America/Chicago')


def create_meal_event(
    day_date: date,
    meal_type: str,
    recipe_name: str | None
) -> Event | None:
    """Create a timed calendar event for a single meal.

    Args:
        day_date: The date for this event
        meal_type: One of 'breakfast', 'lunch', 'snack', 'dinner'
        recipe_name: Recipe name, or None if no meal planned

    Returns:
        Event object, or None if no recipe
    """
    if not recipe_name:
        return None

    hour, minute = MEAL_TIMES[meal_type]

    start_dt = datetime(
        day_date.year,
        day_date.month,
        day_date.day,
        hour,
        minute,
        tzinfo=LOCAL_TZ
    )
    end_dt = start_dt + timedelta(minutes=EVENT_DURATION)

    event = Event()
    event.add('summary', recipe_name)
    event.add('dtstart', start_dt)
    event.add('dtend', end_dt)
    event.add('uid', f'{day_date.isoformat()}-{meal_type}@kitchenos')
    event.add('transp', 'TRANSPARENT')  # Show as free

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
        for meal_type in ['breakfast', 'lunch', 'snack', 'dinner']:
            recipe = day.get(meal_type)
            event = create_meal_event(day['date'], meal_type, recipe)
            if event:
                cal.add_component(event)

    return cal.to_ical()
