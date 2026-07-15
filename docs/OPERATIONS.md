# KitchenOS Operations Runbook

The canonical home for running, deploying, and operating KitchenOS: one-off
CLI commands, the 7 LaunchAgents (install/logs/restart), operational
caveats, health checks, the failure-analysis agent, QuickAdd setup, the test
suite, the native app build/sign/deploy procedure, and the completing-work
checklist. For "what exists and why" see `docs/ARCHITECTURE.md`; for the
full HTTP route / MCP tool list see `docs/API.md`.

All Python commands run from the repo root using the project virtualenv:
`cd /Users/chaseeasterling/Dev/KitchenOS && .venv/bin/python ...`

---

## 1. One-off CLI commands

### Extract a recipe (primary use)

```bash
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Instagram Reel (same command — URL is auto-detected and routed)
.venv/bin/python extract_recipe.py "https://www.instagram.com/reel/REEL_ID/"

# Dry run (preview without saving)
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"
```

### Import from Crouton

```bash
.venv/bin/python import_crouton.py "/path/to/Crouton Recipes"
.venv/bin/python import_crouton.py --dry-run "/path/to/Crouton Recipes"
.venv/bin/python import_crouton.py --no-enrich "/path/to/Crouton Recipes"  # skip Ollama enrichment
```

### Fetch video data only

```bash
.venv/bin/python main.py --json "VIDEO_ID_OR_URL"
```

### Dedupe recipes (maintenance)

Finds duplicate recipe files (same `source_url`, or `X 2.md` Obsidian Sync
conflict copies) and **moves** the redundant copies to
`_Archive/custom-format-dupes/` — never deletes. Run after a Sync conflict or
a bulk re-extract.

```bash
.venv/bin/python scripts/dedupe_recipes.py          # dry-run: report only
.venv/bin/python scripts/dedupe_recipes.py --apply  # move dupes to _Archive
```

### Batch extract from Reminders

```bash
.venv/bin/python batch_extract.py             # process "Recipies to Process" list
.venv/bin/python batch_extract.py --dry-run   # preview
```

### Generate meal plan

```bash
.venv/bin/python generate_meal_plan.py                  # 2 weeks ahead (normal operation)
.venv/bin/python generate_meal_plan.py --week 2026-W05   # specific week
.venv/bin/python generate_meal_plan.py --dry-run
```

### Generate shopping list

```bash
.venv/bin/python shopping_list.py                 # auto-detect current week
.venv/bin/python shopping_list.py --week 2026-W03
.venv/bin/python shopping_list.py --dry-run
.venv/bin/python shopping_list.py --clear          # clear existing items first
```

Or via API (same endpoint the Obsidian button calls):

```bash
curl -X POST http://localhost:5001/generate-shopping-list \
  -H "Content-Type: application/json" -d '{"week": "2026-W04"}'

curl -X POST http://localhost:5001/send-to-reminders \
  -H "Content-Type: application/json" -d '{"week": "2026-W04"}'
```

### Sync calendar

```bash
.venv/bin/python sync_calendar.py
.venv/bin/python sync_calendar.py --dry-run
```

### Generate nutrition dashboard

```bash
.venv/bin/python generate_nutrition_dashboard.py
.venv/bin/python generate_nutrition_dashboard.py --week 2026-W03
.venv/bin/python generate_nutrition_dashboard.py --dry-run
```

### Ingest receipt emails

```bash
.venv/bin/python ingest_receipts.py                        # fetch, parse, record trip + inventory
.venv/bin/python ingest_receipts.py --dry-run               # preview, no DB/inventory writes
.venv/bin/python ingest_receipts.py --since-days 30          # look back further than the default 14 days
.venv/bin/python ingest_receipts.py --file receipt.eml       # parse a single local file instead of Gmail

# CSA produce-share newsletters (also runs at the tail of ingest_receipts.py)
.venv/bin/python ingest_csa.py --dry-run
.venv/bin/python ingest_csa.py
```

### Ingest a photographed receipt (Claude iOS app → paste)

For paper / in-store / HEB-app receipts that never hit email. No server-side LLM
call — the Claude app does the vision, KitchenOS just files the JSON.

1. Open the **Paste a Receipt** page: `http://<tailnet-host>:5001/receipt-paste`
   (also linked from `Dashboards/KitchenOS Web.md`).
2. **Copy prompt** and save it once as a Claude project / saved prompt (or grab it
   any time from `prompts/receipt_photo.md` / `GET /api/receipt/prompt`).
3. In the Claude iOS app: attach a receipt photo + that prompt → copy the JSON it
   returns.
