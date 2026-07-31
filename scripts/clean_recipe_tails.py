#!/usr/bin/env python3
"""Strip duplicated footers and stray YAML fragments from recipe bodies.

A past template-refresh bug appended its output instead of replacing it, so
some recipes accumulated repeated "*Extracted from ...*" footers plus loose
``key: null`` YAML lines sitting in the markdown body (where Obsidian renders
them as literal text and Dataview ignores them).

The recipe template puts the source footer last, so everything after the FIRST
footer line is duplicated tail. This truncates there — but only for files where
the tail is provably junk (footer repeats and/or stray YAML keys), and never
when the tail contains prose the author may have written.

Usage:
    .venv/bin/python scripts/clean_recipe_tails.py --dry-run
    .venv/bin/python scripts/clean_recipe_tails.py
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from lib import paths
from lib.backup import create_backup

FOOTER_RE = re.compile(r"^\*(?:Extracted|Imported) from ", re.M)

# Keys the buggy refresh spilled into the body.
STRAY_KEY_RE = re.compile(
    r"^(?:serving_size|calories|nutrition_protein|carbs|fat|nutrition_source"
    r"|meal_occasion|seasonal_ingredients|peak_months|nutrition_calories"
    r"|nutrition_carbs|nutrition_fat|servings|prep_time|cook_time"
    r"|total_time|difficulty|cuisine|protein|dish_type|dietary):",
    re.M,
)

FM_RE = re.compile(r"^---\n.*?\n---\n", re.S)


# A tail line is safe to delete only if it matches one of these. Anything else
# — a note, a heading, a stray sentence — aborts the cleanup for that file.
JUNK_LINE_PATTERNS = [
    r"---+",                                   # horizontal rule / fence
    r"\*(?:Extracted|Imported) from .*\*",     # duplicated source footer
    r"[A-Za-z_][A-Za-z0-9_]*:\s*"              # "key:" with a scalar or inline list
    r"(?:null|\[[^\]]*\]|\"[^\"]*\"|'[^']*'|[-\d.,: ]*)",
]
_JUNK_LINE_RE = re.compile(
    r"^(?:" + "|".join(f"(?:{p})" for p in JUNK_LINE_PATTERNS) + r")$"
)


def tail_is_junk(tail: str) -> bool:
    """True when every non-blank line after the first footer is throwaway."""
    lines = [ln.strip() for ln in tail.splitlines()]
    return all(not ln or _JUNK_LINE_RE.match(ln) for ln in lines)


def clean(text: str):
    m = FM_RE.match(text)
    if not m:
        return None
    fm_block, body = text[: m.end()], text[m.end():]

    footers = list(FOOTER_RE.finditer(body))
    strays = STRAY_KEY_RE.findall(body)
    if len(footers) <= 1 and not strays:
        return None

    first = footers[0] if footers else None
    if first is None:
        return None

    line_end = body.find("\n", first.start())
    keep_to = len(body) if line_end == -1 else line_end + 1
    tail = body[keep_to:]
    if not tail.strip():
        return None
    if not tail_is_junk(tail):
        return ("SKIP", len(footers), len(strays), tail.strip()[:100])

    return ("CLEAN", len(footers), len(strays),
            fm_block + body[:keep_to].rstrip() + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cleaned = skipped = 0
    for path in sorted(paths.recipes_dir().glob("*.md")):
        text = path.read_text(encoding="utf-8")
        res = clean(text)
        if not res:
            continue
        kind, n_foot, n_stray, payload = res
        if kind == "SKIP":
            skipped += 1
            print(f"  SKIP  {path.name} — tail has real content: {payload!r}")
            continue
        removed = len(text) - len(payload)
        cleaned += 1
        print(f"  CLEAN {path.name} — {n_foot} footers, {n_stray} stray keys, "
              f"-{removed} bytes")
        if not args.dry_run:
            create_backup(path)
            path.write_text(payload, encoding="utf-8")

    print(f"\n{'(dry run) ' if args.dry_run else ''}cleaned={cleaned} skipped={skipped}")


if __name__ == "__main__":
    main()
