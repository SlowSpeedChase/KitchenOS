#!/usr/bin/env python3
"""What to buy so every craving lane has a buffer food ready.

The Meal System note's rule is one per row stocked, because a buffer food only
works if it is already in the house when the urge hits. This reports which
lanes are bare and can push the shortfall to Apple Reminders.

Deliberately a *stock* check, not a recipe check: most of the buffer menu is an
assembly ("apple + nut butter", "handful of pistachios"), so acquiring more
recipes would not move it. See lib/buffer_gaps.py.

Usage:
    .venv/bin/python scripts/buffer_restock.py                # report
    .venv/bin/python scripts/buffer_restock.py --to-reminders # add to Shopping
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from lib import buffer_gaps, profile as profile_mod  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to-reminders", action="store_true",
                    help="add the shortfall to the Shopping list")
    ap.add_argument("--list", default="Shopping", help="Reminders list name")
    args = ap.parse_args()

    prof = profile_mod.load_profile()
    if prof is None:
        print(f"No {profile_mod.PROFILE_FILENAME} in the vault.", file=sys.stderr)
        return 1

    readiness = buffer_gaps.lane_readiness(prof)
    for lane, r in readiness.items():
        status = "; ".join(r["ready"][:3]) if r["ready"] else "— nothing ready —"
        print(f"{lane}:\n    {status}")

    bare = buffer_gaps.bare_lanes(readiness)
    blocks = buffer_gaps.block_gaps(prof)

    print()
    if not bare:
        print("Every craving lane has at least one buffer food ready. ✓")
    else:
        print(f"Bare lanes: {', '.join(bare)}")

    targets = buffer_gaps.shopping_targets(readiness)
    if targets:
        print("\nTo light up the bare lanes:")
        for t in targets:
            print(f"  - {t}")

    if blocks:
        print("\nBuilding blocks not currently stocked:")
        for category, items in blocks.items():
            print(f"  {category}: {', '.join(items)}")

    if args.to_reminders and targets:
        from lib.reminders import add_to_reminders
        add_to_reminders(targets, list_name=args.list)
        print(f"\nAdded {len(targets)} item(s) to Reminders → {args.list}")
    elif args.to_reminders:
        print("\nNothing to add — no bare lanes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
