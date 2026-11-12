#!/usr/bin/env python3
"""Report every recipe planned for a week that contains a disliked ingredient.

Deterministic — a string match against the dislikes in `My Meal System.md`
(lib/dislike_guard.py), no model and no tokens. `--swaps` additionally asks
*local Ollama* for substitute ideas; it never edits a recipe file.

    .venv/bin/python scripts/scan_dislikes.py              # this ISO week
    .venv/bin/python scripts/scan_dislikes.py 2026-W46 --swaps
    .venv/bin/python scripts/scan_dislikes.py --all        # whole recipe library

Exit status is 1 when anything was flagged, so it can gate a script.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import dislike_guard, paths  # noqa: E402


def planned_recipes(week: str) -> list[str]:
    """Distinct recipe names on ``week``'s ledger, in plan order."""
    from lib import serving_ledger
    return list(dict.fromkeys(c["recipe"] for c in serving_ledger.cooks_for_week(week)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("week", nargs="?", help="ISO week id, e.g. 2026-W46 (default: this week)")
    ap.add_argument("--all", action="store_true", help="scan the whole recipe library")
    ap.add_argument("--swaps", action="store_true", help="ask local Ollama for substitutes")
    args = ap.parse_args(argv)

    dislikes = dislike_guard.current_dislikes()
    if not dislikes:
        print("No **Dislike:** bullet found in My Meal System.md — nothing to check.")
        return 0

    if args.all:
        names = sorted(p.stem for p in paths.recipes_dir().glob("*.md"))
        scope = "the recipe library"
    else:
        y, w, _ = date.today().isocalendar()
        week = args.week or f"{y}-W{w:02d}"
        names = planned_recipes(week)
        scope = week

    print(f"Dislikes: {', '.join(dislikes)}")
    flagged = 0
    profile_text = ""
    if args.swaps:
        from lib import profile as profile_mod
        p = profile_mod.load_profile()
        profile_text = p.prompt_context() if p else ""
    for name in names:
        hits = dislike_guard.recipe_hits(name, dislikes)
        if not hits:
            continue
        flagged += 1
        print(f"\n⚠️  {name}")
        swaps = {s["item"]: s for s in dislike_guard.suggest_swaps(hits, profile_text)} \
            if args.swaps else {}
        for h in hits:
            line = f"   - {h['item']}  [{h['dislike']}]"
            if h["item"] in swaps:
                s = swaps[h["item"]]
                line += f"\n       swap → {s['swap']}" + (f"  ({s['role']})" if s["role"] else "")
            print(line)
    print(f"\n{flagged} of {len(names)} recipe(s) in {scope} contain a dislike.")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
