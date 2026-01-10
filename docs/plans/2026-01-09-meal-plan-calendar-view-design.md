# Meal Plan Calendar View Design

## Overview

Display meal plans in a calendar view across three surfaces:
1. **Obsidian** - Full Calendar plugin (primary, view-only)
2. **Apple Calendar** - Day summary events (secondary, synced)
3. **TRMNL** - E-ink display via Apple Calendar integration

## Architecture

```
Meal Plan Files (.md)
        ↓
    sync_calendar.py (LaunchAgent, daily at 6:05am)
        ↓
    meal_calendar.ics
        ↓
   ┌────┴────┐
   ↓         ↓
Obsidian   Apple Calendar
(Full      (subscribes via
Calendar)   API endpoint)
   ↓
 TRMNL
(built-in calendar plugin)
```

## Event Format

All-day events with day summary:

```
SUMMARY: B: Chocolate Cake | L: Salad | D: Pasta
DTSTART;VALUE=DATE:20260119
```

- Empty meals show as "—"
- Days with no meals are skipped (no event)

## Components

### sync_calendar.py

Main entry point that:
1. Reads all `Meal Plans/*.md` files from Obsidian vault
2. Parses meal entries for each day
3. Generates `meal_calendar.ics` in vault root

### lib/meal_plan_parser.py

Parses meal plan markdown:
- Extract week from filename (e.g., `2026-W04.md`)
- Parse day sections (Monday through Sunday)
- Extract recipe links from Breakfast/Lunch/Dinner subsections
- Strip `[[` and `]]` from recipe links

### lib/ics_generator.py

ICS file generation:
- Standard iCalendar format
- `PRODID:-//KitchenOS//Meal Plans//EN`
- One `VEVENT` per day with meals
- All-day events using `DTSTART;VALUE=DATE:`
- Unique UID per day (e.g., `2026-01-19@kitchenos`)

### API Server Addition

Add to `api_server.py`:

```python
@app.route('/calendar.ics')
def serve_calendar():
    return send_file('meal_calendar.ics', mimetype='text/calendar')
```

Accessible via Tailscale at `http://100.111.6.10:5001/calendar.ics`

### LaunchAgent

File: `com.kitchenos.calendar-sync.plist`

Runs daily at 6:05am (after meal plan generator at 6:00am).

## Setup Instructions

### Obsidian Full Calendar Plugin

Configure ICS source in plugin settings:

```yaml
calendars:
  - type: ics
    url: file:///Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/meal_calendar.ics
    name: Meal Plans
    color: "#4CAF50"
```

### Apple Calendar Subscription

1. File → New Calendar Subscription
2. URL: `http://100.111.6.10:5001/calendar.ics`
3. Refresh: Every hour
4. Name: Meal Plans

### TRMNL

Use built-in calendar plugin - it will display Apple Calendar events automatically.

## Files to Create

| File | Purpose |
|------|---------|
| `sync_calendar.py` | Main script - orchestrates parsing and ICS generation |
| `lib/ics_generator.py` | ICS formatting logic |
| `lib/meal_plan_parser.py` | Parses meal plan markdown files |
| `com.kitchenos.calendar-sync.plist` | LaunchAgent for daily sync |

## Edge Cases

- Empty meals → "—" in summary
- Days with no meals → Skip (no event)
- Missing meal plan files → Sync only what exists
- Malformed markdown → Log warning, skip file
- Recipe links with special characters → Strip brackets, use plain text

## Testing

```bash
# Generate ICS
.venv/bin/python sync_calendar.py

# Verify output
cat meal_calendar.ics

# Test API endpoint
curl http://localhost:5001/calendar.ics
```

## Manual Trigger

```bash
.venv/bin/python sync_calendar.py
```
