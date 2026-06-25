#!/usr/bin/env python3
"""Find and archive duplicate recipe files in the Obsidian vault.

Two recipe files are duplicates when they share a `source_url`, or when one is
an Obsidian Sync conflict copy of the other (`X 2.md` next to `X.md`). Within a
duplicate group one file is kept (the most canonical/complete copy) and the rest
are MOVED — never deleted — to `_Archive/custom-format-dupes/` so the recursive
"Recipes" Base/Dataview queries stop showing duplicates.

Keeper preference, in order:
  1. Action buttons point at a stable Tailscale hostname, not a raw 100.x IP.
  2. More complete nutrition (more non-null nutrition_* fields).
  3. Canonical filename (no trailing " 2"/" 3" Sync-conflict suffix).
  4. Most recently modified.

Usage:
    python scripts/dedupe_recipes.py            # dry-run: report only
    python scripts/dedupe_recipes.py --apply    # move dupes to _Archive
"""
import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import paths  # noqa: E402
from lib.recipe_parser import parse_recipe_file  # noqa: E402

CONFLICT_SUFFIX = re.compile(r" \d+\.md$")
RAW_IP_HOST = re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}")
NUTRITION_FIELDS = (
    "nutrition_calories", "nutrition_protein", "nutrition_carbs", "nutrition_fat",
)


def _canonical_stem(name: str) -> str:
    """'Queso Dip Recipe 2.md' -> 'queso dip recipe' (collapses conflict suffix)."""
    base = CONFLICT_SUFFIX.sub(".md", name)
    return base[:-3].strip().lower()


def _has_value(v) -> bool:
    return v not in (None, "", "null")


def _keeper_score(path: Path):
    """Higher tuple sorts first = better keeper."""
    try:
        parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        body = parsed.get("body", "")
    except Exception:
        fm, body = {}, ""
    hostname_buttons = 0 if RAW_IP_HOST.search(body) else 1
    nutrition_complete = sum(1 for f in NUTRITION_FIELDS if _has_value(fm.get(f)))
    canonical_name = 0 if CONFLICT_SUFFIX.search(path.name) else 1
    return (hostname_buttons, nutrition_complete, canonical_name, path.stat().st_mtime)


def _source_url(path: Path) -> str:
    try:
        fm = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
        u = fm.get("source_url", "")
        return u if _has_value(u) else ""
    except Exception:
        return ""


def find_duplicate_groups(recipes_dir: Path) -> list[list[Path]]:
    """Group recipe files that are duplicates of one another."""
    files = [p for p in recipes_dir.glob("*.md") if not p.name.startswith(".")]
    by_key: dict = defaultdict(list)
    for p in files:
        url = _source_url(p)
        # Same source_url is the strongest signal; fall back to name-collision
        # so conflict copies of un-sourced recipes are still caught.
        by_key[("url", url) if url else ("name", _canonical_stem(p.name))].append(p)
    return [g for g in by_key.values() if len(g) > 1]


def dedupe(recipes_dir: Path, archive: Path, apply: bool) -> list[tuple[Path, Path]]:
    """Return list of (loser, keeper). Moves losers to archive when apply=True."""
    moves = []
    dest = archive / "custom-format-dupes"
    for group in find_duplicate_groups(recipes_dir):
        ranked = sorted(group, key=_keeper_score, reverse=True)
        keeper, losers = ranked[0], ranked[1:]
        for loser in losers:
            moves.append((loser, keeper))
            if apply:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(loser), str(dest / loser.name))
    return moves


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="move dupes (default: dry-run)")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()
    moves = dedupe(recipes_dir, paths.archive_dir(), apply=args.apply)

    if not moves:
        print("No duplicate recipes found.")
        return 0

    verb = "Archived" if args.apply else "Would archive"
    print(f"{verb} {len(moves)} duplicate file(s):")
    for loser, keeper in sorted(moves, key=lambda m: m[0].name):
        print(f"  {loser.name}\n      -> keep: {keeper.name}")
    if not args.apply:
        print("\nRe-run with --apply to move them to _Archive/custom-format-dupes/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
