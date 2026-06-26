#!/usr/bin/env python3
"""Ingest Central Texas Farmers Co-op CSA newsletters into inventory.

The co-op's weekly "Week N(A/B)" newsletter lists the produce in each share.
For the subscriber's tier (config/csa.json: ``tier``) on their pickup weeks
(``week_letter``), we add that produce to inventory so it flows into the
Use-It-Up / waste features. There are no prices, so a zero-total "delivery"
trip is recorded purely for dedup (record_trip skips duplicate source_ids).

Runs best-effort at the tail of the hourly receipt ingest; can also run alone:

    .venv/bin/python ingest_csa.py
    .venv/bin/python ingest_csa.py --dry-run
    .venv/bin/python ingest_csa.py --since-days 30
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv

load_dotenv()

from lib import csa_parser  # noqa: E402
from lib.email_fetcher import fetch_emails  # noqa: E402
from lib.inventory import InventoryItem, add_items  # noqa: E402
from lib.inventory_db import record_trip, trip_exists  # noqa: E402
from lib.storage_locations import resolve_location  # noqa: E402


def _delivery_date(payload: dict) -> str:
    """Pickup date (produce 'purchased' date) = the Wednesday of the share week.

    The newsletter goes out a few days before pickup (shares are delivered on
    Wednesdays), so we roll the send date forward to that Wednesday. Using the
    actual pickup day — not the earlier send day — keeps expiry windows honest.
    """
    raw = payload.get("date") or ""
    try:
        sent = parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return date.today().isoformat()
    # weekday(): Mon=0 … Wed=2 … Sun=6. Roll forward to the next Wednesday
    # (same day if already Wednesday).
    from datetime import timedelta
    pickup = sent + timedelta(days=(2 - sent.weekday()) % 7)
    return pickup.isoformat()


def _source_id(payload: dict) -> str:
    mid = payload.get("message_id") or ""
    if mid:
        return mid
    html = payload.get("html") or ""
    return f"<sha1-{hashlib.sha1(html.encode('utf-8')).hexdigest()[:16]}>"


def process_newsletter(payload: dict, config: dict, dry_run: bool = False) -> dict:
    """Process one newsletter email.

    Returns ``{status, week, items}`` where status is one of
    ``ingested | skipped | not_my_week | no_items | duplicate``.
    """
    tier = config.get("tier", "Individual")
    week_letter = (config.get("week_letter") or "A").upper()
    store = config.get("store", "Central Texas Farmers Co-op")
    category = config.get("category", "produce")

    parsed = csa_parser.parse_newsletter(
        payload.get("subject", ""), payload.get("html", ""), tier
    )
    if parsed["week_letter"] and parsed["week_letter"] != week_letter:
        return {"status": "not_my_week", "week": parsed["week"], "items": []}
    if not parsed["items"]:
        return {"status": "no_items", "week": parsed["week"], "items": []}

    source_id = _source_id(payload)
    if trip_exists(source_id):
        return {"status": "duplicate", "week": parsed["week"], "items": parsed["items"]}

    purchased = _delivery_date(payload)
    items = [
        InventoryItem(
            name=name,
            quantity=1,
            unit="ct",
            category=category,
            location=resolve_location(name, category),
            purchased=purchased,
            source="csa",
            notes=f"CSA Week {parsed['week']}" if parsed["week"] else "CSA share",
        )
        for name in parsed["items"]
    ]

    if dry_run:
        return {"status": "ingested", "week": parsed["week"],
                "items": [i.name for i in items]}

    add_items(items)
    record_trip(
        {
            "date": purchased,
            "store": store,
            "source": "csa_newsletter",
            "source_id": source_id,
            "total_cents": None,
            "needs_review": 0,
            "raw_text": payload.get("subject", ""),
        },
        [],
    )
    return {"status": "ingested", "week": parsed["week"],
            "items": [i.name for i in items]}


def run(since_days: int = 21, dry_run: bool = False) -> dict:
    """Fetch and process CSA newsletters. Returns a summary dict."""
    config = csa_parser.load_config()
    domain = config.get("sender_domain", "centraltexasfarmers.com")
    subjects = config.get("newsletter_subject_includes", ["week"])

    # Newsletters get auto-archived (they skip the inbox), so scan All Mail.
    payloads = fetch_emails([domain], subjects, since_days=since_days,
                            mailbox="ALL_MAIL")
    summary = {"ingested": 0, "duplicate": 0, "not_my_week": 0, "no_items": 0,
               "deliveries": []}
    for payload in payloads:
        result = process_newsletter(payload, config, dry_run=dry_run)
        summary[result["status"]] = summary.get(result["status"], 0) + 1
        if result["status"] == "ingested":
            summary["deliveries"].append(
                {"week": result["week"], "items": result["items"]}
            )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest CSA newsletters into inventory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report without writing inventory/DB")
    parser.add_argument("--since-days", type=int, default=21,
                        help="How many days back to scan (default 21)")
    args = parser.parse_args()

    summary = run(since_days=args.since_days, dry_run=args.dry_run)
    tag = " (dry run)" if args.dry_run else ""
    print(f"CSA newsletters{tag}: {summary['ingested']} ingested, "
          f"{summary['duplicate']} already in, {summary['not_my_week']} other-week, "
          f"{summary['no_items']} unparsed")
    for d in summary["deliveries"]:
        print(f"  Week {d['week']}: {', '.join(d['items'])}")
    return 0


if __name__ == "__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("kitchenos-csa")
    except ImportError:
        pass
    sys.exit(main())
