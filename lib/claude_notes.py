"""Read/write the single shared Claude Notes.md at the vault root.

The file's entire contents ARE the notes body — no frontmatter, no banner — so
what you type in the web textarea, edit in Obsidian, and hand to `claude` on
launch are byte-identical. Missing file reads as empty string. Writes are atomic
(tmp + os.replace) so an interrupted save can't truncate the file.
"""
import os

from lib.paths import claude_notes_path


def read_notes() -> str:
    p = claude_notes_path()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def write_notes(text: str) -> None:
    p = claude_notes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = (text.rstrip("\n") + "\n") if text.strip() else ""
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, p)
