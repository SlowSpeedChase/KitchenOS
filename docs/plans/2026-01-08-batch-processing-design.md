# Batch Processing Design

Process YouTube URLs from iOS Reminders list in bulk.

## Problem

User saves cooking videos to iOS Reminders ("Recipies to Process") while browsing on phone. Wants to batch extract recipes later on Mac without waiting for each one individually.

## Solution

New `batch_extract.py` script that:
1. Reads uncompleted reminders from "Recipies to Process" list
2. Extracts each recipe using existing pipeline
3. Marks successful extractions as complete
4. Leaves failures unchecked for natural retry

## Architecture

```
Reminders ("Recipies to Process")
    ↓
batch_extract.py
    ↓ (for each uncompleted reminder)
extract_recipe.extract_single_recipe()
    ↓ (on success)
Mark reminder complete
```

### Files Changed

| File | Change |
|------|--------|
| `batch_extract.py` | **New** - batch processing script |
| `extract_recipe.py` | Refactor: extract `extract_single_recipe()` function |
| `requirements.txt` | Add `pyobjc-framework-EventKit` |

## Reminders Integration

Uses `pyobjc-framework-EventKit` for native macOS Reminders access.

```python
from EventKit import EKEventStore, EKEntityTypeReminder

store = EKEventStore.alloc().init()
store.requestAccessToEntityType_completion_(EKEntityTypeReminder, callback)

# Find list by name
calendars = store.calendarsForEntityType_(EKEntityTypeReminder)
target = [c for c in calendars if c.title() == "Recipies to Process"][0]

# Get uncompleted reminders
predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
    None, None, [target]
)
reminders = store.remindersMatchingPredicate_(predicate)

# Mark complete on success
reminder.setCompleted_(True)
store.saveReminder_commit_error_(reminder, True, None)
```

First run triggers macOS permission dialog for Reminders access.

## CLI Interface

```bash
# Process all uncompleted reminders
.venv/bin/python batch_extract.py

# Preview without extracting or marking complete
.venv/bin/python batch_extract.py --dry-run
```

## Output Format

```
Connecting to Reminders...
Found 27 uncompleted items in "Recipies to Process"

[1/27] https://youtube.com/watch?v=abc123
       → Fetching: "Perfect Pasta Carbonara"
       → Source: webpage
       → Saved: 2026-01-08-perfect-pasta-carbonara.md
       ✓ Marked complete

[2/27] https://youtube.com/watch?v=def456
       → Fetching: "Thai Green Curry"
       → Already exists, skipping
       ✓ Marked complete

[3/27] https://youtube.com/watch?v=ghi789
       → Fetching: "Homemade Ramen"
       → Error: Ollama timeout
       ✗ Left unchecked (will retry next run)

=== Summary ===
Processed: 27
Succeeded: 24
Skipped (duplicates): 2
Failed: 1
  - https://youtube.com/watch?v=ghi789 (Ollama timeout)
```

## Behaviors

| Scenario | Behavior |
|----------|----------|
| Successful extraction | Mark reminder complete |
| Recipe already exists | Skip extraction, mark complete |
| Extraction fails | Leave unchecked (retry next run) |
| Invalid URL | Leave unchecked, report in summary |
| Rate limiting | 3-second delay between videos |
| Ctrl+C | Graceful exit, show partial summary |
| Empty list | "No uncompleted reminders found" |
| List not found | Error and exit |
| Permission denied | Instructions to grant in System Settings |

## Duplicate Detection

Before extracting, check if video ID exists in Obsidian using `find_existing_recipe()`. If found, skip extraction and mark complete.

## Dependencies

```
pyobjc-framework-EventKit  # macOS Reminders API
```

## Out of Scope

- Processing from other sources (playlists, channels)
- Parallel processing (sequential is simpler, respects rate limits)
- Scheduling (user runs manually when ready)
