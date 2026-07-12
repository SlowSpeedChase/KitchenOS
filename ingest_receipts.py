#!/usr/bin/env python3
"""Ingest HEB receipt emails into the KitchenOS DB.

Run hourly by ops/com.kitchenos.receipt-ingest.plist. For each new email
(dedup by Message-ID against trips.source_id): parse with Ollama, validate,
record trip + purchases, update inventory (skipping fee lines), regenerate
the Inventory.md view and the price dashboard.

Usage:
    .venv/bin/python ingest_receipts.py                 # normal hourly run
    .venv/bin/python ingest_receipts.py --dry-run       # no DB/inventory/failure-log
                                                        # writes; may still prime the
                                                        # item-alias cache
                                                        # (config/item_aliases.json)
    .venv/bin/python ingest_receipts.py --since-days 30
    .venv/bin/python ingest_receipts.py --file r.eml    # one local file (.eml or .html)
"""
import argparse
import hashlib
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from lib.email_fetcher import extract_email_payload, fetch_receipt_emails  # noqa: E402
from lib.failure_logger import classify_error, log_failures  # noqa: E402
from lib.inventory_db import trip_exists  # noqa: E402
from lib.receipt_ingest import ingest_parsed  # noqa: E402
from lib.receipt_parser import email_to_text, parse_receipt_text  # noqa: E402


def _source_for(parsed: dict) -> str:
    return (
        "email_curbside"
        if (parsed.get("order_type") or "").startswith("curb")
        else "email_receipt"
    )


def process_email(payload: dict, dry_run: bool = False) -> str:
    """Process one email payload. Returns 'ingested'|'needs_review'|'skipped'."""
    msg_id = payload.get("message_id") or ""
    if not msg_id:
        # No Message-ID → dedup on content hash so a refetch can't re-ingest
        html = payload.get("html") or ""
        msg_id = f"<sha1-{hashlib.sha1(html.encode('utf-8')).hexdigest()[:16]}>"
    if trip_exists(msg_id):
        return "skipped"

    text = email_to_text(payload.get("html") or "")
    parsed = parse_receipt_text(text)
    result = ingest_parsed(
        parsed, source=_source_for(parsed), source_id=msg_id,
        raw_text=text, dry_run=dry_run,
    )

    if dry_run:
        status = "OK" if not result["problems"] else f"NEEDS REVIEW ({'; '.join(result['problems'])})"
        print(f"[dry-run] {result['date']} {_source_for(parsed)} "
              f"total={result['total_cents']} items={len(result['items'])} — {status}")
        for it in result["items"]:
            recipe = it.get("for_recipe") or "-"
            print(f"    {it['canonical_name']:30s} {it['quantity']} {it['unit']}"
                  f"  {it['total_cents']}c  [{it['category']}/{it['location']}]  → {recipe}")
        return result["status"]

    if result["status"] == "needs_review":
        print(f"  ⚠️  needs review: {'; '.join(result['problems'])}")
    return result["status"]


def ingest(since_days: int = 14, dry_run: bool = False,
           file: str = None) -> dict:
    summary = {"ingested": 0, "skipped": 0, "needs_review": 0, "failed": 0}
    failures = []

    if file:
        p = Path(file)
        raw = p.read_bytes()
        if p.suffix == ".eml":
            emails = [extract_email_payload(raw)]
        else:
            emails = [{"message_id": f"<file-{p.name}>", "from": "file",
                       "subject": p.name, "date": "", "html": raw.decode("utf-8")}]
    else:
        emails = fetch_receipt_emails(since_days=since_days)

    print(f"Found {len(emails)} candidate email(s)")
    for payload in emails:
        try:
            result = process_email(payload, dry_run=dry_run)
            summary[result] += 1
        except Exception as e:
            summary["failed"] += 1
            failures.append({
                "subject": payload.get("subject", ""),
                "message_id": payload.get("message_id", ""),
                "error": str(e),
                "error_category": classify_error(str(e), type(e)),
                "traceback": traceback.format_exc(),
            })
            print(f"  ❌ {payload.get('subject', '?')}: {e}")

    if failures and not dry_run:
        log_failures(failures, total_processed=len(emails))

    if summary["ingested"] and not dry_run:
        try:
            from lib.price_dashboard import save_dashboard
            save_dashboard()
        except ImportError:
            # Tolerate a partially-deployed checkout where price_dashboard is
            # missing — dashboard regeneration is non-critical to ingestion.
            pass

    # Also pull CSA newsletters (produce shares with no price) into inventory.
    # Best-effort and independent of receipts — a delivery can arrive in a week
    # with no store receipts.
    csa_added = 0
    if not dry_run:
        try:
            import ingest_csa
            csa_summary = ingest_csa.run()
            csa_added = csa_summary.get("ingested", 0)
            if csa_added:
                print(f"CSA: ingested {csa_added} delivery(ies)")
        except Exception as e:
            print(f"Warning: CSA ingest failed: {e}", file=sys.stderr)

    # Refresh the Use-It-Up waste suggestions after new produce/purchases. (Pruning
    # stale inventory is left to the daily meal-plan run — pruning here would
    # immediately drop items from an old backfilled receipt.)
    if (summary["ingested"] or csa_added) and not dry_run:
        try:
            from lib import use_it_up
            use_it_up.write_note()
            from lib import cook_now
            cook_now.write_note()
        except Exception as e:
            print(f"Warning: use-it-up refresh failed: {e}", file=sys.stderr)

    print(f"Done: {summary}")
    return summary


if __name__ == "__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("kitchenos-receipt-ingest")
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since-days", type=int, default=14)
    ap.add_argument("--file", help="parse one local .eml or .html file")
    args = ap.parse_args()
    try:
        ingest(since_days=args.since_days, dry_run=args.dry_run, file=args.file)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
