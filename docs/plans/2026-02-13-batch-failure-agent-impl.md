# Batch Failure Analysis Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Log batch extract failures to structured JSON files and trigger a Claude Code agent to analyze them and create fix PRs.

**Architecture:** `batch_extract.py` calls `lib/failure_logger.py` to write categorized failure JSON. At end of run, if failures exist, it spawns `scripts/analyze_failures.sh` (detached) which invokes `claude -p` with the failure data.

**Tech Stack:** Python 3.11, JSON, shell script, Claude Code CLI (`claude -p`)

---

### Task 1: Failure Logger Module

**Files:**
- Create: `lib/failure_logger.py`
- Test: `tests/test_failure_logger.py`

**Step 1: Write the failing tests**

```python
# tests/test_failure_logger.py
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
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_failure_logger.py -v`
Expected: FAIL (module not found)

**Step 3: Write the implementation**

```python
# lib/failure_logger.py
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
        exception_type: The exception class (e.g., ConnectionError)

    Returns:
        Error category string
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
        failures: List of failure dicts with keys:
            url, error, error_category, traceback, reminder_title, timestamp
        total_processed: Total number of URLs processed in this run
        project_root: Project root directory (default: current working directory)

    Returns:
        Path to the created JSON file
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
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_failure_logger.py -v`
Expected: All 14 tests PASS

**Step 5: Commit**

```bash
git add lib/failure_logger.py tests/test_failure_logger.py
git commit -m "feat: add failure logger module with error classification

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Integrate Failure Logger into Batch Extract

**Files:**
- Modify: `batch_extract.py:1-257`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run tests to verify they pass** (these test the logger, not batch_extract itself)

Run: `.venv/bin/python -m pytest tests/test_batch_failure_integration.py -v`
Expected: PASS (tests use already-implemented logger)

**Step 3: Modify batch_extract.py**

Add these changes to `batch_extract.py`:

1. Add imports at the top (after existing imports):

```python
import traceback
from datetime import datetime
from lib.failure_logger import classify_error, log_failures, cleanup_old_failure_logs, FAILURES_DIR_NAME
```

2. Add cleanup call at start of `main()`, after `args = parser.parse_args()` (line 127):

```python
    # Clean up old failure logs
    failures_dir = Path(__file__).parent / FAILURES_DIR_NAME
    removed = cleanup_old_failure_logs(failures_dir)
    if removed:
        print(f"Cleaned up {removed} old failure log(s)")
```

3. Change the exception handler (lines 190-199) to capture traceback and classify:

```python
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
```

4. In the failure branch (line 226), capture structured failure data:

```python
        else:
            error = result.get("error", "Unknown error")
            print(f"       → Error: {error}")
            print(f"       ✗ Left unchecked (will retry next run)")
            tb = result.get("_traceback", "")
            category = result.get("_error_category", classify_error(error, Exception))
            failed.append({
                "url": url,
                "error": error,
                "error_category": category,
                "traceback": tb,
                "reminder_title": url,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })
```

5. After the summary section (after line 253), add failure logging and agent trigger:

```python
    # Write failure log and trigger analysis agent
    if failed and not args.dry_run:
        total = len(succeeded) + len(skipped) + len(failed) + len(invalid)
        failure_log = log_failures(failed, total_processed=total)
        print(f"\nFailure log written to: {failure_log}")

        # Trigger analysis agent
        trigger_analysis_agent(failure_log)
