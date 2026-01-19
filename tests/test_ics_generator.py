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
