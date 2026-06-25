#!/usr/bin/env python3
"""Bulk-add inventory from a pasted markdown table (preview-then-commit).

Usage:
    python paste_inventory.py table.md            # preview only
    python paste_inventory.py table.md --commit   # add to inventory
    pbpaste | python paste_inventory.py -         # read the table from stdin

Table columns (only Item is required; headers are case-insensitive):
    | Item | Qty | Unit | Category | Location | Expires | Notes |
Missing location auto-resolves and missing expiry auto-fills, same as the
email/photo receipt paths.
"""
import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from lib import receipt_paster


def main():
    parser = argparse.ArgumentParser(description="Bulk-add inventory from a markdown table")
    parser.add_argument("file", help="Markdown file with the table, or - for stdin")
    parser.add_argument("--commit", action="store_true", help="Persist (default previews only)")
    args = parser.parse_args()

    markdown = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()

    if args.commit:
        result = receipt_paster.commit(markdown)
        for w in result.get("warnings", []):
            print(f"⚠️  {w}", file=sys.stderr)
        print(f"Added {result['added']}, merged {result['merged']}, total {result['total']}")
    else:
        prev = receipt_paster.preview(markdown)
        for w in prev["warnings"]:
            print(f"⚠️  {w}", file=sys.stderr)
        print(f"Preview — {prev['count']} item(s):")
        for it in prev["items"]:
            exp = f", expires {it['expires']}" if it.get("expires") else ""
            print(f"  • {it['name']} — {it['quantity']} {it['unit']} "
                  f"[{it['category']}/{it['location']}]{exp}")
        if prev["count"]:
            print("\nRe-run with --commit to add.")


if __name__ == "__main__":
    main()
