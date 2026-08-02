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

from lib import cook_sweep, verdict_nudge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent, send nothing")
    ap.add_argument("--no-sweep", action="store_true",
                    help="skip the assumed-cook sweep; only send the nudge")
    args = ap.parse_args()

    # Sweep first: a cook nobody marked is still a cook that happened, and the
    # nudge below asks about cooks whose day has passed — so without this it
    # would be asking "how was it?" about rows the rest of the system still
    # believes were never made. See lib/cook_sweep for why the plan is treated
    # as the record.
    if not args.no_sweep and not args.dry_run:
        result = cook_sweep.sweep()
        if result["marked"]:
            shown = ", ".join(result["marked"][:5])
            more = "…" if len(result["marked"]) > 5 else ""
            print(f"Swept {len(result['marked'])} assumed cook(s): {shown}{more}")
            print(f"  pantry spent for {result['consumed']}, "
                  f"{result['failed']} failed")
        else:
            print("Nothing to sweep — no past cooks left unmarked.")
    elif args.dry_run:
        due = cook_sweep.due_cooks()
        print(f"[dry run] would sweep {len(due)} assumed cook(s): "
              f"{', '.join(c['recipe'] for c in due[:5])}")

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
