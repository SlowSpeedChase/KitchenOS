#!/usr/bin/env python3
"""Regenerate the 'Dashboards/On Track.md' vault note.

Summarises the cooking that actually happened — from the serving ledger, not
from meal plans — against the personal food profile in `My Meal System.md`.
Regenerates automatically whenever a cook is logged; run this by hand to
refresh it after tagging recipes with `backfill_fit.py`. See lib/on_track.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import on_track  # noqa: E402


def main() -> int:
    summary = on_track.summarize()
    gaps = on_track.library_gaps()
    path = on_track.write_note()
    print(f"Wrote {path}")
    print(f"  {summary['cooks']} cooks since {summary['since']}"
          f" ({summary['verdicts']} judged)")
    print(f"  {gaps['tagged']}/{gaps['recipes']} recipes assessed,"
          f" {gaps['buffer_candidates']} buffer candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
