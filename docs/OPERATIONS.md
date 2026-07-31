# KitchenOS Operations Runbook

The canonical home for running, deploying, and operating KitchenOS: one-off
CLI commands, the 8 LaunchAgents (install/logs/restart), operational
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

### Reclassify recipe dish types (one-off repair)

Batch-classifies every recipe into `normalizer.VALID_DISH_TYPES` via the Claude
Batches API. Dry-run by default. `--apply` backs each file up into `.history/`
before writing. Needs `ANTHROPIC_API_KEY`; costs well under $1 for ~240 recipes.

```bash
.venv/bin/python scripts/reclassify_dish_type.py            # dry-run report
.venv/bin/python scripts/reclassify_dish_type.py --apply    # write changes
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
(Meal Planner, Nutrition Review, Inventory Review, System Health, Paste a
Receipt, current plan/shopping list). Links point at `KITCHENOS_API_BASE`
(default the Tailscale MagicDNS host
`http://chases-mac-mini.taila69703.ts.net:5001`), so the note works from any
device on the tailnet, not just localhost on the server. Re-run when the web
base URL changes **or when `SECTIONS` in `lib/web_dashboard.py` changes**.

```bash
.venv/bin/python scripts/generate_web_dashboard.py
# point it at a different host first, if needed:
KITCHENOS_API_BASE=http://other-host.taila69703.ts.net:5001 .venv/bin/python scripts/generate_web_dashboard.py
```

### Sync Safari bookmarks

Mirrors that same `SECTIONS` registry into the Safari **KitchenOS** bookmarks
folder (first item in the Bookmarks Bar), so every page is one tap away and
iCloud carries it to the iPad and iPhone. Additive and idempotent — matches on
URL, never deletes or reorders, leaves hand-made bookmarks alone.

```bash
.venv/bin/python scripts/sync_safari_bookmarks.py           # report drift, touch nothing (exit 1 if stale)
.venv/bin/python scripts/sync_safari_bookmarks.py --apply   # add the missing ones
```

`--apply` **quits and relaunches Safari**, because Safari caches
`Bookmarks.plist` in memory and rewrites it on quit — a write made while it is
running is silently discarded. Session restore brings the tabs back, and if
Safari isn't running the quit/relaunch is skipped. Every apply backs the plist
up to `~/Library/Safari/KitchenOS-bookmark-backups/` first, and verifies after
the relaunch that the new entries actually survived; if they didn't, it prints
the exact `cp` to restore. The folder itself must already exist — the script
refuses to create a second one. On non-macOS (a cloud session) it exits cleanly
without doing anything.

See the page-registry invariant in `CLAUDE.md`: adding an HTML page route
without registering it here fails `tests/test_web_dashboard.py`.

### Tag recipes against the personal food profile

Assesses each recipe against `My Meal System.md` (craving lane, buffer-food
candidacy, dairy load, effort, and inferred heart/steady flags), writing
`fit_*` frontmatter. Claude Haiku with an Ollama fallback; a recipe no model
answers for is left **untagged rather than mistagged**.

Every value is inference from an ingredient list, so each tagged recipe carries
`fit_source` and `fit_needs_review: true`. Newly extracted recipes are tagged
automatically (`extract_recipe.py`), so this is only needed for the initial
pass or after editing the profile note.

```bash
.venv/bin/python backfill_fit.py --dry-run --limit 10   # preview, writes nothing
.venv/bin/python backfill_fit.py                        # tag everything untagged
.venv/bin/python backfill_fit.py --force                # re-assess the whole library
```

Skips already-tagged recipes unless `--force`, so it's cheap to re-run. Each
rewritten note gets a timestamped `.history/` backup.

### Backfill missing `servings` (review aid)

A recipe with no `servings` has its per-serving macros divided by 1, so the
whole-batch numbers masquerade as one serving — and the macro-aware suggester
and the print-week macros skip or flag it. `scripts/backfill_servings.py` fills
the count in from what's already in the file — no vault DB / USDA / LLM needed.

