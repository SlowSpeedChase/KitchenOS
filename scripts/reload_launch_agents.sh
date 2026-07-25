#!/usr/bin/env bash
# Reload all KitchenOS LaunchAgents from ~/Library/LaunchAgents/.
#
# Run this from a Terminal in your normal GUI (Aqua) session — NOT from a
# Background context like an SSH session or Claude Code's Bash tool, since
# user LaunchAgents live in the gui/<uid> domain and can only be managed
# from a process inside that session.
#
# Use after editing any com.kitchenos.*.plist file.

set -u

UID_VAL=$(id -u)

# Discovered from disk, never hardcoded — a hardcoded list silently stops
# reloading agents added later, and this script's whole job is "reload them
# all". Everything in ops/ that has been installed is picked up automatically.
AGENTS=()
for plist in "$HOME"/Library/LaunchAgents/com.kitchenos.*.plist; do
    [[ -f "$plist" ]] || continue
    name="${plist##*/com.kitchenos.}"
    AGENTS+=("${name%.plist}")
done

if [[ ${#AGENTS[@]} -eq 0 ]]; then
    echo "No com.kitchenos.*.plist found in ~/Library/LaunchAgents/."
    echo "Install them first:  cp ops/com.kitchenos.*.plist ~/Library/LaunchAgents/"
    exit 1
fi

echo "--- ${#AGENTS[@]} agent(s) found: ${AGENTS[*]} ---"
echo ""
echo "--- bootout (stale unloads — errors here are normally fine) ---"
for p in "${AGENTS[@]}"; do
    launchctl bootout "gui/${UID_VAL}/com.kitchenos.${p}" 2>&1 | sed "s/^/  ${p}: /"
done

echo ""
echo "--- bootstrap from plists ---"
for p in "${AGENTS[@]}"; do
    plist="$HOME/Library/LaunchAgents/com.kitchenos.${p}.plist"
    if [[ ! -f "$plist" ]]; then
        echo "  ${p}: SKIP (plist not found)"
        continue
    fi
    launchctl bootstrap "gui/${UID_VAL}" "$plist" 2>&1 | sed "s/^/  ${p}: /"
done

echo ""
echo "--- loaded kitchenos agents ---"
launchctl list | grep kitchenos || echo "  (none loaded — check errors above)"
