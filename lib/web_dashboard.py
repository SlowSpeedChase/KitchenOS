"""Generate the 'KitchenOS Web.md' vault note and the '/' home-page HTML fragment.

The note is a regenerated read-only view (like ``Inventory.md`` / ``Use It Up.md``)
whose only job is to be a tap-anywhere launcher for the KitchenOS web app. Every
link points at the configured web base URL — a stable Tailscale MagicDNS hostname
by default — so the same note works from any device on the tailnet (Mac, iPad,
iPhone), not just localhost on the server. ``render_html()`` renders the same
SECTIONS registry as the HTML fragment served at ``/``, the in-browser counterpart
to the vault note.

Base URL resolution matches ``templates/recipe_template.py``: the
``KITCHENOS_API_BASE`` env var, defaulting to the tailnet host. Change the host
in one place (env) and regenerate.
"""

import os
from html import escape
from typing import Optional

# Same default as templates/recipe_template.py — a stable Tailscale MagicDNS
# hostname, never a raw 100.x IP (IPs churn; MagicDNS names don't).
DEFAULT_API_BASE = "http://chases-mac-mini.taila69703.ts.net:5001"

NOTE_FILENAME = "KitchenOS Web.md"
NOTE_SUBDIR = "Dashboards"

# The registry *root* — deliberately not a SECTIONS entry, because the home page
# renders SECTIONS and would otherwise list itself. Anything that walks SECTIONS
# to build a link list must add this explicitly (see scripts/sync_safari_bookmarks.py).
HOME = ("🏠", "KitchenOS Home", "/", "every page, one tap away")

# (emoji, title, route path, one-line description). Grouped by section below.
#
# This is the registry of *browsable* KitchenOS pages, and it has three consumers:
# the vault launcher note rendered below, ``render_html()`` for the '/' home page,
# and ``scripts/sync_safari_bookmarks.py``, which mirrors it into the Safari
# "KitchenOS" bookmarks folder. Adding a new HTML page route without adding it
# here fails ``tests/test_web_dashboard.py`` — pages that genuinely can't be
# bookmarked go in that test's ``NOT_BOOKMARKABLE`` set.
SECTIONS = [
    (
        "Plan & cook",
        [
            ("🗓️", "Plan your week", "/plan-week",
             "the Sunday front door: one page, three steps — fill the week, "
             "review nutrition, print it for the fridge"),
            ("🍳", "Meal Planner", "/meal-planner",
             "drag recipes onto the week, set cook scale, place servings in "
             "slots / freezer / trash, and read the daily macro totals row"),
            ("🥘", "Cook Now", "/cook-now",
             "what you could cook right now, ranked by how much you already "
             "have; filter by meal type to drop desserts"),
            ("📅", "This week's meal plan", "/current/meal-plan",
             "the rendered weekly plan"),
            ("🛒", "This week's shopping list", "/current/shopping-list",
             "consolidated, inventory-aware, grouped by store aisle"),
            ("🖨️", "Print this week", "/print/week",
             "one printable page — the week's plan, macros vs targets, shopping "
             "list, and do-ahead prep, for the fridge"),
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
        "Stock",
        [
            ("📸", "Paste a Receipt", "/receipt-paste",
             "photograph an HEB receipt in the Claude app, paste the JSON it "
             "produces, preview, and file it into inventory"),
            ("🧊", "Inventory Review", "/review",
             "what's on hand, soonest-expiring first; remove an item or push "
             "its date out by 3 / 7 days"),
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
    emoji, title, path, desc = HOME
    lines += [f"- {emoji} **[{title}]({base}{path})** — {desc}", ""]
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


def render_html(base: str = "") -> str:
    """Render SECTIONS as an HTML fragment for the home page. Pure — no I/O.

    ``base`` defaults to empty so the served page emits relative links and you
    stay on whatever host you loaded it from. ``render_markdown`` needs absolute
    tailnet URLs because the vault note is opened from other devices; a page
    already being served over the tailnet does not.
    """
    base = base.rstrip("/")
    out = []
    for section_title, items in SECTIONS:
        out.append(f"<section><h2>{escape(section_title)}</h2>")
        for emoji, title, path, desc in items:
            out.append(
                f'<a class="card" href="{escape(base + path)}">'
                f'<span class="emoji">{escape(emoji)}</span>'
                f'<span class="text"><span class="title">{escape(title)}</span>'
                f'<span class="desc">{escape(desc)}</span></span></a>'
            )
        out.append("</section>")
    return "\n".join(out)


def write_note() -> "object":
    """Regenerate 'Dashboards/KitchenOS Web.md'. Returns its path."""
    from lib import paths

    path = paths.vault_root() / NOTE_SUBDIR / NOTE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(), encoding="utf-8")
    return path