It reads each recipe two ways, and the distinction matters:

| Source | How | Written as |
|--------|-----|------------|
| **Stated** — the recipe says "Serves 4" / "Makes 24 cookies" | read from the body | plain fact: **no** review flag, and not capped at 12 |
| **Estimated** — nothing stated | `servings ≈ batch_kcal / anchor(dish_type)`, clamped 1–12 | `servings_inferred: true` + `servings_needs_review: true` |

A stated yield is a measurement, so it wins outright and isn't flagged. An
estimate is a heuristic and always is. Dry-run by default.

Two guards keep the unflagged path honest, and both exist because they failed once:

- **Measure nouns disqualify a match** — "Makes 2 cups of sauce" is a batch volume,
  not two servings.
- **Only a human-sounding *statement* counts** ("Serves 4", "Makes 24 cookies",
  "Cut into 6 servings") — never a bare "N serving(s)". Our own generated nutrition
  footer reads `*Serving size: 1 serving • Source: Fdc*`, and a bare pattern scraped
  `servings: 1` off it in **3 of 3** candidate recipes — writing the batch-as-one-serving
  corruption this tool repairs, as unflagged fact.

```bash
.venv/bin/python scripts/backfill_servings.py            # preview table, writes nothing
.venv/bin/python scripts/backfill_servings.py --apply    # write the counts (+ .history backup)
.venv/bin/python backfill_nutrition.py --force           # recompute per-serving macros from the new counts
```

The preview table's `status` column tells you which is which. Then review the
recipes flagged `servings_needs_review` and correct any that look off — the
anchor is a heuristic, not the truth.

### Generate the On Track view

Writes `Dashboards/On Track.md` — what you actually cooked (from the serving
ledger, never from meal plans), how it leaned heart/steady, the verdicts and
notes you recorded, and where the recipe library is thin. Regenerates
automatically whenever a cook or verdict is logged; run by hand after a
`backfill_fit.py` pass so the library-gap counts refresh.

```bash
.venv/bin/python scripts/generate_on_track.py
```

### Buffer-food stock check

Answers the question the Meal System note actually turns on: is something you
like reachable with no prep *right now*, in each craving lane? Deliberately a
**stock** check rather than a recipe check — most of the buffer menu is an
assembly ("apple + nut butter", "handful of pistachios"), so acquiring more
recipes cannot move it. Also lists building blocks that aren't stocked.

```bash
.venv/bin/python scripts/buffer_restock.py                 # report
.venv/bin/python scripts/buffer_restock.py --to-reminders  # push the shortfall to Shopping
```

Only **bare** lanes contribute shopping targets; padding the list with things
for already-covered lanes is how a shopping list stops being read. The same
readiness summary appears in `Dashboards/On Track.md`.

### The verdict nudge (daily cue)

`com.kitchenos.verdict-nudge` runs `scripts/nudge_verdicts.py` at 20:15 and adds
**one** Reminders item asking how a recent unjudged cook went — silent when
nothing is pending, nothing older than 4 days, extra cooks as a count rather
than a queue. Reminders rather than a macOS notification because the mini is
headless and the answer happens on a phone.

