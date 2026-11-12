import json

import batch_extract as be


def test_dry_run_dead_letter_has_no_side_effects(tmp_path, monkeypatch):
    dead_letter = tmp_path / "dead_letter.json"
    monkeypatch.setattr(be, "_DEAD_LETTER_PATH", dead_letter)
    monkeypatch.setattr(
        be, "mark_reminder_complete",
        lambda store, reminder: (_ for _ in ()).throw(
            AssertionError("dry-run must not touch Reminders")))

    moved = be._move_to_dead_letter(
        object(), object(), "https://example.com", "Example", "blocked",
        "blocked", 1, dry_run=True)

    assert moved is True
    assert not dead_letter.exists()


def test_failed_reminder_completion_does_not_write_dead_letter(
        tmp_path, monkeypatch):
    dead_letter = tmp_path / "dead_letter.json"
    monkeypatch.setattr(be, "_DEAD_LETTER_PATH", dead_letter)
    monkeypatch.setattr(be, "mark_reminder_complete",
                        lambda store, reminder: False)

    moved = be._move_to_dead_letter(
        object(), object(), "https://example.com", "Example", "blocked",
        "blocked", 1, dry_run=False)

    assert moved is False
    assert not dead_letter.exists()


def test_successful_reminder_completion_writes_dead_letter(
        tmp_path, monkeypatch):
    dead_letter = tmp_path / "missing-logs" / "dead_letter.json"
    monkeypatch.setattr(be, "_DEAD_LETTER_PATH", dead_letter)
    monkeypatch.setattr(be, "mark_reminder_complete",
                        lambda store, reminder: True)

    moved = be._move_to_dead_letter(
        object(), object(), "https://example.com", "Example", "blocked",
        "blocked", 2, dry_run=False)

    assert moved is True
    assert json.loads(dead_letter.read_text(encoding="utf-8"))[0]["attempts"] == 2


def test_blocked_errors_still_get_the_retry_cap():
    url = "https://example.com"
    tracker = {url: {"attempts": 1, "last_category": "blocked"}}

    assert be._should_dead_letter(tracker, url, "blocked") is False

    tracker[url]["attempts"] = be.MAX_RETRIES
    assert be._should_dead_letter(tracker, url, "blocked") is True


def test_failed_success_completion_keeps_retry_history(monkeypatch):
    url = "https://example.com"
    tracker = {url: {"attempts": 3}}
    monkeypatch.setattr(be, "mark_reminder_complete",
                        lambda store, reminder: False)

    completed = be._mark_complete_and_clear_retry(
        object(), object(), tracker, url, dry_run=False)

    assert completed is False
    assert tracker[url]["attempts"] == 3


def test_dead_letter_write_failure_does_not_complete_reminder(monkeypatch):
    completed = []
    monkeypatch.setattr(
        be, "_dead_letter",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(
        be, "mark_reminder_complete",
        lambda store, reminder: completed.append(reminder) or True)

    try:
        be._move_to_dead_letter(
            object(), object(), "https://example.com", "Example", "blocked",
            "blocked", 5, dry_run=False)
    except OSError:
        pass

    assert completed == []


def test_dry_run_does_not_prune_failure_logs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        be, "cleanup_old_failure_logs",
        lambda path: calls.append(path) or 1)

    removed = be._cleanup_failure_logs_for_run(tmp_path, dry_run=True)

    assert removed == 0
    assert calls == []
