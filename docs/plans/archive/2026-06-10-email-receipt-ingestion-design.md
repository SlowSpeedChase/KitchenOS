# Email Receipt Ingestion & Price History — Design

**Date:** 2026-06-10
**Status:** Approved

## Goal

Ingest HEB grocery emails (in-store e-receipts and curbside/delivery order
confirmations) automatically, add purchased items to a unified pantry
inventory with purchase dates, and maintain a permanent price-history ledger
with an Obsidian dashboard for price trends and spending analytics. The
existing Claude receipt-photo flow is upgraded to feed the same stores.

## Decisions

| Decision | Choice |
|----------|--------|
| Store | HEB only (sender list is config, extensible later) |
| Email types | In-store e-receipts + curbside/delivery confirmations |
| Fetch mechanism | IMAP polling of Gmail via app password (LaunchAgent, hourly) |
| Inventory destination | **Unify** on one canonical store (SQLite); `Inventory.md` becomes a generated read-only view; `config/pantry.json` retired |
| Price history use | Item price over time + spending analytics |
| Viewing | Obsidian dashboard (`Price Tracker.md`), nutrition-dashboard pattern |
| Paper receipts | Keep the Claude Desktop photo flow; MCP tool gains price/trip fields |
| Parsing | HTML → text → Ollama (`mistral:7b`) structured extraction |

## Architecture

```
Gmail (HEB senders)                Claude Desktop (photo)
        │ IMAP, hourly LaunchAgent          │ MCP add_to_inventory (+prices)
        ▼                                   ▼
ingest_receipts.py ──────────────► data/kitchenos.db (SQLite)
  html→text → Ollama parse           ├── trips       (one per receipt)
  validate → canonicalize            ├── purchases   (price ledger, append-only)
                                     └── inventory   (current on-hand)
                                            │
                ┌───────────────────────────┼─────────────────────────┐
                ▼                           ▼                         ▼
        Inventory.md (generated)   Price Tracker.md (dashboard)   lib/pantry.py
        read-only vault view       trends + spending              same API, DB-backed
                                                                  → shopping list split
```

## Data model (`data/kitchenos.db`, stdlib sqlite3)

**trips** — `id`, `date`, `store`, `source` (`email_receipt` | `email_curbside`
| `photo` | `manual`), `source_id` (Gmail Message-ID or photo hash,
**UNIQUE** — reprocessing can never double-ingest), `total_cents`,
`needs_review` flag, `raw_text` (kept when parsing was uncertain).

**purchases** — `id`, `trip_id`, `raw_name` (verbatim receipt string),
`canonical_name`, `quantity`, `unit`, `unit_price_cents`, `total_cents`,
`category`. Append-only ledger; never deleted. Non-grocery lines (tax, fees,
totes, tips) get `category: fee` — counted in spending, never in inventory.

**inventory** — `name`, `quantity`, `unit`, `category`, `location`,
`purchased` (most recent purchase date), `source`, `notes`. Same
`(name, unit, location)` merge rule as today's `Inventory.md`. Receipts
increment; shopping-list confirm decrements (existing flow).

All money is integer cents.

### Canonicalization

`config/item_aliases.json` maps raw receipt strings → canonical names
(`"HCF BNLS SKNLS BRST"` → `"chicken breast"`). On a cache miss, Ollama
proposes the canonical form and the result is cached in the file. Repeat
receipts parse instantly; bad mappings are hand-correctable in a text editor.

### Consequences

- `lib/pantry.py` keeps its public API (`load_pantry`,
  `split_against_pantry`, decrement-on-confirm) but is backed by the
  `inventory` table. Shopping-list code is unchanged.
- **`Inventory.md` becomes a generated, read-only view**, regenerated after
  every write. Edits go through Claude MCP tools, not Obsidian.

## Email ingestion pipeline (`ingest_receipts.py`)

Run hourly by `ops/com.kitchenos.receipt-ingest.plist` (batch-extract
pattern). Supports `--dry-run` (print parsed trips, write nothing).

1. **Fetch** — `imaplib` to Gmail with `GMAIL_APP_PASSWORD` from `.env`.
   Search senders listed in `config/receipt_senders.json` since last run.
2. **Dedup** — skip any Message-ID already in `trips.source_id`.
3. **Parse** — strip HTML to text; one Ollama prompt returns trip date,
   order type, line items (raw name, qty, unit, unit price, line total),
   and receipt total. The prompt distinguishes e-receipt vs curbside.
4. **Validate** — line totals must sum to the receipt total within a
   tolerance (tax/fee lines allowed). On failure or missing fields, write
   the trip with `needs_review` + `raw_text` for later correction —
   honest-about-inference, like recipes.
5. **Write** — canonicalize names, insert trip + purchases, increment
   inventory with the purchase date, regenerate `Inventory.md`.

Failures route through `lib/failure_logger.py` (existing categories:
`network` / `parsing` / `ollama`), so the failure-analysis agent sees them.

**YAGNI exclusions (v1):** no refund/substitution-email handling; the
senders config matches receipt-type messages only.

## Price dashboard (`generate_price_dashboard.py`)

Writes `Price Tracker.md` to the vault root; regenerated after each ingest;
`--dry-run` supported.

- **Spending:** last 4 weeks and last 12 months — tables by week and by
  category; average trip cost.
- **Price trends:** top ~20 most-purchased items — last price vs 90-day
  average with ▲/▼ markers; per-item history in a collapsible section.
- **Needs review:** trips flagged during validation, listed at the bottom.

## Photo flow upgrade

`add_to_inventory` MCP tool gains optional `unit_price` per item and an
optional `trip` object (date, store, total). The API endpoint writes a
`trips` row (`source: photo`) plus `purchases` rows. Price fields optional —
a photo without legible prices still updates inventory only.

## Migration (`migrate_inventory_db.py`, one-time)

Creates the schema, imports current `Inventory.md` rows into `inventory`,
regenerates `Inventory.md` from the DB to verify round-trip, leaves a `.bak`
of the original. (`config/pantry.json` does not exist on disk — nothing to
import.)

## Error handling

| Failure | Behavior |
|---------|----------|
| IMAP/auth error | Log, exit; next hourly run retries |
| Ollama down | Emails stay unprocessed (nothing marked done); retried next run |
| Malformed parse | Trip saved with `needs_review` + raw text; shown on dashboard |
| Duplicate email | UNIQUE `source_id` makes re-ingest a no-op |

## Testing

- Fixture HEB emails (one e-receipt, one curbside HTML) with mocked Ollama
  responses: parser → validation → DB writes → dedup on re-run.
- `lib/pantry.py` equivalence: DB-backed API returns the same shapes as the
  old JSON-backed version.
- `ingest_receipts.py --dry-run` end-to-end smoke.
