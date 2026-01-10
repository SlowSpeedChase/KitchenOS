"""Tests for calendar sync script."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from sync_calendar import parse_week_from_filename, collect_all_days


class TestParseWeekFromFilename:
    """Test week parsing from filenames."""

    def test_parses_valid_filename(self):
        year, week = parse_week_from_filename('2026-W04.md')
        assert year == 2026
        assert week == 4

    def test_returns_none_for_invalid(self):
        result = parse_week_from_filename('notes.md')
        assert result is None


class TestCollectAllDays:
    """Test collecting days from all meal plans."""

    @patch('sync_calendar.MEAL_PLANS_PATH')
    def test_collects_from_multiple_weeks(self, mock_path):
        # Create mock file objects
        week4_content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch

### Dinner

### Notes


## Tuesday (Jan 20)
### Breakfast

### Lunch

### Dinner

### Notes


## Wednesday (Jan 21)
### Breakfast

### Lunch

### Dinner

### Notes


## Thursday (Jan 22)
### Breakfast

### Lunch

### Dinner

### Notes


## Friday (Jan 23)
### Breakfast

### Lunch

### Dinner

### Notes


## Saturday (Jan 24)
### Breakfast

### Lunch

### Dinner

### Notes


## Sunday (Jan 25)
### Breakfast

### Lunch

### Dinner

### Notes

"""
        mock_file = MagicMock()
        mock_file.name = '2026-W04.md'
        mock_file.read_text.return_value = week4_content

        mock_path.glob.return_value = [mock_file]
        mock_path.exists.return_value = True

        days = collect_all_days()

        assert len(days) == 7
        assert days[0]['breakfast'] == 'Pancakes'
