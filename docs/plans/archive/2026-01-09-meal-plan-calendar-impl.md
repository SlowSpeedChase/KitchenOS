# Meal Plan Calendar View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate ICS calendar file from meal plans for viewing in Obsidian Full Calendar plugin and Apple Calendar.

**Architecture:** Parse meal plan markdown files → extract meals per day → generate ICS events → serve via API. LaunchAgent runs daily at 6:05am.

**Tech Stack:** Python 3.11, icalendar library, Flask

---

## Task 1: Add icalendar Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add icalendar to requirements**

Add this line to `requirements.txt`:

```
icalendar               # ICS calendar file generation
```

**Step 2: Install dependency**

Run: `.venv/bin/pip install icalendar`

**Step 3: Verify installation**

Run: `.venv/bin/python -c "from icalendar import Calendar; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add icalendar dependency"
```

---

## Task 2: Create Meal Plan Parser

**Files:**
- Create: `lib/meal_plan_parser.py`
- Create: `tests/test_meal_plan_parser.py`

**Step 1: Write failing tests**

Create `tests/test_meal_plan_parser.py`:

```python
"""Tests for meal plan parser."""

import pytest
from datetime import date
from lib.meal_plan_parser import parse_meal_plan, extract_meals_for_day


class TestParseMealPlan:
    """Test parsing full meal plan files."""

    def test_extracts_week_dates(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert len(result) == 7
        assert result[0]['date'] == date(2026, 1, 19)
        assert result[0]['day'] == 'Monday'

    def test_extracts_recipe_links(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Rich Fudgy Chocolate Cake]]
### Lunch
[[Caesar Salad]]
### Dinner
[[Pasta Aglio E Olio]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] == 'Rich Fudgy Chocolate Cake'
        assert result[0]['lunch'] == 'Caesar Salad'
        assert result[0]['dinner'] == 'Pasta Aglio E Olio'

    def test_handles_empty_meals(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner
[[Pasta]]
### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        assert result[0]['breakfast'] is None
        assert result[0]['lunch'] is None
        assert result[0]['dinner'] == 'Pasta'

    def test_handles_multiple_recipes_uses_first(self):
        content = """# Meal Plan - Week 04 (Jan 19 - Jan 25, 2026)

## Monday (Jan 19)
### Breakfast
[[Eggs]]
[[Toast]]
### Lunch

### Dinner

### Notes
"""
        result = parse_meal_plan(content, 2026, 4)

        # Use first recipe only for simplicity
        assert result[0]['breakfast'] == 'Eggs'


class TestExtractMealsForDay:
    """Test extracting meals from a day section."""

    def test_extracts_all_meals(self):
        section = """## Monday (Jan 19)
### Breakfast
[[Pancakes]]
### Lunch
[[Salad]]
### Dinner
[[Steak]]
### Notes
Some notes here
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] == 'Pancakes'
        assert result['lunch'] == 'Salad'
        assert result['dinner'] == 'Steak'

    def test_returns_none_for_empty(self):
        section = """## Monday (Jan 19)
### Breakfast

### Lunch

### Dinner

### Notes
"""
        result = extract_meals_for_day(section)

        assert result['breakfast'] is None
        assert result['lunch'] is None
        assert result['dinner'] is None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py -v`
Expected: FAIL with "No module named 'lib.meal_plan_parser'"

**Step 3: Write implementation**

Create `lib/meal_plan_parser.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add lib/meal_plan_parser.py tests/test_meal_plan_parser.py
git commit -m "feat: add meal plan parser for calendar generation"
```

---

## Task 3: Create ICS Generator

**Files:**
- Create: `lib/ics_generator.py`
- Create: `tests/test_ics_generator.py`

**Step 1: Write failing tests**

Create `tests/test_ics_generator.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ics_generator.py -v`
Expected: FAIL with "No module named 'lib.ics_generator'"

**Step 3: Write implementation**

Create `lib/ics_generator.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ics_generator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add lib/ics_generator.py tests/test_ics_generator.py
git commit -m "feat: add ICS calendar generator"
```

---

## Task 4: Create Main Sync Script

**Files:**
- Create: `sync_calendar.py`
- Create: `tests/test_sync_calendar.py`

