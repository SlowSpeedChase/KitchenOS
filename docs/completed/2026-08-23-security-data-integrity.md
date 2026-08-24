# Completed: Security and Data Integrity Repair

**Completed:** 2026-08-23  
**Branch:** `security-data-integrity`  
**Pull request:** [#75](https://github.com/SlowSpeedChase/KitchenOS/pull/75)  
**Duration:** 1 day (started 2026-08-23)

## Summary

KitchenOS no longer exposes the privileged Claude browser bridge. Request-derived
recipe and shopping-list paths are contained beneath their configured roots, and
inventory plus receipt persistence is safe under concurrent writers, retries, and
partial failures.

## Key Changes

- Removed the injected Claude page widget and unregistered `/api/claude-send` plus
  both `/api/claude-notes` methods; the underlying helper modules remain dormant.
- Added one Markdown-path authority that rejects absolute paths, traversal, NULs,
  wrong suffixes, and symlink escapes without double-decoding Flask inputs.
- Validated real canonical ISO weeks on the four shopping-list mutation/preview
  handlers.
- Replaced additive inventory read/replace writes with `BEGIN IMMEDIATE` UPSERTs
  while preserving quantity, purchase-date, expiry, provenance, notes, category,
  and recipe-attribution semantics.
- Serialized every full-set inventory mutation and pantry reconciliation from read
  through replace. No-op mutations skip database replacement and view regeneration.
- Serialized post-commit Inventory/Cook Now regeneration across threads and
  processes; derived-view failures are logged instead of turning committed writes
  into retryable API failures.
- Made valid receipt trips, purchases, and stock one atomic transaction. Duplicate
  source IDs are successful no-ops, and supplied trip payloads require a stable
  nonempty `source_id` before any write.
- Updated API, architecture, operations, and environment contracts from the measured
  Flask surface: 91 route decorators and 82 unique literal paths.

## Verification

- Default suite: **4,108 passed, 1 skipped, 133 deselected, 9 existing warnings**.
- Focused final-review suite: **281 passed**.
- E2E: **128 passed, 1 skipped, 3 expected xfails, 1 xpass**, with no hard failures.
- Independent task reviews, whole-branch review, and scoped fix re-review completed
  with no remaining Critical or Important findings.

## Design Doc

[Security and data integrity design](../superpowers/specs/2026-08-23-security-data-integrity-design.md)

## Lessons Learned

- SQLite `UNIQUE` permits multiple `NULL` values, so receipt idempotency requires a
  validated nonempty identity at the request boundary.
- A transaction is not enough when a derived view runs afterward: refresh failures
  must never produce a retryable error after durable data commits.
- Refresh serialization must cover the database read and every output write; locking
  only the final write still allows an older snapshot to finish last.
- Full-set reconciliation and additive merging need distinct algorithms but one
  shared SQLite write authority to avoid lost updates and lock-order drift.

## Operational Follow-up

The merge is on `origin/main`, but the local main checkout has user-owned changes and
has not incorporated it yet. Restart `com.kitchenos.api` and run the live smoke check
only after that checkout is safely updated; restarting earlier would reload the old
local main code.
