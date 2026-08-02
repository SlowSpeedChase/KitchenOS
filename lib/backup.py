"""Backup management for recipe files"""
from datetime import datetime
from pathlib import Path
import shutil

HISTORY_DIR = ".history"


def create_backup(file_path: Path) -> Path:
    """Create a timestamped backup of a file in .history directory.

    Args:
        file_path: Path to the file to back up

    Returns:
        Path to the created backup file

    Raises:
        FileNotFoundError: If the file doesn't exist
        OSError: If backup creation fails
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Cannot backup non-existent file: {file_path}")

    # Create .history directory in same folder as file
    history_dir = file_path.parent / HISTORY_DIR
    history_dir.mkdir(exist_ok=True)

    # Generate timestamped backup filename. The vault is not in git, so this
    # snapshot is the only recovery path there is — it must never overwrite an
    # earlier one. A second-resolution stamp plus copy2 did exactly that: two
    # writes to one file inside the same second left only the second snapshot,
    # i.e. a backup of already-damaged content with the original gone. That is
    # reachable from the documented normalize-then-backfill follow-up run as one
    # command, and .history already contains files stamped within one second.
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_path = history_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"

    # Suffix on collision rather than clobber. The separator is "_" rather than
    # "-" so names still sort chronologically: "_" (0x5F) sorts after "." (0x2E),
    # keeping "…19-30-00.md" ahead of "…19-30-00_001.md" ahead of "…19-30-01.md".
    # (cleanup_old_backups goes by mtime, but manual recovery reads the listing.)
    if backup_path.exists():
        for n in range(1, 1000):
            candidate = history_dir / f"{file_path.stem}_{timestamp}_{n:03d}{file_path.suffix}"
            if not candidate.exists():
                backup_path = candidate
                break
        else:
            raise OSError(f"Cannot back up {file_path}: 1000 snapshots in one second")

    # Copy file to backup location
    shutil.copy2(file_path, backup_path)

    return backup_path


def write_note(file_path: Path, content: str) -> bool:
    """Write ``content`` to ``file_path``, snapshotting whatever was there first.

    The safe write. ``lib/CLAUDE.md`` asks every recipe writer to call
    ``create_backup`` first, and most do — but that is a convention a new writer
    has to already know, and three did not: ``lib/cook_history.py`` (syncs cook
    stats into real recipes automatically), ``import_crouton.py`` (replaces a
    whole existing file, "My Notes" included) and ``generate_meal_plan.py
    --force``. The vault is not in git, so a missed snapshot is unrecoverable.

    Returns ``True`` if it wrote. An unchanged write is a no-op — a sync that
    runs over the whole corpus must not fill ``.history`` with identical
    snapshots, and must not churn mtimes that sidecar freshness checks read.
    """
    file_path = Path(file_path)

    if file_path.exists():
        if file_path.read_text(encoding="utf-8") == content:
            return False
        create_backup(file_path)
    else:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(content, encoding="utf-8")
    return True


def cleanup_old_backups(history_dir: Path, max_age_days: int = 30) -> int:
    """Remove backup files older than max_age_days.

    Args:
        history_dir: Path to .history directory
        max_age_days: Maximum age in days (default 30)

    Returns:
        Number of files removed
    """
    import time

    history_dir = Path(history_dir)

    if not history_dir.exists():
        return 0

    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    removed = 0

    for backup_file in history_dir.glob("*.md"):
        if backup_file.stat().st_mtime < cutoff_time:
            backup_file.unlink()
            removed += 1

    return removed