**Step 1: Write failing tests**

Create `tests/test_sync_calendar.py`:

```python
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

        days = collect_all_days()

        assert len(days) == 7
        assert days[0]['breakfast'] == 'Pancakes'
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sync_calendar.py -v`
Expected: FAIL with "No module named 'sync_calendar'"

**Step 3: Write implementation**

Create `sync_calendar.py`:

```python
#!/usr/bin/env python3
"""Sync meal plans to ICS calendar file.

Reads all meal plan files and generates a single ICS file for
Obsidian Full Calendar plugin and Apple Calendar subscription.

Usage:
    python sync_calendar.py           # Generate calendar
    python sync_calendar.py --dry-run # Preview without writing
"""

import argparse
import re
import sys
from pathlib import Path

from lib.meal_plan_parser import parse_meal_plan
from lib.ics_generator import generate_ics

# Configuration
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = OBSIDIAN_VAULT / "Meal Plans"
ICS_OUTPUT_PATH = OBSIDIAN_VAULT / "meal_calendar.ics"


def parse_week_from_filename(filename: str) -> tuple[int, int] | None:
    """Extract year and week from filename like '2026-W04.md'.

    Returns:
        Tuple of (year, week) or None if invalid format
    """
    match = re.match(r'^(\d{4})-W(\d{2})\.md$', filename)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def collect_all_days() -> list[dict]:
    """Collect all days from all meal plan files.

    Returns:
        List of day dicts sorted by date
    """
    all_days = []

    if not MEAL_PLANS_PATH.exists():
        return all_days

    for file_path in MEAL_PLANS_PATH.glob('*.md'):
        parsed = parse_week_from_filename(file_path.name)
        if not parsed:
            continue

        year, week = parsed
        try:
            content = file_path.read_text(encoding='utf-8')
            days = parse_meal_plan(content, year, week)
            all_days.extend(days)
        except Exception as e:
            print(f"Warning: Could not parse {file_path.name}: {e}", file=sys.stderr)

    # Sort by date
    all_days.sort(key=lambda d: d['date'])
    return all_days


def main():
    parser = argparse.ArgumentParser(description="Sync meal plans to ICS calendar")
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing file')
    args = parser.parse_args()

    print("Collecting meal plans...")
    days = collect_all_days()

    if not days:
        print("No meal plans found.")
        return

    # Count days with meals
    days_with_meals = sum(1 for d in days if any([d['breakfast'], d['lunch'], d['dinner']]))
    print(f"Found {len(days)} days across meal plans ({days_with_meals} with meals)")

    # Generate ICS
    ics_content = generate_ics(days)

    if args.dry_run:
        print("\n--- Preview (first 2000 chars) ---")
        print(ics_content.decode('utf-8')[:2000])
        print("--- End Preview ---")
        print(f"\nDry run complete. Would write to: {ICS_OUTPUT_PATH}")
        return

    # Write file
    ICS_OUTPUT_PATH.write_bytes(ics_content)
    print(f"Written: {ICS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sync_calendar.py -v`
Expected: All tests PASS

**Step 5: Test manually**

Run: `.venv/bin/python sync_calendar.py --dry-run`
Expected: Shows preview of ICS content

**Step 6: Commit**

```bash
git add sync_calendar.py tests/test_sync_calendar.py
git commit -m "feat: add sync_calendar.py main script"
```

---

## Task 5: Add API Endpoint

**Files:**
- Modify: `api_server.py`

**Step 1: Add calendar endpoint**

Add to `api_server.py` after the `/send-to-reminders` route (around line 299):

```python
@app.route('/calendar.ics', methods=['GET'])
def serve_calendar():
    """Serve the meal plan calendar ICS file."""
    from flask import send_file

    ics_path = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/meal_calendar.ics")

    if not ics_path.exists():
        return "Calendar not generated. Run sync_calendar.py first.", 404

    return send_file(
        ics_path,
        mimetype='text/calendar',
        as_attachment=False,
        download_name='meal_calendar.ics'
    )
```

**Step 2: Test manually**

First generate the calendar:
Run: `.venv/bin/python sync_calendar.py`

Then test endpoint (requires server running):
Run: `curl http://localhost:5001/calendar.ics`
Expected: ICS file content