4. Paste into the page → **Preview** (routed items + total reconciliation; a
   non-reconciling receipt is flagged `needs_review` but still filed) → **Confirm
   & ingest**.

A receipt whose JSON has no legible date defaults to **today** (the preview
returns `date_defaulted: true`); it no longer blocks the inventory update. The
dedup hash is computed before defaulting, so re-pasting the same dateless receipt
still de-duplicates.

Same DB back-end as email ingest (trip + priced purchases + non-fee inventory,
meal-plan recipe assignment). Re-pasting the same receipt is a no-op — dedup is a
content hash of `date + total + item names` on `trips.source_id` (source
`photo_receipt`). The whole path is shared with the email pipeline via
`lib/receipt_ingest.py:ingest_parsed`.

### Generate price dashboard

```bash
.venv/bin/python generate_price_dashboard.py            # writes Price Tracker.md to the vault root
.venv/bin/python generate_price_dashboard.py --dry-run   # print markdown without saving
```

### Generate web dashboard (tailnet launcher)

Writes `Dashboards/KitchenOS Web.md` — a tap-anywhere launcher for the web app
(Meal Planner, Nutrition Review, System Health, current plan/shopping list).
Links point at `KITCHENOS_API_BASE` (default the Tailscale MagicDNS host
`http://chases-mac-mini.taila69703.ts.net:5001`), so the note works from any
device on the tailnet, not just localhost on the server. Re-run only when the
web base URL changes.

```bash
.venv/bin/python scripts/generate_web_dashboard.py
# point it at a different host first, if needed:
KITCHENOS_API_BASE=http://other-host.taila69703.ts.net:5001 .venv/bin/python scripts/generate_web_dashboard.py
```

### Migrations: one-time vs. re-runnable maintenance

**Re-runnable maintenance / backfill** — `migrate_recipes.py` and
`migrate_cuisine.py` are not one-off historical scripts; they're safe to
re-run incrementally (e.g. after new imports or rule changes). Both default
to skipping recipes that are already up to date/correctly tagged, so a
repeat run is cheap and only touches what's changed.

```bash
# Applies template changes to existing recipe files — re-run after template edits
.venv/bin/python migrate_recipes.py --dry-run
.venv/bin/python migrate_recipes.py

# Cuisine cleanup, tag normalization & seasonal population — re-run after new
# imports or rule changes; default path skips recipes already tagged/correct
.venv/bin/python migrate_cuisine.py --dry-run
.venv/bin/python migrate_cuisine.py
.venv/bin/python migrate_cuisine.py --no-seasonal            # cuisine + tags only
.venv/bin/python migrate_cuisine.py --no-tags --force-seasonal  # force re-match seasonal data
```

**Truly one-time (guarded)** — `migrate_inventory_db.py` imports legacy
`Inventory.md` into `data/kitchenos.db` and explicitly refuses to run once
the inventory table already has rows, so it's a genuine one-off (safe to
leave in a startup script — it's a no-op once migrated). Kept here for
reference in case a fresh environment (new machine, restored backup) needs
it replayed.

```bash
.venv/bin/python migrate_inventory_db.py --dry-run
.venv/bin/python migrate_inventory_db.py
```

---

## 2. LaunchAgents (all 7)

All 7 agents run as `~/Library/LaunchAgents/com.kitchenos.<name>.plist`, with
`ops/com.kitchenos.<name>.plist` in the repo as the canonical source —
**edit the repo copy, then re-copy it to `~/Library/LaunchAgents/` and
reload**, don't hand-edit the installed copy. General pattern:

```bash
cp ops/com.kitchenos.<name>.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.<name>.plist

# restart (after any change to the plist or the script it runs)
launchctl unload ~/Library/LaunchAgents/com.kitchenos.<name>.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.<name>.plist
```

### com.kitchenos.api

API server for iOS Shortcut / Siri / native-app integration. Runs
`api_server.py` on port 5001, accessible via Tailscale. **`KeepAlive: true`**
— if the process is killed it auto-relaunches. `RunAtLoad: true`.

```bash
cp ops/com.kitchenos.api.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist

tail -f logs/server.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist

# manual test run
.venv/bin/python api_server.py
```

See "API restart caveat" below — this is the one that most often serves
stale code after an edit.

### com.kitchenos.batch-extract

Processes YouTube, Instagram, and web recipe URLs from the "Recipies to
Process" iOS Reminders list. Runs `batch_extract.py` hourly, at `:10` past
each hour (`RunAtLoad: true`).

