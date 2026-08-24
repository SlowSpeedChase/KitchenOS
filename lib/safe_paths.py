from __future__ import annotations

from datetime import date
from pathlib import Path
import re


_ISO_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def contained_markdown(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid Markdown filename")
    relative = Path(value)
    if relative.is_absolute() or relative.suffix.lower() != ".md":
        raise ValueError("invalid Markdown filename")
    resolved_root = Path(root).resolve()
    candidate = (resolved_root / relative).resolve(strict=False)
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("Markdown path escapes its configured directory")
    return candidate


def parse_iso_week(value: str) -> str:
    match = _ISO_WEEK.fullmatch(value or "")
    if match is None:
        raise ValueError("week required (YYYY-WNN)")
    year, week = map(int, match.groups())
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError("week required (YYYY-WNN)") from exc
    return f"{year:04d}-W{week:02d}"


def shopping_list_path(root: Path, week: str) -> Path:
    return contained_markdown(root, f"{parse_iso_week(week)}.md")
