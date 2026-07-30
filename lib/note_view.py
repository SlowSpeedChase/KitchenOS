"""Render KitchenOS's own generated vault notes as phone-readable HTML.

`/current/meal-plan` and `/current/shopping-list` used to 302 to
``obsidian://open?vault=…``. From a phone browser that either dead-ends or ejects
you into another app, so two of the six "Plan & cook" entries were unusable on the
device this project exists for. They render here instead, keeping an explicit
"Open in Obsidian" link for desktop use.

This is **not** a general Markdown renderer and must not grow into one — KitchenOS
has exactly one runtime dependency (Flask) and adding a Markdown library to display
two files we generate ourselves would be a poor trade. It handles the narrow syntax
that `templates/shopping_list_template.py` and `templates/meal_plan_template.py`
actually emit: ATX headings, task-list items, blockquotes, wikilinks, and the
```button fence. Anything else falls through as an escaped paragraph, which is the
right failure: unknown syntax shows up as visible text rather than vanishing.

Checkbox state is rendered **read-only, exactly as the note has it**. Making the
boxes tickable in the browser would create a second source of truth for what's
already in the cart, diverging from the note the moment either side is touched —
and "the vault note is the truth" is a load-bearing invariant here.
"""

from __future__ import annotations

import re
from html import escape
from typing import Optional
from urllib.parse import quote

_H = re.compile(r"^(#{1,6})\s+(.*)$")
_TASK = re.compile(r"^\s*-\s+\[( |x|X)\]\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_FENCE = re.compile(r"^```(\w*)\s*$")


def _inline(text: str) -> str:
    """Escape a line, then re-introduce the inline syntax we support.

    Order matters: escape first so note content can never inject markup, and only
    then substitute wikilinks — which become real recipe links, so a planned meal
    is one tap from the recipe that makes it.
    """
    out = escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)

    def link(m: re.Match) -> str:
        target, label = m.group(1), m.group(2) or m.group(1)
        return f'<a class="wl" href="/recipe/{quote(target)}">{label}</a>'

    # The pattern runs against already-escaped text; [[ ]] and | survive escaping
    # untouched, so the match is unaffected.
    return _WIKILINK.sub(link, out)


def render(markdown: str, week: Optional[str] = None) -> str:
    """Render one generated note as an HTML fragment."""
    html: list[str] = []
    in_list = False
    fence: Optional[str] = None
    fenced: list[str] = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in markdown.splitlines():
        line = raw.rstrip()

        # --- fenced blocks ---
        m = _FENCE.match(line)
        if m and fence is None:
            close_list()
            fence = m.group(1) or "text"
            fenced = []
            continue
        if fence is not None:
            if line.strip() == "```":
                html.append(_render_fence(fence, fenced, week))
                fence = None
            else:
                fenced.append(line)
            continue

        if not line.strip():
            close_list()
            continue

        m = _H.match(line)
        if m:
            close_list()
            # The note's own H1 is dropped: the page already has a title, and two
            # competing headings at the top just wastes the phone's first screen.
            level = len(m.group(1))
            if level > 1:
                html.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        m = _TASK.match(line)
        if m:
            if not in_list:
                html.append('<ul class="tasks">')
                in_list = True
            done = m.group(1).lower() == "x"
            cls = " class=\"done\"" if done else ""
            box = "☑" if done else "☐"
            html.append(f'<li{cls}><span class="box">{box}</span>'
                        f'<span>{_inline(m.group(2))}</span></li>')
            continue

        m = _QUOTE.match(line)
        if m:
            close_list()
            html.append(f'<blockquote>{_inline(m.group(1))}</blockquote>')
            continue

        m = _BULLET.match(line)
        if m:
            if not in_list:
                html.append('<ul class="tasks">')
                in_list = True
            html.append(f'<li><span>{_inline(m.group(1))}</span></li>')
            continue

        close_list()
        html.append(f"<p>{_inline(line)}</p>")

    close_list()
    if fence is not None:                      # unterminated fence
        html.append(_render_fence(fence, fenced, week))
    return "\n".join(html)


def _render_fence(kind: str, lines: list[str], week: Optional[str]) -> str:
    """Render a fenced block. ``button`` blocks become working HTML buttons.

    The meal-plan note carries an Obsidian ``button`` block whose action is
    ``kitchenos://generate-shopping-list?week=…``. That custom scheme is handled by
    a macOS helper app which no longer exists after the machine rebuild — and being
    macOS-only, it never worked from a phone at all. That single dead trigger is why
    no shopping list has been generated since W27. Rendered here it becomes a plain
    HTTP button that works from any device.
    """
    if kind == "button":
        action = ""
        for ln in lines:
            if ln.strip().startswith("action "):
                action = ln.strip()[len("action "):].strip()
        m = re.search(r"generate-shopping-list\?week=([\w-]+)", action)
        wk = m.group(1) if m else (week or "")
        if wk:
            return (f'<button class="gen" data-week="{escape(wk)}">'
                    f'Generate shopping list</button>')
        return ""
    return f"<pre>{escape(chr(10).join(lines))}</pre>"
