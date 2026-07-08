# Batch Processing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Process YouTube URLs from iOS Reminders "Recipies to Process" list and extract recipes in bulk.

**Architecture:** New `batch_extract.py` script uses macOS EventKit API via pyobjc to read Reminders. Calls refactored `extract_single_recipe()` for each URL. Marks successful extractions complete.

**Tech Stack:** Python 3.9, pyobjc-framework-EventKit, existing extraction pipeline

---

### Task 1: Add pyobjc Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add EventKit dependency**

Add to end of `requirements.txt`:
```
# macOS Reminders integration (batch processing)
pyobjc-framework-EventKit>=10.0
```

**Step 2: Install dependency**

Run: `.venv/bin/pip install pyobjc-framework-EventKit`
Expected: Successfully installed pyobjc-framework-EventKit

**Step 3: Verify import works**

Run: `.venv/bin/python -c "from EventKit import EKEventStore; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add pyobjc-framework-EventKit for Reminders integration"
```

---

### Task 2: Refactor extract_recipe.py - Extract Core Function

**Files:**
- Modify: `extract_recipe.py:122-236`

**Step 1: Create extract_single_recipe function**

Replace the `main()` function with two functions. The new `extract_single_recipe()` contains the core logic, and `main()` becomes a thin CLI wrapper.

In `extract_recipe.py`, replace everything from line 122 to end with:

```python
def extract_single_recipe(url: str, dry_run: bool = False) -> dict:
    """Extract recipe from a YouTube URL.

    Args:
        url: YouTube video URL or ID
        dry_run: If True, don't save to Obsidian

    Returns:
        dict with keys:
            success: bool
            title: str (video title)
            recipe_name: str (extracted recipe name)
            filepath: Path or None (where saved)
            error: str or None (error message if failed)
            skipped: bool (True if already existed)
    """
    from main import youtube_parser, get_video_metadata, get_transcript

    result = {
        "success": False,
        "title": None,
        "recipe_name": None,
        "filepath": None,
        "error": None,
        "skipped": False,
        "source": None,
    }

    try:
        # Parse video ID
        video_id = youtube_parser(url)
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        # Check for existing recipe first
        existing = find_existing_recipe(OBSIDIAN_RECIPES_PATH, video_id)
        if existing and not dry_run:
            result["success"] = True
            result["skipped"] = True
            result["filepath"] = existing
            # Try to get title from existing file
            try:
                content = existing.read_text(encoding='utf-8')
                from lib.recipe_parser import parse_recipe_file
                parsed = parse_recipe_file(content)
                result["title"] = parsed['frontmatter'].get('video_title', existing.stem)
                result["recipe_name"] = parsed['frontmatter'].get('recipe_name', existing.stem)
            except Exception:
                result["title"] = existing.stem
                result["recipe_name"] = existing.stem
            return result

        # Get video metadata
        metadata = get_video_metadata(video_id)
        if not metadata:
            result["error"] = "Could not fetch video metadata"
            return result

        title = metadata['title']
        channel = metadata['channel']
        description = metadata['description']
        result["title"] = title

        # Get transcript
        transcript_result = get_transcript(video_id)
        transcript = transcript_result['text']

        # === PRIORITY CHAIN ===
        recipe_data = None
        source = None
        recipe_link = None

        # 1. Check for recipe link in description
        recipe_link = find_recipe_link(description)

        if recipe_link:
            recipe_data = scrape_recipe_from_url(recipe_link)
            if recipe_data:
                source = "webpage"

        # 2. Try parsing recipe from description
        if not recipe_data:
            recipe_data = parse_recipe_from_description(description, title, channel)
            if recipe_data:
                source = "description"

        # 3. Fall back to AI extraction from transcript
        if not recipe_data:
            recipe_data, error = extract_recipe_with_ollama(title, channel, description, transcript)
            if error:
                result["error"] = error
                return result
            source = "ai_extraction"

        # 4. Extract cooking tips if we got recipe from webpage or description
        if source in ("webpage", "description") and transcript:
            tips = extract_cooking_tips(transcript, recipe_data)
            recipe_data['video_tips'] = tips

        # Add source metadata
        recipe_data['source'] = source
        recipe_data['source_url'] = recipe_link

        recipe_name = recipe_data.get('recipe_name', 'Unknown Recipe')
        result["recipe_name"] = recipe_name
        result["source"] = source

        if dry_run:
            result["success"] = True
            return result

        # Save to Obsidian
        filepath = save_recipe_to_obsidian(recipe_data, video_url, title, channel, video_id)
        result["success"] = True
        result["filepath"] = filepath
        return result

    except Exception as e:
        result["error"] = str(e)
        return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract recipes from YouTube cooking videos"
    )
    parser.add_argument(
        'url',
        type=str,
        help='YouTube video URL or ID'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print recipe without saving to Obsidian'
    )
    args = parser.parse_args()

    video_id = youtube_parser(args.url)
    print(f"Fetching video data for: {video_id}")

    result = extract_single_recipe(args.url, dry_run=args.dry_run)

    if not result["success"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if result["skipped"]:
        print(f"Recipe already exists: {result['filepath']}")
    elif args.dry_run:
        # For dry run, we need to regenerate the markdown for display
        # Re-fetch and display (simplified)
        print(f"Would extract: {result['recipe_name']}")
        print("(Use without --dry-run to save)")
    else:
        print(f"Title: {result['title']}")
        print(f"Extracted: {result['recipe_name']} (source: {result['source']})")
        print(f"Saved to: {result['filepath']}")

    print("\nDone!")


if __name__ == "__main__":
    main()
```

