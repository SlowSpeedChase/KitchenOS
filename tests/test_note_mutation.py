"""Crash recovery and cooperating-writer serialization use isolated real files."""

import hashlib
import multiprocessing
from pathlib import Path
from uuid import uuid4

import pytest

from lib import inventory_db as db, paths
from lib.apple_integration.models import RevisionConflict


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def note(tmp_vault, tmp_db):
    path = paths.shopping_lists_dir() / "2026-W41.md"
    path.parent.mkdir()
    path.write_text("before\r\n", newline="")
    return path


def test_mutation_preserves_exact_bytes_and_retries(note):
    from lib.note_mutation import mutate_note

    op = str(uuid4())
    assert mutate_note(
        note, digest("before\r\n"), lambda s: s + "after\n", op
    ) == digest("before\r\nafter\n")
    assert note.read_bytes() == b"before\r\nafter\n"
    assert mutate_note(
        note, digest("before\r\n"), lambda s: s + "after\n", op
    ) == digest("before\r\nafter\n")
    with db.connect() as conn:
        record = conn.execute("SELECT * FROM apple_file_edits").fetchone()
        assert record["before_text"].encode() == b"before\r\n"
        assert record["status"] == "applied"


def test_external_edit_before_final_check_is_preserved(note):
    from lib.note_mutation import mutate_note

    def edit(text):
        note.write_text("external")
        return "ours"

    with pytest.raises(RevisionConflict):
        mutate_note(note, digest("before\r\n"), edit, str(uuid4()))
    assert note.read_text() == "external"


@pytest.mark.parametrize(
    "current,expected",
    [("before\r\n", "after"), ("after", "after"), ("external", "external")],
)
def test_recovery_only_accepts_observed_before_or_after(note, current, expected):
    from lib.note_mutation import recover_note_edits

    op = str(uuid4())
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO apple_file_edits(operation_id,path,before_hash,after_hash,before_text,after_text,status) VALUES(?,?,?,?,?,?,'pending')",
            (
                op,
                str(note.resolve()),
                digest("before\r\n"),
                digest("after"),
                "before\r\n",
                "after",
            ),
        )
    note.write_bytes(current.encode())
    assert recover_note_edits() == ([op] if current == "external" else [])
    assert note.read_bytes() == expected.encode()


def test_external_edit_between_check_and_replace_is_not_claimed_recoverable(
    note, monkeypatch
):
    from lib import note_mutation

    real_replace = note_mutation.os.replace

    def race(src, dst):
        Path(dst).write_text("unobservable external bytes")
        real_replace(src, dst)

    monkeypatch.setattr(note_mutation.os, "replace", race)
    note_mutation.mutate_note(
        note, digest("before\r\n"), lambda _: "ours", str(uuid4())
    )
    with db.connect() as conn:
        record = conn.execute("SELECT * FROM apple_file_edits").fetchone()
        assert record["before_text"] == "before\r\n"
        assert "unobservable" not in record["after_text"]
    # Advisory locks cannot make a non-cooperating editor compare-and-swap.
    assert note.read_text() == "ours"


def _competing_write(path, expected, ready, release, result):
    from lib.note_mutation import mutate_note

    def transform(text):
        ready.set()
        release.wait(10)
        return text + "winner"

    try:
        mutate_note(Path(path), expected, transform, str(uuid4()))
        result.put("saved")
    except RevisionConflict:
        result.put("conflict")


def test_separate_processes_serialize_read_transform_replace(note):
    ctx = multiprocessing.get_context("fork")
    ready, release, ready2 = ctx.Event(), ctx.Event(), ctx.Event()
    result = ctx.Queue()
    args = (str(note), digest("before\r\n"))
    first = ctx.Process(target=_competing_write, args=(*args, ready, release, result))
    second = ctx.Process(target=_competing_write, args=(*args, ready2, release, result))
    first.start()
    assert ready.wait(10)
    second.start()
    assert not ready2.wait(0.2)
    release.set()
    first.join(10)
    second.join(10)
    assert sorted([result.get(timeout=2), result.get(timeout=2)]) == [
        "conflict",
        "saved",
    ]
    assert note.read_bytes() == b"before\r\nwinner"


