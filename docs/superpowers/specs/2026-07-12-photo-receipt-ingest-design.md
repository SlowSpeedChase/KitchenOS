# Photo-receipt → inventory via the Claude iOS app

**Status:** Implemented · **Branch:** `photo-receipt-ingest` · **Date:** 2026-07-12

## Problem

KitchenOS ingests HEB receipts only from *email* (`ingest_receipts.py` → Gmail →
`receipt_parser.parse_receipt_text` LLM parse → DB). There was no path for a
physical / paper / HEB-app receipt you photograph on your phone.

## Approach

Do the vision in the **Claude iOS app**, not in KitchenOS. The user photographs a
receipt in the Claude app with a saved prompt that emits the exact
`RECEIPT_SCHEMA` JSON, then pastes that JSON into KitchenOS. KitchenOS does zero
server-side LLM work — it validates the JSON and runs the existing trip/inventory
back-end. The `trips` table already documents `photo` as an expected `source`.

Decisions: **JSON output** (the app renders it as a one-tap-copy code block; the
preview page is where it's eyeballed) over a human list (would need a second
server-side LLM parse). **Web paste page now, iOS Shortcut later** (the endpoint
is what a Shortcut will call anyway).

## Design

1. **Shared engine** — extracted the "parsed dict → inventory" tail out of
   `ingest_receipts.process_email` into `lib/receipt_ingest.py:ingest_parsed(...)`
   (validate → build_purchases → assign_recipes → record_trip + add_items,
   fees excluded from stock, `raw_text` stored only when `needs_review`). The
   email path calls it too, so behavior stays identical.
2. **Paste helpers** (same module) — `parse_pasted_json` (tolerant of code
   fences), `content_source_id` (dedup hash of date+total+item names),
   `preview` (dry-run, reports `already_ingested`), `commit`.
3. **Prompt** — `prompts.receipt_extraction.build_receipt_photo_prompt()`, reusing
   `RECEIPT_SCHEMA` so it can't drift; reference copy in `prompts/receipt_photo.md`.
4. **API** — `POST /api/receipt/paste` (`{json, commit?}`; response `mode` +
   engine `status`; 400 on bad JSON; un-gated like `/api/inventory/paste`),
   `GET /api/receipt/prompt`, `GET /receipt-paste` (the page).
5. **Page** — `templates/receipt_paste.html`, matching the dashboard design system;
   linked from `Dashboards/KitchenOS Web.md` (via `lib/web_dashboard.py`).

## Testing

`tests/test_receipt_ingest.py` (engine + paste helpers on isolated DB/vault) and
`tests/test_api_receipt_paste.py` (Flask client: preview vs commit, 400s, prompt).
Regression: existing `test_ingest_receipts.py` / `test_receipt_parser.py` pass
after the refactor. Verified end-to-end against a live server on an isolated DB:
preview writes nothing, commit files 1 trip + 4 purchases, re-commit dedups,
bad JSON 400s, page loads.

## Out of scope / follow-ups

- iOS Shortcut wrapping `POST /api/receipt/paste` (one-tap from clipboard).
- Non-HEB stores (prompt + `store` field already generalize; untested).
