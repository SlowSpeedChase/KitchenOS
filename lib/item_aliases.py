"""Raw receipt string → canonical item name mapping.

``config/item_aliases.json`` maps lowercased raw receipt strings (e.g.
"hcf bnls sknls brst") to canonical names ("chicken breast"). The Ollama
extraction prompt proposes a canonical name per line; this cache makes the
mapping stable across receipts and hand-correctable in a text editor —
a saved alias always wins over the model's suggestion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "item_aliases.json"


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
        return aliases[key]
    canonical = (suggested or "").lower().strip() or key
    if key and canonical != key:
        aliases[key] = canonical
        save_aliases(aliases)
    return canonical