```

6. Add the `trigger_analysis_agent` function before `main()`:

```python
def trigger_analysis_agent(failure_log_path: Path):
    """Spawn the failure analysis agent in the background.

    Runs scripts/analyze_failures.sh detached so batch_extract doesn't wait.
    """
    import subprocess

    script = Path(__file__).parent / "scripts" / "analyze_failures.sh"
    if not script.exists():
        print(f"Warning: Analysis script not found at {script}", file=sys.stderr)
        return

    try:
        subprocess.Popen(
            [str(script), str(failure_log_path)],
            stdout=open(Path(__file__).parent / "failure_analysis.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print("Analysis agent triggered in background")
    except Exception as e:
        print(f"Warning: Failed to trigger analysis agent: {e}", file=sys.stderr)
```

**Step 4: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_failure_logger.py tests/test_batch_failure_integration.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add batch_extract.py tests/test_batch_failure_integration.py
git commit -m "feat: integrate failure logging into batch extract

Records structured failures with error classification and
triggers analysis agent when failures occur.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Analysis Agent Shell Script

**Files:**
- Create: `scripts/analyze_failures.sh`

**Step 1: Write the shell script**

```bash
#!/usr/bin/env bash
# scripts/analyze_failures.sh
# Analyzes batch extract failures using Claude Code CLI.
# Called by batch_extract.py when failures occur.
#
# Usage: ./scripts/analyze_failures.sh <failure_log_path>

set -euo pipefail

FAILURE_LOG="$1"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$FAILURE_LOG" ]; then
    echo "Error: Failure log not found: $FAILURE_LOG"
    exit 1
fi

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "Error: claude CLI not found. Install Claude Code to enable failure analysis."
    exit 1
fi

# Read the failure log
FAILURE_DATA=$(cat "$FAILURE_LOG")

# Build the prompt
PROMPT="You are analyzing batch recipe extraction failures for KitchenOS.

## Failure Log
\`\`\`json
${FAILURE_DATA}
\`\`\`

## Instructions

1. Read the failure log above carefully.
2. Skip any failures with error_category 'network' — these are transient.
3. For each non-transient failure:
   a. Read the relevant source code to understand the error.
   b. Try to reproduce with: .venv/bin/python extract_recipe.py --dry-run \"<url>\"
   c. Identify the root cause.
4. If you can fix the issue:
   a. Create a branch: git checkout -b fix/batch-failure-$(date +%Y-%m-%d)
   b. Write the fix with tests.
   c. Commit and push.
   d. Create a PR with: gh pr create --title \"fix: <description>\" --body \"<details>\"
5. If the failure is unfixable (video deleted, private, etc.), note it in your output.

IMPORTANT: Read CLAUDE.md first for project conventions. Run tests before committing."

echo "=== Failure Analysis Agent ==="
echo "Analyzing: $FAILURE_LOG"
echo "Started: $(date)"
echo ""

cd "$PROJECT_ROOT"
claude -p "$PROMPT" --allowedTools "Edit,Bash,Read,Grep,Glob,Write"

echo ""
echo "Analysis complete: $(date)"
```

**Step 2: Make it executable**

Run: `chmod +x scripts/analyze_failures.sh`

**Step 3: Test that the script validates inputs**

Run: `bash scripts/analyze_failures.sh /nonexistent/file.json 2>&1`
Expected: "Error: Failure log not found: /nonexistent/file.json"

**Step 4: Commit**

```bash
git add scripts/analyze_failures.sh
git commit -m "feat: add failure analysis agent shell script

Invokes claude -p with structured failure data to analyze
extraction failures and create fix PRs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Gitignore and Documentation

**Files:**
- Modify: `.gitignore`
- Modify: `CLAUDE.md`

**Step 1: Add failures/ to .gitignore**

Append to `.gitignore`:

```
# Failure logs (generated by batch_extract)
failures/
failure_analysis.log
```

**Step 2: Update CLAUDE.md**

Add to the "Key Functions" section under `batch_extract.py`:

```markdown
**lib/failure_logger.py:**
- `classify_error()` - Categorizes errors (network, ollama, youtube, parsing, io, unknown)
- `log_failures()` - Writes structured failure JSON to `failures/` directory
- `cleanup_old_failure_logs()` - Removes failure logs older than 30 days
```

Add to the "Architecture" → "Core Components" table:

```markdown
| `lib/failure_logger.py` | Error classification and structured failure logging |
| `scripts/analyze_failures.sh` | Invokes Claude Code CLI to analyze failures and create fix PRs |
```

Add a new section after "Batch Extract (LaunchAgent)":

```markdown
## Failure Analysis Agent

When batch extract encounters failures, it writes a structured JSON log to `failures/` and triggers `scripts/analyze_failures.sh` in the background. The script invokes `claude -p` to:

1. Analyze the failure log
2. Skip transient (network) errors
3. Reproduce and fix code bugs
4. Open a PR for review

### Failure Log Location

Files: `failures/YYYY-MM-DD-HHMMSS.json` (auto-cleaned after 30 days)

### Error Categories

| Category | Meaning | Agent Action |
|----------|---------|--------------|
| `network` | Transient connectivity | Skip |
| `ollama` | Ollama infrastructure | Check config |
| `youtube` | Video/transcript issue | Improve fallbacks |
| `parsing` | Code bug | Create fix |
| `io` | File/permission issue | Flag for review |
| `unknown` | Unrecognized | Investigate |

### Manual Trigger

```bash
# Run analysis on a specific failure log
scripts/analyze_failures.sh failures/2026-02-13-061000.json
```
```

**Step 3: Commit**

```bash
git add .gitignore CLAUDE.md
git commit -m "docs: add failure analysis agent documentation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: End-to-End Verification

**Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify failure logger independently**

Run:
```bash
.venv/bin/python -c "
from lib.failure_logger import classify_error, log_failures
from pathlib import Path
import json

# Test classification
print('network:', classify_error('Connection refused', ConnectionError))
print('ollama:', classify_error('localhost:11434 refused', ConnectionError))
print('youtube:', classify_error('Video unavailable', Exception))
print('parsing:', classify_error('JSON decode error', Exception))

# Test writing
failures = [{'url': 'https://youtube.com/watch?v=test', 'error': 'test', 'error_category': 'unknown', 'traceback': '', 'reminder_title': 'test', 'timestamp': '2026-02-13T06:10:00'}]
path = log_failures(failures, total_processed=1)
print(f'Written to: {path}')
data = json.loads(path.read_text())
print(json.dumps(data, indent=2))

# Cleanup test file
path.unlink()
path.parent.rmdir()
print('Cleaned up test file')
"
```

Expected: Correct classifications and valid JSON output

**Step 3: Verify script exists and is executable**

Run: `ls -la scripts/analyze_failures.sh`
Expected: `-rwxr-xr-x` permissions

**Step 4: Final commit (if any fixes needed)**

Only commit if previous steps required changes.
