"""Parse Central Texas Farmers Co-op CSA newsletters into produce items.

The co-op emails a weekly "Week N(A/B)" newsletter (from
info@centraltexasfarmers.com, sent via Klaviyo) listing the actual contents of
each share tier. Unlike a store receipt there are no prices — just a produce
list under a tier heading. We extract the items for the subscriber's tier so
they land in inventory and feed the Use-It-Up / waste features.

Deterministic — no LLM needed. ``receipt_parser.email_to_text`` flattens the
Klaviyo HTML to one element per line, so the share section is cleanly structured:

    For this week's share we have:
    Individual            <- tier heading
    Storage Onions
    Purple Potatoes
    ...
    Bountiful             <- next tier heading (ends Individual's list)
    ...
    As Always....         <- section terminator

Config (tier, week_letter, sender) lives in ``config/csa.json``; only the
subscriber's tier on their pickup weeks (Week A or Week B) is ingested.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from lib.receipt_parser import email_to_text

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "csa.json"

# Share tiers the co-op offers; the heading line names one of these.
TIERS = ("Individual", "Bountiful")

# Lines that end a tier's item list (the next tier, or a following section).
_STOP_PHRASES = (
    "as always", "this week's contributing", "contributing farms",
    "this week's farm", "farm spotlight",
)

# "Week 13(A)", "Week 9(A) Newsletter", "Week 1A Newsletter" → (number, letter)
_SUBJECT_RE = re.compile(r"week\s*(\d+)\s*\(?\s*([ab])\s*\)?", re.I)


def load_config() -> dict:
    """CSA settings from config/csa.json (tier, week_letter, sender, …)."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_week_label(subject: str) -> Optional[dict]:
    """Parse 'Week 13(A)' → {'number': 13, 'letter': 'A', 'label': '13(A)'}."""
    m = _SUBJECT_RE.search(subject or "")
    if not m:
        return None
    num, letter = int(m.group(1)), m.group(2).upper()
    return {"number": num, "letter": letter, "label": f"{num}({letter})"}


def _is_stop(line: str) -> bool:
    low = line.strip().lower()
    return any(p in low for p in _STOP_PHRASES)


def parse_share_items(text_or_html: str, tier: str = "Individual") -> list[str]:
    """Produce item names for ``tier`` from a newsletter (HTML or flat text).

    Returns the items listed under the tier heading, stopping at the next tier
    or the end of the share section. Empty list if the tier isn't found.
    """
    text = text_or_html or ""
    if "<" in text and ">" in text:
        text = email_to_text(text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    tier_low = tier.lower()
    other_tiers = {t.lower() for t in TIERS if t.lower() != tier_low}

    start = None
    for i, ln in enumerate(lines):
        if ln.lower() == tier_low:
            start = i + 1
            break
    if start is None:
        return []

    items: list[str] = []
    for ln in lines[start:]:
        if ln.lower() in other_tiers or _is_stop(ln):
            break
        items.append(ln)
    return items


def parse_newsletter(subject: str, html: str, tier: str = "Individual") -> dict:
    """Full parse → {'week', 'week_letter', 'tier', 'items'}."""
    week = parse_week_label(subject)
    return {
        "week": week["label"] if week else None,
        "week_letter": week["letter"] if week else None,
        "tier": tier,
        "items": parse_share_items(html, tier),
    }
