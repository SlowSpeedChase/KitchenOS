"""Surgical YAML-frontmatter edits for recipe notes.

Deliberately line-based rather than a parse-and-dump round trip: recipe notes
are hand-edited in Obsidian, and re-emitting them through a YAML serializer
reorders keys, restyles quotes, and expands flow lists — a diff the user never
asked for. Editing only the lines we own leaves everything else byte-identical.

Each caller passes the set of keys it *manages*. Only those are de-duplicated
or overwritten; every other line (including multi-line list values such as
``tags:`` and ``dietary:``) passes through untouched.

Extracted from ``backfill_nutrition.py``, which now imports from here, so the
nutrition backfill and the cook-history sync cannot drift apart.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

_KEY_RE = re.compile(r"^([A-Za-z_][\w]*):")


def split_frontmatter(content: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(frontmatter_text, rest)``, or ``(None, None)`` if absent."""
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, None
    return parts[1], parts[2]


def rewrite(fm: str, updates: dict, managed_keys: Iterable[str],
            remove: Iterable[str] = ()) -> str:
    """De-duplicate the managed keys and apply ``updates``.

    Duplicate occurrences of a managed key collapse to a single line (the last
    position wins, matching YAML's "last key wins"). Keys in ``updates``
    overwrite the kept line, or are appended once if absent. Passing
    ``updates={}`` performs a pure de-duplication pass.

    ``remove`` deletes keys outright — needed when the data behind a key stops
    existing (e.g. the last cook of a recipe is deleted), where leaving a stale
    value would be worse than having none.
    """
    managed = set(managed_keys)
    dropped = set(remove)
    lines = fm.split("\n")
    out: list = []
    last_idx: dict = {}

    for line in lines:
        m = _KEY_RE.match(line)
        # A leading space means this is a list item or continuation, not a key.
        key = m.group(1) if (m and not line[:1].isspace()) else None
        if key is not None and key in dropped:
            continue
        if key in managed:
            if key in last_idx:
                out[last_idx[key]] = None  # drop the earlier duplicate
            last_idx[key] = len(out)
        out.append(line)

    # Append new keys BEFORE any trailing blank lines, so the frontmatter keeps
    # its trailing newline and the closing "---" stays on its own line.
    # (Appending at the very end glued "---" onto the last key, corrupting it.)
    for key, value in updates.items():
        new_line = f"{key}: {value}"
        if key in last_idx:
            out[last_idx[key]] = new_line
        else:
            pos = len(out)
            while pos > 0 and (out[pos - 1] is None or out[pos - 1] == ""):
                pos -= 1
            out.insert(pos, new_line)
            last_idx[key] = pos

    result = "\n".join(l for l in out if l is not None)
    # The frontmatter text must end with a newline so reconstruction as
    # f"---{result}---..." never glues the delimiter onto a key.
    if not result.endswith("\n"):
        result += "\n"
    return result


def apply(content: str, updates: dict, managed_keys: Iterable[str],
          remove: Iterable[str] = ()) -> Optional[str]:
    """Rewrite a whole note's frontmatter, returning None if it has none."""
    fm, rest = split_frontmatter(content)
    if fm is None:
        return None
    return f"---{rewrite(fm, updates, managed_keys, remove)}---{rest}"
