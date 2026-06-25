"""Generate ICS calendar files from meal plan data.

Creates standard iCalendar format for Obsidian Full Calendar and Apple Calendar.
"""

from datetime import date, datetime, timedelta
from icalendar import Calendar, Event

# Start time for each meal slot's timed calendar event, in slot order.
# Events are 30 min and marked TRANSP:TRANSPARENT so they show as free, not busy.
MEAL_TIMES = [
    ('breakfast', (8, 0)),
    ('lunch', (12, 0)),
    ('snack', (15, 0)),
    ('dinner', (19, 30)),
]
MEAL_DURATION_MINUTES = 30


def _format_meal_display(meal) -> str:
    """Format a meal entry for calendar display.

    Args:
        meal: MealEntry, plain string, or None

    Returns:
        Display string like "Recipe x2" or "Recipe" or "—"
    """
    if meal is None:
        return '—'
    # Handle MealEntry (NamedTuple with name and servings)
    if hasattr(meal, 'name') and hasattr(meal, 'servings'):
        if meal.servings > 1:
            return f'{meal.name} x{meal.servings}'
        return meal.name
    return str(meal)


def format_day_summary(breakfast=None, lunch=None, snack=None, dinner=None) -> str:
    """Format meals into a compact summary string.

    Args:
        breakfast: MealEntry, recipe name string, or None
        lunch: MealEntry, recipe name string, or None
        snack: MealEntry, recipe name string, or None
        dinner: MealEntry, recipe name string, or None

    Returns:
        String like "B: Pancakes | L: — | D: Pasta x2"
    """
    b = _format_meal_display(breakfast)
    l = _format_meal_display(lunch)
    d = _format_meal_display(dinner)
    parts = [f'B: {b}', f'L: {l}']
    if snack:
        parts.append(f'S: {_format_meal_display(snack)}')
    parts.append(f'D: {d}')
    return ' | '.join(parts)


def create_meal_events(
    day_date: date,
    breakfast=None,
    lunch=None,
    dinner=None,
    snack=None,
) -> list[Event]:
    """Create a timed 30-minute event per planned meal slot.

    Each slot gets its own event at its scheduled time (breakfast 8:00,
    lunch 12:00, snack 15:00, dinner 19:30), marked TRANSP:TRANSPARENT so it
    shows as free. This makes the meal plan read as an actual day schedule in
    any calendar app, rather than a single all-day blob.

    Args:
        day_date: The date for these events
        breakfast/lunch/dinner/snack: MealEntry, recipe name string, or None

    Returns:
        List of Event objects (empty if no meals planned that day)
    """
    slots = {'breakfast': breakfast, 'lunch': lunch, 'snack': snack, 'dinner': dinner}
    events = []

    for slot, (hour, minute) in MEAL_TIMES:
        meal = slots.get(slot)
        if not meal:
            continue

        start = datetime.combine(day_date, datetime.min.time()).replace(hour=hour, minute=minute)
        event = Event()
        event.add('summary', _format_meal_display(meal))
        event.add('dtstart', start)
        event.add('dtend', start + timedelta(minutes=MEAL_DURATION_MINUTES))
        event.add('transp', 'TRANSPARENT')
        event.add('uid', f'{day_date.isoformat()}-{slot}@kitchenos')
        events.append(event)

    return events


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
        for event in create_meal_events(
            day['date'],
            day.get('breakfast'),
            day.get('lunch'),
            day.get('dinner'),
            snack=day.get('snack'),
        ):
            cal.add_component(event)

    return cal.to_ical()
