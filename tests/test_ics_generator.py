"""Tests for ICS calendar generator."""

import pytest
from datetime import date, datetime
from icalendar import Calendar
from lib.ics_generator import format_day_summary, create_meal_events, generate_ics
from lib.meal_plan_parser import MealEntry


class TestFormatDaySummary:
    """Test day summary formatting."""

    def test_formats_all_meals(self):
        result = format_day_summary('Pancakes', 'Salad', dinner='Steak')
        assert result == 'B: Pancakes | L: Salad | D: Steak'

    def test_formats_snack_slot(self):
        result = format_day_summary('Pancakes', 'Salad', 'Almonds', 'Steak')
        assert result == 'B: Pancakes | L: Salad | S: Almonds | D: Steak'

    def test_uses_dash_for_empty(self):
        result = format_day_summary(None, 'Salad', None)
        assert result == 'B: — | L: Salad | D: —'

    def test_all_empty(self):
        result = format_day_summary(None, None, None)
        assert result == 'B: — | L: — | D: —'

    def test_formats_meal_entry_without_multiplier(self):
        result = format_day_summary(
            MealEntry('Pancakes', 1),
            MealEntry('Salad', 1),
            dinner=MealEntry('Steak', 1),
        )
        assert result == 'B: Pancakes | L: Salad | D: Steak'

    def test_formats_meal_entry_with_multiplier(self):
        result = format_day_summary(
            MealEntry('Pancakes', 2),
            None,
            dinner=MealEntry('Steak', 1),
        )
        assert result == 'B: Pancakes x2 | L: — | D: Steak'


class TestCreateMealEvents:
    """Test timed per-slot ICS event creation."""

    def test_creates_one_timed_event_per_meal(self):
        events = create_meal_events(
            date(2026, 1, 19),
            'Pancakes',
            'Salad',
            'Steak',
        )
        # breakfast + lunch + dinner = 3 events (no snack)
        assert len(events) == 3
        summaries = [str(e['SUMMARY']) for e in events]
        assert summaries == ['Pancakes', 'Salad', 'Steak']

    def test_event_times_and_transparency(self):
        events = create_meal_events(date(2026, 1, 19), breakfast='Pancakes')
        ev = events[0]
        assert ev['DTSTART'].dt == datetime(2026, 1, 19, 8, 0)
        assert ev['DTEND'].dt == datetime(2026, 1, 19, 8, 30)
        assert str(ev['TRANSP']) == 'TRANSPARENT'
        assert str(ev['UID']) == '2026-01-19-breakfast@kitchenos'

    def test_dinner_time(self):
        events = create_meal_events(date(2026, 1, 19), dinner='Steak')
        assert events[0]['DTSTART'].dt == datetime(2026, 1, 19, 19, 30)

    def test_snack_included_when_present(self):
        events = create_meal_events(date(2026, 1, 19), snack='Almonds')
        assert len(events) == 1
        assert events[0]['DTSTART'].dt == datetime(2026, 1, 19, 15, 0)

    def test_meal_entry_multiplier_in_summary(self):
        events = create_meal_events(date(2026, 1, 19), dinner=MealEntry('Steak', 2))
        assert str(events[0]['SUMMARY']) == 'Steak x2'

    def test_empty_day_yields_no_events(self):
        assert create_meal_events(date(2026, 1, 19), None, None, None) == []


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

        # Monday has breakfast + dinner = 2 timed events; Tuesday has none.
        events = [c for c in cal.walk() if c.name == 'VEVENT']
        assert len(events) == 2
        summaries = sorted(str(e['SUMMARY']) for e in events)
        assert summaries == ['Pancakes', 'Pasta']

    def test_includes_calendar_metadata(self):
        days = [{'date': date(2026, 1, 19), 'day': 'Monday', 'breakfast': 'X', 'lunch': None, 'dinner': None}]

        ics_content = generate_ics(days)
        cal = Calendar.from_ical(ics_content)

        assert cal['PRODID'] == '-//KitchenOS//Meal Plans//EN'
        assert cal['VERSION'] == '2.0'
