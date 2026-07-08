# Cleanup & Consolidate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate three on-disk KitchenOS code copies into one canonical repo at `~/KitchenOS/`, move Obsidian vault data into `~/KitchenOS/vault/` (gitignored), and demolish the duplicates.

**Architecture:** Strictly mechanical migration. Code stays at repo root (no `app/` rename). The Obsidian vault becomes a gitignored subfolder. A single `lib/paths.py` helper centralizes the vault path — every script reads from there instead of hardcoding the iCloud path. LaunchAgent plists move into `ops/` and get reinstalled to point at `~/KitchenOS/`.

**Tech Stack:** Python 3.11, bash, launchctl, git, Obsidian Sync.

**Source design:** `docs/plans/2026-04-25-cleanup-and-consolidate-design.md`

**Critical:** The verification gate (Task 9) is non-negotiable. Do not proceed to deletion (Task 10+) until every check passes.

---

## Pre-flight check

Before starting any task, confirm baseline:

```bash
pwd                                     # /Users/chaseeasterling/KitchenOS
git -C ~/KitchenOS status               # tree clean except known SESSION_SUMMARY.md deletion
git -C ~/KitchenOS rev-parse HEAD       # 4a011e2 or later (design + plan committed)
ls ~/Documents/GitHub/KitchenOS         # exists (will delete in Task 10)
ls "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"  # exists
launchctl list | grep kitchenos | wc -l # 4
```

Stop here if anything is unexpected.

---

## Task 1: Backup and push baseline

**Why:** Make every later step reversible. The tarball is the ultimate undo button; the GitHub push pins the canonical commits remotely.

**Step 1.1: Create backup directory**

```bash
mkdir -p ~/Backups
ls ~/Backups
```
Expected: `~/Backups` exists (may or may not contain prior backups).

**Step 1.2: Tarball the iCloud vault**

```bash
cd "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents"
tar -czf ~/Backups/kitchenos-icloud-2026-04-25.tar.gz KitchenOS
ls -lh ~/Backups/kitchenos-icloud-2026-04-25.tar.gz
```
Expected: file exists, size > 5 MB (recipe markdown + images).

**Step 1.3: Push canonical repo to GitHub**

```bash
cd ~/KitchenOS
git push origin main
```
Expected: `Everything up-to-date` OR a normal push of new commits. No errors.

**Step 1.4: Review checkpoint**

User confirms tarball exists and `git log origin/main` matches local `main`. Do not proceed otherwise.

---

## Task 2: Stop running services

**Why:** Files we're about to move are open by these processes. Quiesce them first.

**Step 2.1: Unload all four LaunchAgents**

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl unload ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist
launchctl unload ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist
launchctl unload ~/Library/LaunchAgents/com.kitchenos.mealplan.plist
```
Expected: no output on success. Each `unload` prints nothing if it worked.

**Step 2.2: Verify all four are gone**

```bash
launchctl list | grep kitchenos
```
Expected: zero output (no matches). If any remain, repeat unload for the survivor.

**Step 2.3: Confirm API server is no longer responding**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/health
```
Expected: `000` or `Connection refused`. Anything 2xx means a service is still running — investigate before proceeding.

**Step 2.4: Quit Obsidian on Mac**

Manual action: ⌘Q out of Obsidian. We'll reopen it pointing at the new vault later. (Don't quit Obsidian on iPad; we'll reconfigure Sync from there in Task 5.)

**Step 2.5: Pause Obsidian Sync (manual)**

Open Obsidian briefly only if needed, go to Settings → Sync → toggle off Sync for the current vault, then quit again. Or use the menu before quitting in 2.4. The point is Sync should NOT be live during the file move.

**Step 2.6: Review checkpoint**

User confirms all services stopped, Obsidian quit, Sync paused.

---

## Task 3: Add `lib/paths.py` (centralize vault path)

**Why:** Eleven Python files hardcode the iCloud path. Replace them with one helper that reads `KITCHENOS_VAULT` env var, falls back to `~/KitchenOS/vault/`. After this task, changing the vault location is a one-line edit.

**Files:**
- Create: `lib/paths.py`
- Create: `tests/test_paths.py`

