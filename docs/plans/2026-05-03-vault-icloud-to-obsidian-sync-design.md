# Vault Migration: iCloud → Local Disk + Obsidian Sync

**Date:** 2026-05-03  
**Status:** Approved

## Goal

Move the KitchenOS Obsidian vault from iCloud (`~/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS`) to a local path adjacent to the code (`~/KitchenOS/vault/`), and use Obsidian Sync for cross-device access (Mac, iPhone, iPad, other Mac).

## Why

- Remove iCloud as a dependency; keep data local
- `~/KitchenOS/vault/` is already the hardcoded default in `lib/paths.py` — removing the env var simplifies config
- Obsidian Sync is more reliable for Obsidian-specific content than iCloud Drive

## Code-Side Changes

1. Copy vault files: `cp -r "<iCloud path>/KitchenOS/" ~/KitchenOS/vault/`
2. Remove `export KITCHENOS_VAULT=...` from `~/.zshrc`
3. Remove `KITCHENOS_VAULT` key+value from 4 LaunchAgent plists:
   - `com.kitchenos.mealplan.plist`
   - `com.kitchenos.calendar-sync.plist`
   - `com.kitchenos.batch-extract.plist`
   - `com.kitchenos.dashboard-update.plist`
4. Reload all 4 LaunchAgents (`launchctl unload` + `launchctl load`)
5. Smoke-test: `curl http://localhost:5001/health`

## Obsidian-Side Steps (manual)

1. In Obsidian on this Mac: Open folder as vault → `~/KitchenOS/vault/`
2. Settings → Sync → Create new remote vault (name: KitchenOS)
3. Wait for full upload
4. On iPhone, iPad, other Mac: Settings → Sync → Connect → pick KitchenOS remote vault
5. Once confirmed on all devices, remove old iCloud vault from Obsidian on each device
6. Optionally delete `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/` after confirming

## Non-goals

- No changes to `lib/paths.py` (default is already correct)
- No changes to API server (it inherits env from shell; once `KITCHENOS_VAULT` is removed it uses the default)
- No git-tracking of vault files
