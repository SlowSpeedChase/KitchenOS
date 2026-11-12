#!/usr/bin/env python3
"""
KitchenOS - Batch Recipe Extractor
Processes YouTube URLs from iOS Reminders and extracts recipes in bulk.

Usage:
    python batch_extract.py              # Process all uncompleted reminders
    python batch_extract.py --dry-run    # Preview without extracting or marking complete
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from lib.failure_logger import classify_error, log_failures, cleanup_old_failure_logs, FAILURES_DIR_NAME
from lib.reminders_url import urls_by_identifier

# macOS Reminders integration
from EventKit import (
    EKEventStore,
    EKEntityTypeReminder,
    EKAuthorizationStatusAuthorized,
    EKAuthorizationStatusNotDetermined,
)
from Foundation import NSRunLoop, NSDate

from extract_recipe import (
    extract_single_recipe,
    extract_single_web_recipe,
    extract_single_instagram_recipe,
)
from main import route_url

RUNS_LOG_DIR = Path(__file__).parent / "logs" / "runs"
_RETRY_TRACKER_PATH = Path(__file__).parent / "logs" / "retry_tracker.json"
_DEAD_LETTER_PATH = Path(__file__).parent / "logs" / "dead_letter.json"

# Configuration
REMINDERS_LIST_NAME = "Recipies to Process"
DELAY_BETWEEN_VIDEOS = 3  # seconds

MAX_RETRIES = 5


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

        if granted[0] is None:
            print("Error: Reminders access request timed out (60s).", file=sys.stderr)

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

    if reminders[0] is None:
        print("Error: Fetching reminders timed out (30s).", file=sys.stderr)

    return list(reminders[0]) if reminders[0] else []


def mark_reminder_complete(store, reminder):
    """Mark a reminder as completed."""
    reminder.setCompleted_(True)
    success, error = store.saveReminder_commit_error_(reminder, True, None)
    if not success and error:
        print(f"       Warning: Failed to save reminder: {error}", file=sys.stderr)
    return success


_URL_RE = re.compile(r'https?://[^\s<>"\')]+')


def _first_url(text):
    """Return the first http(s) URL found in text, or None."""
    if not text:
        return None
    m = _URL_RE.search(str(text))
    return m.group(0) if m else None


def resolve_reminder_url(title, url_field=None, notes=None):
    """Resolve the best URL for a reminder.

    iOS share-sheet reminders often store the page title as the reminder title
    and the link in the reminder's URL field or notes. Prefer, in order:
    a URL in the title, then the reminder URL field, then the first URL in notes.
    Returns the URL string, or None if none is found.
    """
    title = (title or "").strip()
    if title.startswith(('http://', 'https://')):
        return title

    embedded = _first_url(title)
    if embedded:
        return embedded

    if url_field:
        u = url_field.absoluteString() if hasattr(url_field, 'absoluteString') else str(url_field)
        u = (u or "").strip()
        if u.startswith(('http://', 'https://')):
            return u

    return _first_url(notes)


def _cleanup_run_logs(runs_dir: Path, max_age_days: int = 30) -> int:
    if not runs_dir.exists():
        return 0
    cutoff = time.time() - (max_age_days * 24 * 60 * 60)
    removed = 0
    for f in runs_dir.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed


def _write_run_log(total, succeeded, skipped, failed, invalid, start_time,
                   dead_lettered=None):
    RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_run_logs(RUNS_LOG_DIR)
    filename = datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".json"
    data = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "duration_seconds": int((datetime.now() - start_time).total_seconds()),
        "total": total,
        "succeeded": len(succeeded),
        "skipped_duplicate": len(skipped),
        "failed": len(failed),
        "invalid": len(invalid),
        "dead_lettered": len(dead_lettered) if dead_lettered else 0,
        "invalid_urls": [url for url, _ in invalid],
        "succeeded_urls": succeeded,
    }
    (RUNS_LOG_DIR / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


#: Values that mean "not enabled". Matches lib/llm_gate's rule: a blank
#: `KITCHENOS_FAILURE_ANALYSIS=` left in a shell profile is not a decision.
_FALSEY = {"", "0", "false", "no", "off"}


def _env_flag(name: str) -> bool:
    """Is this env var set to something that means yes?"""
    return os.getenv(name, "").strip().lower() not in _FALSEY


def trigger_analysis_agent(failure_log_path: Path):
    """Spawn the failure analysis agent in the background, if it is enabled.

    Opt-in via ``KITCHENOS_FAILURE_ANALYSIS``, and **off by default**, for two
    reasons found on 2026-08-02:

    1. It never ran. ``scripts/analyze_failures.sh`` resolves ``claude`` off
       ``PATH``, which under launchd is bare, so 276 of 277 spawns died on
       "claude CLI not found" — while this function printed "Analysis agent
       triggered in background" unconditionally, so the success message
       outlived the corpse. Reporting a launch we did not verify is the bug;
       printing the real reason is the fix.
    2. It should not simply be revived. The script hands Claude
       ``Edit,Bash,Write`` and instructs it to branch, commit, push and open a
       PR — unattended, hourly, against a queue that does not drain (the same
       handful of items retry forever). Wiring that back up silently, on a
       timer, is not a change to make on the user's behalf.

    Enable deliberately once the queue drains and a throttle exists:
    ``KITCHENOS_FAILURE_ANALYSIS=1``.
    """
    import shutil
    import subprocess

    if not _env_flag("KITCHENOS_FAILURE_ANALYSIS"):
        print("Failure analysis agent: disabled "
              "(set KITCHENOS_FAILURE_ANALYSIS=1 to enable)")
        return

    script = Path(__file__).parent / "scripts" / "analyze_failures.sh"
    if not script.exists():
        print(f"Warning: Analysis script not found at {script}", file=sys.stderr)
        return

    # The script's own `command -v claude` guard exits 1 into a log nobody
    # reads. Check here so the reason reaches the run summary instead.
    if shutil.which("claude") is None:
        print("Warning: Analysis agent not started — 'claude' is not on PATH. "
              "launchd runs with a bare PATH; give the shim an absolute path.",
              file=sys.stderr)
        return

    try:
        log_file = open(Path(__file__).parent / "failure_analysis.log", "a")
        subprocess.Popen(
            [str(script), str(failure_log_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        # log_file intentionally left open — inherited by child process
        print("Analysis agent triggered in background")
    except Exception as e:
        print(f"Warning: Failed to trigger analysis agent: {e}", file=sys.stderr)


def _load_retry_tracker() -> dict:
    try:
        return json.loads(_RETRY_TRACKER_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_retry_tracker(tracker: dict):
    _RETRY_TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RETRY_TRACKER_PATH.write_text(
        json.dumps(tracker, indent=2), encoding="utf-8")


def _record_failure(tracker: dict, url: str, error_category: str):
    entry = tracker.get(url, {"attempts": 0, "last_category": ""})
    entry["attempts"] = entry["attempts"] + 1
    entry["last_category"] = error_category
    entry["last_seen"] = datetime.now().isoformat(timespec="seconds")
    tracker[url] = entry


def _should_dead_letter(tracker: dict, url: str, error_category: str) -> bool:
    entry = tracker.get(url)
    if not entry:
        return False
    return entry["attempts"] >= MAX_RETRIES


def _dead_letter(url: str, title: str, error: str, category: str, attempts: int):
    try:
        items = json.loads(_DEAD_LETTER_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    entry = {
        "url": url,
        "title": title,
        "error": error,
        "error_category": category,
        "attempts": attempts,
        "dead_lettered_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(entry)
    _DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DEAD_LETTER_PATH.write_text(
        json.dumps(items, indent=2), encoding="utf-8")
    return entry


def _rollback_dead_letter(entry: dict):
    items = json.loads(_DEAD_LETTER_PATH.read_text(encoding="utf-8"))
    items.remove(entry)
    if items:
        _DEAD_LETTER_PATH.write_text(
            json.dumps(items, indent=2), encoding="utf-8")
    else:
        _DEAD_LETTER_PATH.unlink()


def _move_to_dead_letter(store, reminder, url: str, title: str, error: str,
                         category: str, attempts: int, dry_run: bool) -> bool:
    """Persist the dead letter, then complete the reminder or roll it back."""
    if dry_run:
        return True
    entry = _dead_letter(url, title, error, category, attempts)
    if not mark_reminder_complete(store, reminder):
        _rollback_dead_letter(entry)
        return False
    return True


def _cleanup_failure_logs_for_run(failures_dir: Path, dry_run: bool) -> int:
    if dry_run:
        return 0
    return cleanup_old_failure_logs(failures_dir)


def _mark_complete_and_clear_retry(store, reminder, tracker: dict, url: str,
                                   dry_run: bool) -> bool:
    if dry_run:
        return True
    if not mark_reminder_complete(store, reminder):
        return False
    tracker.pop(url, None)
    return True


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
    run_start = datetime.now()

    # Clean up old failure logs
    failures_dir = Path(__file__).parent / FAILURES_DIR_NAME
    removed = _cleanup_failure_logs_for_run(failures_dir, args.dry_run)
    if removed:
        print(f"Cleaned up {removed} old failure log(s)")

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
    dead_lettered = []

    retry_tracker = _load_retry_tracker()

    # Share-sheet reminders store the shared link as a rich-link attachment that
    # EventKit/AppleScript can't read; recover those URLs from the Reminders
    # SQLite store, keyed by calendarItemIdentifier. Empty dict if unreadable.
    attachment_urls = urls_by_identifier(REMINDERS_LIST_NAME)

    # Process each reminder
    for i, reminder in enumerate(reminders, 1):
        title = reminder.title()
        # Resolve the URL from the title / URL field / notes first, then fall
        # back to the rich-link attachment recovered from the Reminders store.
        url = resolve_reminder_url(title, reminder.URL(), reminder.notes())
        if not url:
            url = attachment_urls.get(reminder.calendarItemIdentifier())
        print(f"[{i}/{len(reminders)}] {title}")

        # Validate URL and route to appropriate extractor
        def print_status(msg):
            print(f"       {msg}")

        if not url:
            print("       → No URL in title, URL field, or notes — skipping")
            print("       ✗ Left unchecked")
            invalid.append((title, "Not a URL"))
            continue

        if url != title:
            print(f"       → Resolved URL: {url}")

        try:
            pipeline = route_url(url)
            if pipeline == 'youtube':
                result = extract_single_recipe(url, dry_run=args.dry_run, on_status=print_status)
            elif pipeline == 'instagram':
                print("       → Instagram Reel, routing to reel pipeline")
                result = extract_single_instagram_recipe(url, dry_run=args.dry_run, on_status=print_status)
            else:
                print("       → Web recipe URL, routing to scrape pipeline")
                result = extract_single_web_recipe(url, dry_run=args.dry_run, on_status=print_status)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            break
        except Exception as e:
            tb = traceback.format_exc()
            category = classify_error(str(e), type(e))
            result = {
                "success": False,
                "title": None,
                "recipe_name": None,
                "filepath": None,
                "error": str(e),
                "skipped": False,
                "source": None,
                "_traceback": tb,
                "_error_category": category,
            }

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
                if _mark_complete_and_clear_retry(
                        store, reminder, retry_tracker, url, args.dry_run):
                    print("       ✓ Marked complete")
                else:
                    print("       ⚠ Failed to mark complete")
            else:
                print("       ○ Would mark complete")
        else:
            error = result.get("error", "Unknown error")
            tb = result.get("_traceback", "")
            category = result.get("_error_category", classify_error(error, Exception))
            _record_failure(retry_tracker, url, category)

            if _should_dead_letter(retry_tracker, url, category):
                attempts = retry_tracker[url]["attempts"]
                print(f"       → Error: {error}")
                moved = _move_to_dead_letter(
                    store, reminder, url, title, error, category, attempts,
                    args.dry_run)
                if moved:
                    if args.dry_run:
                        print("       ○ Would mark complete (dead-lettered)")
                    else:
                        retry_tracker.pop(url, None)
                        dead_lettered.append(url)
                        print(f"       ✗ Dead-lettered after {attempts} attempts")
                        print("       ✓ Marked complete (dead-lettered)")
                else:
                    print("       ⚠ Failed to mark complete; left queued")
                    failed.append({
                        "url": url,
                        "error": error,
                        "error_category": category,
                        "traceback": tb,
                        "reminder_title": title,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
            else:
                attempts = retry_tracker[url]["attempts"]
                print(f"       → Error: {error}")
                print(f"       ✗ Left unchecked (attempt {attempts}/{MAX_RETRIES})")
                failed.append({
                    "url": url,
                    "error": error,
                    "error_category": category,
                    "traceback": tb,
                    "reminder_title": title,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })

        # Delay between videos (unless last one or dry run)
        if i < len(reminders) and not args.dry_run and result["success"]:
            time.sleep(DELAY_BETWEEN_VIDEOS)

    if not args.dry_run:
        _save_retry_tracker(retry_tracker)

    # Summary
    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    total = len(succeeded) + len(skipped) + len(failed) + len(invalid) + len(dead_lettered)
    print(f"Processed: {total}")
    print(f"Succeeded: {len(succeeded)}")
    print(f"Skipped (duplicates): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    if dead_lettered:
        print(f"Dead-lettered: {len(dead_lettered)}")
    if invalid:
        print(f"Invalid URLs: {len(invalid)}")

    if failed:
        print("\nFailed items:")
        for f in failed:
            print(f"  - {f['url']}")
            print(f"    ({f['error']}) [{f['error_category']}]")

    if invalid:
        print("\nInvalid URLs:")
        for url, reason in invalid:
            print(f"  - {url} ({reason})")

    # Write failure log and trigger analysis agent
    if failed and not args.dry_run:
        failure_log = log_failures(failed, total_processed=total)
        print(f"\nFailure log written to: {failure_log}")

        # Trigger analysis agent
        trigger_analysis_agent(failure_log)

    # Write run summary log (always, unless dry-run)
    if not args.dry_run:
        _write_run_log(
            total=total,
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            invalid=invalid,
            start_time=run_start,
            dead_lettered=dead_lettered,
        )


if __name__ == "__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("kitchenos-batch-extract")
    except ImportError:
        pass
    main()
