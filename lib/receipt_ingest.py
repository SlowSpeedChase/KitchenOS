"""Shared receipt-ingest engine + a paste-JSON front door.

The email path (``ingest_receipts.process_email``) and the photo path (the
``/api/receipt/paste`` web page) both turn a *parsed receipt dict* — matching
``prompts.receipt_extraction.RECEIPT_SCHEMA`` — into a trip + priced purchases +
inventory. ``ingest_parsed`` is that shared tail.

``preview`` / ``commit`` wrap it for JSON pasted from the Claude iOS app: you
photograph an HEB receipt in the Claude app, it emits the schema JSON, and you
paste that here. No server-side LLM call happens — the app already did the
vision + structuring, so we only validate and file the result.
"""
from __future__ import annotations

import hashlib
import json

from lib.inventory import InventoryItem, add_items
from lib.inventory_db import record_trip, trip_exists
from lib.recipe_matcher import assign_recipes
from lib.receipt_parser import (
    _extract_json_object,
    build_purchases,
    to_cents,
    validate_receipt,
)
from lib.storage_locations import resolve_location

PHOTO_SOURCE = "photo_receipt"


def _routed_items(purchases: list[dict]) -> list[dict]:
    """Purchase rows + resolved storage location — JSON-able for a preview.

    Routing (location) is applied here so a dry-run preview matches the commit.
    """
    return [
        {
            "canonical_name": p["canonical_name"],
            "raw_name": p["raw_name"],
            "quantity": p["quantity"],
            "unit": p["unit"],
            "total_cents": p["total_cents"],
            "category": p["category"],
            "location": resolve_location(p["canonical_name"], p["category"]),
            "for_recipe": p.get("for_recipe"),
        }
        for p in purchases
    ]


def ingest_parsed(
    parsed: dict, *, source: str, source_id: str,
    raw_text: str | None = None, dry_run: bool = False,
) -> dict:
    """Turn a parsed receipt dict into a trip + inventory. Shared email + photo tail.

    Returns ``{status, problems, items, total_cents, date}`` where ``status`` is
    ``'ingested' | 'needs_review' | 'skipped'``. ``skipped`` means a trip with
    this ``source_id`` already exists (duplicate). Nothing is written on dry-run.
    """
    ok, problems = validate_receipt(parsed)
    purchases = build_purchases(parsed)
    # Tag each line with the meal-plan recipe it was bought for (this/next
    # week); unmatched lines stay None and fall through to general inventory.
    assign_recipes(purchases)
    total_cents = to_cents(parsed.get("total"))
    date = parsed.get("date") or ""
    result = {
        "problems": problems,
        "items": _routed_items(purchases),
        "total_cents": total_cents,
        "date": date,
    }

    if dry_run:
        result["status"] = "ingested" if ok else "needs_review"
        return result

    trip = {
        "date": date,
        "store": parsed.get("store") or "HEB",
        "source": source,
        "source_id": source_id,
        "total_cents": total_cents,
        "needs_review": not ok,
        "raw_text": raw_text if not ok else None,
    }
    if record_trip(trip, purchases) is None:
        result["status"] = "skipped"
        return result

    if not ok:
        result["status"] = "needs_review"
        return result

    stock = [
        InventoryItem(
            name=p["canonical_name"],
            quantity=float(p["quantity"] or 1),
            unit=p["unit"],
            category=p["category"],
            location=resolve_location(p["canonical_name"], p["category"]),
            purchased=date,
            source="receipt",
            for_recipe=p.get("for_recipe"),
        )
        for p in purchases
        if p["category"] != "fee"
    ]
    if stock:
        add_items(stock)
    result["status"] = "ingested"
    return result


# --- JSON paste front door (Claude iOS app → phone paste) ----------------

def parse_pasted_json(text: str) -> dict:
    """Extract the receipt JSON object from pasted text (tolerates fences/prose).

    Raises ``json.JSONDecodeError`` or ``ValueError`` on unparseable input.
    """
    parsed = json.loads(_extract_json_object(text or ""))
    if not isinstance(parsed, dict):
        raise ValueError("receipt JSON is not an object")
    return parsed


def content_source_id(parsed: dict) -> str:
    """Stable dedup id from receipt content (date + total + item raw names)."""
    names = "|".join((it.get("raw_name") or "") for it in (parsed.get("items") or []))
    basis = f"{parsed.get('date')}|{parsed.get('total')}|{names}"
    return "photo-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def preview(text: str) -> dict:
    """Dry-run a pasted receipt for a confirmation step (no DB writes).

    Returns the routed items + reconciliation, plus ``count`` and an
    ``already_ingested`` flag. On unparseable input returns ``{'error': ...}``.
    """
    try:
        parsed = parse_pasted_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"Could not parse receipt JSON: {e}"}
    source_id = content_source_id(parsed)
    result = ingest_parsed(parsed, source=PHOTO_SOURCE, source_id=source_id, dry_run=True)
    result["count"] = len(result["items"])
    result["already_ingested"] = trip_exists(source_id)
    return result


def commit(text: str) -> dict:
    """Parse and persist a pasted receipt via the shared ingest engine.

    On unparseable input returns ``{'error': ...}``.
    """
    try:
        parsed = parse_pasted_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"Could not parse receipt JSON: {e}"}
    source_id = content_source_id(parsed)
    result = ingest_parsed(
        parsed, source=PHOTO_SOURCE, source_id=source_id,
        raw_text=text if isinstance(text, str) else None,
    )
    result["count"] = len(result["items"])
    return result
