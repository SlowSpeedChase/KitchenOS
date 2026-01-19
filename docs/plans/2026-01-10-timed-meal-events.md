# Timed Meal Events Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert calendar sync from all-day events to separate timed events per meal (Breakfast 8am, Lunch 12pm, Snack 3pm, Dinner 7:30pm).

**Architecture:** Add snack support to meal plan templates and parser, then rewrite ICS generator to create individual 30-minute events marked as free (TRANSP: TRANSPARENT).

**Tech Stack:** Python 3.11, icalendar library, pytest

---

## Task 1: Add Snack Extraction to Parser

**Files:**
- Modify: `lib/meal_plan_parser.py:29-41`
- Test: `tests/test_meal_plan_parser.py`

**Step 1: Write failing test for snack extraction**

Add to `tests/test_meal_plan_parser.py` after line 118:

```python
    def test_extracts_snack(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch
[[Salad]]
### Snack
[[Cookies]]
### Dinner
[[Steak]]
### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == 'Pancakes'
        assert result['lunch'] == 'Salad'
        assert result['snack'] == 'Cookies'
        assert result['dinner'] == 'Steak'
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestExtractMealsForDay::test_extracts_snack -v`
Expected: FAIL with KeyError 'snack'

**Step 3: Update extract_meals_for_day to include snack**

In `lib/meal_plan_parser.py`, change line 29:

```python
    meals = {'breakfast': None, 'lunch': None, 'snack': None, 'dinner': None}
```

And change line 31:

```python
    for meal_type in ['breakfast', 'lunch', 'snack', 'dinner']:
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestExtractMealsForDay::test_extracts_snack -v`
Expected: PASS

**Step 5: Add test for snack=None when empty**

Add to `tests/test_meal_plan_parser.py`:

```python
    def test_returns_none_for_empty_snack(self):
        section = """## Monday (Jan 19)
### Breakfast

### Lunch

### Snack

### Dinner

### Notes
"""
        result = extract_meals_for_day(section)

        assert result['snack'] is None
```

**Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py::TestExtractMealsForDay::test_returns_none_for_empty_snack -v`
Expected: PASS (implementation already handles this)

**Step 7: Commit**

```bash
git add lib/meal_plan_parser.py tests/test_meal_plan_parser.py
git commit -m "feat: add snack extraction to meal plan parser"
```

---

## Task 2: Add Snack Section to Meal Plan Template

**Files:**
- Modify: `templates/meal_plan_template.py:55-68`
- Test: `tests/test_meal_plan_template.py` (create)

**Step 1: Write failing test for snack section**

Create `tests/test_meal_plan_template.py`:

```python
"""Tests for meal plan template generation."""

import pytest
from templates.meal_plan_template import generate_meal_plan_markdown


class TestGenerateMealPlanMarkdown:
    """Test meal plan markdown generation."""

    def test_includes_snack_section(self):
        result = generate_meal_plan_markdown(2026, 4)

        # Check Monday has snack section
        assert '### Snack' in result

        # Verify order: Lunch before Snack before Dinner
        lunch_pos = result.find('### Lunch')
        snack_pos = result.find('### Snack')
        dinner_pos = result.find('### Dinner')

        assert lunch_pos < snack_pos < dinner_pos
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_template.py::TestGenerateMealPlanMarkdown::test_includes_snack_section -v`
Expected: FAIL with AssertionError (no Snack section)

**Step 3: Add Snack section to template**

In `templates/meal_plan_template.py`, change lines 57-68 to:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_template.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add templates/meal_plan_template.py tests/test_meal_plan_template.py
git commit -m "feat: add snack section to meal plan template"
```

---

## Task 3: Rewrite ICS Generator for Timed Events

**Files:**
- Rewrite: `lib/ics_generator.py`
- Rewrite: `tests/test_ics_generator.py`

**Step 1: Write new test file**

Replace `tests/test_ics_generator.py` entirely:

