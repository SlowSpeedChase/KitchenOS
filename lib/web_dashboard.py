"""Generate the 'KitchenOS Web.md' vault note.

The note is a regenerated read-only view (like ``Inventory.md`` / ``Use It Up.md``)
whose only job is to be a tap-anywhere launcher for the KitchenOS web app. Every
link points at the configured web base URL — a stable Tailscale MagicDNS hostname
by default — so the same note works from any device on the tailnet (Mac, iPad,
iPhone), not just localhost on the server.

Base URL resolution matches ``templates/recipe_template.py``: the
``KITCHENOS_API_BASE`` env var, defaulting to the tailnet host. Change the host
in one place (env) and regenerate.
"""

import os
from typing import Optional

# Same default as templates/recipe_template.py — a stable Tailscale MagicDNS
# hostname, never a raw 100.x IP (IPs churn; MagicDNS names don't).
DEFAULT_API_BASE = "http://chases-mac-mini.taila69703.ts.net:5001"

NOTE_FILENAME = "KitchenOS Web.md"
NOTE_SUBDIR = "Dashboards"

# (emoji, title, route path, one-line description). Grouped by section below.
SECTIONS = [
    (
        "Plan & cook",
        [
            ("🍳", "Meal Planner", "/meal-planner",
             "drag recipes onto the week, set cook scale, place servings in "
             "slots / freezer / trash, and read the daily macro totals row"),
            ("📅", "This week's meal plan", "/current/meal-plan",
             "the rendered weekly plan"),
            ("🛒", "This week's shopping list", "/current/shopping-list",
             "consolidated, inventory-aware, grouped by store aisle"),
        ],
    ),
    (
        "Nutrition",
        [
            ("🥗", "Nutrition Review", "/nutrition-review",
             "fix bad USDA matches worst-coverage-first; every fix teaches the "
             "resolver vault-wide"),
        ],
    ),
    (
        "System",
        [
            ("📊", "System Health", "/system-health",
             "services, pipeline status, and recent extraction runs"),
        ],
    ),
]


def base_url() -> str:
    """The web base URL for links, from KITCHENOS_API_BASE (tailnet default)."""
    return os.environ.get("KITCHENOS_API_BASE", DEFAULT_API_BASE).rstrip("/")


def render_markdown(base: Optional[str] = None) -> str:
    """Render the 'KitchenOS Web.md' note. Pure — no I/O."""
    base = (base if base is not None else base_url()).rstrip("/")
    lines = [
        "---",
        "type: web-dashboard",
        "---",
        "",
        "# 📱 KitchenOS on the Web",
        "",
        "> ⚠️ **Generated** — these links open the KitchenOS web app over "
        "Tailscale, so they work from any device on the tailnet (Mac, iPad, "
        "iPhone). Do not edit here; regenerate with "
        "`scripts/generate_web_dashboard.py`.",
        "",
    ]
    for section_title, items in SECTIONS:
        lines += [f"## {section_title}", ""]
        for emoji, title, path, desc in items:
            lines.append(f"- {emoji} **[{title}]({base}{path})** — {desc}")
        lines.append("")

    lines += [
        "> 💡 A recipe's own web page (live ingredient scaling + macros) opens "
        "from its card in the Meal Planner or the **Open in KitchenOS** button "
        "on the recipe note.",
        "",
        "---",
        f"*Base URL: `{base}` — set `KITCHENOS_API_BASE` and regenerate to "
        "change it.*",
    ]
    return "\n".join(lines) + "\n"


def write_note() -> "object":
    """Regenerate 'Dashboards/KitchenOS Web.md'. Returns its path."""
    from lib import paths

    path = paths.vault_root() / NOTE_SUBDIR / NOTE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(), encoding="utf-8")
    return path
