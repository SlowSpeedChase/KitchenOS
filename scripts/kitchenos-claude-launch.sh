#!/usr/bin/env bash
# scripts/kitchenos-claude-launch.sh
# SSH forced-command entrypoint for the "Launch Claude" button (Termius host
# "KitchenOS Claude"). Attaches to — or creates — a persistent tmux session named
# `ko-claude` running `claude` seeded with your Claude Notes.
#
# `new-session -A` = attach if it exists, else create. So tapping Launch Claude
# again from the phone re-attaches the SAME running session: the work survives a
# disconnect / screen lock. Wire this up as the forced command on a dedicated key:
#
#   command="/Users/chaseeasterling/Dev/KitchenOS/scripts/kitchenos-claude-launch.sh",\
#   no-port-forwarding,no-X11-forwarding <ssh-ed25519 ...>
#
# in ~/.ssh/authorized_keys on the mini. Requires tmux (`brew install tmux`).
set -uo pipefail

RUN="/Users/chaseeasterling/Dev/KitchenOS/scripts/kitchenos-claude-run.sh"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

exec tmux new-session -A -s ko-claude "$RUN"