```bash
cp ops/com.kitchenos.batch-extract.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist

tail -f logs/batch_extract.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.batch-extract.plist

.venv/bin/python batch_extract.py
```

Requires **Full Disk Access** for the `.venv` python (System Settings →
Privacy & Security → Full Disk Access) so `lib/reminders_url.py` can read the
Reminders SQLite store directly to recover share-sheet rich-link URLs.
Without it the read fails silently and reminders fall back to their title
(no crash).

### com.kitchenos.calendar-sync

Syncs meal plans to the ICS calendar file. Runs `sync_calendar.py` daily at
6:05am — 5 minutes after `mealplan` so it picks up that day's freshly
generated plan (`RunAtLoad: true`).

```bash
cp ops/com.kitchenos.calendar-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist

tail -f logs/calendar_sync.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.calendar-sync.plist

.venv/bin/python sync_calendar.py
```

Output ICS file: `{Obsidian Vault}/meal_calendar.ics`, also served at
`http://localhost:5001/calendar.ics`.

### com.kitchenos.cleanup-icloud-old

Runs `scripts/cleanup_old_icloud.sh` (a bash script, not Python) once a
year — `StartCalendarInterval` fires May 2 at 10:00am. No `RunAtLoad`. This
is the only one of the 7 not invoked via `.venv/bin/python`.

```bash
cp ops/com.kitchenos.cleanup-icloud-old.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.cleanup-icloud-old.plist

tail -f logs/cleanup_old_icloud.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.cleanup-icloud-old.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.cleanup-icloud-old.plist

# manual test run
bash scripts/cleanup_old_icloud.sh
```

### com.kitchenos.dashboard-update

Runs `scripts/update_dashboard_canvas.py` daily at 6:15am — after
`mealplan` (6:00) and `calendar-sync` (6:05), so the dashboard canvas
reflects the day's freshly generated plan and calendar. No `RunAtLoad`.
This run is also the **reliable daily refresh for `Cook Now.md`** (the
on-hand recipe-coverage view): it calls `cook_now.write_note()` every day,
whereas `Cook Now.md` otherwise only refreshes on inventory mutations (via
`inventory.write_inventory()`) and receipt ingest. Its sibling `Use It Up.md`
refreshes on receipt ingest and the `mealplan` run.

```bash
cp ops/com.kitchenos.dashboard-update.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.dashboard-update.plist

tail -f logs/dashboard_update.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.dashboard-update.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.dashboard-update.plist

.venv/bin/python scripts/update_dashboard_canvas.py
```

### com.kitchenos.mealplan

Auto-generates weekly meal plan templates 2 weeks in advance. Runs
`generate_meal_plan.py` daily at 6:00am. No `RunAtLoad` — reloading the
agent does not trigger an immediate run, it only fires at the next 6:00am
`StartCalendarInterval`.

```bash
cp ops/com.kitchenos.mealplan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

tail -f logs/meal_plan_generator.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.mealplan.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

.venv/bin/python generate_meal_plan.py
```

Files are created in `{Obsidian Vault}/Meal Plans/2026-W03.md`.

### com.kitchenos.receipt-ingest

Ingests HEB receipt emails (and, at its tail, CSA produce-share
newsletters) from Gmail. Runs `ingest_receipts.py` hourly, at `:25` past
each hour (`RunAtLoad: true`). Parses with the Claude API (Opus, when
`ANTHROPIC_API_KEY` is set; Ollama fallback), records trips/purchases in
`data/kitchenos.db`, updates inventory, then regenerates `Inventory.md` and
`Price Tracker.md`.

```bash
cp ops/com.kitchenos.receipt-ingest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist

tail -f logs/receipt_ingest.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.receipt-ingest.plist

.venv/bin/python ingest_receipts.py
```

---

## 3. Caveats

### API restart (load-bearing)

`api_server.py` imports `lib/*` modules **once at process startup**. After
editing `api_server.py` itself, or any `lib/` module the API imports, you
**must**:

```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

Skipping this means the running process keeps serving the **old** in-memory
code. Symptoms look like data bugs (wrong values, missing fields, stale
logic, 500s) but are actually a stale process — always restart the API
before debugging further when behavior doesn't match the code you just
edited.

### setproctitle

The LaunchAgent services self-rename their process title via `setproctitle`
to `kitchenos-*` (e.g. the API server becomes `kitchenos-api`). This means
`pgrep -f <script>.py` (e.g. `pgrep -f api_server.py`) **no longer
matches** — use the renamed title instead:

```bash
pgrep -fl kitchenos-api
```

The `api` service additionally has `KeepAlive: true` — killing the process
(`kill <pid>`) triggers an automatic relaunch by launchd, which is a valid
way to force-restart it without unload/load, but `launchctl unload`/`load`
is the safer/explicit path when you specifically need to guarantee the code
was reloaded.

---

## 4. Health checks

```bash
# API liveness
curl http://localhost:5001/health