```bash
.venv/bin/python scripts/nudge_verdicts.py --dry-run   # show without sending
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

### Recipe repair: bodies and missing frontmatter

Two re-runnable repair passes over `Recipes/*.md`. Both back up each file via
`lib/backup.create_backup` before writing, and both are no-ops on a corpus
that's already clean — **always `--dry-run` first.**

`clean_recipe_tails.py` strips duplicated `*Extracted from …*` footers and
loose `key: null` YAML that a past template-refresh bug appended into the
markdown body (Obsidian renders those as literal text; Dataview ignores
them). The template puts the source footer last, so everything after the
*first* footer is duplicated tail — but a file is only truncated when every
line of that tail is provably junk. A tail containing prose is reported as
`SKIP` and left alone, because that prose may be a note you wrote.

```bash
.venv/bin/python scripts/clean_recipe_tails.py --dry-run
.venv/bin/python scripts/clean_recipe_tails.py
```

`enrich_recipes.py` fills *missing* frontmatter with Haiku and flags internal
inconsistencies. Strictly additive: a field is written only when its current
value is absent, null, or a known junk placeholder (`"null"`, `"0 seconds"`,
`"Not explicitly mentioned"`). An existing good value is never overwritten —
a small model guessing over curated data is how a recipe library silently
rots. Needs `ANTHROPIC_API_KEY`.

Two guards worth knowing before you widen its scope:

- **`nut-free`, `gluten-free` and `dairy-free` are never auto-filled.** A
  wrong `vegetarian` is a bad dinner; a wrong `nut-free` is a medical event,
  and a small model reading a partial ingredient list cannot clear a recipe
  of trace allergens. Those stay empty until a human sets them.
- **Consistency problems are reported, not applied.** The model is asked for
  ingredients used in steps but absent from the table (and vice versa), plus
  implausible quantities — it is never asked to edit ingredients or steps.

```bash
.venv/bin/python scripts/enrich_recipes.py --dry-run --limit 10
.venv/bin/python scripts/enrich_recipes.py --only-servings   # servings drives per-serving nutrition
.venv/bin/python scripts/enrich_recipes.py --out /tmp/enrich-report.json
```

---

## 2. LaunchAgents (all 8)

All 8 agents run as `~/Library/LaunchAgents/com.kitchenos.<name>.plist`, with
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
Grant it to the interpreter itself (`/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python`,
reachable in the file picker with ⇧⌘G) — the grant does not follow the repo, so
it has to be redone after a machine rebuild or a recreated `.venv`.

Without it, a share-sheet reminder resolves no URL, is reported as an invalid
URL, and is left unchecked to be retried forever. **The denial does not raise:**
TCC hands a launchd job an empty directory listing, so the code sees "no stores"
rather than an error. `lib/reminders_url.py` now logs a warning naming Full Disk
Access whenever that happens — check `logs/batch_extract.log` for
`No Reminders store files` before assuming the list is simply full of junk
entries. Run `.venv/bin/python batch_extract.py` from a terminal to confirm:
an interactive run inherits the terminal's access and resolves the same
reminders the LaunchAgent cannot.

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

### com.kitchenos.verdict-nudge

The one recurring cue in the system: asks "how did that go?" about a recent
cook that has no verdict yet. Runs `scripts/nudge_verdicts.py` daily at
**20:15** — after dinner and cleanup, while the meal is still recallable, and
before the late-evening window `My Meal System.md` identifies as the hard one.
No `RunAtLoad`. **Stays silent unless there is something to answer** — see
`lib/verdict_nudge.py` for why that restraint is load-bearing.

```bash
cp ops/com.kitchenos.verdict-nudge.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kitchenos.verdict-nudge.plist

tail -f logs/verdict_nudge.log

launchctl unload ~/Library/LaunchAgents/com.kitchenos.verdict-nudge.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.verdict-nudge.plist

.venv/bin/python scripts/nudge_verdicts.py --dry-run   # show, send nothing
```

### Reload them all at once

`scripts/reload_launch_agents.sh` boots out and re-bootstraps every installed
`com.kitchenos.*` agent, discovering them from `~/Library/LaunchAgents/` rather
than a hardcoded list. **Run it from a Terminal in your GUI session** — user
agents live in the `gui/<uid>` domain and can't be managed from an SSH session
or Claude Code's Bash tool.

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
| New browsable HTML page | `SECTIONS` in `lib/web_dashboard.py`, then run `scripts/generate_web_dashboard.py` + `scripts/sync_safari_bookmarks.py --apply` |
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
