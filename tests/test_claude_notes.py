"""Tests for the Claude Notes storage layer."""
import pytest

from lib import claude_notes
from lib.paths import claude_notes_path


def test_read_missing_returns_empty(tmp_vault):
    """read_notes() on a fresh vault (no file) returns empty string."""
    assert claude_notes.read_notes() == ""


def test_path_under_vault(tmp_vault):
    """claude_notes_path() resolves to <tmp_vault>/Claude Notes.md."""
    assert claude_notes_path() == tmp_vault / "Claude Notes.md"


def test_round_trip_single_line(tmp_vault):
    """write_notes() then read_notes() preserves text with trailing newline normalization."""
    claude_notes.write_notes("buy milk")
    assert claude_notes.read_notes() == "buy milk\n"
    assert claude_notes_path().exists()


def test_write_empty_creates_empty_file(tmp_vault):
    """write_notes("") creates an empty file; read_notes() returns empty string."""
    claude_notes.write_notes("")
    assert claude_notes.read_notes() == ""
    assert claude_notes_path().exists()
    assert claude_notes_path().stat().st_size == 0


def test_write_whitespace_creates_empty_file(tmp_vault):
    """write_notes() with whitespace-only text creates an empty file."""
    claude_notes.write_notes("   \n\n")
    assert claude_notes.read_notes() == ""
    assert claude_notes_path().stat().st_size == 0


def test_multiline_round_trip(tmp_vault):
    """Multi-line body with markdown and special chars round-trips verbatim (modulo trailing newline)."""
    text = "# Heading\n- item | pipe\n`code`\nline2"
    claude_notes.write_notes(text)
    assert claude_notes.read_notes() == text + "\n"


def test_overwrite(tmp_vault):
    """write_notes() full overwrites, not appends."""
    claude_notes.write_notes("a")
    claude_notes.write_notes("b")
    assert claude_notes.read_notes() == "b\n"
