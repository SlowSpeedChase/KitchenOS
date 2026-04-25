#!/bin/bash
# One-shot cleanup of the renamed iCloud KitchenOS leftover.
# Triggered by ~/Library/LaunchAgents/com.kitchenos.cleanup-icloud-old.plist on 2026-05-02 at 10am.
# Performs four pre-checks; deletes the leftover iff all pass; self-removes the LaunchAgent on success
# (or on no-op when the leftover is already gone).

set -u

ICLOUD_OLD="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS.OLD-DELETE-AFTER-2026-05-02"
PLIST_INSTALLED="$HOME/Library/LaunchAgents/com.kitchenos.cleanup-icloud-old.plist"
TARBALL="$HOME/Backups/kitchenos-icloud-2026-04-25.tar.gz"
LOG_DIR="$HOME/KitchenOS/logs"

mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/cleanup_old_icloud.log" 2>&1
echo "==== $(date) — cleanup_old_icloud.sh starting ===="

# Idempotency: already cleaned up
if [ ! -d "$ICLOUD_OLD" ]; then
    echo "iCloud OLD dir not present — nothing to do. Self-removing LaunchAgent."
    launchctl unload "$PLIST_INSTALLED" 2>/dev/null
    rm -f "$PLIST_INSTALLED"
    exit 0
fi

fail=0
if [ ! -f "$TARBALL" ]; then
    echo "FAIL check 1: safety-net tarball missing at $TARBALL"
    fail=1
fi
if [ ! -d "$HOME/KitchenOS/vault/Recipes" ] || [ "$(ls -1 "$HOME/KitchenOS/vault/Recipes" | wc -l)" -lt 1 ]; then
    echo "FAIL check 2: ~/KitchenOS/vault/Recipes empty or missing"
    fail=1
fi
if ! curl -sf --max-time 5 http://localhost:5001/health >/dev/null; then
    echo "FAIL check 3: API server /health not responding"
    fail=1
fi
agent_count=$(launchctl list | grep -c kitchenos)
if [ "$agent_count" -lt 4 ]; then
    echo "FAIL check 4: only $agent_count KitchenOS LaunchAgents loaded (expected 4+)"
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    echo "Pre-checks failed — leaving iCloud OLD dir intact. Investigate manually."
    exit 1
fi

size_before=$(du -sh "$ICLOUD_OLD" 2>/dev/null | awk '{print $1}')
echo "All pre-checks passed. Deleting $ICLOUD_OLD ($size_before)"
rm -rf "$ICLOUD_OLD"

if [ -d "$ICLOUD_OLD" ]; then
    echo "ERROR: deletion did not remove $ICLOUD_OLD"
    exit 2
fi

echo "Deletion succeeded — freed $size_before"
echo "Self-removing LaunchAgent"
launchctl unload "$PLIST_INSTALLED" 2>/dev/null
rm -f "$PLIST_INSTALLED"
echo "Done."
