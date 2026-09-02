"""Shopping list template generation.

Creates markdown shopping list files with checkboxes and send button.
"""

import base64
import json

from templates.meal_plan_template import format_week_range


def generate_shopping_list_markdown(week: str, items: list[str],
                                    on_hand: list[str] | None = None,
                                    check_pantry: list[str] | None = None,
                                    generated_items: list[str] | None = None) -> str:
    """Generate shopping list markdown.

    Args:
        week: Week identifier like '2026-W04'
        items: List of formatted ingredient strings — what to buy
        on_hand: Optional notes about what the pantry already covered
            (`shopping_list_generator.on_hand_notes`). Rendered as **plain
            bullets, never checkboxes**: `parse_shopping_list_file` collects every
            `- [ ]` line in the file regardless of section, so a checkbox here
            would be sent to Reminders as something to buy and would come back as
            a phantom "manual item" on the next regeneration.
        check_pantry: Optional uncertain inventory-match notes. These stay as
            plain bullets while the corresponding ingredient remains an item
            checkbox.
        generated_items: Items produced from recipes, excluding preserved manual
            additions. Stored as encoded metadata so a later regeneration can
            distinguish provenance even when inventory removes a generated item.

    Returns:
        Formatted markdown string
    """
    # The date range *is* the title — a week number identifies nothing to a human.
    # Falls back to the raw id only when the id is malformed.
    try:
        title = f"# Shopping List - {format_week_range(week)}"
    except ValueError:
        title = f"# Shopping List - {week}"

    lines = [
        title,
        "",
        f"Generated from [[{week}|Meal Plan]]",
    ]

    if generated_items is not None:
        payload = base64.urlsafe_b64encode(
            json.dumps(generated_items, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        lines.extend(["", f"<!-- kitchenos-generated-items-v2:{payload} -->"])

    lines.extend(["", "## Items", ""])

    # Add checklist items
    for item in items:
        lines.append(f"- [ ] {item}")

    if on_hand:
        lines.extend([
            "",
            "## Already have",
            "",
            "<!-- Credited from inventory. Nothing here was deducted from your"
            " stock — that only happens when you confirm a cook. -->",
            "",
        ])
        lines.extend(f"- {note}" for note in on_hand)

    if check_pantry:
        lines.extend([
            "",
            "## Check pantry",
            "",
            "<!-- Possible inventory matches were not credited. The matching"
            " ingredients remain checked items above until you verify them. -->",
            "",
        ])
        lines.extend(f"- {note}" for note in check_pantry)

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
