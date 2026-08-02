"""Tests for backup module"""
import tempfile
import time
import os
from pathlib import Path
from lib.backup import create_backup, cleanup_old_backups, HISTORY_DIR


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


def test_cleanup_old_backups_removes_old_files():
    """Cleanup should remove backups older than max_age_days"""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_dir = Path(tmpdir) / ".history"
        history_dir.mkdir()

        # Create an "old" backup (fake the mtime)
        old_backup = history_dir / "recipe_2026-01-01T00-00-00.md"
        old_backup.write_text("old content")
        old_time = time.time() - (31 * 24 * 60 * 60)  # 31 days ago
        os.utime(old_backup, (old_time, old_time))

        # Create a "new" backup
        new_backup = history_dir / "recipe_2026-01-08T00-00-00.md"
        new_backup.write_text("new content")

        removed = cleanup_old_backups(history_dir, max_age_days=30)

        assert not old_backup.exists()
        assert new_backup.exists()
        assert removed == 1


def test_cleanup_old_backups_handles_missing_dir():
    """Cleanup should return 0 if directory doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_dir = Path(tmpdir) / "nonexistent"
        removed = cleanup_old_backups(missing_dir)
        assert removed == 0


class TestSameSecondBackupsDoNotClobber:
    """The .history snapshot is the ONLY recovery path — the vault is not in git.

    The filename was second-resolution and shutil.copy2 overwrites, so two
    writes to the same file within one second left only the LAST snapshot —
    i.e. a backup of already-damaged content, with the pristine original gone.
    Reachable from the tool's own documented follow-up (normalize --apply then
    backfill --only, chained), and the live .history already shows three files
    snapshotted inside one second.
    """

    def test_two_backups_in_the_same_second_both_survive(self, tmp_path):
        from lib.backup import create_backup

        f = tmp_path / "Recipe.md"
        f.write_text("PRISTINE ORIGINAL\n", encoding="utf-8")
        first = create_backup(f)

        f.write_text("DAMAGED REWRITE\n", encoding="utf-8")
        second = create_backup(f)

        assert first != second, "second backup overwrote the first"
        assert first.read_text(encoding="utf-8") == "PRISTINE ORIGINAL\n"
        assert second.read_text(encoding="utf-8") == "DAMAGED REWRITE\n"

    def test_many_rapid_backups_all_survive(self, tmp_path):
        from lib.backup import create_backup

        f = tmp_path / "Recipe.md"
        made = []
        for i in range(8):
            f.write_text(f"version {i}\n", encoding="utf-8")
            made.append(create_backup(f))

        assert len(set(made)) == 8, "some snapshots clobbered each other"
        for i, p in enumerate(made):
            assert p.read_text(encoding="utf-8") == f"version {i}\n"

    def test_the_backup_still_sorts_chronologically_by_name(self, tmp_path):
        """cleanup_old_backups and the recovery flow both rely on name order."""
        from lib.backup import create_backup

        f = tmp_path / "Recipe.md"
        made = []
        for i in range(5):
            f.write_text(f"v{i}\n", encoding="utf-8")
            made.append(create_backup(f))

        assert [p.name for p in made] == sorted(p.name for p in made)


class TestWriteNote:
    """One call that backs up and writes, so the safe path is the easy path.

    lib/CLAUDE.md says "any code that overwrites a recipe file should call
    backup.create_backup() first", and most writers do — but it is a convention
    a new writer has to know about, and three did not: lib/cook_history.py
    (syncs cook stats into real recipes automatically), import_crouton.py
    (replaces a whole existing file, My Notes included) and
    generate_meal_plan.py --force.
    """

    def test_it_writes_the_content(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        write_note(p, "hello\n")
        assert p.read_text(encoding="utf-8") == "hello\n"

    def test_a_new_file_needs_no_backup(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        write_note(p, "first write\n")
        assert not (tmp_path / ".history").exists(), "backed up a file that did not exist"

    def test_overwriting_backs_up_the_previous_content(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        p.write_text("ORIGINAL\n", encoding="utf-8")
        write_note(p, "REPLACEMENT\n")
        snaps = list((tmp_path / ".history").glob("Recipe_*.md"))
        assert len(snaps) == 1
        assert snaps[0].read_text(encoding="utf-8") == "ORIGINAL\n"
        assert p.read_text(encoding="utf-8") == "REPLACEMENT\n"

    def test_an_unchanged_write_is_a_no_op(self, tmp_path):
        """Re-running a sync must not fill .history with identical snapshots."""
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        p.write_text("same\n", encoding="utf-8")
        before = p.stat().st_mtime_ns
        assert write_note(p, "same\n") is False
        assert p.stat().st_mtime_ns == before
        assert not (tmp_path / ".history").exists()

    def test_it_reports_whether_it_wrote(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        assert write_note(p, "a\n") is True
        assert write_note(p, "a\n") is False
        assert write_note(p, "b\n") is True

    def test_repeated_overwrites_each_keep_their_own_snapshot(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "Recipe.md"
        p.write_text("v0\n", encoding="utf-8")
        for i in range(1, 4):
            write_note(p, f"v{i}\n")
        snaps = sorted((tmp_path / ".history").glob("Recipe_*.md"))
        assert len(snaps) == 3, "same-second snapshots collided"
        assert [s.read_text(encoding="utf-8") for s in snaps] == ["v0\n", "v1\n", "v2\n"]

    def test_it_creates_parent_directories(self, tmp_path):
        from lib.backup import write_note
        p = tmp_path / "nested" / "Recipe.md"
        write_note(p, "x\n")
        assert p.read_text(encoding="utf-8") == "x\n"
