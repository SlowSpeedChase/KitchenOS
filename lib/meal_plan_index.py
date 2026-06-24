"""Generate a human-navigable index of weekly meal plans.

Obsidian lists meal-plan files by their bare ISO id (``2026-W26.md``), which is
hard to map to actual dates. This builds a ``Meal Plans Index.md`` note that
lists each week as ``Week NN | <date range> | [[2026-Www]]`` so a week can be
found by its dates and opened with a click.

The index filename is deliberately NOT ``YYYY-Www.md``, so the strict
``parse_week_from_filename`` scanners (calendar sync, etc.) skip it.
"""

import re
from datetime import date
from pathlib import Path
from typing import Optional

from lib import paths
from templates.meal_plan_template import (
    parse_week_id,
    format_week_range,
    get_week_date_range,
)

INDEX_FILENAME = "Meal Plans Index.md"

# Meal-plan files are exactly YYYY-Www (the index note itself won't match).
_WEEK_FILE_RE = re.compile(r'^(\d{4})-W(\d{2})$')


def build_index_markdown(week_ids: list[str], today: Optional[date] = None) -> str:
    """Build the index markdown for the given week ids (newest week first)."""
    today = today or date.today()

    unique_sorted = sorted(set(week_ids), key=parse_week_id, reverse=True)

    lines = [
        "# Meal Plans Index",
        "",
        "> Auto-generated — find a week by its dates, then open the plan.",
        "",
        "| Week | Dates | Plan |",
        "| --- | --- | --- |",
    ]
    for week_id in unique_sorted:
        _, week_num = parse_week_id(week_id)
        start, end = get_week_date_range(*parse_week_id(week_id))
        date_range = format_week_range(week_id)  # e.g. "Jun 22 - Jun 28, 2026"
        marker = " **(this week)**" if start <= today <= end else ""
        lines.append(f"| Week {week_num:02d} | {date_range}{marker} | [[{week_id}]] |")
    lines.append("")
    return "\n".join(lines)


def regenerate_index(
    meal_plans_directory: Optional[Path] = None,
    today: Optional[date] = None,
) -> Optional[Path]:
    """Scan the meal-plans dir and (re)write the index note.

    Returns the index path, or None if the directory is missing or has no
    meal-plan files yet.
    """
    directory = Path(meal_plans_directory) if meal_plans_directory else paths.meal_plans_dir()
    if not directory.exists():
        return None

    week_ids = [p.stem for p in directory.glob("*.md") if _WEEK_FILE_RE.match(p.stem)]
    if not week_ids:
        return None

    index_path = directory / INDEX_FILENAME
    index_path.write_text(build_index_markdown(week_ids, today=today), encoding="utf-8")
    return index_path
