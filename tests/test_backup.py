"""Tests for backup module"""
import tempfile
import os
from pathlib import Path
from lib.backup import create_backup, HISTORY_DIR


def test_create_backup_creates_history_dir():
    """Backup should create .history directory if it doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        original.write_text("# Test Recipe\n\nContent here")

        backup_path = create_backup(original)

        history_dir = recipes_dir / HISTORY_DIR
        assert history_dir.exists()
        assert history_dir.is_dir()


def test_create_backup_preserves_content():
    """Backup should contain exact same content as original"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        content = "---\ntitle: Test\n---\n\n# Test Recipe\n\nContent here"
        original.write_text(content)

        backup_path = create_backup(original)

        assert backup_path.read_text() == content


def test_create_backup_uses_timestamp_in_name():
    """Backup filename should include timestamp"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "2026-01-07-pasta.md"
        original.write_text("content")

        backup_path = create_backup(original)

        # Should be like: 2026-01-07-pasta_2026-01-07T14-30-00.md
        assert backup_path.name.startswith("2026-01-07-pasta_")
        assert "T" in backup_path.name  # ISO timestamp has T separator
        assert backup_path.name.endswith(".md")


def test_create_backup_returns_path():
    """Backup should return the path to the backup file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        original = recipes_dir / "test-recipe.md"
        original.write_text("content")

        backup_path = create_backup(original)

        assert isinstance(backup_path, Path)
        assert backup_path.exists()
