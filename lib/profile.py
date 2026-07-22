"""The user's personal food profile, read from `My Meal System.md`.

Follows the precedent of `lib/macro_targets.py` reading `My Macros.md`: a
hand-written vault note is the source of truth, and code adapts to it rather
than demanding a config file.

**The note is expected to grow.** So this parser is deliberately lopsided: it
extracts only the handful of sections something consumes *structurally* (the
buffer menu, the building blocks), and exposes the entire prose for LLM
callers. A new section reaches the model with no code change here — only a new
*structural* consumer needs one.

Heading matching is substring-based and case-insensitive for the same reason.
Headings are prose; "## The buffer menu — eat this first" will get reworded,
and an exact-match parser would silently start returning nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib import paths

PROFILE_FILENAME = "My Meal System.md"

# Health shorthand used throughout the note: [heart] = helps lower LDL,
# [steady] = keeps blood sugar level.
_TAG_RE = re.compile(r"\[(\w+)\]")
_BLOCK_RE = re.compile(r"^-\s*\*\*(?P<category>[^:*]+):?\*\*:?\s*(?P<items>.+)$")


@dataclass
class Profile:
    """Parsed personal food profile. Absent sections are empty, never missing."""

    prose: str
    health_goals: list[str] = field(default_factory=list)
    buffer_menu: dict[str, list[str]] = field(default_factory=dict)
    building_blocks: dict[str, list[str]] = field(default_factory=dict)

    def buffer_tags(self, item_prefix: str) -> set[str]:
        """Health tags on the first buffer item matching ``item_prefix``."""
        needle = item_prefix.strip().lower()
        for items in self.buffer_menu.values():
            for item in items:
                if item.lower().startswith(needle):
                    return set(_TAG_RE.findall(item))
        return set()

    def all_buffer_foods(self) -> list[str]:
        return [item for items in self.buffer_menu.values() for item in items]

    def prompt_context(self, max_chars: int = 4000) -> str:
        """The profile as prompt text, truncated at a paragraph boundary.

        Bounded because this rides along with every suggestion request; an
        unbounded personal note would quietly inflate the cost and latency of
        every call as it grows.
        """
        text = self.prose.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        boundary = cut.rfind("\n\n")
        return cut[:boundary] if boundary > max_chars // 2 else cut


def _strip_frontmatter(content: str) -> tuple[str, dict]:
    """Split off YAML frontmatter, returning (body, parsed_frontmatter)."""
    from lib.recipe_parser import parse_recipe_file
    parsed = parse_recipe_file(content)
    return parsed.get("body", content), (parsed.get("frontmatter") or {})


def _sections(body: str, level: int) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, text)`` pairs at the given ``#`` depth."""
    marker = "#" * level
    pattern = re.compile(rf"^{marker} +(.*)$", re.MULTILINE)
    out: list[tuple[str, str]] = []
    matches = list(pattern.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((m.group(1).strip(), body[m.end():end]))
    return out


def _find_section(body: str, needle: str, level: int = 2) -> Optional[str]:
    needle = needle.lower()
    for heading, text in _sections(body, level):
        if needle in heading.lower():
            return text
    return None


def _bullets(text: str) -> list[str]:
    """Bare list items, ignoring surrounding instruction prose."""
    return [
        line.strip()[2:].strip()
        for line in text.splitlines()
        if line.strip().startswith("- ")
    ]


def _parse_buffer_menu(body: str) -> dict[str, list[str]]:
    section = _find_section(body, "buffer menu")
    if section is None:
        return {}
    lanes: dict[str, list[str]] = {}
    for lane, text in _sections(section, 3):
        items = _bullets(text)
        if items:
            lanes[lane] = items
    return lanes


def _parse_building_blocks(body: str) -> dict[str, list[str]]:
    section = _find_section(body, "building blocks")
    if section is None:
        return {}
    blocks: dict[str, list[str]] = {}
    for line in section.splitlines():
        m = _BLOCK_RE.match(line.strip())
        if not m:
            continue
        category = m.group("category").strip()
        # Drop a trailing tag/aside such as "[heart] (dairy replacement)".
        items_text = re.sub(r"\s*\[\w+\].*$", "", m.group("items")).strip()
        items = [i.strip().rstrip(".") for i in items_text.split(",") if i.strip()]
        if items:
            blocks[category] = items
    return blocks


def profile_path(vault_path: Optional[Path] = None) -> Path:
    return (vault_path or paths.vault_root()) / PROFILE_FILENAME


def load_profile(vault_path: Optional[Path] = None) -> Optional[Profile]:
    """Load the profile, or None if the note does not exist.

    Callers must treat None as "no preferences expressed" and carry on — the
    profile is an enhancement, never a prerequisite.
    """
    path = profile_path(vault_path)
    if not path.exists():
        return None

    body, fm = _strip_frontmatter(path.read_text(encoding="utf-8"))
    goals = fm.get("health_goals") or []
    if isinstance(goals, str):
        goals = [goals]

    return Profile(
        prose=body,
        health_goals=list(goals),
        buffer_menu=_parse_buffer_menu(body),
        building_blocks=_parse_building_blocks(body),
    )
