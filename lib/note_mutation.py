"""Recoverable UTF-8 note edits for cooperating KitchenOS writers.

Thread locks plus flock serialize cooperating processes. An editor that ignores
flock can still write between our last read and rename: those unseen bytes
cannot be recovered or claimed as journaled. Atomic rename is not filesystem CAS.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Callable

from lib import inventory_db as db, paths
from lib.apple_integration.models import RevisionConflict
from lib.safe_paths import parse_iso_week

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_DEPTH = threading.local()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _known_path(path: Path) -> Path:
    path = Path(path).absolute()
    configured = paths.vault_root().absolute()
    root = configured.resolve()
    if path.is_relative_to(configured):
        path = root / path.relative_to(configured)
    # Never journal arbitrary personal files or resolve a symlink as another note.
    if path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("Note must be a known path inside the configured vault")
    relative = path.relative_to(root)
    if len(relative.parts) != 2 or relative.parts[0] not in {
        "Shopping Lists",
        "Meal Plans",
    }:
        raise ValueError("Unknown note path")
    match = re.fullmatch(r"(\d{4}-W\d{2})(\.md|\.tasks\.json)", relative.name)
    if not match or (relative.parts[0] == "Shopping Lists" and match[2] != ".md"):
        raise ValueError("Unknown note path")
    parse_iso_week(match[1])
    return path


def _read(path):
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return ""


@contextmanager
def _locked(path):
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(path), threading.RLock())
    with lock:
        depths = getattr(_LOCK_DEPTH, "paths", None)
        if depths is None:
            depths = _LOCK_DEPTH.paths = {}
        key = str(path)
        if depths.get(key, 0):
            depths[key] += 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / ("." + path.name + ".lock")).open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            depths[key] = 1
            try:
                yield
            finally:
                del depths[key]
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def mutation_lock(path: Path):
    """Lock one known note across read/merge/write, including nested journal edits.

    The outer acquisition owns the advisory lock's descriptor until exit;
    nested calls on the same thread reuse it without unlocking the outer call.
    No database transaction should span work inside this file lock.
    """
    with _locked(_known_path(path)):
        yield


def _replace(path, text, before):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="." + path.name + ".", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            if path.exists():
                os.fchmod(handle.fileno(), path.stat().st_mode & 0o777)
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if _read(path) != before:
            raise RevisionConflict("Note changed while preparing replacement")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _status(operation_id, status):
    with db.write_transaction() as conn:
        conn.execute(
            "UPDATE apple_file_edits SET status=? WHERE operation_id=?",
            (status, operation_id),
        )


def mutate_note(
    path: Path, expected_hash: str, transform: Callable[[str], str], operation_id: str
) -> str:
    """Journal exact before/after bytes, atomically replace, return the new hash.

    Retry the same operation with the same input hash and transformation. Drift
    on retry conflicts instead of restoring an older image over a newer edit.
    """
    path = _known_path(path)
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
        raise ValueError("Invalid operation ID")
    with _locked(path):
        with db.connect() as conn:
            previous = conn.execute(
                "SELECT * FROM apple_file_edits WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if previous:
            if (
                previous["path"] != str(path)
                or previous["before_hash"] != expected_hash
                or previous["status"] == "conflict"
            ):
                raise RevisionConflict("File operation does not match")
            after = transform(previous["before_text"])
            if after != previous["after_text"]:
                raise RevisionConflict("File operation payload changed")
            before = previous["before_text"]
        else:
            before = _read(path)
            if content_hash(before) != expected_hash:
                raise RevisionConflict("Note changed before mutation")
            after = transform(before)
            if not isinstance(after, str):
                raise ValueError("Note transform must return UTF-8 text")
            with db.write_transaction() as conn:
                conn.execute(
                    "INSERT INTO apple_file_edits(operation_id,path,before_hash,after_hash,before_text,after_text,status) VALUES(?,?,?,?,?,?,'pending')",
                    (
                        operation_id,
                        str(path),
                        expected_hash,
                        content_hash(after),
                        before,
                        after,
                    ),
                )
        current = _read(path)
        if current == after:
            _status(operation_id, "applied")
            return content_hash(after)
        if current != before:
            _status(operation_id, "conflict")
            raise RevisionConflict("Note changed before replacement")
        try:
            _replace(path, after, before)
        except RevisionConflict:
            _status(operation_id, "conflict")
            raise
        _status(operation_id, "applied")
        return content_hash(after)


def recover_note_edits() -> list[str]:
    """Finish pending edits only at their exact before/after image; report drift."""
    with db.connect() as conn:
        pending = list(
            conn.execute(
                "SELECT * FROM apple_file_edits WHERE status='pending' ORDER BY created_at, rowid"
            )
        )
    conflicts = []
    for edit in pending:
        try:
            mutate_note(
                Path(edit["path"]),
                edit["before_hash"],
                lambda _, e=edit: e["after_text"],
                edit["operation_id"],
            )
        except (RevisionConflict, ValueError, UnicodeError):
            _status(edit["operation_id"], "conflict")
            conflicts.append(edit["operation_id"])
    return conflicts
