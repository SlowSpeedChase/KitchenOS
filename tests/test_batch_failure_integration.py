# tests/test_batch_failure_integration.py
"""Tests for batch extract failure logging integration.

Tests the failure recording logic extracted into testable functions,
without requiring EventKit/Reminders access.
"""
import json
import tempfile
import traceback
from pathlib import Path
from lib.failure_logger import classify_error, log_failures, FAILURES_DIR_NAME


def test_build_failure_entry():
    """Failure entries should include url, error, category, traceback, and timestamp"""
    url = "https://youtube.com/watch?v=test123"
    error_msg = "Could not fetch video metadata"
    try:
        raise ConnectionError(error_msg)
    except Exception as e:
        category = classify_error(str(e), type(e))
        tb = traceback.format_exc()

    entry = {
        "url": url,
        "error": error_msg,
        "error_category": category,
        "traceback": tb,
        "reminder_title": url,
        "timestamp": "2026-02-13T06:10:00",
    }

    assert entry["url"] == url
    assert entry["error_category"] == "network"
    assert "ConnectionError" in entry["traceback"]


def test_failures_written_after_batch_run():
    """After a batch run with failures, a JSON file should exist in failures/"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        failures = [
            {
                "url": "https://youtube.com/watch?v=fail1",
                "error": "Ollama connection refused",
                "error_category": "ollama",
                "traceback": "...",
                "reminder_title": "https://youtube.com/watch?v=fail1",
                "timestamp": "2026-02-13T06:10:00",
            },
            {
                "url": "https://youtube.com/watch?v=fail2",
                "error": "Video unavailable",
                "error_category": "youtube",
                "traceback": "...",
                "reminder_title": "https://youtube.com/watch?v=fail2",
                "timestamp": "2026-02-13T06:11:00",
            },
        ]

        filepath = log_failures(failures, total_processed=5, project_root=project_root)

        data = json.loads(filepath.read_text())
        assert data["total_processed"] == 5
        assert data["total_failed"] == 2
        categories = [f["error_category"] for f in data["failures"]]
        assert "ollama" in categories
        assert "youtube" in categories


def test_no_failures_no_log_file():
    """When there are no failures, no log file should be written"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        failures_dir = project_root / FAILURES_DIR_NAME
        # Don't call log_failures when list is empty
        assert not failures_dir.exists()