**Step 2: Test single extraction still works**

Run: `.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"`
Expected: Completes without error, shows extraction info

**Step 3: Commit**

```bash
git add extract_recipe.py
git commit -m "refactor: extract extract_single_recipe() for reuse

Separates core extraction logic from CLI handling.
Enables batch_extract.py to reuse the extraction pipeline."
```

---

### Task 3: Create batch_extract.py - Reminders Integration

**Files:**
- Create: `batch_extract.py`

**Step 1: Create the batch extraction script**

Create `batch_extract.py`:

```python
#!/usr/bin/env python3
"""
KitchenOS - Batch Recipe Extractor
Processes YouTube URLs from iOS Reminders and extracts recipes in bulk.

Usage:
    python batch_extract.py              # Process all uncompleted reminders
    python batch_extract.py --dry-run    # Preview without extracting or marking complete
"""

import argparse
import sys
import time
from pathlib import Path

# macOS Reminders integration
from EventKit import (
    EKEventStore,
    EKEntityTypeReminder,
    EKAuthorizationStatusAuthorized,
    EKAuthorizationStatusNotDetermined,
)
from Foundation import NSRunLoop, NSDate

from extract_recipe import extract_single_recipe
from main import youtube_parser

# Configuration
REMINDERS_LIST_NAME = "Recipies to Process"
DELAY_BETWEEN_VIDEOS = 3  # seconds


def request_reminders_access(store):
    """Request access to Reminders. Blocks until user responds."""
    status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeReminder)

    if status == EKAuthorizationStatusAuthorized:
        return True

    if status == EKAuthorizationStatusNotDetermined:
        # Need to request access
        granted = [None]  # Use list to allow mutation in callback

        def callback(granted_access, error):
            granted[0] = granted_access

        store.requestAccessToEntityType_completion_(EKEntityTypeReminder, callback)

        # Wait for callback (run loop needed for async callback)
        timeout = 60  # seconds
        start = time.time()
        while granted[0] is None and (time.time() - start) < timeout:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )

        return granted[0] == True

    return False


def get_reminders_list(store, list_name):
    """Find a Reminders list by name."""
    calendars = store.calendarsForEntityType_(EKEntityTypeReminder)
    for cal in calendars:
        if cal.title() == list_name:
            return cal
    return None


def get_uncompleted_reminders(store, calendar):
    """Get all uncompleted reminders from a calendar."""
    predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, None, [calendar]
    )

    # fetchRemindersMatchingPredicate is async, need to wait
    reminders = [None]

    def callback(result):
        reminders[0] = result

    store.fetchRemindersMatchingPredicate_completion_(predicate, callback)

    # Wait for callback
    timeout = 30
    start = time.time()
    while reminders[0] is None and (time.time() - start) < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )

    return list(reminders[0]) if reminders[0] else []


def mark_reminder_complete(store, reminder):
    """Mark a reminder as completed."""
    reminder.setCompleted_(True)
    error = None
    success = store.saveReminder_commit_error_(reminder, True, error)
    return success


def is_youtube_url(text):
    """Check if text looks like a YouTube URL."""
    if not text:
        return False
    text = text.strip().lower()
    return any(domain in text for domain in ['youtube.com', 'youtu.be'])


def main():
    parser = argparse.ArgumentParser(
        description="Batch extract recipes from YouTube URLs in Reminders"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without extracting or marking complete'
    )
    args = parser.parse_args()

    print("Connecting to Reminders...")

    # Initialize EventKit
    store = EKEventStore.alloc().init()

    # Request access
    if not request_reminders_access(store):
        print("Error: Reminders access denied.", file=sys.stderr)
        print("Grant access in System Settings → Privacy & Security → Reminders", file=sys.stderr)
        sys.exit(1)

    # Find the target list
    calendar = get_reminders_list(store, REMINDERS_LIST_NAME)
    if not calendar:
        print(f'Error: Reminders list "{REMINDERS_LIST_NAME}" not found.', file=sys.stderr)
        print("Available lists:", file=sys.stderr)
        for cal in store.calendarsForEntityType_(EKEntityTypeReminder):
            print(f"  - {cal.title()}", file=sys.stderr)
        sys.exit(1)

    # Get uncompleted reminders
    reminders = get_uncompleted_reminders(store, calendar)

    if not reminders:
        print(f'No uncompleted reminders found in "{REMINDERS_LIST_NAME}".')
        print("Nothing to do.")
        return

    print(f'Found {len(reminders)} uncompleted items in "{REMINDERS_LIST_NAME}"')
    if args.dry_run:
        print("(DRY RUN - no changes will be made)\n")
    else:
        print()

    # Track results
    succeeded = []
    skipped = []
    failed = []
    invalid = []

    # Process each reminder
    for i, reminder in enumerate(reminders, 1):
        url = reminder.title()
        print(f"[{i}/{len(reminders)}] {url}")

        # Validate URL
        if not is_youtube_url(url):
            print("       → Not a YouTube URL, skipping")
            print("       ✗ Left unchecked")
            invalid.append((url, "Not a YouTube URL"))
            continue

        # Extract recipe
        try:
            result = extract_single_recipe(url, dry_run=args.dry_run)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            break
        except Exception as e:
            result = {"success": False, "error": str(e)}

        if result["success"]:
            if result.get("skipped"):
                print(f"       → Already exists: {result.get('recipe_name', 'unknown')}")
                skipped.append(url)
            else:
                title = result.get("title", "Unknown")
                source = result.get("source", "unknown")
                print(f"       → Fetching: \"{title}\"")
                print(f"       → Source: {source}")
                if result.get("filepath"):
                    print(f"       → Saved: {result['filepath'].name}")
                succeeded.append(url)

            # Mark complete (unless dry run)
            if not args.dry_run:
                if mark_reminder_complete(store, reminder):
                    print("       ✓ Marked complete")
                else:
                    print("       ⚠ Failed to mark complete")
            else:
                print("       ○ Would mark complete")
        else:
            error = result.get("error", "Unknown error")
            print(f"       → Error: {error}")
            print("       ✗ Left unchecked (will retry next run)")
            failed.append((url, error))

        # Delay between videos (unless last one or dry run)
        if i < len(reminders) and not args.dry_run and result["success"]:
            time.sleep(DELAY_BETWEEN_VIDEOS)

    # Summary
    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    total = len(succeeded) + len(skipped) + len(failed) + len(invalid)
    print(f"Processed: {total}")
    print(f"Succeeded: {len(succeeded)}")
    print(f"Skipped (duplicates): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    if invalid:
        print(f"Invalid URLs: {len(invalid)}")

    if failed:
        print("\nFailed items:")
        for url, error in failed:
            print(f"  - {url}")
            print(f"    ({error})")

    if invalid:
        print("\nInvalid URLs:")
        for url, reason in invalid:
            print(f"  - {url} ({reason})")


if __name__ == "__main__":
    main()
```

