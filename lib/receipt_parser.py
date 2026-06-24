"""Parse HEB receipt emails into trip + purchase records.

Pipeline: HTML email body → plain text (BeautifulSoup) → Ollama structured
extraction (mistral:7b, same pattern as recipe_sources.py) → validation
(line totals must sum to the receipt total within tolerance) → purchase
dicts ready for inventory_db.record_trip().
"""
from __future__ import annotations

import json
from datetime import date
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

from lib.inventory import normalize_category
from lib.item_aliases import canonicalize
from prompts.receipt_extraction import build_receipt_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"

PURCHASE_CATEGORIES = (
    "produce", "dairy", "meat", "seafood", "pantry", "frozen",
    "bakery", "beverages", "household", "fee", "other",
)

def email_to_text(html: str) -> str:
    """Flatten email HTML to readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def to_cents(value) -> Optional[int]:
    """Dollars (float/str) → integer cents. None passes through."""
    if value is None:
        return None
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return None


def _call_ollama(prompt: str) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt,
              "stream": False, "format": "json"},
        timeout=180,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def parse_receipt_text(
    text: str, ollama_call: Callable[[str], str] = _call_ollama
) -> dict:
    """Extract structured receipt data. Raises on Ollama/JSON failure."""
    raw = ollama_call(build_receipt_prompt(text))
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("receipt JSON is not an object")
    return parsed


def validate_receipt(parsed: dict) -> tuple[bool, list[str]]:
    """Sanity-check a parsed receipt. Returns (ok, problems)."""
    problems: list[str] = []
    d = parsed.get("date")
    if not d:
        problems.append("missing date")
    else:
        try:
            date.fromisoformat(str(d))
        except ValueError:
            problems.append(f"date not in YYYY-MM-DD format: {d!r}")
    items = parsed.get("items") or []
    if not items:
        problems.append("no line items")
    for it in items:
        if not it.get("raw_name"):
            problems.append("item missing raw_name")
            break

    total_cents = to_cents(parsed.get("total"))
    if total_cents is None:
        problems.append("missing or unparseable total")
    elif items:
        line_sum = sum(to_cents(it.get("line_total")) or 0 for it in items)
        tolerance = max(100, abs(total_cents) // 50)  # $1 or 2%
        if abs(line_sum - total_cents) > tolerance:
            problems.append(
                f"line totals ({line_sum}c) don't match total ({total_cents}c)"
            )
    return (not problems, problems)


def build_purchases(parsed: dict) -> list[dict]:
    """Convert parsed items into purchase rows (cents, canonical names)."""
    purchases = []
    for it in parsed.get("items") or []:
        raw = (it.get("raw_name") or "").strip()
        if not raw:
            continue
        cat = (it.get("category") or "other").lower().strip()
        if cat not in PURCHASE_CATEGORIES:
            cat = normalize_category(cat)
        purchases.append({
            "raw_name": raw,
            "canonical_name": canonicalize(raw, it.get("canonical_name")),
            "quantity": it.get("quantity") if it.get("quantity") is not None else 1,
            "unit": (it.get("unit") or "ct").lower().strip() or "ct",
            "unit_price_cents": to_cents(it.get("unit_price")),
            "total_cents": to_cents(it.get("line_total")),
            "category": cat,
        })
    return purchases


def default_location(category: str) -> str:
    """Category-only storage-location fallback.

    Kept for callers without an item name; the item-aware path uses
    ``lib.storage_locations.resolve_location(name, category)`` directly.
    Delegates to the JSON table so there's one source of truth.
    """
    from lib.storage_locations import resolve_location

    return resolve_location("", category)
