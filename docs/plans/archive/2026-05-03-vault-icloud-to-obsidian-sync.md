# Vault Migration: iCloud → Local + Obsidian Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the KitchenOS vault from iCloud to `~/KitchenOS/vault/` and remove all iCloud path references from config.

**Architecture:** The `lib/paths.py` default is already `~/KitchenOS/vault/` — no code changes needed. The ops/ plist copies are already clean (no `KITCHENOS_VAULT`). Migration is: copy files, remove env var from `.zshrc`, copy clean plists over installed ones, reload LaunchAgents. Obsidian Sync setup is manual.

**Tech Stack:** bash, launchctl, Obsidian

---

### Task 1: Copy vault files to local path

**Files:**
- Source: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/`
- Destination: `~/KitchenOS/vault/`

**Step 1: Create the destination directory and copy**

```bash
mkdir -p ~/KitchenOS/vault
rsync -av --progress \
  "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/" \
  "/Users/chaseeasterling/KitchenOS/vault/"
```

**Step 2: Verify the copy**

```bash
ls ~/KitchenOS/vault/
```

Expected: see `Recipes`, `Meal Plans`, `Shopping Lists`, `Meals`, `Inventory`, `meal_calendar.ics`, etc.

```bash
# Spot-check recipe count matches
ls "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes/" | wc -l
ls ~/KitchenOS/vault/Recipes/ | wc -l
```

Expected: counts match.

---

### Task 2: Remove KITCHENOS_VAULT from ~/.zshrc

**Files:**
- Modify: `~/.zshrc` (line 26)

**Step 1: Verify the line**

```bash
grep -n "KITCHENOS_VAULT" ~/.zshrc
```

Expected: one line like `26: export KITCHENOS_VAULT="/Users/chaseeasterling/Library/Mobile Documents/..."`

**Step 2: Remove it**

Open `~/.zshrc` in an editor and delete the line:
```
export KITCHENOS_VAULT="/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
```

**Step 3: Verify it's gone**

```bash
grep "KITCHENOS_VAULT" ~/.zshrc
```

Expected: no output.

**Step 4: Reload shell config**

```bash
source ~/.zshrc
echo $KITCHENOS_VAULT
```

Expected: empty output (env var is unset).

**Step 5: Verify Python uses the new path**

```bash
cd ~/KitchenOS
.venv/bin/python -c "from lib.paths import vault_root; print(vault_root())"
```

Expected: `/Users/chaseeasterling/KitchenOS/vault`

**Step 6: Commit**

```bash
cd ~/KitchenOS
git add -p  # nothing to stage — .zshrc is not tracked
# No git commit needed for this step (zshrc is not in the repo)
```

---

### Task 3: Update LaunchAgent plists

The `ops/` directory already has clean plist copies without `KITCHENOS_VAULT`. Copy them over the installed versions for all 4 affected agents.

**Files:**
- `ops/com.kitchenos.mealplan.plist` → `~/Library/LaunchAgents/com.kitchenos.mealplan.plist`
- `ops/com.kitchenos.batch-extract.plist` → `~/Library/LaunchAgents/com.kitchenos.batch-extract.plist`
- `ops/com.kitchenos.calendar-sync.plist` → `~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist`
- `ops/com.kitchenos.dashboard-update.plist` → `~/Library/LaunchAgents/com.kitchenos.dashboard-update.plist`

**Step 1: Verify the ops/ copies are clean (no KITCHENOS_VAULT)**

```bash
grep "KITCHENOS_VAULT" ~/KitchenOS/ops/com.kitchenos.mealplan.plist \
  ~/KitchenOS/ops/com.kitchenos.batch-extract.plist \
  ~/KitchenOS/ops/com.kitchenos.calendar-sync.plist \
  ~/KitchenOS/ops/com.kitchenos.dashboard-update.plist
```

Expected: no output.

**Step 2: Copy clean plists to LaunchAgents**

```bash
cp ~/KitchenOS/ops/com.kitchenos.mealplan.plist ~/Library/LaunchAgents/
cp ~/KitchenOS/ops/com.kitchenos.batch-extract.plist ~/Library/LaunchAgents/
cp ~/KitchenOS/ops/com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
cp ~/KitchenOS/ops/com.kitchenos.dashboard-update.plist ~/Library/LaunchAgents/
```

**Step 3: Verify KITCHENOS_VAULT is gone from installed plists**

```bash
grep "KITCHENOS_VAULT" \
  ~/Library/LaunchAgents/com.kitchenos.mealplan.plist \
  ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist \
  ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist \
  ~/Library/LaunchAgents/com.kitchenos.dashboard-update.plist
```

Expected: no output.

---

### Task 4: Reload LaunchAgents

**Step 1: Unload and reload all 4 agents**

```bash
for label in com.kitchenos.mealplan com.kitchenos.batch-extract com.kitchenos.calendar-sync com.kitchenos.dashboard-update; do
  launchctl unload ~/Library/LaunchAgents/${label}.plist
  launchctl load ~/Library/LaunchAgents/${label}.plist
  echo "Reloaded $label"
done
```

Expected: `Reloaded com.kitchenos.mealplan` etc. for each (no error messages).

---

### Task 5: Smoke-test

**Step 1: Verify API server health**

```bash
curl http://localhost:5001/health
```

Expected: `{"status": "ok"}` or similar.

**Step 2: Verify API server resolves vault to new path**

```bash
curl -s http://localhost:5001/api/meal-plan/$(date +%G-W%V) | head -c 200
```

Expected: JSON response (not a file-not-found error).

**Step 3: Test a recipe list endpoint**

```bash
curl -s "http://localhost:5001/api/recipes?limit=3" | python3 -m json.tool | head -30
```

Expected: JSON list of recipes from `~/KitchenOS/vault/Recipes/`.

---

### Task 6: Obsidian Sync setup (manual — not automated)

Do these steps in the Obsidian UI after Tasks 1–5 are confirmed working.

**Step 1:** In Obsidian on this Mac:
- File → Open Folder as Vault → navigate to `~/KitchenOS/vault/` → Open

**Step 2:** Settings → Sync → Create new remote vault
- Name it: `KitchenOS`
- Wait for full upload to complete (watch the sync icon in the bottom bar)

**Step 3:** On iPhone:
- Settings → Sync → Connect to remote vault → pick `KitchenOS`

**Step 4:** On iPad:
- Same as iPhone

**Step 5:** On other Mac:
- Open Obsidian → Open Remote Vault → pick `KitchenOS` → choose a local path
- Recommended path on the other Mac: `~/KitchenOS/vault/` (consistent naming)

**Step 6:** Once sync is confirmed on all devices, remove old iCloud vault:
- In Obsidian on each device: close/remove the iCloud vault
- Optionally delete the source: `rm -rf "/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/"`
  - **Wait at least 24 hours and confirm Obsidian Sync is fully working before deleting**

---

### Notes

- The API server (`com.kitchenos.api.plist`) doesn't need changes — it has no `KITCHENOS_VAULT` in its plist and the new vault location matches the `lib/paths.py` default.
- `.env` doesn't need changes — `KITCHENOS_VAULT` was never in it.
- No Python code changes needed.
- Do not delete the iCloud vault until Obsidian Sync is confirmed working on all devices.
