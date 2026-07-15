#!/usr/bin/env bash
# scripts/kitchenos-claude-run.sh
# Runs INSIDE the `ko-claude` tmux session (started by kitchenos-claude-launch.sh).
# cd's into the KitchenOS main checkout, resolves the shared `Claude Notes.md` via
# lib.paths, and starts `claude` seeded with those notes (if any) as the opening
# prompt — so tapping "Launch Claude" on the phone drops you into a session already
# primed with what you wrote in the web notes box / Obsidian.
#
# Invoked under an SSH forced command, i.e. a NON-login, non-interactive shell, so
# `claude` / Homebrew are not on PATH by default — we source ~/.zprofile and prepend
# the usual Homebrew bin dirs before resolving `claude`.
set -uo pipefail

REPO="/Users/chaseeasterling/Dev/KitchenOS"
cd "$REPO" || { echo "KitchenOS checkout not found at $REPO" >&2; exit 1; }

# Bring `claude` (and Homebrew) onto PATH for a non-login shell. Set the known-good
# fallback FIRST so `claude` resolves even if sourcing ~/.zprofile is a no-op, and
# guard the source with `set +u` so an unbound-var reference in ~/.zprofile can't
# abort this script before `exec claude` (which would kill the tmux session).
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
# shellcheck disable=SC1090,SC1091
if [ -r "$HOME/.zprofile" ]; then
  set +u
  source "$HOME/.zprofile"
  set -u
fi

# Resolve the notes file through the same helper the web app / Obsidian use, so the
# bytes are identical everywhere. Empty/whitespace notes are written as a 0-byte file
# by lib/claude_notes.py, so `-s` (non-empty) correctly means "there are notes".
NOTES_FILE="$("$REPO/.venv/bin/python" -c 'from lib.paths import claude_notes_path; print(claude_notes_path())' 2>/dev/null)"

if [ -n "${NOTES_FILE:-}" ] && [ -s "$NOTES_FILE" ]; then
  # Whole file = one argv, so no nested-quote / word-splitting surprises.
  exec claude "$(cat "$NOTES_FILE")"
else
  exec claude
fi
