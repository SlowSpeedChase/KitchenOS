# Completed: Photo-receipt → inventory via the Claude iOS app

**Completed:** 2026-07-12
**Branch:** photo-receipt-ingest
**Duration:** 1 day (started 2026-07-12)

## Summary

Added a front door for **photographed** HEB receipts (paper / in-store / HEB-app)
that never arrive by email. The vision happens in the **Claude iOS app**: a saved
prompt makes it emit the receipt as `RECEIPT_SCHEMA` JSON, which the user pastes
into KitchenOS at `/receipt-paste`. KitchenOS does zero server-side LLM work — it
validates the JSON and runs the existing trip/inventory back-end.

## Key Changes

- **`lib/receipt_ingest.py`** (new) — `ingest_parsed()`, the shared "parsed dict →
  trip + priced purchases + non-fee inventory" engine extracted from
  `ingest_receipts.process_email` (email path now calls it; behavior unchanged).
  Plus `parse_pasted_json` / `content_source_id` (dedup) / `preview` / `commit`.
- **`prompts/receipt_extraction.py`** — `build_receipt_photo_prompt()` reusing
  `RECEIPT_SCHEMA` (drift-proof); reference copy in `prompts/receipt_photo.md`.
- **`api_server.py`** — `POST /api/receipt/paste` (preview/commit, `mode` +
  engine `status`, 400 on bad JSON, un-gated like `/api/inventory/paste`),
  `GET /api/receipt/prompt`, `GET /receipt-paste`.
- **`templates/receipt_paste.html`** (new) — copy-prompt → paste → preview
  (routed items + reconciliation) → confirm; linked from the KitchenOS Web note
  via `lib/web_dashboard.py`.
- Docs: `docs/API.md`, `docs/OPERATIONS.md`; tests
  `tests/test_receipt_ingest.py`, `tests/test_api_receipt_paste.py`.

## Design Doc

`docs/superpowers/specs/2026-07-12-photo-receipt-ingest-design.md`

## Verification

Full suite 1177 passed / 1 skipped after the refactor. Driven end-to-end against a
live server on an isolated DB: prompt endpoint returns the prompt; preview writes
nothing; commit files 1 trip + 4 purchases; re-commit dedups (`skipped`); bad JSON
→ 400; page loads. Not browser-driven (no Chrome for Playwright) — the page is
plain `fetch` against the verified endpoints.

## Lessons Learned

- The whole feature reduced to one refactor + thin adapters because `process_email`'s
  second half already operated on a plain parsed dict, and `/api/inventory/paste`
  gave a preview/commit precedent to mirror.
- Watch the alias cache during manual E2E: running the real server (isolated DB but
  shared `config/item_aliases.json`) primed synthetic-fixture aliases; reverted before
  commit. Tests avoid this via the `alias_tmp` fixture.

## Follow-ups

- iOS Shortcut wrapping `POST /api/receipt/paste` (one-tap from clipboard) — the
  endpoint was built to be its call target.
- Non-HEB stores (prompt + `store` field generalize; untested).
