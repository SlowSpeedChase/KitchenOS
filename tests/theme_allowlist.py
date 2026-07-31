"""The one shrinking list that drives the light/dark conversion.

Two tests read this module: ``tests/test_theme_tokens.py`` (static) and
``tests/e2e/test_dark_mode.py`` (browser). A template in ``UNCONVERTED``
is exempt from both. Every conversion commit removes exactly one entry,
and the work is finished when the set is empty — at which point the
``test_allowlist_is_temporary`` guard below stops being skipped.

Do not add an entry to buy time. The set only ever shrinks.
"""
from __future__ import annotations

import re

# A hex colour literal, and NOT a CSS id selector.
#
# A naive `#[0-9a-fA-F]{3,8}` matches `#add-week-status` (recipe_detail.html)
# and `#add-sub-recipe` (meal_planner.html) as the colour `#add`. A trailing
# \b does not help, because `-` is itself a word boundary — hence the explicit
# "no identifier character follows" lookahead.
#
# The length alternation matters on its own: an unanchored {3,8} accepts 5- and
# 7-digit runs, which is how review.html's invalid `#d3355` reads as a colour.
#
# A third case: HTML numeric character entities. api_server.py's Claude bar
# spells emoji as `&#127968;`, `&#128221;`, `&#129302;` — without a lookbehind
# `#127968` reads as a plausible six-digit hex colour. The `(?<!&)` rejects any
# `#` immediately preceded by `&`, leaving the entities alone.
HEX = re.compile(
    r'(?<!&)#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![0-9a-zA-Z_-])'
)

# CSS system colours. They adapt to light/dark on their own, which is exactly
# why they slip past a hex-only check — but they are the OS palette, not ours:
# GrayText is not --muted, and Canvas is pure white/black rather than the Dawn
# cream or Ink ground. A color-mix() against Canvas is wrong in both themes.
SYSTEM_COLOR = re.compile(r'\b(?:CanvasText|Canvas|GrayText)\b')

# `<meta name="theme-color">` cannot hold a var(), so these two literals are
# permanently legal — but only on a theme-color line.
THEME_COLOR_LITERALS = {"#f4ede3", "#0f1116"}

# Surfaces not yet converted. SHRINKS TO EMPTY.
#
# api_server.py held the Claude bar and six inline pages under the same
# mechanism; Task 4 converted it and removed its entry here.
UNCONVERTED: set[str] = {
    "meal_planner.html",
    "nutrition_review.html",
    "print_week.html",
    "receipt_paste.html",
    "recipe_card.html",
    "recipe_detail.html",
    "review.html",
    "system_health.html",
}

# One representative route per template, for the browser test. None means the
# template is not reachable as a standalone page.
#
# The two path-param entries carry a `{recipe}` placeholder that
# tests/e2e/test_dark_mode.py fills from the fixture vault.
TEMPLATE_ROUTES: dict[str, str | None] = {
    "home.html": "/",
    "prep.html": "/prep",
    "recent.html": "/recent",
    "note_view.html": "/current/meal-plan",
    "cook_now.html": "/cook-now",
    "plan_week.html": "/plan-week",
    "print_week.html": "/print/week",
    "recipe_card.html": "/recipe-card/{recipe}",
    "receipt_paste.html": "/receipt-paste",
    "system_health.html": "/system-health",
    "nutrition_review.html": "/nutrition-review",
    "review.html": "/review",
    "recipe_detail.html": "/recipe/{recipe}",
    "meal_planner.html": "/meal-planner",
}
