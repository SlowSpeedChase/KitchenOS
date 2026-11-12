"""Delivering dictated/typed notes into the live ko-claude tmux session."""

import subprocess

import pytest

from lib import claude_send


class _FakeRun:
    """Records subprocess.run calls and replays canned return codes."""

    def __init__(self, has_session_rc=0, fail_on=None):
        self.calls = []
        self.has_session_rc = has_session_rc
        self.fail_on = fail_on

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.fail_on and self.fail_on in argv:
            raise subprocess.CalledProcessError(1, argv)
        rc = self.has_session_rc if "has-session" in argv else 0
        return subprocess.CompletedProcess(argv, rc, b"", b"")

    def call_for(self, verb):
        """The (argv, kwargs) of the call carrying `verb`, or (None, {})."""
        for argv, kwargs in self.calls:
            if verb in argv:
                return argv, kwargs
        return None, {}

    def argv_for(self, verb):
        return self.call_for(verb)[0]


@pytest.fixture
def fake(monkeypatch):
    f = _FakeRun()
    monkeypatch.setattr(claude_send, "subprocess", subprocess)
    monkeypatch.setattr(claude_send.subprocess, "run", f)
    monkeypatch.setattr(claude_send, "tmux_bin", lambda: "/opt/homebrew/bin/tmux")
    return f


class TestSendText:
    def test_sends_when_session_is_running(self, fake):
        assert claude_send.send_text("add oat milk to the list") is True

    def test_returns_false_when_no_session(self, monkeypatch, fake):
        fake.has_session_rc = 1
        assert claude_send.send_text("anything") is False

    def test_empty_and_whitespace_are_refused_without_touching_tmux(self, fake):
        assert claude_send.send_text("") is False
        assert claude_send.send_text("   \n  ") is False
        assert fake.calls == []

    def test_text_travels_as_a_buffer_on_stdin_not_as_keystrokes(self, fake):
        """A note saying 'Enter' must be typed, not executed as a keypress.

        Regression guard: send-keys would interpret it. load-buffer carries the
        text as data on stdin, so it can't be parsed as a key name.
        """
        claude_send.send_text("press Enter then C-c")
        load, kwargs = fake.call_for("load-buffer")
        assert load is not None
        assert "-" in load, "text must arrive on stdin"
        assert kwargs.get("input") == b"press Enter then C-c"
        # And it must never appear in a send-keys argv, where tmux would parse it.
        assert fake.argv_for("send-keys")[-1] == "Enter"

    def test_paste_is_bracketed_so_multiline_stays_one_prompt(self, fake):
        """Without -p, each newline replays as Return and splits one dictated
        note into several half-formed prompts."""
        claude_send.send_text("line one\nline two")
        paste = fake.argv_for("paste-buffer")
        assert paste is not None
        assert "-p" in paste, "bracketed paste required"
        assert "-d" in paste, "buffer should be deleted after pasting"

    def test_return_is_a_separate_deliberate_keypress(self, fake):
        claude_send.send_text("go")
        keys = fake.argv_for("send-keys")
        assert keys is not None
        assert keys[-1] == "Enter"

    def test_targets_the_ko_claude_session(self, fake):
        claude_send.send_text("go")
        paste = fake.argv_for("paste-buffer")
        assert "ko-claude" in paste

    def test_tmux_failure_is_reported_not_raised(self, fake):
        fake.fail_on = "paste-buffer"
        assert claude_send.send_text("go") is False


class TestSessionRunning:
    def test_false_when_tmux_is_absent(self, monkeypatch):
        monkeypatch.setattr(claude_send, "tmux_bin", lambda: None)
        assert claude_send.session_running() is False
        assert claude_send.send_text("go") is False

    def test_true_when_has_session_succeeds(self, fake):
        assert claude_send.session_running() is True

    def test_false_when_has_session_fails(self, fake):
        fake.has_session_rc = 1
        assert claude_send.session_running() is False


class TestCompose:
    """The note must carry the page it was written on.

    A real note read "This has a whole greek yogurt which doesn't make sense" —
    accurate, actionable, and impossible to act on, because the widget is on
    every page and nothing recorded which one.
    """

    def test_page_is_prefixed(self):
        out = claude_send.compose("fix this", page="/recipe/Mousse")
        assert "/recipe/Mousse" in out
        assert out.endswith("fix this")

    def test_title_is_included_with_the_page(self):
        out = claude_send.compose("fix this", page="/recipe/Mousse", title="Mousse — KitchenOS")
        assert "/recipe/Mousse" in out and "Mousse — KitchenOS" in out

    def test_title_alone_still_gives_context(self):
        assert "Mousse" in claude_send.compose("fix this", title="Mousse")

    def test_no_context_yields_the_bare_text(self):
        assert claude_send.compose("fix this") == "fix this"
        assert claude_send.compose("fix this", page="  ", title="") == "fix this"

    def test_absurd_context_cannot_bury_the_request(self):
        out = claude_send.compose("fix this", page="/x" * 5000)
        assert len(out) < 500
        assert out.endswith("fix this")


class TestDisabledSendRoute:
    @pytest.fixture
    def client(self):
        from api_server import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_absent_send_route_does_not_call_send_text(self, client, monkeypatch):
        called = False

        def send_text(_text):
            nonlocal called
            called = True

        monkeypatch.setattr(claude_send, "send_text", send_text)
        response = client.post("/api/claude-send", json={"text": "use up the spinach"})

        assert response.status_code == 404
        assert called is False


class TestTmuxBin:
    def test_falls_back_to_homebrew_when_path_is_minimal(self, monkeypatch):
        """The API server runs as a LaunchAgent with a minimal PATH, so a bare
        `tmux` does not resolve there even though it works in a shell."""
        monkeypatch.setattr(claude_send.shutil, "which", lambda _: None)
        monkeypatch.setattr(
            claude_send.os.path, "exists", lambda p: p == "/opt/homebrew/bin/tmux"
        )
        assert claude_send.tmux_bin() == "/opt/homebrew/bin/tmux"

    def test_none_when_tmux_is_nowhere(self, monkeypatch):
        monkeypatch.setattr(claude_send.shutil, "which", lambda _: None)
        monkeypatch.setattr(claude_send.os.path, "exists", lambda _: False)
        assert claude_send.tmux_bin() is None