**Step 3.1: Write the failing test**

Create `tests/test_paths.py`:

```python
"""Tests for lib.paths vault location helper."""
import os
from pathlib import Path

import pytest

from lib import paths


def test_default_vault_is_home_kitchenos_vault(monkeypatch):
    monkeypatch.delenv("KITCHENOS_VAULT", raising=False)
    assert paths.vault_root() == Path.home() / "KitchenOS" / "vault"


def test_env_override_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.vault_root() == tmp_path


def test_env_override_expands_tilde(monkeypatch):
    monkeypatch.setenv("KITCHENOS_VAULT", "~/some/place")
    assert paths.vault_root() == Path.home() / "some" / "place"


def test_recipes_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.recipes_dir() == tmp_path / "Recipes"


def test_meal_plans_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.meal_plans_dir() == tmp_path / "Meal Plans"


def test_shopping_lists_dir_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.shopping_lists_dir() == tmp_path / "Shopping Lists"


def test_calendar_ics_path_is_under_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("KITCHENOS_VAULT", str(tmp_path))
    assert paths.calendar_ics_path() == tmp_path / "meal_calendar.ics"
```

**Step 3.2: Run test to verify it fails**

```bash
cd ~/KitchenOS
.venv/bin/pytest tests/test_paths.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.paths'` or similar — `lib.paths` does not exist yet.

**Step 3.3: Write minimal implementation**

Create `lib/paths.py`:

```python
"""Centralized vault path resolution.

The vault location is configurable via the KITCHENOS_VAULT environment
variable. Default is ~/KitchenOS/vault/.

All recipe-data paths in the codebase should be derived from these
helpers — never hardcoded.
"""
import os
from pathlib import Path


def vault_root() -> Path:
    """Return the Obsidian vault root directory."""
    raw = os.environ.get("KITCHENOS_VAULT")
    if raw:
        return Path(os.path.expanduser(raw))
    return Path.home() / "KitchenOS" / "vault"


def recipes_dir() -> Path:
    return vault_root() / "Recipes"


def meal_plans_dir() -> Path:
    return vault_root() / "Meal Plans"


def shopping_lists_dir() -> Path:
    return vault_root() / "Shopping Lists"


def calendar_ics_path() -> Path:
    return vault_root() / "meal_calendar.ics"
```

**Step 3.4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_paths.py -v
```
Expected: 7 passed.

**Step 3.5: Commit**

```bash
git add lib/paths.py tests/test_paths.py
git commit -m "feat: add lib.paths helper for vault location

Centralized vault path resolution with KITCHENOS_VAULT env var
and ~/KitchenOS/vault/ default. Replaces hardcoded iCloud paths
in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**Step 3.6: Review checkpoint**

User confirms test passes and commit is clean.

---

## Task 4: Replace hardcoded vault paths in callers

**Why:** Wire the 11 caller files into `lib.paths`. After this, no Python file mentions `Mobile Documents` or `iCloud~md~obsidian` outside of historical doc references.

**Files (11 total):**
- `extract_recipe.py`
- `api_server.py`
- `migrate_recipes.py`
- `migrate_cuisine.py`
- `import_crouton.py`
- `generate_meal_plan.py`
- `generate_nutrition_dashboard.py`
- `shopping_list.py`
- `sync_calendar.py`
- `lib/shopping_list_generator.py`
- `scripts/add_button_to_meal_plans.py`

**Step 4.1: For each file, locate and replace the hardcoded path**

For each file, find the existing pattern (one of):
```python
OBSIDIAN_RECIPES_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Recipes")
OBSIDIAN_VAULT = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS")
MEAL_PLANS_PATH = Path("/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/Meal Plans")
```

Replace with the appropriate helper call. Examples:

```python
from lib import paths

OBSIDIAN_RECIPES_PATH = paths.recipes_dir()
OBSIDIAN_VAULT = paths.vault_root()
MEAL_PLANS_PATH = paths.meal_plans_dir()
```

For `api_server.py:497` (the inline `ics_path` and `vault_path`):

```python
ics_path = paths.calendar_ics_path()
vault_path = paths.vault_root()
```