def test_unknown_paths_never_enter_journal(note):
    from lib.note_mutation import mutate_note

    bad = paths.vault_root() / "My Meal System.md"
    with pytest.raises(ValueError):
        mutate_note(bad, digest(""), lambda _: "bad", str(uuid4()))
    assert not bad.exists()


def test_external_edit_during_temp_fsync_is_seen_by_final_check(note, monkeypatch):
    from lib import note_mutation

    real_fsync = note_mutation.os.fsync

    def external_edit(fd):
        note.write_text("external during temp preparation")
        real_fsync(fd)

    monkeypatch.setattr(note_mutation.os, "fsync", external_edit)
    with pytest.raises(RevisionConflict):
        note_mutation.mutate_note(
            note, digest("before\r\n"), lambda _: "ours", str(uuid4())
        )
    assert note.read_text() == "external during temp preparation"


def test_crash_after_replace_recovers_without_replacing_external_edit(
    note, monkeypatch
):
    from lib import note_mutation

    real_status = note_mutation._status

    def crash(*args):
        raise OSError("crash after replace")

    monkeypatch.setattr(note_mutation, "_status", crash)
    with pytest.raises(OSError):
        note_mutation.mutate_note(
            note, digest("before\r\n"), lambda _: "after", str(uuid4())
        )
    assert note.read_text() == "after"
    monkeypatch.setattr(note_mutation, "_status", real_status)
    assert note_mutation.recover_note_edits() == []
    assert note.read_text() == "after"


def test_unknown_journal_path_cannot_be_recovered(note, tmp_path):
    from lib.note_mutation import recover_note_edits

    outside = tmp_path / "outside.md"
    outside.write_text("before")
    op = str(uuid4())
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO apple_file_edits(operation_id,path,before_hash,after_hash,before_text,after_text,status) VALUES(?,?,?,?,?,?,'pending')",
            (op, str(outside), digest("before"), digest("after"), "before", "after"),
        )
    assert recover_note_edits() == [op]
    assert outside.read_text() == "before"


def _nested_locked_writer(path, ready, release, result):
    from lib.note_mutation import mutation_lock, mutate_note

    with mutation_lock(Path(path)):
        with mutation_lock(Path(path)):
            mutate_note(
                Path(path), digest("before\r\n"), lambda _: "nested", str(uuid4())
            )
        ready.set()
        release.wait(10)
    result.put("released")


def test_nested_lock_keeps_outer_advisory_lock_until_exit(note):
    """A nested journal edit must neither deadlock nor release the outer flock."""
    ctx = multiprocessing.get_context("spawn")
    ready, release, competing_ready = ctx.Event(), ctx.Event(), ctx.Event()
    result = ctx.Queue()
    first = ctx.Process(
        target=_nested_locked_writer, args=(str(note), ready, release, result)
    )
    second = ctx.Process(
        target=_competing_write,
        args=(str(note), digest("nested"), competing_ready, release, result),
    )
    try:
        first.start()
        assert ready.wait(10), "nested lock or mutate_note deadlocked"
        second.start()
        assert not competing_ready.wait(0.3), "nested exit released the outer file lock"
        release.set()
        first.join(10)
        second.join(10)
        assert first.exitcode == second.exitcode == 0
        assert sorted([result.get(timeout=2), result.get(timeout=2)]) == [
            "released",
            "saved",
        ]
        assert note.read_text() == "nestedwinner"
    finally:
        release.set()
        for process in (first, second):
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)


def test_public_mutation_lock_rejects_unknown_path(note):
    from lib.note_mutation import mutation_lock

    bad = paths.vault_root() / "My Meal System.md"
    with pytest.raises(ValueError):
        with mutation_lock(bad):
            pytest.fail("unknown path locked")