**Step 2: Make executable**

Run: `chmod +x batch_extract.py`

**Step 3: Test --dry-run with empty list or non-existent list**

Run: `.venv/bin/python batch_extract.py --dry-run`
Expected: Either shows reminders found, or shows "list not found" with available lists

**Step 4: Commit**

```bash
git add batch_extract.py
git commit -m "feat: add batch_extract.py for Reminders integration

Processes YouTube URLs from iOS Reminders 'Recipies to Process' list.
- Marks successful extractions complete
- Leaves failures unchecked for natural retry
- 3-second delay between videos for rate limiting"
```

---

### Task 4: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

Add to "Running Commands" section after "Migrate Recipes to New Schema":

```markdown
### Batch Extract from Reminders

```bash
# Process all uncompleted reminders from "Recipies to Process" list
.venv/bin/python batch_extract.py

# Preview what would be processed
.venv/bin/python batch_extract.py --dry-run
```
```

Add to "Key Functions" table in "Core Components":

```markdown
| `batch_extract.py` | Batch processor - reads from iOS Reminders, extracts in bulk |
```

Update "Future Enhancements" table - mark batch processing as completed:

```markdown
| ~~Batch processing~~ | ~~Medium~~ | **Completed** - Processes URLs from iOS Reminders list |
```

**Step 2: Update README.md with batch processing usage**

Add a "Batch Processing" section after the main usage section explaining:
- How to set up the Reminders list
- How to run batch extraction
- What happens on success/failure

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add batch processing documentation"
```

---

### Task 5: End-to-End Test

**Step 1: Add a test URL to Reminders**

Manually add a YouTube cooking video URL to the "Recipies to Process" list in iOS Reminders (or macOS Reminders app).

**Step 2: Run batch extraction**

Run: `.venv/bin/python batch_extract.py`
Expected:
- Finds the reminder
- Extracts the recipe
- Marks it complete
- Shows summary

**Step 3: Verify in Obsidian**

Check that the recipe file was created in the Obsidian vault.

**Step 4: Verify in Reminders**

Check that the reminder is now marked as complete.

---

## Execution Notes

- First run will trigger macOS permission dialog for Reminders access
- The Reminders list name "Recipies to Process" must match exactly (with the typo)
- If Ollama isn't running, recipes from webpage/description sources will still succeed