# Tail the API log for recent activity/errors
tail logs/server.log

# Confirm the running process actually restarted after a code change:
# compare process start time to the source file's mtime — if the process
# started before your last edit, it's serving stale code.
ps -o lstart= -p "$(pgrep -f kitchenos-api)"
stat -f '%Sm' api_server.py
```

If `ps -o lstart` predates the mtime of `api_server.py` (or any `lib/`
module it imports), reload per the API restart caveat above.

---

## 5. Failure-analysis agent

When `batch_extract.py` encounters failures, it writes a structured JSON log
to `failures/` and triggers `scripts/analyze_failures.sh` in the background.
The script invokes `claude -p` to:

1. Analyze the failure log
2. Skip transient (network) errors
3. Reproduce and fix code bugs
4. Open a PR for review

**Failure log location:** `failures/YYYY-MM-DD-HHMMSS.json` (auto-cleaned
after 30 days).

**Error categories:**

| Category | Meaning | Agent action |
|----------|---------|---------------|
| `network` | Transient connectivity | Skip |
| `ollama` | Ollama infrastructure | Check config |
| `youtube` | Video/transcript issue | Improve fallbacks |
| `parsing` | Code bug | Create fix |
| `io` | File/permission issue | Flag for review |
| `unknown` | Unrecognized | Investigate |

**Manual trigger:**

```bash
scripts/analyze_failures.sh failures/2026-02-13-061000.json
```

---

## 6. QuickAdd setup (Obsidian)

The "Add Ingredients" button in shopping lists requires QuickAdd plugin
configuration:

1. Settings → QuickAdd → Add Choice → name: `Add Ingredients to Shopping
   List` → type: Capture
2. Configure the Capture:
   - **Capture To:** Active file
   - **Insert at:** Bottom of file
   - **Capture format:** Enabled
3. Format template: `{{VALUE:Paste ingredients (one per line):}}`
4. Add format function to transform lines to checkboxes:
   ```javascript
   return value
     .split('\n')
     .map(line => line.trim())
     .filter(line => line.length > 0)
     .map(line => `- [ ] ${line}`)
     .join('\n');
   ```

---

## 7. Running the test suite

From the repo root:

```bash
.venv/bin/python -m pytest
```

Tests never touch the real `data/kitchenos.db` — the `tmp_db` fixture in
`tests/conftest.py` points DB access at a temp file via the `KITCHENOS_DB`
env var for the duration of the test (all SQLite access goes through
`lib/inventory_db.py`, so this fixture is sufficient to isolate every test).
See `lib/CLAUDE.md` for `lib/`-specific conventions.

---

## 8. Native app build / sign / deploy

The live procedure for building, signing, and installing the native
KitchenOSSiri (iOS/macOS) app — the sole home for these deploy commands.

**Signing:** free personal Apple developer team **`XZJ6358HHF`**.
`DEVELOPMENT_TEAM: XZJ6358HHF` is pinned in `project.yml`'s base settings
because `xcodegen generate` regenerates the gitignored `.xcodeproj` on every
run and wipes any team set via the Xcode GUI — pinning it in `project.yml`
is the only way the signing team survives regeneration.

**Deploy:**

```bash
xcodegen generate
xcodebuild build -scheme KitchenOSSiri -destination 'platform=iOS,id=AC76BD14-9BDF-50F9-9087-3E7229EBF38D' -allowProvisioningUpdates
xcrun devicectl device install app --device AC76BD14-9BDF-50F9-9087-3E7229EBF38D <Debug-iphoneos/KitchenOS.app>
# macOS: build -destination 'platform=macOS' then `open` the .app
```

**Free-team caveat:** signed apps **expire after ~7 days** — reinstall via
the same `xcodebuild` + `devicectl` steps above when the app stops
launching. First launch on the iPad after a fresh install may require
trusting the developer certificate: Settings → General → VPN & Device
Management → trust developer.

---

## 9. Launch Claude from your phone (Termius + tmux)

Every KitchenOS web page and the top of `Inventory.md` carry a **🤖 Launch Claude**
button plus a **Notes** box. The button opens an `ssh://$KITCHENOS_SSH_TARGET` link
(Termius on the phone), SSHes into the mini over Tailscale, and — via an SSH forced
command — drops you into `claude` running inside a persistent tmux session
(`ko-claude`), pre-seeded with whatever is in the shared `Claude Notes.md`.

