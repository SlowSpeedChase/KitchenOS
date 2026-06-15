"""System health checks for the KitchenOS health dashboard.

Provides pure functions that aggregate status from Ollama, the vault,
failure logs, and run logs. No Flask dependency — safe to import anywhere.
"""

import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from lib import paths

_PROJECT_ROOT = Path(__file__).parent.parent
_FAILURES_DIR = _PROJECT_ROOT / "failures"
_RUNS_DIR = _PROJECT_ROOT / "logs" / "runs"


def check_ollama() -> dict:
    """Probe Ollama at localhost:11434. Returns {alive, models, error}."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        return {"alive": True, "models": models, "error": None}
    except Exception as e:
        return {"alive": False, "models": [], "error": str(e)}


def check_vault() -> dict:
    """Confirm vault path resolves and is writable. Returns {path, exists, writable}."""
    vault = paths.vault_root()
    exists = vault.exists()
    writable = False
    if exists:
        try:
            test = vault / ".kitchenos_health_check"
            test.touch()
            test.unlink()
            writable = True
        except Exception:
            pass
    return {"path": str(vault), "exists": exists, "writable": writable}


def list_recent_vault_writes(n: int = 10) -> list:
    """Return the n most-recently modified recipe files.

    Returns list of {name, modified_iso}.
    """
    recipes = paths.recipes_dir()
    if not recipes.exists():
        return []

    files = [
        (f, f.stat().st_mtime)
        for f in recipes.glob("*.md")
        if not f.name.startswith('.')
    ]
    files.sort(key=lambda x: x[1], reverse=True)
    return [
        {
            "name": f.stem,
            "modified_iso": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        }
        for f, mtime in files[:n]
    ]


def read_failure_logs(n: int = 10) -> list:
    """Return the n most-recent failure log summaries.

    Returns list of {timestamp, total_processed, total_failed, categories}.
    """
    if not _FAILURES_DIR.exists():
        return []

    logs = sorted(_FAILURES_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    for log_file in logs[:n]:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            categories: dict[str, int] = {}
            for failure in data.get("failures", []):
                cat = failure.get("error_category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1
            results.append({
                "timestamp": data.get("run_timestamp", log_file.stem),
                "total_processed": data.get("total_processed", 0),
                "total_failed": data.get("total_failed", 0),
                "categories": categories,
            })
        except Exception:
            continue
    return results


def read_run_logs(n: int = 10) -> list:
    """Return the n most-recent batch-extract run summaries.

    Returns list of {timestamp, total, succeeded, skipped_duplicate,
                      failed, invalid, duration_seconds}.
    """
    if not _RUNS_DIR.exists():
        return []

    logs = sorted(_RUNS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    for log_file in logs[:n]:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            results.append({
                "timestamp": data.get("timestamp", log_file.stem),
                "total": data.get("total", 0),
                "succeeded": data.get("succeeded", 0),
                "skipped_duplicate": data.get("skipped_duplicate", 0),
                "failed": data.get("failed", 0),
                "invalid": data.get("invalid", 0),
                "invalid_urls": data.get("invalid_urls", []),
                "duration_seconds": data.get("duration_seconds", 0),
            })
        except Exception:
            continue
    return results


def count_reminders_queue() -> int | None:
    """Count uncompleted items in 'Recipies to Process' via osascript.

    Returns None if not on macOS or if osascript fails.
    """
    if platform.system() != "Darwin":
        return None
    script = (
        'tell application "Reminders" to count (reminders of list '
        '"Recipies to Process" whose completed is false)'
    )
    try:
        out = subprocess.check_output(
            ["osascript", "-e", script], timeout=5, stderr=subprocess.DEVNULL
        )
        return int(out.strip())
    except Exception:
        return None


def get_system_health() -> dict:
    """Aggregate all health checks into a single dict for the JSON endpoint."""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ollama": check_ollama(),
        "vault": check_vault(),
        "recent_recipes": list_recent_vault_writes(10),
        "failure_logs": read_failure_logs(10),
        "run_logs": read_run_logs(10),
        "reminders_queue": count_reminders_queue(),
    }
