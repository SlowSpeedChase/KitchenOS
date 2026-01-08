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

    # Generate timestamped backup filename
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
    backup_path = history_dir / backup_name

    # Copy file to backup location
    shutil.copy2(file_path, backup_path)

    return backup_path
