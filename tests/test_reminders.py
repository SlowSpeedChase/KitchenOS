"""Tests for the Apple Reminders bridge.

The security-relevant property here is that shopping-list text never reaches the
AppleScript *source*. These strings trace back to ingredient lines an LLM
extracted from arbitrary recipe pages, so a quote in an ingredient used to be
able to close the string literal and have the remainder evaluated.
"""

import pytest

from lib import reminders


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def calls(monkeypatch):
    """Capture the subprocess invocation instead of talking to Reminders."""
    seen = []

    def fake_run(cmd, **kw):
        seen.append({"cmd": cmd, "input": kw.get("input", "")})
        return _Proc(stdout="ok")

    monkeypatch.setattr(reminders.subprocess, "run", fake_run)
    return seen


class TestNoInjection:
    def test_items_are_passed_as_argv_not_interpolated(self, calls):
        payload = 'a" & (do shell script "touch /tmp/PWNED") & "b'
        reminders.add_to_reminders([payload], "Shopping")

        script = calls[0]["input"]
        cmd = calls[0]["cmd"]
        # The payload must appear ONLY as an argument, never in the source.
        assert payload not in script
        assert payload in cmd
        assert "do shell script" not in script

    def test_script_is_read_from_stdin(self, calls):
        reminders.add_to_reminders(["milk"], "Shopping")
        assert calls[0]["cmd"][:2] == ["osascript", "-"]
        assert calls[0]["cmd"][2] == "Shopping"        # list name first
        assert calls[0]["cmd"][3:] == ["milk"]

    def test_quotes_and_backslashes_survive_untouched(self, calls):
        items = ['1 tbsp "gochujang"', r"back\slash", "1 jalapeño pepper"]
        reminders.add_to_reminders(items, "Shopping")
        assert calls[0]["cmd"][3:] == items       # no escaping applied at all


class TestBatching:
    def test_all_items_go_in_one_subprocess_call(self, calls):
        """Each Reminders round-trip costs ~0.4s; one call per item was ~10s."""
        reminders.add_to_reminders([f"item {i}" for i in range(24)], "Shopping")
        assert len(calls) == 1
        assert len(calls[0]["cmd"]) == 2 + 1 + 24

    def test_returns_the_number_added(self, calls):
        assert reminders.add_to_reminders(["a", "b", "c"]) == 3

    def test_empty_and_blank_items_are_dropped_without_calling_out(self, calls):
        assert reminders.add_to_reminders([]) == 0
        assert reminders.add_to_reminders(["", "   "]) == 0
        assert calls == []

    def test_blank_items_are_filtered_but_real_ones_still_sent(self, calls):
        assert reminders.add_to_reminders(["milk", "  ", "eggs"]) == 2
        assert calls[0]["cmd"][3:] == ["milk", "eggs"]


class TestFailuresAreDiagnosable:
    def test_applescript_error_surfaces_its_message(self, monkeypatch):
        monkeypatch.setattr(
            reminders.subprocess, "run",
            lambda cmd, **kw: _Proc(returncode=1, stderr="Reminders got an error: no"),
        )
        with pytest.raises(RuntimeError, match="Reminders got an error: no"):
            reminders.add_to_reminders(["milk"])

    def test_silent_failure_still_raises_something_useful(self, monkeypatch):
        monkeypatch.setattr(
            reminders.subprocess, "run",
            lambda cmd, **kw: _Proc(returncode=1),
        )
        with pytest.raises(RuntimeError, match="osascript failed"):
            reminders.add_to_reminders(["milk"])


class TestListManagement:
    def test_create_passes_the_name_as_an_argument(self, calls):
        reminders.create_reminders_list("Groceries")
        assert calls[0]["cmd"] == ["osascript", "-", "Groceries"]
        assert "Groceries" not in calls[0]["input"]

    def test_clear_passes_the_name_as_an_argument(self, calls):
        reminders.clear_reminders_list("Groceries")
        assert calls[0]["cmd"] == ["osascript", "-", "Groceries"]
        assert "Groceries" not in calls[0]["input"]
