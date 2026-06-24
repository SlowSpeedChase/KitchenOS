"""Shopping list template generation.

Creates markdown shopping list files with checkboxes and send button.
"""

import re

from templates.meal_plan_template import format_week_range


def generate_shopping_list_markdown(week: str, items: list[str]) -> str:
    """Generate shopping list markdown.

    Args:
        week: Week identifier like '2026-W04'
        items: List of formatted ingredient strings

    Returns:
        Formatted markdown string
    """
    # Extract week number for display
    match = re.match(r'\d{4}-W(\d{2})', week)
    week_num = int(match.group(1)) if match else 0

    # Lead the title with the human date range so the week is identifiable at a glance
    try:
        title = f"# Shopping List - Week {week_num:02d} ({format_week_range(week)})"
    except ValueError:
        title = f"# Shopping List - Week {week_num:02d}"

    lines = [
        title,
        "",
        f"Generated from [[{week}|Meal Plan]]",
        "",
        "## Items",
        "",
    ]

    # Add checklist items
    for item in items:
        lines.append(f"- [ ] {item}")

    # Add buttons
    lines.extend([
        "",
        "---",
        "",
        "```button",
        "name Add Ingredients",
        "type command",
        "action QuickAdd: Add Ingredients to Shopping List",
        "```",
        "",
        "```button",
        "name Send to Reminders",
        "type link",
        f"action kitchenos://send-to-reminders?week={week}",
        "```",
        "",
    ])

    return '\n'.join(lines)


def generate_filename(week: str) -> str:
    """Generate filename for shopping list.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Filename like '2026-W04.md'
    """
    return f"{week}.md"
