"""Send text into the live `ko-claude` tmux session.

The Launch Claude button starts `claude` inside a *named* tmux session so the
work survives a phone disconnect or a locked screen. That name is what makes
this module possible: because the session can be addressed from outside, text
typed (or dictated) into the web Notes box can be delivered to a Claude that is
already running.

Notes alone cannot do that. `Claude Notes.md` seeds the *opening prompt*, so a
note saved while a session is live is ignored until someone resets the session —
which throws away whatever Claude was in the middle of. This is the path that
reaches a running session without killing it.
"""

from __future__ import annotations

import os
import shutil
import subprocess

SESSION = "ko-claude"
_BUFFER = "ko-send"

# Page/title are echoed back into a prompt, so they are length-capped. Long
# enough for any real recipe path, short enough that a junk value can't bury
# the actual request.
_CONTEXT_CAP = 200


def compose(text: str, page: str = "", title: str = "") -> str:
    """Prefix `text` with the page it was written on.

    The Notes box lives on every page, so a note reading "this has a whole greek
    yogurt, fix it" arrives with no referent for "this" — the words survive the
    trip and the subject does not. Carrying the URL turns an unactionable note
    into an actionable one.

    Context is omitted entirely rather than sent empty, so a caller that has no
    page (curl, a test) produces a clean prompt instead of a dangling header.
    """
    page = (page or "").strip()[:_CONTEXT_CAP]
    title = (title or "").strip()[:_CONTEXT_CAP]
    if not page and not title:
        return text
    where = page
    if title:
        where = f"{page} — {title}" if page else title
    return f"[written on the KitchenOS page: {where}]\n\n{text}"


def tmux_bin() -> str | None:
    """Absolute path to tmux, or None if it isn't installed.

    Resolved explicitly because the API server runs as a LaunchAgent, whose PATH
    is minimal — a bare ``tmux`` does not resolve there even though it works in
    an interactive shell.
    """
    found = shutil.which("tmux")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux"):
        if os.path.exists(candidate):
            return candidate
    return None


def session_running() -> bool:
    """Whether a `ko-claude` session currently exists."""
    tmux = tmux_bin()
    if not tmux:
        return False
    try:
        return subprocess.run(
            [tmux, "has-session", "-t", SESSION],
            capture_output=True,
        ).returncode == 0
    except OSError:
        return False


def send_text(text: str) -> bool:
    """Deliver `text` to the live session as one prompt. False if not running.

    Sent as a tmux *paste buffer* with bracketed paste (``-p``) rather than
    ``send-keys``, for two reasons. Bracketed paste tells the TUI the block is
    pasted text, so embedded newlines stay part of one prompt — send-keys would
    replay each newline as a Return and fire a multi-line dictated note off as
    several separate half-formed prompts. And a buffer carries the text as data,
    so a note containing ``Enter`` or ``C-c`` is typed rather than interpreted as
    a keystroke.

    Return is then a single deliberate keypress, which is what submits.
    """
    if not text.strip():
        return False
    tmux = tmux_bin()
    if not tmux or not session_running():
        return False
    try:
        subprocess.run(
            [tmux, "load-buffer", "-b", _BUFFER, "-"],
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [tmux, "paste-buffer", "-b", _BUFFER, "-t", SESSION, "-p", "-d"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [tmux, "send-keys", "-t", SESSION, "Enter"],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True
