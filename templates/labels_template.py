"""Render printable shelf labels from the layout config.

Output format: a single ``Kitchen Labels.md`` with one card per shelf. Each
card lists the supply groups that belong on that shelf so the physical label
matches what gets stored there.
"""

from __future__ import annotations

from datetime import date

from lib.inventory import Layout


def render_labels(layout: Layout, generated: date | None = None) -> str:
    generated = generated or date.today()
    out: list[str] = [
        "# Kitchen Labels",
        f"Generated: {generated.isoformat()}",
        "",
        "> Print this page to label every shelf. Each card lists the supply",
        "> groups that should live on that shelf — keep it consistent with",
        "> `config/storage_locations.json`.",
        "",
    ]

    current_space: str | None = None
    for shelf in layout.shelves:
        if shelf.space_id != current_space:
            out.append(f"## {shelf.space_label}")
            out.append("")
            current_space = shelf.space_id

        out.append(f"### {shelf.shelf_label}")
        out.append("")
        out.append(f"_Location id: `{shelf.location_id}`_")
        out.append("")
        if shelf.groups:
            out.append("**Holds:**")
            for gid in shelf.groups:
                group = layout.groups.get(gid)
                label = group.label if group else gid
                out.append(f"- {label}")
        else:
            out.append("_No supply groups assigned._")
        out.append("")
        out.append("---")
        out.append("")

    while out and out[-1] in ("", "---"):
        out.pop()
    return "\n".join(out) + "\n"