```python
"""Tests for ICS calendar generator with timed events."""

import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from icalendar import Calendar
from lib.ics_generator import create_meal_event, generate_ics, MEAL_TIMES


class TestMealTimes:
    """Test meal time configuration."""

    def test_meal_times_defined(self):
        assert MEAL_TIMES['breakfast'] == (8, 0)
        assert MEAL_TIMES['lunch'] == (12, 0)
        assert MEAL_TIMES['snack'] == (15, 0)
        assert MEAL_TIMES['dinner'] == (19, 30)


class TestCreateMealEvent:
    """Test ICS event creation."""

    def test_creates_timed_event(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'breakfast',
            'Pancakes'
        )

        assert event['SUMMARY'] == 'Pancakes'
        assert event['UID'] == '2026-01-19-breakfast@kitchenos'

    def test_event_has_correct_time(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'dinner',
            'Steak'
        )

        # Dinner at 7:30pm
        dtstart = event['DTSTART'].dt
        assert dtstart.hour == 19
        assert dtstart.minute == 30

    def test_event_duration_30_minutes(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'breakfast',
            'Pancakes'
        )

        dtstart = event['DTSTART'].dt
        dtend = event['DTEND'].dt
        duration = dtend - dtstart

        assert duration.total_seconds() == 30 * 60  # 30 minutes

    def test_event_marked_as_free(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'breakfast',
            'Pancakes'
        )

        assert event['TRANSP'] == 'TRANSPARENT'

    def test_returns_none_for_empty_recipe(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'breakfast',
            None
        )

        assert event is None


class TestGenerateIcs:
    """Test full ICS generation."""

    def test_generates_separate_events_per_meal(self):
        days = [
            {
                'date': date(2026, 1, 19),
                'day': 'Monday',
                'breakfast': 'Pancakes',
                'lunch': 'Salad',
                'snack': None,
                'dinner': 'Pasta'
            }
        ]

        ics_content = generate_ics(days)
        cal = Calendar.from_ical(ics_content)

        events = [c for c in cal.walk() if c.name == 'VEVENT']
        assert len(events) == 3  # breakfast, lunch, dinner (no snack)

        summaries = [str(e['SUMMARY']) for e in events]
        assert 'Pancakes' in summaries
        assert 'Salad' in summaries
        assert 'Pasta' in summaries

    def test_skips_days_with_no_meals(self):
        days = [
            {
                'date': date(2026, 1, 19),
                'day': 'Monday',
                'breakfast': None,
                'lunch': None,
                'snack': None,
                'dinner': None
            }
        ]

        ics_content = generate_ics(days)
        cal = Calendar.from_ical(ics_content)

        events = [c for c in cal.walk() if c.name == 'VEVENT']
        assert len(events) == 0

    def test_includes_calendar_metadata(self):
        days = [{'date': date(2026, 1, 19), 'day': 'Monday', 'breakfast': 'X', 'lunch': None, 'snack': None, 'dinner': None}]

        ics_content = generate_ics(days)
        cal = Calendar.from_ical(ics_content)

        assert cal['PRODID'] == '-//KitchenOS//Meal Plans//EN'
        assert cal['VERSION'] == '2.0'
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ics_generator.py -v`
Expected: FAIL (old implementation doesn't match new tests)

**Step 3: Rewrite ics_generator.py**

Replace `lib/ics_generator.py` entirely:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ics_generator.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add lib/ics_generator.py tests/test_ics_generator.py
git commit -m "feat: convert calendar to timed meal events

- Separate events for breakfast (8am), lunch (12pm), snack (3pm), dinner (7:30pm)
- 30-minute duration per event
- Events marked as free (TRANSP: TRANSPARENT)
- Removes all-day summary format"
```

---

## Task 4: Test End-to-End

**Files:**
- None (manual testing)

**Step 1: Run calendar sync dry run**

Run: `.venv/bin/python sync_calendar.py --dry-run`
Expected: Output shows ICS content with timed events

**Step 2: Run calendar sync**

Run: `.venv/bin/python sync_calendar.py`
Expected: ICS file written to Obsidian vault

**Step 3: Verify in Apple Calendar**

1. Open Apple Calendar
2. File > New Calendar Subscription
3. Enter: `http://localhost:5001/calendar.ics`
4. Verify events show at correct times (8am, 12pm, 3pm, 7:30pm)
5. Verify events show as "free" (not blocking time)

---

## Task 5: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md Key Functions section**

Find the `lib/ics_generator.py` entry in the Key Functions section and update to:

```markdown
**lib/ics_generator.py:**
- `MEAL_TIMES` - Dict mapping meal types to (hour, minute) tuples
- `create_meal_event()` - Creates single timed event for a meal
- `generate_ics()` - Creates ICS calendar with timed events per meal
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for timed meal events"
```

---

## Task 6: Final Verification and Merge

**Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All 176+ tests pass

**Step 2: Verify git status clean**

Run: `git status`
Expected: Clean working tree

**Step 3: Push branch**

Run: `git push -u origin feature/timed-meal-events`

**Step 4: Create PR or merge**

Use superpowers:finishing-a-development-branch skill.