**Step 3: Commit**

```bash
git add api_server.py
git commit -m "feat: add /calendar.ics API endpoint"
```

---

## Task 6: Create LaunchAgent

**Files:**
- Create: `com.kitchenos.calendar-sync.plist`

**Step 1: Create LaunchAgent plist**

Create `com.kitchenos.calendar-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kitchenos.calendar-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/chaseeasterling/KitchenOS/.venv/bin/python</string>
        <string>/Users/chaseeasterling/KitchenOS/sync_calendar.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>5</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/chaseeasterling/KitchenOS/calendar_sync.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/chaseeasterling/KitchenOS/calendar_sync.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/chaseeasterling/KitchenOS</string>
</dict>
</plist>
```

**Step 2: Commit**

```bash
git add com.kitchenos.calendar-sync.plist
git commit -m "feat: add LaunchAgent for calendar sync"
```

---

## Task 7: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add Calendar Sync section to CLAUDE.md**

Add after "### Generate Shopping List" section (around line 120):

```markdown
### Sync Calendar

```bash
# Generate meal calendar ICS file
.venv/bin/python sync_calendar.py

# Preview without writing
.venv/bin/python sync_calendar.py --dry-run
```
```

**Step 2: Add to Architecture section**

Add to Core Components table:

```markdown
| `sync_calendar.py` | Generates ICS calendar from meal plans |
| `lib/meal_plan_parser.py` | Parses meal plan markdown files |
| `lib/ics_generator.py` | Creates ICS calendar format |
```

**Step 3: Add API endpoint to table**

Add to Endpoints table:

```markdown
| `/calendar.ics` | GET | Serves meal plan calendar file |
```

**Step 4: Add to Key Functions**

```markdown
**sync_calendar.py:**
- `collect_all_days()` - Collects all days from meal plan files
- `parse_week_from_filename()` - Extracts year/week from filename

**lib/meal_plan_parser.py:**
- `parse_meal_plan()` - Parses meal plan markdown into structured data
- `extract_meals_for_day()` - Extracts meals from a day section

**lib/ics_generator.py:**
- `generate_ics()` - Creates ICS calendar content
- `create_meal_event()` - Creates single calendar event
- `format_day_summary()` - Formats "B: X | L: Y | D: Z" string
```

**Step 5: Add LaunchAgent section**

Add after "## Meal Plan Generator (LaunchAgent)" section:

```markdown
## Calendar Sync (LaunchAgent)

Syncs meal plans to ICS calendar file daily at 6:05am (after meal plan generator).

### Management

```bash
# Install the LaunchAgent
cp com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist

# View logs
tail -f /Users/chaseeasterling/KitchenOS/calendar_sync.log

# Test run manually
.venv/bin/python sync_calendar.py
```

### Output

ICS file is written to: `{Obsidian Vault}/meal_calendar.ics`

Accessible via API at: `http://localhost:5001/calendar.ics` (or Tailscale IP)
```

**Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add calendar sync documentation"
```

---

## Task 8: Final Integration Test

**Step 1: Run full sync**

Run: `.venv/bin/python sync_calendar.py`
Expected: "Written: /Users/.../meal_calendar.ics"

**Step 2: Verify ICS file**

Run: `head -20 "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/meal_calendar.ics"`
Expected: Valid ICS header with VCALENDAR, VERSION, PRODID

**Step 3: Test API endpoint**

Run: `curl http://localhost:5001/calendar.ics | head -10`
Expected: Same ICS content

**Step 4: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_meal_plan_parser.py tests/test_ics_generator.py tests/test_sync_calendar.py -v`
Expected: All tests PASS

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete meal plan calendar view implementation"
```

---

## Post-Implementation: Setup Instructions

After merging, user needs to:

1. **Install LaunchAgent:**
   ```bash
   cp com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist
   ```

2. **Install Obsidian Full Calendar plugin** and configure:
   - Settings → Add calendar → ICS
   - URL: `file:///Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/meal_calendar.ics`

3. **Subscribe in Apple Calendar:**
   - File → New Calendar Subscription
   - URL: `http://100.111.6.10:5001/calendar.ics`
   - Refresh: Every hour

4. **TRMNL:** Enable calendar widget (will show Apple Calendar events)
