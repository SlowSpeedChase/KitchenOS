"""Failure logging for batch recipe extraction.

Writes structured JSON logs of extraction failures for automated analysis.
"""
import json
import time
from datetime import datetime
from pathlib import Path

FAILURES_DIR_NAME = "failures"

# Error classification patterns
_OLLAMA_PATTERNS = ["localhost:11434", "ollama", "model", "11434"]
_YOUTUBE_PATTERNS = ["video unavailable", "private", "transcript", "video is", "no captions", "subtitles"]
_NETWORK_PATTERNS = ["connection refused", "timed out", "timeout", "dns", "unreachable", "connection error"]
_IO_PATTERNS = ["permission denied", "no such file", "is a directory", "disk full", "read-only"]
_PARSING_PATTERNS = ["json", "expecting value", "decode", "key error", "missing field", "schema"]

# Exception type mapping
_EXCEPTION_CATEGORIES = {
    "JSONDecodeError": "parsing",
    "KeyError": "parsing",
    "ValueError": "parsing",
    "PermissionError": "io",
    "FileNotFoundError": "io",
    "OSError": "io",
    "TimeoutError": "network",
    "ConnectionError": "network",
}


def classify_error(error_message: str, exception_type: type = Exception) -> str:
    """Classify an error into a category for the analysis agent.

    Categories: network, ollama, youtube, parsing, io, unknown

    Args:
        error_message: The error message string
        exception_type: The exception class (e.g., ConnectionError, KeyError)

    Returns:
        One of: "network", "ollama", "youtube", "parsing", "io", "unknown"
    """
    msg_lower = error_message.lower()
    exc_name = exception_type.__name__

    # Ollama errors (check before network since Ollama connection errors are specific)
    if any(p in msg_lower for p in _OLLAMA_PATTERNS):
        return "ollama"

    # Check exception type mapping
    if exc_name in _EXCEPTION_CATEGORIES:
        return _EXCEPTION_CATEGORIES[exc_name]

    # Pattern matching on message
    if any(p in msg_lower for p in _YOUTUBE_PATTERNS):
        return "youtube"
    if any(p in msg_lower for p in _NETWORK_PATTERNS):
        return "network"
    if any(p in msg_lower for p in _IO_PATTERNS):
        return "io"
    if any(p in msg_lower for p in _PARSING_PATTERNS):
        return "parsing"

    return "unknown"


def log_failures(
    failures: list[dict],
    total_processed: int,
    project_root: Path = None,
) -> Path:
    """Write failure data to a timestamped JSON file.

    Args:
        failures: List of failure dicts with url, error, error_category, traceback, etc.
        total_processed: Total number of items processed in the batch run
        project_root: Root directory for the project (defaults to parent of lib/)

    Returns:
        Path to the created JSON log file
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent

    failures_dir = project_root / FAILURES_DIR_NAME
    failures_dir.mkdir(exist_ok=True)

    now = datetime.now()
    filename = now.strftime("%Y-%m-%d-%H%M%S") + ".json"

    data = {
        "run_timestamp": now.isoformat(timespec="seconds"),
        "total_processed": total_processed,
        "total_failed": len(failures),
        "failures": failures,
    }

    filepath = failures_dir / filename
    filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return filepath


def cleanup_old_failure_logs(failures_dir: Path, max_age_days: int = 30) -> int:
    """Remove failure log files older than max_age_days.

    Args:
        failures_dir: Path to failures directory
        max_age_days: Maximum age in days (default 30)

    Returns:
        Number of files removed
    """
    failures_dir = Path(failures_dir)

    if not failures_dir.exists():
        return 0

    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    removed = 0

    for log_file in failures_dir.glob("*.json"):
        if log_file.stat().st_mtime < cutoff_time:
            log_file.unlink()
            removed += 1

    return removed
