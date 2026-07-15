#!/usr/bin/env bash
# scripts/kitchenos-claude-reset.sh
# Kill the persistent `ko-claude` tmux session so the NEXT "Launch Claude" starts a
# fresh `claude` re-seeded with the current Claude Notes.md.
#
# Why this exists: `kitchenos-claude-launch.sh` uses `tmux new-session -A`, which
# re-attaches an existing session. That's what makes the session survive a
# disconnect — but it also means edits to your notes only take effect in a *new*
# session. Run this (over SSH, or from a Mac mini terminal) when you've changed the
# notes and want the next launch to pick them up.
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if tmux kill-session -t ko-claude 2>/dev/null; then
  echo "ko-claude session killed — next Launch Claude will re-seed from Claude Notes.md."
else
  echo "No ko-claude session was running (next launch already starts fresh)."
fi
