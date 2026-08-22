# Capture Queue: Retry Cap + Dead-Letter Path

**Status:** Vision
**Created:** 2026-08-22
**Updated:** 2026-08-22

> Captured 2026-08-22 while landing `stale-server-detection`. The `capture_queue`
> health assertion has been `failing` continuously and the cause is fully
> diagnosed — but the fix has real design decisions that were not settled, so it
> is filed here rather than built. See "Open questions".

---

## Problem

`batch_extract` keeps **no attempt counter**, so a permanently dead item is
indistinguishable from a transient one and is reprocessed every hour forever.

Measured on 2026-08-22:

- **22 consecutive zero-capture runs**, unbroken since `2026-08-21-201006`
  (~21 hours of hourly retries), every one `total=1, succeeded=0, failed=1`.
- The single item is one H-E-B recipe URL
  (`heb.com/recipe/recipe-detail/thai-style-larb-lettuce-wraps`) that fails with
  `www.heb.com served an anti-bot challenge page instead of the recipe`,
  classified `blocked`. Scraping it needs a real browser session, which the
  scrape pipeline does not have — so it will **never** succeed as written.
- `check_capture_queue` (`lib/health_assertions.py:111`) reports `failing` at
  `JAMMED_RUN_THRESHOLD = 3`, correctly, and has done so for the whole streak.

The consequence the check already names: *"the same items are being retried every
hour and will never succeed. Real failures are buried in the repetition."* A
genuinely new, genuinely transient failure arriving tomorrow is invisible — it
looks exactly like the 22 runs before it.

## Solution (sketch)

Give the queue the two things it lacks: an **attempt counter** so a dead item can
be recognised, and a **dead-letter path** so it can leave. This is the fix named
in the check's own `fix` field.

Deliberately **not** in scope: fixing the underlying heb.com block. Adding a real
browser session (Playwright is currently an e2e-test-only dependency, absent from
`lib/` and `scripts/`) would rescue this item and the whole `blocked` family, but
it is a separate, larger piece of work — and the queue would still need a cap for
everything a browser cannot rescue.

## Design notes

- **The queue is Apple Reminders.** Uncompleted items in the `Recipies to Process`
  list *are* the queue. Success calls `mark_reminder_complete` and the item leaves;
  failure hits `batch_extract.py:396` — `✗ Left unchecked (will retry next run)` —
  and it stays. There is no separate queue store, which is exactly why there is
  nowhere obvious to keep a counter.
- **Error classification already exists and is category-aware.**
  `lib/failure_logger.classify_error` returns one of eight categories, and they
  already split along the axis a cap cares about:
  - *likely permanent* — `blocked` (anti-bot, cloudflare, captcha, 403/429/451),
    `instagram` (auth/cookies), `youtube` (private, no captions)
  - *likely transient* — `network` (timeout, DNS, refused), `ollama`, `parsing`,
    `io`, `unknown`

  So a cap can be **category-aware** rather than a blunt count: one `blocked`
  result is already near-certain to repeat, while three `network` failures may
  just be a bad afternoon. This is an asset the design should use.
- **Run logs already carry the evidence** (`logs/runs/*.json`, 30-day retention,
  733 files) and failure logs carry per-item detail (`failures/`, 30-day
  retention). Neither is keyed by item, so neither can currently answer "how many
  times has *this URL* failed".

## Open questions / blockers

1. **What happens to a dead item in Reminders?** Not settled. Three candidates,
   each with a different recovery story:
   - move it to a second list (`Recipies — Stuck`) — queue drains, item stays
     visible and recoverable on the phone by dragging it back;
   - mark it complete and record it in a dead-letter file surfaced on
     `/system-health` — cleanest queue, but the item reads as "done" when it
     wasn't, and recovery becomes desktop-only;
   - leave it in place, flagged and skipped — nothing vanishes, but the list
     accumulates dead items forever and "the queue is draining" stops being a
     fact.
2. **Where does the attempt counter live?** Follows from (1). Candidates: the
   reminder's own `notes` field (state travels with the item, survives a DB
   wipe, but mutates the user's data), a sidecar JSON keyed by resolved URL, or
   a table in the existing DB.
3. **What is the cap, and is it per-category?** See the classification split
   above. A single number is simpler; per-category is more honest.

## Acceptance criteria (draft — not yet Ready)

- A permanently failing item stops being retried after a bounded number of
  attempts, and `capture_queue` returns to `ok` **because the queue drained**,
  not because the check was loosened.
- A dead item is still discoverable and re-queueable by the user without
  editing files.
- A new, unrelated failure arriving after a jam is visible rather than buried.
- The existing `classify_error` categories are reused, not duplicated.

## Related

- `lib/health_assertions.py:111` — `check_capture_queue`, `JAMMED_RUN_THRESHOLD`
- `lib/failure_logger.py:54` — `classify_error`
- `batch_extract.py:396` — the "left unchecked" failure path
- Prior art: the 2026-08-02 daily-driver audit Phase 0 revived capture after 725
  runs produced 18 recipes; this is the *other* half — capture works now, but the
  queue still cannot let go of what it can never process.
