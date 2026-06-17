#!/usr/bin/env python3
"""Generate the Price Tracker dashboard in the Obsidian vault.

Usage:
    .venv/bin/python generate_price_dashboard.py
    .venv/bin/python generate_price_dashboard.py --dry-run
"""
import argparse

from dotenv import load_dotenv

load_dotenv()

from lib.price_dashboard import generate_dashboard, save_dashboard  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print markdown without saving")
    args = ap.parse_args()
    if args.dry_run:
        print(generate_dashboard())
    else:
        path = save_dashboard()
        print(f"Wrote {path}")
