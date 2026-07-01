# Batch Failure Analysis Agent

**Date:** 2026-02-13
**Status:** Approved

## Problem

When `batch_extract.py` fails to extract a recipe, the error is printed to stdout/log but not persisted in a structured way. Failures are left unchecked in Reminders and retried next run, but if the failure is a code bug, it will keep failing forever.

## Solution

1. **Structured failure logging** — Write failures to JSON files in `failures/` directory
2. **Error classification** — Categorize failures to help prioritize fixes
3. **Automated agent** — Trigger `claude -p` to analyze failures and create fix PRs

## Failure Log Structure

Each batch run with failures writes `failures/YYYY-MM-DD-HHMMSS.json`:

```json
{
  "run_timestamp": "2026-02-13T06:10:05",
  "total_processed": 5,
  "total_failed": 2,
  "failures": [
    {
      "url": "https://www.youtube.com/watch?v=abc123",
      "error": "Ollama connection refused",
      "error_category": "network",
      "traceback": "Traceback (most recent call last):\n  ...",
      "reminder_title": "https://www.youtube.com/watch?v=abc123",
      "timestamp": "2026-02-13T06:10:12"
    }
  ]
}
```

## Error Categories

| Category | Examples | Agent action |
|----------|----------|--------------|
| `network` | Connection refused, timeout, DNS | Transient — skip |
| `ollama` | Ollama down, model not found | Infrastructure — check config |
| `youtube` | Video unavailable, private, no transcript | Data issue — improve fallbacks |
| `parsing` | JSON parse error, missing fields | Code bug — create fix |
| `io` | File write error, permission denied | Environment — flag for review |
| `unknown` | Anything else | Investigate |

Classification uses pattern matching on error message and exception type.

## Agent Trigger Flow

```
batch_extract.py finishes
    |
    v
Any failures? --no--> exit normally
    | yes
    v
Write failures/YYYY-MM-DD-HHMMSS.json
    |
    v
Spawn: scripts/analyze_failures.sh (background, detached)
    |
    v
Shell script:
  1. cd to project root
  2. Build prompt with failure JSON contents
  3. Run: claude -p "<prompt>"
  4. Claude Code analyzes, creates branch, commits fix, opens PR
```

The shell script runs detached so batch_extract doesn't block.

## Agent Behavior

The `claude -p` prompt instructs the agent to:

1. Read the failure JSON
2. Skip `network` category failures (transient)
3. For fixable failures (`parsing`, `youtube`, `ollama`):
   - Read relevant source code
   - Reproduce the error with `--dry-run` if possible
   - Identify root cause
   - Create fix on branch `fix/batch-failure-YYYY-MM-DD`
   - Open a PR for review
4. For unfixable failures (video private, deleted):
   - Update the failure log entry with `"status": "wontfix"` and reason

## Cleanup

Failure logs older than 30 days are deleted at batch_extract startup (mirrors existing backup cleanup pattern).

## Files Changed

| File | Change |
|------|--------|
| `batch_extract.py` | Add failure JSON writing, error classification, agent trigger, cleanup |
| `lib/failure_logger.py` | New — failure logging and classification logic |
| `scripts/analyze_failures.sh` | New — shell script that invokes `claude -p` |
| `failures/` | New directory (gitignored) |
| `.gitignore` | Add `failures/` |
| `CLAUDE.md` | Document new feature |
