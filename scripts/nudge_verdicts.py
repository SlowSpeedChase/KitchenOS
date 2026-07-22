#!/usr/bin/env python3
"""Ask "how did that go?" about a recent cook that has no verdict yet.

The one recurring cue in the system. Runs unattended from
`com.kitchenos.verdict-nudge` and stays silent unless there is something to
answer — see lib/verdict_nudge.py for why that restraint matters.

Usage:
    .venv/bin/python scripts/nudge_verdicts.py            # deliver if pending
    .venv/bin/python scripts/nudge_verdicts.py --dry-run  # show, send nothing
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from lib import verdict_nudge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent, send nothing")
    args = ap.parse_args()

    items = verdict_nudge.pending()
    if not items:
        print("Nothing to ask about — no unjudged cooks in the last "
              f"{verdict_nudge.RECENT_DAYS} days.")
        return 0

    text = verdict_nudge.message(items)
    if args.dry_run:
        print(f"[dry run] would add to Reminders → {verdict_nudge.REMINDER_LIST}:")
        print(f"  {text}")
        print(f"  ({len(items)} pending: "
              f"{', '.join(i['recipe'] for i in items[:5])})")
        return 0

    return 0 if verdict_nudge.run() else 1


if __name__ == "__main__":
    sys.exit(main())