**Pieces (all in the main checkout):**

- `scripts/kitchenos-claude-launch.sh` — forced-command entrypoint;
  `tmux new-session -A -s ko-claude` (attach-or-create → survives disconnect).
- `scripts/kitchenos-claude-run.sh` — runs inside tmux; resolves `Claude Notes.md`
  via `lib.paths.claude_notes_path()` and `exec claude "$(cat notes)"` (or bare
  `claude` when notes are empty).
- `scripts/kitchenos-claude-reset.sh` — `tmux kill-session -t ko-claude`; run it
  after editing notes so the **next** launch re-seeds from the new notes (an
  attach-only re-launch keeps the old session, so edited notes don't take effect
  until you reset).
- Notes are edited in the web textarea (saved via `POST /api/claude-notes`) or
  directly in Obsidian as `Claude Notes.md` at the vault root — byte-identical.

```bash
# Reset the session so the next launch picks up freshly-edited notes:
/Users/chaseeasterling/Dev/KitchenOS/scripts/kitchenos-claude-reset.sh
```

### One-time setup

On the mini:

```bash
brew install tmux
chmod +x scripts/kitchenos-claude-*.sh   # already +x in git, but confirm
ssh-keygen -t ed25519 -f ~/.ssh/kitchenos_claude   # dedicated key, no passphrase or one you'll store in Termius
```

Add the public key to `~/.ssh/authorized_keys` on the mini with a forced command so
this key can ONLY launch Claude (never a plain shell):

```
command="/Users/chaseeasterling/Dev/KitchenOS/scripts/kitchenos-claude-launch.sh",no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA...your-kitchenos_claude.pub
```

On the phone (Termius): import the `kitchenos_claude` private key; create a host
**"KitchenOS Claude"** = `chase@chases-mac-mini.taila69703.ts.net` presenting **only**
that key (so the forced command always fires). Connect once to confirm you land in
`claude` inside tmux. Set `KITCHENOS_SSH_TARGET` in `.env` if the `user@host` differs
from the default, then restart the API LaunchAgent so pages emit the right link.

**Caveats:** iOS routing of `ssh://` → Termius isn't guaranteed across versions — the
saved Termius host is the reliable entry, the button is convenience. `claude` needs it
on PATH under a non-login shell; `kitchenos-claude-run.sh` sources `~/.zprofile` and
prepends Homebrew dirs. tmux/claude need a PTY (Termius interactive default).

## 10. Completing work

When finishing a feature or fix, follow this checklist before committing.

### 1. Verify

- [ ] Run `extract_recipe.py --dry-run` with a test video (if extraction
      logic changed)
- [ ] Check for Python errors or warnings
- [ ] Verify Ollama is responding correctly (`curl
      http://localhost:11434/api/tags`)
- [ ] Run the test suite: `.venv/bin/python -m pytest`

### 2. Test end-to-end (if applicable)

- [ ] Run full extraction: `.venv/bin/python extract_recipe.py "VIDEO_URL"`
- [ ] Check the recipe file was created in the Obsidian vault
- [ ] Open in Obsidian — verify frontmatter and content look correct

### 3. Update documentation (required)

Review the change against the table below, update the doc(s) it maps to,
and if nothing applies, confirm why (e.g. "refactor only, no
architecture/API/CLI changes").

**Which doc to update — new doc homes:**

| Change type | Update this |
|-------------|-------------|
| Architecture change (pipeline flow, AI stack, new core component) | `docs/ARCHITECTURE.md` |
| New HTTP route or MCP tool | `docs/API.md` |
| New CLI command, LaunchAgent/service, or operational procedure | `docs/OPERATIONS.md` (this file) |
| Roadmap / future-enhancement idea | `docs/ROADMAP.md` |
| User-facing change (setup, usage, configuration) | `README.md` |
| New `lib/` convention | `lib/CLAUDE.md` |
| Lessons learned | `docs/history/ORIGINS.md` → "Lessons learned" |

Do not re-embed the full HTTP route table here — link to `docs/API.md`,
which is the single canonical route/tool reference.

### 4. Commit

**Do not commit until step 3 is complete.**

```bash
git add -A
git commit -m "feat/fix/docs: description

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### 5. Update roadmap

- [ ] Mark completed features as done in `docs/ROADMAP.md` (move to
      "Completed" or remove)
- [ ] Add any new ideas discovered during implementation
