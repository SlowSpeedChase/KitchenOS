"""Raw receipt string → canonical item name mapping.

``config/item_aliases.json`` maps lowercased raw receipt strings (e.g.
"hcf bnls sknls brst") to canonical names ("chicken breast"). The Ollama
extraction prompt proposes a canonical name per line; this cache makes the
mapping stable across receipts and hand-correctable in a text editor —
a saved alias always wins over the model's suggestion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "item_aliases.json"

# "Fresh" is a retail descriptor (vs. frozen/canned), not part of an item's
# identity — HEB stamps it on produce ("Fresh Cilantro"). Strip it so
# "fresh cilantro" and "cilantro" canonicalize to the same name and merge.
_FRESH_RE = re.compile(r"\bfresh\b", re.IGNORECASE)


def strip_fresh(name: str) -> str:
    """Drop the standalone 'fresh' descriptor from a canonical name.

    'fresh cilantro' -> 'cilantro'. Collapses leftover whitespace/commas and
    never returns empty (falls back to the original if 'fresh' was the whole
    name).
    """
    cleaned = _FRESH_RE.sub("", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    return cleaned or name


def load_aliases() -> dict:
    if not ALIASES_PATH.exists():
        return {}
    try:
        data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_aliases(aliases: dict) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALIASES_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(dict(sorted(aliases.items())), indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(ALIASES_PATH)


def canonicalize(raw_name: str, suggested: Optional[str]) -> str:
    """Resolve a raw receipt string to its canonical name.

    Priority: saved alias > model suggestion (which gets cached) >
    cleaned lowercase raw string.
    """
    key = (raw_name or "").lower().strip()
    aliases = load_aliases()
    if key in aliases:
        return strip_fresh(aliases[key])
    canonical = strip_fresh((suggested or "").lower().strip() or key)
    if key and canonical != key:
        aliases[key] = canonical
        save_aliases(aliases)
    return canonical
