"""Tests for failure logger module"""
import json
import tempfile
import time
import os
from pathlib import Path
from datetime import datetime
from lib.failure_logger import (
    classify_error,
    log_failures,
    cleanup_old_failure_logs,
    FAILURES_DIR_NAME,
)


def test_classify_error_network_connection_refused():
    """Connection refused should be classified as network"""
    assert classify_error("Connection refused", ConnectionError) == "network"


def test_classify_error_network_timeout():
    """Timeout should be classified as network"""
    assert classify_error("Read timed out", TimeoutError) == "network"


def test_classify_error_ollama():
    """Ollama errors should be classified as ollama"""
    assert classify_error("Failed to connect to localhost:11434", ConnectionError) == "ollama"


def test_classify_error_ollama_model():
    """Ollama model errors should be classified as ollama"""
    assert classify_error("model 'mistral:7b' not found", Exception) == "ollama"


def test_classify_error_youtube_unavailable():
    """Video unavailable should be classified as youtube"""
    assert classify_error("Video unavailable", Exception) == "youtube"


def test_classify_error_youtube_private():
    """Private video should be classified as youtube"""
    assert classify_error("This video is private", Exception) == "youtube"


def test_classify_error_youtube_transcript():
    """Transcript errors should be classified as youtube"""
    assert classify_error("Could not retrieve a transcript", Exception) == "youtube"


def test_classify_error_parsing_json():
    """JSON decode errors should be classified as parsing"""
    assert classify_error("Expecting value: line 1", json.JSONDecodeError) == "parsing"


def test_classify_error_parsing_key():
    """KeyError should be classified as parsing"""
    assert classify_error("'recipe_name'", KeyError) == "parsing"


def test_classify_error_io_permission():
    """Permission denied should be classified as io"""
    assert classify_error("Permission denied", PermissionError) == "io"


def test_classify_error_unknown():
    """Unrecognized errors should be classified as unknown"""
    assert classify_error("Something weird happened", Exception) == "unknown"


def test_log_failures_creates_directory():
    """log_failures should create failures directory if it doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        failures = [
            {"url": "https://youtube.com/watch?v=abc", "error": "test error", "error_category": "unknown", "traceback": "", "reminder_title": "abc", "timestamp": "2026-02-13T06:10:00"}
        ]
        log_failures(failures, total_processed=1, project_root=project_root)

        failures_dir = project_root / FAILURES_DIR_NAME
        assert failures_dir.exists()
        assert failures_dir.is_dir()


def test_log_failures_writes_valid_json():
    """log_failures should write a valid JSON file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        failures = [
            {"url": "https://youtube.com/watch?v=abc", "error": "test error", "error_category": "parsing", "traceback": "Traceback...", "reminder_title": "abc", "timestamp": "2026-02-13T06:10:00"}
        ]
        filepath = log_failures(failures, total_processed=3, project_root=project_root)

        data = json.loads(filepath.read_text())
        assert data["total_processed"] == 3
        assert data["total_failed"] == 1
        assert len(data["failures"]) == 1
        assert data["failures"][0]["url"] == "https://youtube.com/watch?v=abc"
        assert data["failures"][0]["error_category"] == "parsing"


def test_log_failures_returns_filepath():
    """log_failures should return the path to the created file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        failures = [
            {"url": "https://youtube.com/watch?v=abc", "error": "err", "error_category": "unknown", "traceback": "", "reminder_title": "abc", "timestamp": "2026-02-13T06:10:00"}
        ]
        filepath = log_failures(failures, total_processed=1, project_root=project_root)

        assert filepath.exists()
        assert filepath.suffix == ".json"
        assert filepath.parent.name == FAILURES_DIR_NAME


def test_cleanup_old_failure_logs():
    """Cleanup should remove failure logs older than max_age_days"""
    with tempfile.TemporaryDirectory() as tmpdir:
        failures_dir = Path(tmpdir) / "failures"
        failures_dir.mkdir()

        # Create an old log
        old_log = failures_dir / "2026-01-01-060000.json"
        old_log.write_text('{"failures": []}')
        old_time = time.time() - (31 * 24 * 60 * 60)
        os.utime(old_log, (old_time, old_time))

        # Create a new log
        new_log = failures_dir / "2026-02-13-060000.json"
        new_log.write_text('{"failures": []}')

        removed = cleanup_old_failure_logs(failures_dir, max_age_days=30)

        assert not old_log.exists()
        assert new_log.exists()
        assert removed == 1


def test_cleanup_old_failure_logs_handles_missing_dir():
    """Cleanup should return 0 if directory doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "nonexistent"
        removed = cleanup_old_failure_logs(missing)
        assert removed == 0
