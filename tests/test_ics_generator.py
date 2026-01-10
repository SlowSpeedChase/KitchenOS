"""Tests for ICS calendar generator."""

import pytest
from datetime import date
from icalendar import Calendar
from lib.ics_generator import format_day_summary, create_meal_event, generate_ics


class TestFormatDaySummary:
    """Test day summary formatting."""

    def test_formats_all_meals(self):
        result = format_day_summary('Pancakes', 'Salad', 'Steak')
        assert result == 'B: Pancakes | L: Salad | D: Steak'

    def test_uses_dash_for_empty(self):
        result = format_day_summary(None, 'Salad', None)
        assert result == 'B: — | L: Salad | D: —'

    def test_all_empty(self):
        result = format_day_summary(None, None, None)
        assert result == 'B: — | L: — | D: —'


class TestCreateMealEvent:
    """Test ICS event creation."""

    def test_creates_all_day_event(self):
        event = create_meal_event(
            date(2026, 1, 19),
            'Pancakes',
            'Salad',
            'Steak'
        )

        assert event['SUMMARY'] == 'B: Pancakes | L: Salad | D: Steak'
        assert str(event['DTSTART'].dt) == '2026-01-19'
        assert event['UID'] == '2026-01-19@kitchenos'

    def test_skips_empty_days(self):
        event = create_meal_event(
            date(2026, 1, 19),
            None,
            None,
            None
        )

        assert event is None


class TestGenerateIcs:
    """Test full ICS generation."""

    def test_generates_valid_ics(self):
        days = [
            {
                'date': date(2026, 1, 19),
                'day': 'Monday',
                'breakfast': 'Pancakes',
                'lunch': None,
                'dinner': 'Pasta'
            },
            {
                'date': date(2026, 1, 20),
                'day': 'Tuesday',
                'breakfast': None,
                'lunch': None,
                'dinner': None
            }
        ]

        ics_content = generate_ics(days)

        # Parse to verify valid
        cal = Calendar.from_ical(ics_content)

        # Should have 1 event (Tuesday has no meals)
        events = [c for c in cal.walk() if c.name == 'VEVENT']
        assert len(events) == 1
        assert events[0]['SUMMARY'] == 'B: Pancakes | L: — | D: Pasta'

    def test_includes_calendar_metadata(self):
        days = [{'date': date(2026, 1, 19), 'day': 'Monday', 'breakfast': 'X', 'lunch': None, 'dinner': None}]

        ics_content = generate_ics(days)
        cal = Calendar.from_ical(ics_content)

        assert cal['PRODID'] == '-//KitchenOS//Meal Plans//EN'
        assert cal['VERSION'] == '2.0'
