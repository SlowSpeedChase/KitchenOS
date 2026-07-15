# Completed: Launch-Claude button + Notes-to-Claude box

**Completed:** 2026-07-15
**Branch:** claude-launch-and-notes
**Duration:** 1 session

## Summary
Every KitchenOS web page and the top of the generated `Inventory.md` now carry a
**🤖 Launch Claude** button plus a shared **Notes** box. From the phone, the button opens
Termius over Tailscale, SSHes into the mini via an SSH forced command, and drops into
`claude` running inside a persistent tmux session (`ko-claude`) — pre-seeded with whatever
is in the shared `Claude Notes.md`. The notes box (and the same file, editable directly in
Obsidian) is what seeds the session.

## Key Changes
- **`lib/claude_notes.py`** (new) + `claude_notes_path()` in `lib/paths.py` — one plain-body
  `Claude Notes.md` at the vault root; missing → "", atomic write, trailing-newline
  normalized, empty/whitespace → 0-byte file (so the launcher treats it as "no notes").
- **`GET`/`POST /api/claude-notes`** (ungated, like `/api/inventory/*`) — load/save the notes.
- **Serve-time injection** in `api_server.py`: `_inject_after_body` (string splice) +
  `_claude_bar_html()` + `_serve_page_with_claude_bar()`; all 6 raw-HTML page handlers funnel
  through it, so the templates stay untouched (one source of truth for the widget). The
  `vault=KitchenOS` replace is preserved for recipe_detail + meal_planner only.
- **`lib/inventory.py`** — Launch Claude link + `[[Claude Notes]]` wikilink under the Open
  Review line in the generated `Inventory.md`.
- **`scripts/kitchenos-claude-{launch,run,reset}.sh`** — forced-command entrypoint
  (`tmux new-session -A -s ko-claude`), notes-resolving runner (`exec claude "$(cat notes)"`),
  and a reset to re-seed a fresh session after editing notes.
- **Docs** — `docs/API.md` (endpoint + ungated-notes security note), `docs/OPERATIONS.md §9`
  (scripts, tmux reset, one-time SSH/Termius setup), `.env.example` (`KITCHENOS_SSH_TARGET`).

## Design Doc
Plan: `~/.claude/plans/sprightly-strolling-peach.md`

## Verification
- Full suite: **1213 passed, 1 skipped**; 71 tests directly cover the new code.
- Final whole-branch review: APPROVE_WITH_NITS, no correctness defects; `exec claude
  "$(cat notes)"` argv path confirmed shell-safe; SSH-target default consistent across
  code + docs.

## Remaining manual setup (one-time, user-only — feature is inert until done)
- `launchctl unload/load ~/Library/LaunchAgents/com.kitchenos.api.plist` (API runs from the
  main checkout — pages serve stale code until reloaded).
- On the mini: `brew install tmux`; generate a dedicated ed25519 key; add
  `command="…/kitchenos-claude-launch.sh",no-port-forwarding,no-X11-forwarding <pubkey>` to
  `~/.ssh/authorized_keys`.
- On the phone (Termius): import that key; host **"KitchenOS Claude"** =
  `chase@chases-mac-mini.taila69703.ts.net` presenting only that key.
- Set `KITCHENOS_SSH_TARGET` in `.env` if the `user@host` differs from the default.

## Lessons Learned
- 6 standalone raw-HTML pages with no partial system → a single serve-time string-splice
  injection helper beats editing 6 templates and keeps one source of truth.
- Separating "start tmux" (launch.sh) from "read notes + exec claude" (run.sh) sidesteps
  nested-quoting hell: the whole notes file becomes one argv.
- Under an SSH forced command (non-login shell) `claude`/Homebrew aren't on PATH — set a
  known-good fallback PATH *before* sourcing `~/.zprofile`, and guard the source with
  `set +u` so an unbound var there can't abort the launcher before `exec claude`.