For files using two-line concatenated path constants (`migrate_cuisine.py`, `import_crouton.py`, `generate_nutrition_dashboard.py`), collapse to a single helper call.

**Step 4.2: Quick smoke test — module imports still work**

```bash
.venv/bin/python -c "import api_server; import extract_recipe; import shopping_list; import sync_calendar; import generate_meal_plan; import generate_nutrition_dashboard; import import_crouton; import migrate_recipes; import migrate_cuisine; from lib import shopping_list_generator; print('OK')"
```
Expected: `OK`. Any ImportError means a typo.

**Step 4.3: Verify zero hardcoded references remain**

```bash
grep -rn "Mobile Documents\|iCloud~md~obsidian" --include="*.py" --include="*.sh" .
```
Expected: zero hits. (Hits in `docs/` markdown files are fine — they're historical and won't be touched.)

**Step 4.4: Run the full test suite**

```bash
.venv/bin/pytest -q
```
Expected: all tests pass. If pre-existing failures are unrelated to this change, note them but don't fix in this commit.

**Step 4.5: Dry-run extraction with a test video**

Note: at this point `~/KitchenOS/vault/` does NOT yet exist. Pass an explicit env var to point at the still-live iCloud vault so the dry-run resolves recipe data:

```bash
KITCHENOS_VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS" \
  .venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```
Expected: dry-run completes, prints recipe JSON, no path-related errors.

**Step 4.6: Commit**

