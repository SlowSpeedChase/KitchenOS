#!/usr/bin/env python3
"""Read-only: shopping-list disposition counts per week against the live pantry.

Usage: .venv/bin/python scripts/measure_shopping_list.py 2026-W45 2026-W46 2026-W48 [--show on_hand,credited]
Never writes inventory or notes: generate_shopping_list only computes.
"""
import os
import sys
from collections import Counter

os.environ.setdefault("KITCHENOS_NO_LLM", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import pantry as pantry_module  # noqa: E402
from lib.shopping_list_generator import generate_shopping_list  # noqa: E402


def main(argv):
    show = set()
    if "--show" in argv:
        i = argv.index("--show")
        show = set(argv[i + 1].split(","))
        argv = argv[:i] + argv[i + 2:]
    pan = pantry_module.load_pantry()
    print("| Week | Lines | buy | credited | on_hand | review |")
    print("|---|---|---|---|---|---|")
    detail = []
    for week in argv:
        lines = generate_shopping_list(week, pantry=pan).get("lines") or []
        c = Counter(line["status"] for line in lines)
        print(f"| {week} | {len(lines)} | {c['buy']} | {c['credited']} | {c['on_hand']} | {c['review']} |")
        for line in lines:
            if line["status"] in show:
                m = line.get("matched_inventory") or {}
                detail.append(f"{week} {line['status']:8} {line['display']} <- {m.get('item')} {m.get('amount')} {m.get('unit')}")
    print("\n".join(detail))


if __name__ == "__main__":
    main(sys.argv[1:])
