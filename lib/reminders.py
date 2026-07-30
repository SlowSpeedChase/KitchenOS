"""Apple Reminders integration via AppleScript.

Two things here are deliberate and shouldn't be "simplified" back:

**Item text is passed as `argv`, never interpolated into the script.** These
strings are shopping-list lines, which trace back to ingredient text an LLM
extracted from arbitrary recipe pages — so they are untrusted input. Building the
AppleScript by substitution meant a quote in an ingredient could close the string
and have the rest evaluated: `a" & (do shell script "…") & "b` was a working
command-execution payload. Passing them through `on run argv` removes the escaping
problem entirely rather than trying to out-escape it.

**All items go in one `osascript` call.** Each round-trip to Reminders costs
~0.4s, so the previous item-at-a-time loop took ~10s for a 24-item list — long
enough that the phone button firing it looked broken.
"""

import subprocess

# Creating the list here (rather than in a separate call) keeps the whole
# operation to a single round-trip.
_ADD_SCRIPT = """
on run argv
    set listName to item 1 of argv
    tell application "Reminders"
        if not (exists list listName) then
            make new list with properties {name:listName}
        end if
        tell list listName
            repeat with i from 2 to (count of argv)
                make new reminder with properties {name:(item i of argv)}
            end repeat
        end tell
    end tell
    return (count of argv) - 1
end run
"""

_CREATE_SCRIPT = """
on run argv
    tell application "Reminders"
        if not (exists list (item 1 of argv)) then
            make new list with properties {name:(item 1 of argv)}
        end if
    end tell
end run
"""

_CLEAR_SCRIPT = """
on run argv
    tell application "Reminders"
        if exists list (item 1 of argv) then
            tell list (item 1 of argv) to delete every reminder
        end if
    end tell
end run
"""


def _run(script: str, *args: str) -> str:
    """Run an AppleScript from stdin with ``args`` as its ``argv``.

    ``osascript -`` reads the program from stdin, leaving everything after it as
    arguments — which is what keeps untrusted item text out of the source.
    """
    proc = subprocess.run(
        ["osascript", "-", *args],
        input=script, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # Surface AppleScript's own message; the caller turns this into a 500
        # the page can display, and "failed" alone is undiagnosable.
        raise RuntimeError((proc.stderr or "osascript failed").strip())
    return proc.stdout.strip()


def add_to_reminders(items, list_name="Shopping"):
    """Add items to an Apple Reminders list, creating it if needed.

    Returns the number of items added.
    """
    items = [str(i) for i in items if str(i).strip()]
    if not items:
        return 0
    _run(_ADD_SCRIPT, list_name, *items)
    return len(items)


def clear_reminders_list(list_name="Shopping"):
    """Remove all items from a Reminders list. A missing list is not an error."""
    _run(_CLEAR_SCRIPT, list_name)


def create_reminders_list(list_name="Shopping"):
    """Create a Reminders list if it doesn't exist."""
    _run(_CREATE_SCRIPT, list_name)