```bash
git add extract_recipe.py api_server.py migrate_recipes.py migrate_cuisine.py \
  import_crouton.py generate_meal_plan.py generate_nutrition_dashboard.py \
  shopping_list.py sync_calendar.py lib/shopping_list_generator.py \
  scripts/add_button_to_meal_plans.py
git commit -m "refactor: replace hardcoded vault paths with lib.paths helpers

Routes all 11 callers through lib.paths.* (vault_root, recipes_dir,
meal_plans_dir, shopping_lists_dir, calendar_ics_path). No behavior
change — current default still resolves data via KITCHENOS_VAULT
override, will resolve to ~/KitchenOS/vault/ once data is moved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**Step 4.7: Review checkpoint**

User confirms zero grep hits, dry-run worked, tests pass.

---

## Task 5: Move vault data from iCloud to `~/KitchenOS/vault/`

**Why:** This is the actual relocation. Use `mv` (not `cp`) so we don't temporarily double-occupy disk and so any in-flight sync conflicts surface immediately rather than later.

**Pre-step check:** Obsidian app must be quit (Task 2.4), Sync paused (Task 2.5).

**Step 5.1: Create the target structure**

```bash
mkdir -p ~/KitchenOS/vault
mkdir -p ~/KitchenOS/vault/Inventory
mkdir -p ~/KitchenOS/vault/Dashboards
ls ~/KitchenOS/vault
```
Expected: `Dashboards  Inventory` (just those two empty dirs so far).

**Step 5.2: Move user data folders**

```bash
ICLOUD="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
mv "$ICLOUD/Recipes" ~/KitchenOS/vault/
mv "$ICLOUD/Meal Plans" ~/KitchenOS/vault/
mv "$ICLOUD/Shopping Lists" ~/KitchenOS/vault/
mv "$ICLOUD/.obsidian" ~/KitchenOS/vault/
ls ~/KitchenOS/vault
```
Expected: `.obsidian  Dashboards  Inventory  Meal Plans  Recipes  Shopping Lists`.

**Step 5.3: Move dashboard / canvas / base files**

```bash
ICLOUD="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
mv "$ICLOUD/Home.md" ~/KitchenOS/vault/Dashboards/
mv "$ICLOUD/Dashboard.md" ~/KitchenOS/vault/Dashboards/
mv "$ICLOUD/KitchenOS Dashboard.canvas" ~/KitchenOS/vault/Dashboards/
mv "$ICLOUD"/*.base ~/KitchenOS/vault/Dashboards/   # Recipes by Cuisine.base, Untitled.base, etc.
mv "$ICLOUD/Macro Worksheet.md" ~/KitchenOS/vault/
mv "$ICLOUD/Quick Add Template.md" ~/KitchenOS/vault/
mv "$ICLOUD/meal_calendar.ics" ~/KitchenOS/vault/ 2>/dev/null || true
ls ~/KitchenOS/vault/Dashboards
```
Expected: `Home.md`, `Dashboard.md`, `KitchenOS Dashboard.canvas`, plus the `.base` files.

**Step 5.4: Audit what remains in iCloud — should be only duplicated code**

```bash
ls "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS"
```
Expected: only the duplicated code (`api_server.py`, `lib/`, `prompts/`, `templates/`, `scripts/`, `config/`, `tests/`, `*.plist`, `requirements.txt`, `CLAUDE.md`, `README.md`, `LICENSE`, `KitchenOSApp/`, `dashboard_update.log`, etc.) and possibly leftover `docs/`. **No** `Recipes/`, `Meal Plans/`, `Shopping Lists/`, `.obsidian/`, dashboards, `*.base`, or `*.canvas`. If user data is still there, repeat the appropriate `mv` from 5.2/5.3.

**Step 5.5: Sanity-check vault contents**

```bash
echo "Recipes:";       ls ~/KitchenOS/vault/Recipes | wc -l
echo "Meal Plans:";    ls ~/KitchenOS/vault/"Meal Plans" | wc -l
echo "Shopping Lists:";ls ~/KitchenOS/vault/"Shopping Lists" | wc -l
echo ".obsidian/plugins:"; ls ~/KitchenOS/vault/.obsidian/plugins | wc -l
```
Expected: nonzero counts in each. Remember the rough count of recipes for Task 9 verification.

**Step 5.6: Update `.gitignore`**

In `~/KitchenOS/.gitignore`, replace the existing "Obsidian vault content" block with:

```
# ============================================
# Obsidian vault (lives at vault/, synced via Obsidian Sync)
# ============================================
vault/

# ============================================
# Logs (gitignored — see logs/ subdir for new code, root logs are legacy)
# ============================================
logs/
*.log
```

Old entries to remove: `Recipes/`, `Meal Plans/`, `Shopping Lists/`, `*.base`, `meal_calendar.ics`, `Dashboard.md`, `Home.md`, `Quick Add Template.md`, the `.obsidian/workspace*` lines (now under vault/, all ignored).

**Step 5.7: Verify nothing in vault/ is tracked by git**

```bash
cd ~/KitchenOS
git status --short
git ls-files vault/ | head     # should be empty
```
Expected: `git ls-files vault/` returns nothing. `git status` may show modified `.gitignore` and any moved files git was previously aware of.

**Step 5.8: Commit `.gitignore` update**

```bash
git add .gitignore
git commit -m "chore: gitignore the new vault/ subfolder

Replaces per-file vault entries (Recipes/, Meal Plans/, etc.) with
single vault/ ignore. Also gitignores logs/ and root *.log.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**Step 5.9: Review checkpoint**

User confirms vault contents are present, recipe count looks right, iCloud has only code copies left.

---

## Task 6: Reconfigure Obsidian Sync to track new vault

**Why:** Get iPad / Mac Obsidian back online, pointing at the new local vault.

**Step 6.1: Open Obsidian on Mac**

Manual action. Open Obsidian → "Open folder as vault" → pick `~/KitchenOS/vault/`. The vault opens with all recipes visible.

**Step 6.2: Re-enable Obsidian Sync on this vault**

Settings → Sync → Choose remote vault. Either:

- (a) **If the existing remote vault matches** (most likely — the `.obsidian/` we moved already had Sync configured) — turn Sync back on. It will reconcile.
- (b) **If the remote shows the old iCloud-located vault as the source** — set up Sync fresh on `~/KitchenOS/vault/`, name it "KitchenOS", select all categories (notes, attachments, canvas, .obsidian config, etc.).

Wait until Sync status shows "Fully synced" (or the equivalent in the current Obsidian version).

**Step 6.3: Verify on iPad**

Open Obsidian on iPad. The vault should still be there (Sync should reconcile to the new source). Browse to `Recipes/` and confirm a known recipe loads. If iPad shows an out-of-date version, leave Sync running for a couple minutes.

**Step 6.4: Review checkpoint**

User confirms Mac and iPad both show recipes from `~/KitchenOS/vault/`. Do not proceed if iPad is broken — debug Sync first.

---

## Task 7: Move plists into `ops/` and rewrite paths

**Why:** Plists currently point at `~/Documents/GitHub/KitchenOS/`. Repoint to `~/KitchenOS/`. While we're at it, move the plist source files into `ops/` so the repo root has fewer top-level files.

**Files (4):**
- `com.kitchenos.api.plist`
- `com.kitchenos.batch-extract.plist`
- `com.kitchenos.calendar-sync.plist`
- `com.kitchenos.mealplan.plist`

**Step 7.1: Create `ops/` and move plists**

```bash
cd ~/KitchenOS
mkdir -p ops
git mv com.kitchenos.api.plist ops/
git mv com.kitchenos.batch-extract.plist ops/
git mv com.kitchenos.calendar-sync.plist ops/
git mv com.kitchenos.mealplan.plist ops/
ls ops
```
Expected: 4 plist files in `ops/`.

**Step 7.2: Rewrite paths in each plist**

For each plist in `ops/`, replace `/Users/chaseeasterling/Documents/GitHub/KitchenOS` with `/Users/chaseeasterling/KitchenOS`. This changes:
- `<string>` for python interpreter (`/.venv/bin/python`)
- `<string>` for the script path
- `<string>` for `WorkingDirectory`
- `<string>` for `StandardOutPath` and `StandardErrorPath`

Use sed for the bulk rename (preview first, then in-place):

```bash
# Preview
grep -n "Documents/GitHub/KitchenOS" ops/*.plist
# Apply
sed -i '' 's|/Users/chaseeasterling/Documents/GitHub/KitchenOS|/Users/chaseeasterling/KitchenOS|g' ops/*.plist
# Verify
grep -n "Documents/GitHub/KitchenOS" ops/*.plist  # should print nothing
grep -n "Users/chaseeasterling/KitchenOS" ops/*.plist | head
```
Expected: zero hits for the old path. Several hits for the new path in each plist.

**Step 7.3: Reroute log paths to `logs/`**

While we're editing plists, point `StandardOutPath` / `StandardErrorPath` at `~/KitchenOS/logs/<service>.log` instead of repo root. First create the logs dir:

```bash
mkdir -p ~/KitchenOS/logs
```

Then in each plist, change:
- `com.kitchenos.api`: log path → `/Users/chaseeasterling/KitchenOS/logs/server.log`
- `com.kitchenos.batch-extract`: log path → `/Users/chaseeasterling/KitchenOS/logs/batch_extract.log`
- `com.kitchenos.calendar-sync`: log path → `/Users/chaseeasterling/KitchenOS/logs/calendar_sync.log`
- `com.kitchenos.mealplan`: log path → `/Users/chaseeasterling/KitchenOS/logs/meal_plan_generator.log`

**Step 7.4: Move existing root-level logs into `logs/` (best-effort)**

```bash
cd ~/KitchenOS
mv server.log batch_extract.log calendar_sync.log meal_plan_generator.log failure_analysis.log logs/ 2>/dev/null || true
ls logs/
```
Expected: existing logs are now in `logs/`. Some may not exist; that's fine.

**Step 7.5: Reinstall plists into `~/Library/LaunchAgents/`**

```bash
cp ops/com.kitchenos.api.plist ~/Library/LaunchAgents/
cp ops/com.kitchenos.batch-extract.plist ~/Library/LaunchAgents/
cp ops/com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
cp ops/com.kitchenos.mealplan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist
```
Expected: no errors.

**Step 7.6: Verify all four are loaded**

```bash
launchctl list | grep kitchenos
```
Expected: 4 lines, each ending in a non-negative exit code (`-` is fine for "not yet exited"; large negative numbers indicate failure).

**Step 7.7: Verify api server is up**

```bash
sleep 3
curl -s http://localhost:5001/health
```
Expected: 200 OK with a body.

**Step 7.8: Check api server log for errors**

```bash
tail -n 50 ~/KitchenOS/logs/server.log
```
Expected: startup banner, route registrations, no Python tracebacks.

**Step 7.9: Commit**

```bash
cd ~/KitchenOS
git add ops/ .gitignore  # plists moved (git mv) and gitignore already covers logs/
# logs/ contents are gitignored; nothing to add there
git commit -m "chore: move LaunchAgent plists into ops/ and repoint to ~/KitchenOS

Plists now reference /Users/chaseeasterling/KitchenOS/ instead of
/Users/chaseeasterling/Documents/GitHub/KitchenOS/. Standard out/err
log paths redirected to logs/ subdir.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**Step 7.10: Review checkpoint**

User confirms `launchctl list | grep kitchenos` shows 4 entries, `/health` returns 200, log tail looks clean.

---

## Task 8: Update CLAUDE.md and check ancillary configs

**Why:** CLAUDE.md is loaded every session. Stale paths there mislead future Claude runs. Also check MCP and the URI handler.

**Step 8.1: Update CLAUDE.md vault path references**

In `~/KitchenOS/CLAUDE.md`, find the `## Key Paths` table and the section that says:

> **Obsidian Vault**: `/Users/chaseeasterling/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS/`

Change to:

> **Obsidian Vault**: `~/KitchenOS/vault/` (configurable via `KITCHENOS_VAULT` env var)

Also update the LaunchAgent install instructions: `cp com.kitchenos.*.plist ~/Library/LaunchAgents/` → `cp ops/*.plist ~/Library/LaunchAgents/`. Update log tail commands: `tail -f /Users/chaseeasterling/KitchenOS/server.log` → `tail -f ~/KitchenOS/logs/server.log` (and similar for batch_extract, calendar_sync).

**Step 8.2: Check MCP config**

```bash
grep -n "Documents/GitHub/KitchenOS\|Mobile Documents" "$HOME/Library/Application Support/Claude/claude_desktop_config.json" 2>/dev/null
```
If hits: edit that file, replace `/Users/chaseeasterling/Documents/GitHub/KitchenOS` with `/Users/chaseeasterling/KitchenOS`. (This file is system-level, not in the repo.)

**Step 8.3: Check `.mcp.json` in the repo**

```bash
grep -n "Documents/GitHub/KitchenOS\|Mobile Documents" ~/KitchenOS/.mcp.json
```
If hits: edit the file to use `~/KitchenOS/`.

**Step 8.4: Check the URI handler**

```bash
cat ~/KitchenOS/scripts/kitchenos-uri-handler/handler.sh
```
If it contains hardcoded `Documents/GitHub/KitchenOS` paths, edit to use `~/KitchenOS`. Note: if the handler is registered system-wide (in `~/Library/Application Support/`), it may need re-registration.

**Step 8.5: Commit**

```bash
cd ~/KitchenOS
git add CLAUDE.md .mcp.json scripts/kitchenos-uri-handler/handler.sh
git commit -m "docs: update CLAUDE.md and configs for new paths

Vault is now ~/KitchenOS/vault/. LaunchAgent install path is
ops/*.plist. Log paths are under logs/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If `.mcp.json` and the handler had no changes, omit them from `git add`.

**Step 8.6: Push everything to GitHub**

```bash
git push origin main
```
Expected: clean push.

**Step 8.7: Review checkpoint**

User confirms CLAUDE.md is updated and changes are pushed.

---

## Task 9: VERIFICATION GATE — must pass before deletion

**Why:** This is the firewall between reversible work and destructive deletion. **Do not skip any check.** If any fails, fix it before proceeding to Task 10.

**Step 9.1: No hardcoded vault paths in code**

```bash
cd ~/KitchenOS
grep -rn "Mobile Documents\|iCloud~md~obsidian" --include="*.py" --include="*.sh" --include="*.plist" --include="*.json" --include="*.html" .
```
Expected: zero hits in code/config. (Hits in `docs/` markdown are fine — they're history.)

**Step 9.2: Smoke-test extraction**

```bash
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"
```
Expected: completes without error, prints recipe JSON. The vault path it resolves should be `~/KitchenOS/vault/` (visible in any "would write to" output).

**Step 9.3: API server health**

```bash
curl -s http://localhost:5001/health
```
Expected: 200 OK with body.

**Step 9.4: API server can list recipes from new vault**

```bash
curl -s http://localhost:5001/api/recipes | python -m json.tool | head -30
```
Expected: a JSON array with recipe entries from `~/KitchenOS/vault/Recipes/`.

**Step 9.5: All four LaunchAgents loaded with no failure exit codes**

```bash
launchctl list | grep kitchenos
```
Expected: 4 entries. The middle column is the last exit code; `0` or `-` is OK, large negative numbers (`-9`, `-15`) or `78` indicate failure.

**Step 9.6: Vault content count sanity check**

```bash
echo "Recipes:       $(ls ~/KitchenOS/vault/Recipes | wc -l)"
echo "Meal Plans:    $(ls ~/KitchenOS/vault/Meal\ Plans | wc -l)"
echo "Shopping Lists:$(ls ~/KitchenOS/vault/Shopping\ Lists | wc -l)"
```
Expected: counts match what the user remembers from before the move.

**Step 9.7: Mac Obsidian opens vault from new location**

Manual: Mac Obsidian shows the vault rooted at `~/KitchenOS/vault/`. Any known recipe opens correctly.

**Step 9.8: iPad Obsidian shows the same recipes via Sync**

Manual: open Obsidian on iPad, browse `Recipes/`, confirm a recipe matches Mac.

**Step 9.9: pytest suite passes**

```bash
.venv/bin/pytest -q
```
Expected: green. Pre-existing flakes are tolerable but should be noted.

**Step 9.10: Review checkpoint — explicit go/no-go**

User explicitly says **"verification passed, proceed to delete"** before Task 10. If any check failed, stop here and fix before deletion.

---

## Task 10: Delete `~/Documents/GitHub/KitchenOS/`

**Why:** Eliminate the second code copy that LaunchAgents used to point at. After Task 7 they no longer point here, so this directory is fully orphaned.

**Step 10.1: Confirm nothing in the running system references this path**

```bash
grep -rn "Documents/GitHub/KitchenOS" ~/Library/LaunchAgents/com.kitchenos.*.plist
grep -n "Documents/GitHub/KitchenOS" "$HOME/Library/Application Support/Claude/claude_desktop_config.json" 2>/dev/null
launchctl list | grep kitchenos | xargs -I {} echo {}
```
Expected: zero hits referencing the old path.

**Step 10.2: List what's about to be deleted (last look)**

```bash
ls ~/Documents/GitHub/KitchenOS
du -sh ~/Documents/GitHub/KitchenOS
```
Expected: matches your memory of the older clone (api_server.py, lib/, etc.). The size will probably be around the .venv size (~hundreds of MB).

**Step 10.3: Delete the directory**

```bash
rm -rf ~/Documents/GitHub/KitchenOS
ls ~/Documents/GitHub/ 2>/dev/null
```
Expected: `~/Documents/GitHub/KitchenOS` no longer listed. The parent `~/Documents/GitHub/` may still exist with other repos — leave it.

**Step 10.4: Verify services are still healthy**

```bash
curl -s http://localhost:5001/health
launchctl list | grep kitchenos | wc -l
```
Expected: 200 OK and 4. If anything broke, the LaunchAgents were still using the old path somehow — restore from a workspace-level Time Machine snapshot or re-clone.

**Step 10.5: Review checkpoint**

User confirms directory is gone and services are still up.

---

## Task 11: Rename iCloud vault for delayed deletion

**Why:** The iCloud copy is the last redundant code+data location. Rename it (don't delete yet) so it still exists as a recovery option for 7 days, but the rename signals it's no longer authoritative.

**Step 11.1: Confirm the iCloud copy is no longer referenced**

```bash
grep -rn "Mobile Documents\|iCloud~md~obsidian" --include="*.py" --include="*.sh" --include="*.plist" --include="*.json" ~/KitchenOS/
```
Expected: zero hits.

**Step 11.2: Rename the iCloud vault**

```bash
ICLOUD_PARENT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents"
mv "$ICLOUD_PARENT/KitchenOS" "$ICLOUD_PARENT/KitchenOS.OLD-DELETE-AFTER-2026-05-02"
ls "$ICLOUD_PARENT"
```
Expected: directory now named with the deletion-date suffix.

**Step 11.3: Verify the running system still works**

```bash
curl -s http://localhost:5001/health
.venv/bin/python -c "from lib import paths; print(paths.vault_root())"
```
Expected: 200 OK; vault_root prints `/Users/chaseeasterling/KitchenOS/vault`. Nothing should fall over because we already moved off iCloud in Task 5.

**Step 11.4: Confirm Obsidian iPad still works after the rename**

Manual: open Obsidian on iPad once more. Recipes should still load (because Obsidian Sync is now sourcing from `~/KitchenOS/vault/`, not iCloud). If iPad now sees a phantom "KitchenOS.OLD..." vault, it's a Sync UI artifact — safe to ignore or remove from the Sync source list.

**Step 11.5: Review checkpoint**

User confirms iCloud rename is in place and nothing depends on it. **At this point, the migration is functionally complete.**

---

## Task 12: Schedule the final iCloud deletion (manual, +7 days)

**Why:** A week of running on the new layout makes a hidden missing-file regression very unlikely. After that, the rename's purpose has been served.

**Step 12.1: Calendar reminder**

Set a manual reminder (Reminders app, calendar event, or `/schedule` agent) for **2026-05-02** with body:

> Delete iCloud KitchenOS leftover: `rm -rf "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/KitchenOS.OLD-DELETE-AFTER-2026-05-02"`. Verify backup tarball still exists at `~/Backups/kitchenos-icloud-2026-04-25.tar.gz`. Confirm `~/KitchenOS/vault/` still works on Mac and iPad before deleting.

**Step 12.2: Recommended `/schedule` offer**

After plan execution completes, offer `/schedule` an agent for 2026-05-02 to perform Step 12.1's verification and (if green) actually delete the iCloud directory.

**Step 12.3: Final review checkpoint**

User confirms the reminder is set.

---

## Final state

```
~/KitchenOS/                                ← single canonical repo
├── api_server.py, extract_recipe.py, …    ← code at root, untouched
├── lib/, prompts/, templates/, scripts/, config/, tests/
├── lib/paths.py                            ← NEW: centralized vault config
├── tests/test_paths.py                     ← NEW
├── docs/
├── ops/                                    ← NEW: 4 plists
├── KitchenOSApp/
├── logs/                       (gitignored, contains live logs)
├── failures/                   (gitignored)
├── .venv/                      (gitignored)
└── vault/                      (gitignored, Obsidian Sync source)
    ├── .obsidian/, Recipes/, Meal Plans/, Shopping Lists/
    ├── Inventory/  (empty placeholder)
    ├── Dashboards/
    └── Macro Worksheet.md, meal_calendar.ics, …
```

Deleted: `~/Documents/GitHub/KitchenOS/`. Renamed pending deletion: iCloud `KitchenOS.OLD-DELETE-AFTER-2026-05-02/`.

GitHub: `SlowSpeedChase/KitchenOS` `main` is the canonical history.

---

## Risks index (cross-reference to design doc)

| Risk | Mitigated in |
|---|---|
| Missed hardcoded path | Task 4.3 grep, Task 9.1 grep |
| Obsidian Sync confusion | Task 2.5 pause, Task 6 reconfigure |
| `.obsidian/` config drift | Task 5.2 — move iCloud's `.obsidian/`, not repo-root copy |
| LaunchAgents fail silently | Task 7.6, Task 7.8, Task 9.5 |
| Stale `.venv` in old GitHub clone | Task 10.3 deletes whole tree |
| MCP/Claude Desktop stale paths | Task 8.2, Task 8.3 |
| URI handler stale paths | Task 8.4 |
| iCloud delete data loss | Task 1.2 tarball; Task 11 rename-not-delete; Task 12 +7-day delay |

---

## Dependencies between tasks

```
1 (backup+push) → 2 (stop services) → 3 (lib/paths.py) → 4 (replace callers)
4 → 5 (move data) → 6 (reconfigure Sync) → 7 (move plists, restart)
7 → 8 (docs/MCP) → 9 (VERIFICATION GATE)
9 → 10 (delete GitHub copy) → 11 (rename iCloud) → 12 (schedule final delete)
```

Each task has a Review Checkpoint at the end; do not start the next task until the current task's user confirmation lands.
