# KitchenOS Docs Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate KitchenOS documentation to "one home per information-type" — slim the 50KB auto-loaded `CLAUDE.md`, create three canonical docs (ARCHITECTURE / API / OPERATIONS), correct every doc↔code contradiction, and archive/delete dead docs — without losing any load-bearing knowledge.

**Architecture:** Pure documentation refactor on a dedicated branch. No production code changes. Work proceeds in dependency order: reversible moves first, then write the new canonical docs (so nothing is deleted before its content has a new home), then slim `CLAUDE.md` and rewrite `README`/`ROADMAP` (which point at the new docs), then surgical in-place fixes. Each task ends with a grep/ls verification gate and a commit so any task can be reviewed or reverted independently.

**Tech Stack:** Markdown, git, bash (grep/ls/wc for verification). Source of truth for "what exists" is the live code in this repo (`api_server.py`, `mcp_server.py`, `lib/`, `ops/*.plist`) plus the design spec at `docs/superpowers/specs/2026-07-01-docs-reorg-design.md`.

## Global Constraints

Copy these verbatim into every rewritten/new doc; they are the cross-cutting correctness fixes and apply to all tasks:

- **Framework:** synchronous **Flask** (`app.run`, port 5001) — never n8n, never FastAPI/async. `/extract` and `/reprocess` **subprocess out** to `extract_recipe.py` (extraction is not in-process).
- **AI is hybrid, not Ollama-only:** Ollama `mistral:7b` = recipe extraction/nutrition/seasonality/resolver-fallback only. Claude (`claude-opus-4-8` receipts, `claude-haiku-4-5` suggestions/food_resolver/task_extractor) is load-bearing when `ANTHROPIC_API_KEY` is set. Whisper (OpenAI) = transcript fallback. Native app = Apple Foundation Models on-device.
- **Python floor is 3.11** everywhere (not 3.9+). Drop the old 3.9 f-string-backslash workaround note.
- **Vault path:** "resolved via `lib/paths.py` / `KITCHENOS_VAULT`" — **never quote a default path.**
- **Data truth:** `data/kitchenos.db` (SQLite) is the single source of truth for inventory/price. `Inventory.md`, `Price Tracker.md`, `Use It Up.md` are **generated read-only views**. `config/pantry.json` is gone.
- **Nutrition:** live path is `lib/nutrition_engine.py` → `lib/food_db.py`/`lib/food_resolver.py` (USDA FoodData Central + Open Food Facts, `USDA_FDC_API_KEY`). `lib/nutrition_lookup.py` + Nutritionix are **deprecated**.
- **Native app exists:** `KitchenOSKit` (shared SPM) + `KitchenOSSiri` app target, iOS 26 + macOS 26, 8–9 App Intents + AppShortcutsProvider + Foundation Models + CoreSpotlight. Both forked branches are **converged on `main`**.
- **7 LaunchAgents** (not 4–5): `api`, `batch-extract`, `calendar-sync`, `cleanup-icloud-old`, `dashboard-update`, `mealplan`, `receipt-ingest`.
- **Co-Authored-By string:** standardize to `Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (replaces the drifted 4.5 / 4.6).
- **Repo root is `/Users/chaseeasterling/Dev/KitchenOS`** (post-rebuild); `/Users/chaseeasterling/KitchenOS` is a dead pre-rebuild path. Selene is at `~/Dev/selene` (not `~/selene`).

**Decisions locked in (from the spec):** pragmatic consolidation (3 new docs: ARCHITECTURE, API, OPERATIONS) · broaden README · delete dead docs outright · plan-then-execute in phases on a branch. OPERATIONS.md also absorbs the completing-work checklist and the native build/sign/deploy procedure. Only **two** archive locations exist: `docs/plans/archive/` (frozen shipped-feature provenance) and `docs/history/` (curated readable narrative).

---

## File Structure (target)

**New files:**
- `docs/ARCHITECTURE.md` — the single "what exists" technical reference
- `docs/API.md` — HTTP routes + MCP tools + Siri intent surface
- `docs/OPERATIONS.md` — runbook (CLI, 7 LaunchAgents, native build/deploy, completing-work checklist, pytest)
- `docs/history/ORIGINS.md` — salvaged n8n-vs-standalone rationale + Lessons Learned
- `docs/history/SIRI_BUILD_LOG.md` — relocated `BUILD_LOG.md`
- `docs/plans/archive/INDEX.md` — generated index of the 71 archived legacy plans

**Rewritten:** `CLAUDE.md`, `README.md`, `docs/ROADMAP.md`, `docs/workflows/end-to-end.md`, `.env.example`

**Updated (surgical):** `docs/setup/iOS_SHORTCUT_SETUP.md`, `docs/setup/DRAFTS_RECIPE_ACTION.md`, `docs/superpowers/specs/*`, `docs/superpowers/plans/*`, `.claude/agents/meal-plan-reviewer.md`, `.claude/skills/recipe-debug/SKILL.md`, `.claude/skills/finish-feature/SKILL.md`, `scripts/kitchenos-uri-handler/README.md`

**Deleted (git-tracked, recoverable):** `docs/SESSION_SUMMARY.md`, `docs/setup/HOW_TO_RUN.md`, `docs/weekly-planning-session.md`, `docs/IMPLEMENTATION_SUMMARY.md` (after salvage), `docs/stories/**`, `templates/BRANCH-STATUS.md`, `scripts/story.sh`

**Moved into `docs/plans/archive/`:** the 71 dated `docs/plans/2026-*.md` files. **Kept in place:** `docs/plans/ingredient-data-cleaning.md`.

---

## Task 1: Create the working branch and capture a stale-reference baseline

**Files:**
- Create: none (baseline only)

**Interfaces:**
- Produces: branch `docs-reorg`; a saved `/tmp/docs-reorg-stale.txt` inventory that later tasks grep against to confirm each stale reference is gone.

- [ ] **Step 1: Create the branch off the current HEAD**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git checkout -b docs-reorg
git rev-parse --abbrev-ref HEAD
```
Expected: prints `docs-reorg`.

- [ ] **Step 2: Snapshot every stale reference the reorg must eliminate**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
{ grep -rniE 'n8n|nutrition_lookup|Nutritionix|Opus 4\.5|Opus 4\.6|python 3\.9|/Users/chaseeasterling/KitchenOS[^/]|~/selene[^/]|HOW_TO_RUN|IMPLEMENTATION_SUMMARY|KitchenOS-siri|Ollama-only' \
    --include='*.md' . ; } > /tmp/docs-reorg-stale.txt 2>/dev/null
wc -l /tmp/docs-reorg-stale.txt
```
Expected: a non-zero line count (the current stale-reference debt). This file is the checklist; later tasks re-run targeted greps and expect **zero** matches in the files they touch.

- [ ] **Step 3: Confirm the ground-truth counts the plan relies on**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
ls ops/*.plist | wc -l                          # expect 7
ls docs/plans/ | grep -cE '^2026-'              # expect 71
ls docs/plans/ | grep -vE '^2026-'              # expect: archive not-yet-made -> only ingredient-data-cleaning.md
```
Expected: `7`, `71`, and `ingredient-data-cleaning.md`.

- [ ] **Step 4: Commit the branch point (no content change yet)**

No commit needed — the branch itself is the deliverable. Proceed to Task 2.

---

## Task 2: Archive the 71 legacy plans and generate their INDEX

**Files:**
- Create: `docs/plans/archive/` (dir), `docs/plans/archive/INDEX.md`
- Move: `docs/plans/2026-*.md` → `docs/plans/archive/`
- Keep in place: `docs/plans/ingredient-data-cleaning.md`

**Interfaces:**
- Produces: `docs/plans/archive/` as the frozen shipped-feature provenance home; `INDEX.md` as its table of contents (linked later from ROADMAP and CLAUDE.md pointer index).

- [ ] **Step 1: Create the archive dir and move only the dated plans**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
mkdir -p docs/plans/archive
git mv docs/plans/2026-*.md docs/plans/archive/
ls docs/plans/
```
Expected: `docs/plans/` now lists only `archive` and `ingredient-data-cleaning.md`.

- [ ] **Step 2: Generate INDEX.md from the archived filenames**

Create `docs/plans/archive/INDEX.md`. Header + one table row per archived file. Derive the row from each filename (`YYYY-MM-DD-<slug>-<design|impl|plan>.md`): date column = the date prefix, feature column = the slug humanized, kind column = design/impl/plan suffix. Mark all as shipped-on-main (these are pre-superpowers completed work). Build the body mechanically:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
{
  echo "# Archived Legacy Plans (pre-superpowers)"
  echo
  echo "Frozen build records for features that shipped on \`main\` before the superpowers spec/plan convention. Kept for provenance only — not live. Live per-feature design lives in \`docs/superpowers/\`; current work lives in \`docs/ROADMAP.md\`."
  echo
  echo "| Date | Plan file | Kind |"
  echo "|---|---|---|"
  for f in docs/plans/archive/2026-*.md; do
    b=$(basename "$f")
    d=$(echo "$b" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}')
    kind=$(echo "$b" | grep -oE '(design|impl|plan)\.md$' | sed 's/\.md//'); [ -z "$kind" ] && kind="plan"
    echo "| $d | [$b]($b) | $kind |"
  done
} > docs/plans/archive/INDEX.md
grep -c '^| 2026-' docs/plans/archive/INDEX.md
```
Expected: prints `71`.

- [ ] **Step 3: Verify no live doc links to the old flat `docs/plans/2026-*` paths**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rnE 'docs/plans/2026-' --include='*.md' . | grep -v 'docs/plans/archive/'
```
Expected: no output (any remaining hit is a link to repoint — fix it to `docs/plans/archive/…` before committing). Note: `CLAUDE.md`'s generic `docs/plans/` pointer is handled in the CLAUDE.md rewrite (Task 11).

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add -A
git commit -m "docs: archive 71 legacy plans under docs/plans/archive/ with INDEX

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Delete the dead user-story system and the wrong-project quick-start

**Files:**
- Delete: `docs/stories/INDEX.md`, `docs/stories/templates/STORY-TEMPLATE.md`, `templates/BRANCH-STATUS.md`, `scripts/story.sh`, `docs/setup/HOW_TO_RUN.md`

**Interfaces:**
- Consumes: nothing.
- Produces: removal of never-run story tooling and the `yt_vid_info` quick-start that `CLAUDE.md` currently mis-advertises. (`HOW_TO_RUN.md` reference in `CLAUDE.md` is repointed in Task 11.)

- [ ] **Step 1: Confirm story.sh has no live callers before deleting**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rnE 'story\.sh|BRANCH-STATUS|docs/stories' --include='*.md' --include='*.py' --include='*.sh' . \
  | grep -v -e 'docs/stories/INDEX.md' -e 'STORY-TEMPLATE.md' -e 'templates/BRANCH-STATUS.md' -e 'scripts/story.sh' \
  | grep -v 'docs/superpowers/'
```
Expected: no output (the only references are the files themselves + this plan/spec under `docs/superpowers/`). If a live doc references them, note it for repointing in its own task.

- [ ] **Step 2: Delete the files**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git rm docs/stories/INDEX.md docs/stories/templates/STORY-TEMPLATE.md templates/BRANCH-STATUS.md scripts/story.sh docs/setup/HOW_TO_RUN.md
git status --short
```
Expected: five `D` (deleted) entries; `docs/stories/` becomes empty and drops out.

- [ ] **Step 3: Verify the paths are gone**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
ls docs/stories 2>&1; ls docs/setup/HOW_TO_RUN.md 2>&1; ls scripts/story.sh 2>&1
```
Expected: three "No such file or directory" errors.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add -A
git commit -m "docs: delete dead user-story system and wrong-project HOW_TO_RUN

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Write docs/ARCHITECTURE.md (the single "what exists")

**Files:**
- Create: `docs/ARCHITECTURE.md`
- Read for source material: `CLAUDE.md` (Architecture, Receipt→Inventory, Core Components), `api_server.py`, `lib/inventory_db.py`, `lib/paths.py`

**Interfaces:**
- Produces: the canonical technical reference that `CLAUDE.md` and `README.md` will link to. Later tasks (CLAUDE.md slim, README) rely on this existing so they can delete their inline architecture prose.

- [ ] **Step 1: Write the document with these exact sections (grounded in code, honoring Global Constraints)**

Create `docs/ARCHITECTURE.md` with this structure — fill each section from the cited live source, not from memory:

1. `# KitchenOS Architecture` + one-paragraph overview: local-first kitchen OS = synchronous Flask API (port 5001, `com.kitchenos.api`) on the Mac mini + Obsidian vault + SQLite DB + native iOS 26/macOS 26 app; hybrid AI.
2. `## Extraction pipeline` — the flow from `CLAUDE.md`'s "Pipeline Flow" block (`extract_recipe.py` → `main.py` → `recipe_sources.py` fallbacks → tips → validate → seasonal → `nutrition_engine` → image → template). State that `/extract` **subprocesses** out to `extract_recipe.py`.
3. `## Web/API tier` — synchronous Flask, ~50 routes; link to `docs/API.md` for the route list (do not duplicate it here). Note Tailscale exposure + optional `KITCHENOS_API_TOKEN` bearer auth for remote Siri callers.
4. `## Background services` — the 7 LaunchAgents by responsibility (one line each); link to `docs/OPERATIONS.md` for install/logs/restart. Note services self-rename via `setproctitle`.
5. `## Data model — SQLite as single source of truth` — `data/kitchenos.db` (`lib/inventory_db.py`): `trips`, `purchases` (integer-cents ledger, `category='fee'` rows never touch inventory), `inventory` (`(name,unit,location)` merge key). State `Inventory.md`/`Price Tracker.md`/`Use It Up.md` are generated read-only views; `config/pantry.json` is gone.
6. `## Receipt → inventory` — the five entry paths (email/CSA/photo/manual/markdown-paste) condensed from `CLAUDE.md`; the additive-not-a-chore principle (auto-add, auto-age-out, staples assumed, consume-on-cook optional, waste-aware suggester).
7. `## Vault taxonomy` — `Recipes/`, `Recipes/Images/`, `Meals/`, `Meal Plans/`, `My Macros.md`, generated `Inventory.md`/`Use It Up.md`/`Price Tracker.md`. Vault resolved via `lib/paths.py`/`KITCHENOS_VAULT`.
8. `## MCP server` — Claude Desktop integration via `mcp_server.py`/`lib/mcp_tools.py`; link to `docs/API.md` for the tool list.
9. `## Native app tier` — `KitchenOSKit` (shared SPM: `Intents/`, `AI/`, models + client) + `KitchenOSSiri` target; single XcodeGen project building iOS 26 + macOS 26 (`#if os(macOS)` AppShell sidebar / `#else` iOS TabView); App Intents + AppShortcutsProvider + Foundation Models + CoreSpotlight. Converged on `main`. Link build/sign/deploy → `docs/OPERATIONS.md`; how-it-connects (baseURL/Tailscale/token) → `docs/setup/`.
10. `## Feature semantics` — servings multiplier (`[[Recipe]] x2`), composite meals (`[[Meal: X]]`), pantry-aware shopping (`/api/shopping-list/preview|confirm`), cross-recipe prep tasks (sidecar cache).

- [ ] **Step 2: Verify the load-bearing corrections are present and the anti-patterns absent**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -qi 'synchronous Flask' docs/ARCHITECTURE.md && echo "flask OK"
grep -qi 'single source of truth' docs/ARCHITECTURE.md && echo "db-truth OK"
grep -qi 'KitchenOSKit' docs/ARCHITECTURE.md && echo "native OK"
grep -niE 'n8n|FastAPI|Ollama-only' docs/ARCHITECTURE.md
```
Expected: `flask OK`, `db-truth OK`, `native OK`, and **no** output from the last grep.

- [ ] **Step 3: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add docs/ARCHITECTURE.md
git commit -m "docs: add canonical ARCHITECTURE.md (what exists)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Write docs/API.md (routes + MCP tools + Siri intents)

**Files:**
- Create: `docs/API.md`
- Read for source material: `api_server.py` (`@app.route`), `mcp_server.py` (tool registrations), `KitchenOSSiri`/`KitchenOSKit` App Intents

**Interfaces:**
- Consumes: nothing.
- Produces: the single interface reference; `CLAUDE.md` and `ARCHITECTURE.md` link here instead of embedding route/tool tables. Must be **complete** (the current `CLAUDE.md` MCP table omits `use_it_up`/`cook_recipe` and is duplicated).

- [ ] **Step 1: Enumerate the real routes and tools to guarantee completeness**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -nE "@app.route" api_server.py | sed -E "s/.*@app.route\(//"
echo "--- MCP tools ---"
grep -niE 'name="|Tool\(|def .*tool|use_it_up|cook_recipe' mcp_server.py lib/mcp_tools.py | head -60
```
Expected: the authoritative list of endpoints and tools. Use this output as the source; every route printed here must appear in `docs/API.md`.

- [ ] **Step 2: Write docs/API.md with three sections**

Create `docs/API.md`:
1. `## HTTP endpoints` — a table of every `@app.route` from Step 1 (path | method | purpose). Preserve the non-obvious-contract notes currently in `CLAUDE.md`'s Endpoints table (`/reprocess` preserves `## My Notes`; `/refresh` re-renders only; `/api/use-it-up`; `/api/cook`; pantry preview/confirm; `/add-to-meal-plan` modes). Fix `/extract` doc to say it returns key `recipe` (not `recipe_name`).
2. `## MCP tools` — the **complete** tool list from Step 1 including `use_it_up` and `cook_recipe`; listed **once**. Group inventory tools (`add_to_inventory`, `list_inventory`, `remove_from_inventory`, `update_inventory_item`) with their signatures.
3. `## Siri / App Intents surface` — the App Intents exposed by the native app and which HTTP endpoints back them (e.g. "recipes with X" → `/api/recipes?ingredient=`).

- [ ] **Step 3: Verify completeness (every route documented; new MCP tools present; no duplication)**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
routes=$(grep -cE "@app.route" api_server.py)
documented=$(grep -cE '^\| *`?/' docs/API.md)
echo "routes in code: $routes  |  rows in API.md: $documented"
grep -c 'use_it_up' docs/API.md; grep -c 'cook_recipe' docs/API.md
```
Expected: `documented` ≥ `routes`; and `use_it_up`/`cook_recipe` each appear ≥1.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add docs/API.md
git commit -m "docs: add canonical API.md (routes + 15 MCP tools + Siri intents)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Write docs/OPERATIONS.md (runbook + native build/deploy + completing-work checklist)

**Files:**
- Create: `docs/OPERATIONS.md`
- Read for source material: `CLAUDE.md` (Running Commands, all LaunchAgent sections, QuickAdd, Failure Analysis, Completing Work), `ops/*.plist`, `BUILD_LOG.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the runbook. **Must include the native build/sign/deploy procedure BEFORE Task 7 moves `BUILD_LOG.md` to history** — this is the live home for that at-risk knowledge (the critic's top risk).

- [ ] **Step 1: Write the runbook sections from CLAUDE.md's command blocks**

Create `docs/OPERATIONS.md`:
1. `## One-off CLI commands` — all the `.venv/bin/python …` invocations from `CLAUDE.md`'s "Running Commands" (extract, crouton import, `migrate_*`, dedupe, `migrate_inventory_db`, meal plan, shopping list, calendar, nutrition/price dashboards, receipt + CSA ingest). Flag the `migrate_*.py` scripts as **completed one-time migrations** (`migrate_inventory_db` refuses once inventory has rows), not routine steps.
2. `## LaunchAgents (all 7)` — a subsection per plist enumerating install (`cp ops/<name>.plist ~/Library/LaunchAgents/` + `launchctl load`), logs (`tail -f logs/<log>`), and restart (`launchctl unload`/`load`). Cover all 7: `api`, `batch-extract`, `calendar-sync`, `cleanup-icloud-old`, `dashboard-update`, `mealplan`, `receipt-ingest`. `ops/*.plist` are the canonical definitions.
3. `## Caveats` — (a) **API restart**: `api_server.py` imports `lib/*` once at startup; after editing `api_server.py` or any `lib/` module the API uses, `launchctl unload`/`load com.kitchenos.api.plist` or it serves stale code (500s that look like data bugs). (b) **setproctitle**: services self-rename to `kitchenos-*`; `pgrep -f <script>.py` no longer matches — use `pgrep -fl kitchenos-api`. The `api` service has `KeepAlive` (kill → auto-relaunch).
4. `## Health checks` — `curl http://localhost:5001/health`; `tail logs/server.log`; compare `ps -o lstart` vs file mtimes to catch staleness.
5. `## Failure-analysis agent` — `failures/*.json`, `scripts/analyze_failures.sh`, error categories, manual trigger.
6. `## QuickAdd setup (Obsidian)` — the "Add Ingredients to Shopping List" Capture config + JS format function from `CLAUDE.md`.
7. `## Running the test suite` — `.venv/bin/python -m pytest` from repo root; note tests use the `KITCHENOS_DB`/tmp_db fixture (see `lib/CLAUDE.md`).
8. `## Native app build / sign / deploy` — the live procedure (migrated from the app-signing note, the sole home for the deploy commands): free personal team **`XZJ6358HHF`** (`DEVELOPMENT_TEAM` pinned in `project.yml` base settings because `xcodegen generate` regenerates the gitignored `.xcodeproj` and wipes GUI-set teams). Deploy:
   ```bash
   xcodegen generate
   xcodebuild build -scheme KitchenOSSiri -destination 'platform=iOS,id=AC76BD14-9BDF-50F9-9087-3E7229EBF38D' -allowProvisioningUpdates
   xcrun devicectl device install app --device AC76BD14-9BDF-50F9-9087-3E7229EBF38D <Debug-iphoneos/KitchenOS.app>
   # macOS: build -destination 'platform=macOS' then `open` the .app
   ```
   Free-team caveat: signed apps **expire after ~7 days** → reinstall; first iPad launch may need Settings → General → VPN & Device Management → trust developer.
9. `## Completing work` — the checklist + "which doc to update" table, **updated to the new doc homes** (architecture change → `ARCHITECTURE.md`; new route → `API.md`; new CLI/service → `OPERATIONS.md`; roadmap → `ROADMAP.md`; user-facing → `README.md`). Commit rule uses the standardized Co-Authored-By string. Replaces `CLAUDE.md`'s "Completing Work" section.

- [ ] **Step 2: Verify all 7 LaunchAgents and the native deploy commands are present**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
for a in api batch-extract calendar-sync cleanup-icloud-old dashboard-update mealplan receipt-ingest; do
  grep -q "com.kitchenos.$a" docs/OPERATIONS.md && echo "$a OK" || echo "$a MISSING"; done
grep -q 'XZJ6358HHF' docs/OPERATIONS.md && echo "signing OK"
grep -q 'devicectl device install' docs/OPERATIONS.md && echo "deploy OK"
```
Expected: seven `OK`, plus `signing OK` and `deploy OK`. No `MISSING`.

- [ ] **Step 3: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add docs/OPERATIONS.md
git commit -m "docs: add OPERATIONS.md runbook incl. native build/deploy + completing-work

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Move BUILD_LOG.md → docs/history/SIRI_BUILD_LOG.md

**Files:**
- Create: `docs/history/` (dir)
- Move: `BUILD_LOG.md` → `docs/history/SIRI_BUILD_LOG.md`

**Interfaces:**
- Consumes: `docs/OPERATIONS.md` §"Native app build / sign / deploy" (Task 6) — the live successor must exist before this freeze.
- Produces: `docs/history/` as the narrative-history home.

- [ ] **Step 1: Guard — confirm the live build/deploy home exists first**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -q 'devicectl device install' docs/OPERATIONS.md && echo "SAFE TO MOVE" || echo "STOP: OPERATIONS lacks deploy commands"
```
Expected: `SAFE TO MOVE`. If `STOP`, return to Task 6 Step 1 §8.

- [ ] **Step 2: Move the file verbatim (preserve history via git mv)**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
mkdir -p docs/history
git mv BUILD_LOG.md docs/history/SIRI_BUILD_LOG.md
ls BUILD_LOG.md 2>&1; ls docs/history/SIRI_BUILD_LOG.md
```
Expected: root `BUILD_LOG.md` → "No such file"; new path lists OK.

- [ ] **Step 3: Repoint any references to BUILD_LOG**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rnE 'BUILD_LOG\.md' --include='*.md' . | grep -v 'docs/history/SIRI_BUILD_LOG.md' | grep -v 'docs/superpowers/'
```
Expected: no output (fix any live reference to point at `docs/history/SIRI_BUILD_LOG.md` before committing).

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add -A
git commit -m "docs: relocate BUILD_LOG.md to docs/history/SIRI_BUILD_LOG.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Salvage into docs/history/ORIGINS.md, then delete the Jan-7 time capsules

**Files:**
- Create: `docs/history/ORIGINS.md`
- Delete: `docs/IMPLEMENTATION_SUMMARY.md`, `docs/SESSION_SUMMARY.md`

**Interfaces:**
- Consumes: `docs/history/` (Task 7).
- Produces: `ORIGINS.md` preserving the only content worth keeping from the two time capsules.

- [ ] **Step 1: Extract the salvage content into ORIGINS.md**

Read `docs/IMPLEMENTATION_SUMMARY.md` and `docs/SESSION_SUMMARY.md`. Create `docs/history/ORIGINS.md` containing only: (a) `## Why standalone over n8n` — the rationale for building a standalone Python solution instead of the originally-planned n8n orchestration; (b) `## Lessons learned` — the Lessons Learned list. Add a one-line header noting these are historical (Jan 2026) and that current architecture lives in `docs/ARCHITECTURE.md`. Do **not** copy the stale n8n webhook steps, worktree/vault paths, or the Future-Enhancements table.

- [ ] **Step 2: Verify salvage captured the rationale, then delete both originals**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -qi 'n8n' docs/history/ORIGINS.md && grep -qi 'lesson' docs/history/ORIGINS.md && echo "SALVAGE OK"
git rm docs/IMPLEMENTATION_SUMMARY.md docs/SESSION_SUMMARY.md
ls docs/IMPLEMENTATION_SUMMARY.md docs/SESSION_SUMMARY.md 2>&1
```
Expected: `SALVAGE OK`; then two "No such file" errors. (If `SALVAGE OK` does not print, do not delete — revisit Step 1.)

- [ ] **Step 3: Verify no live doc still routes updates to the deleted files**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rnE 'IMPLEMENTATION_SUMMARY|SESSION_SUMMARY' --include='*.md' . | grep -v 'docs/superpowers/' | grep -v 'docs/history/ORIGINS.md'
```
Expected: no output. (The `CLAUDE.md` "Lessons learned → IMPLEMENTATION_SUMMARY" checklist row is removed in Task 11; if it still shows here, that's expected and handled there — but any other live reference must be repointed to `docs/history/ORIGINS.md` now.)

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add -A
git commit -m "docs: salvage n8n rationale + lessons into history/ORIGINS.md, delete Jan-7 summaries

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Merge weekly-planning-session into workflows/end-to-end.md, then delete it

**Files:**
- Modify: `docs/workflows/end-to-end.md`
- Delete: `docs/weekly-planning-session.md`

**Interfaces:**
- Produces: `end-to-end.md` as the single user-workflow doc.

- [ ] **Step 1: Diff the two before merging so nothing unique is dropped**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
diff <(grep -E '^#{1,3} ' docs/workflows/end-to-end.md) <(grep -E '^#{1,3} ' docs/weekly-planning-session.md)
```
Expected: a heading diff showing which sections are unique to `weekly-planning-session.md` (e.g. background-services / troubleshooting tables). Those unique sections are what must be folded in.

- [ ] **Step 2: Update end-to-end.md**

Edit `docs/workflows/end-to-end.md`: fold in the unique sections from Step 1 (tutorial voice, background-services + troubleshooting tables). Apply corrections: fix Stage 1a `/extract` response field from `recipe_name` → `recipe`; add the native Siri/App-Intents app as a first-class capture/query surface alongside the Share-Sheet shortcut; fix any `~/KitchenOS` repo-root/log paths to `~/Dev/KitchenOS`.

- [ ] **Step 3: Verify the corrections landed, then delete the source**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -q "'recipe'" docs/workflows/end-to-end.md || grep -qi 'returns .*recipe' docs/workflows/end-to-end.md && echo "field OK"
grep -niE 'recipe_name|/Users/chaseeasterling/KitchenOS[^/]|~/KitchenOS[^/]' docs/workflows/end-to-end.md
git rm docs/weekly-planning-session.md
```
Expected: `field OK`; **no** output from the stale grep; then the file is deleted.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add -A
git commit -m "docs: merge weekly-planning-session into workflows/end-to-end.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Rewrite docs/ROADMAP.md

**Files:**
- Modify (rewrite): `docs/ROADMAP.md`

**Interfaces:**
- Produces: the single "what's next" doc; `CLAUDE.md` and `ORIGINS.md` no longer carry Future-Enhancements tables (CLAUDE.md's is removed in Task 11).

- [ ] **Step 1: Rewrite following the spec's 7-step ROADMAP plan**

Edit `docs/ROADMAP.md`:
1. Header: "ROADMAP = what's next; shipped design history → `docs/superpowers/specs` + `docs/plans/archive`; build history → `docs/history`."
2. Add `## Done / Shipped` recording the native tier: `KitchenOSSiri` XcodeGen target (iOS 26 + macOS 26, bundle `com.kitchenos.siri`), `KitchenOSKit` package, 8–9 App Intents + AppShortcutsProvider, Foundation Models (RecipeAI, MealPlanAssistant + tools), CoreSpotlight/IndexedEntity search (Subsystem C: C1/C2/C3), backend Phase 0 (ingredient filter + bearer auth + `/api/recipes/by-ingredients`), inventory-cleanup screen (`expiry_status`), and the convergence merge (both forked branches gone; both surfaces coexist on `main`).
3. Correct statuses vs code: ML ingredient parser (`lib/ingredient_ml.py`, `KITCHENOS_ML_INGREDIENTS`) GAP → **Done/opt-in**; timed calendar events (`lib/ics_generator.py` `MEAL_TIMES`) PARTIAL/GAP → **Done**.
4. Reframe native inventory: cleanup screen shipped; the concrete next step is the zone+shelf richer layout + the item→(zone,shelf,location) router reconciliation.
5. Add pending native/Siri polish from the superpowers plans: CoreSpotlight keyword enrichment + reindex cadence (C3 follow-up); AppShell `ComingSoonView` placeholder sections not yet native.
6. Keep the branch+commit provenance convention for salvaged Python ideas.

- [ ] **Step 2: Verify**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -qi 'Done' docs/ROADMAP.md && grep -qi 'KitchenOSSiri\|App Intents' docs/ROADMAP.md && echo "shipped-section OK"
grep -qi 'ingredient_ml\|ML ingredient' docs/ROADMAP.md && echo "ml-status OK"
```
Expected: `shipped-section OK` and `ml-status OK`.

- [ ] **Step 3: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add docs/ROADMAP.md
git commit -m "docs: rewrite ROADMAP with native tier Done/Shipped + corrected statuses

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Slim CLAUDE.md to a ~150–250 line always-on quick reference

**Files:**
- Modify (rewrite): `CLAUDE.md`

**Interfaces:**
- Consumes: `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`, `docs/history/ORIGINS.md` — all must exist (Tasks 4–10) so their content can be dropped from `CLAUDE.md` and replaced with pointers.
- Produces: the slim auto-loaded file with a working pointer index and no dangling links.

- [ ] **Step 1: Record the starting size for the reduction check**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
wc -l CLAUDE.md
```
Expected: ~905 lines (baseline).

- [ ] **Step 2: Rewrite CLAUDE.md to keep only always-on content (per the spec's slimming plan)**

Rewrite `CLAUDE.md` to contain **only**:
1. One-paragraph overview mentioning the native app + hybrid AI (per Global Constraints).
2. Design principles/constraints that change how code is written: local-first + honest-about-inference; Python 3.11; Ollama required for extraction; Claude load-bearing for receipts/suggestions; single-DB truth. Drop the "standalone beats n8n" origin framing.
3. Key paths + non-negotiable invariants: vault via `lib/paths.py`/`KITCHENOS_VAULT` (never quote a default); `data/kitchenos.db` single source of truth; generated read-only views; task-ID stability + tasks-cache freshness rule; API restart caveat; `setproctitle`/`kitchenos-*` search rule; `/extract` subprocesses out.
4. Primary commands only: `extract_recipe.py <url>`, `batch_extract.py`, health check, API LaunchAgent restart. Everything else → `docs/OPERATIONS.md`.
5. Env-var/API-key **names only** (label `.env.example` authoritative): `KITCHENOS_VAULT`, `ANTHROPIC_API_KEY`, `USDA_FDC_API_KEY`, `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD` (+ `_2` CSA account), `OPENAI_API_KEY`, `YOUTUBE_API_KEY`, `KITCHENOS_API_TOKEN`.
6. `## Where things live` pointer table → `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`, `docs/workflows/end-to-end.md`, `docs/superpowers/`, `docs/history/`, `docs/plans/archive/INDEX.md`, `lib/CLAUDE.md`.
7. Commit convention with the standardized Co-Authored-By string.

**Delete** (do not relocate): the ~75-row Core Components module index, the Future Enhancements table (→ link to ROADMAP), the inlined Dependencies list (→ `requirements.txt`), the "no maintained function index — it drifts" self-contradiction, the "Obsidian Sync (not iCloud)" constraint. **Remove** the references to the now-deleted `HOW_TO_RUN.md` and `IMPLEMENTATION_SUMMARY.md` and the generic `docs/plans/` pointer (→ `docs/plans/archive/INDEX.md`).

- [ ] **Step 3: Verify size, no dangling links, no stale framing**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
wc -l CLAUDE.md
grep -niE 'n8n|HOW_TO_RUN|IMPLEMENTATION_SUMMARY|Opus 4\.5|python 3\.9|Ollama-only|Core Components' CLAUDE.md
for d in ARCHITECTURE API OPERATIONS ROADMAP; do grep -q "docs/$d.md" CLAUDE.md && echo "ptr $d OK" || echo "ptr $d MISSING"; done
```
Expected: line count ≤ ~260; **no** output from the stale grep; four `ptr … OK`.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add CLAUDE.md
git commit -m "docs: slim CLAUDE.md to always-on quick reference + pointer index

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Rewrite README.md (broaden to the full kitchen OS)

**Files:**
- Modify (rewrite): `README.md`

**Interfaces:**
- Consumes: `docs/ARCHITECTURE.md` (links out for depth).
- Produces: the human front door.

- [ ] **Step 1: Rewrite README**

Edit `README.md`: broaden scope from "YouTube→Obsidian extraction" to the full local-first kitchen OS + native app. Apply corrections: receipts default to Claude (not Ollama-only); Python **3.11** (not 3.9+); fix the broken `iOS_SHORTCUT_SETUP.md` link → `docs/setup/iOS_SHORTCUT_SETUP.md`; add Instagram Reels as a supported source. Keep it a human overview and link to `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md` for depth.

- [ ] **Step 2: Verify the corrections**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -niE 'python 3\.9|Ollama-only' README.md
grep -q 'docs/setup/iOS_SHORTCUT_SETUP.md' README.md && echo "link OK"
grep -qiE 'instagram|reel' README.md && echo "reels OK"
```
Expected: no output from the stale grep; `link OK`; `reels OK`.

- [ ] **Step 3: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add README.md
git commit -m "docs: broaden README to full kitchen OS + native app; fix stale claims

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Surgical in-place fixes — setup, workflows, superpowers docs

**Files:**
- Modify: `docs/setup/iOS_SHORTCUT_SETUP.md`, `docs/setup/DRAFTS_RECIPE_ACTION.md`, `docs/superpowers/specs/2026-06-21-siri-app-intents-voice-design.md`, `docs/superpowers/specs/2026-06-23-apple-intelligence-subsystem-c-design.md`, `docs/superpowers/specs/2026-06-26-inventory-cleanup-screen-design.md`, `docs/superpowers/plans/*.md`

**Interfaces:**
- Produces: corrected setup + superpowers docs (no content moves, just fixes).

- [ ] **Step 1: Fix the setup docs**

Edit `docs/setup/iOS_SHORTCUT_SETUP.md`: add a note at the top that the Share-Sheet `/extract` shortcut is now a **legacy/alternate** path to the primary native app; drop the vestigial "find Tailscale IP" step; replace any inlined LaunchAgent plist with a link to `docs/OPERATIONS.md` / `ops/*.plist`.
Edit `docs/setup/DRAFTS_RECIPE_ACTION.md`: fix `~/selene` → `~/Dev/selene` (all occurrences).

- [ ] **Step 2: Fix the superpowers specs/plans**

Edit each file in `docs/superpowers/specs/`: flip `Status:` lines from "Approved design, pending implementation plan / pending per-phase plans" → **Implemented**. In `2026-06-23-apple-intelligence-subsystem-c-design.md`, annotate that the C3 "App Schemas" approach was superseded by **IndexedEntity** in its own plan.
Edit `docs/superpowers/plans/*.md`: fix stale `~/Dev/KitchenOS-siri` worktree references → `~/Dev/KitchenOS` (worktree retired at convergence).

- [ ] **Step 3: Verify**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rn '~/selene[^/]' docs/setup/DRAFTS_RECIPE_ACTION.md
grep -rn 'KitchenOS-siri' docs/superpowers/
grep -rniE 'pending (implementation plan|per-phase)' docs/superpowers/specs/
```
Expected: **no** output from all three (except this plan/spec, which legitimately name `KitchenOS-siri` in historical context — if the second grep only hits `docs/superpowers/specs/2026-07-01-docs-reorg-*` or `plans/2026-07-01-docs-reorg-plan.md`, that is acceptable).

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add docs/setup docs/superpowers
git commit -m "docs: fix setup Selene path, mark superpowers specs Implemented, drop stale worktree refs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Surgical in-place fixes — .claude, scripts, .env.example

**Files:**
- Modify: `.claude/agents/meal-plan-reviewer.md`, `.claude/skills/recipe-debug/SKILL.md`, `.claude/skills/finish-feature/SKILL.md`, `scripts/kitchenos-uri-handler/README.md`, `.env.example`

**Interfaces:**
- Produces: corrected agent/skill/script/config files. `failure-pattern-analyzer.md` is verified current — do **not** touch it.

- [ ] **Step 1: Fix the agent and skills**

Edit `.claude/agents/meal-plan-reviewer.md`: line ~22 `cd /Users/chaseeasterling/KitchenOS` → `/Users/chaseeasterling/Dev/KitchenOS`; fix vault-relative inputs to include the `KitchenOS/` subfolder (`vault/KitchenOS/Meal Plans/…`, `vault/KitchenOS/My Macros.md`).
Edit `.claude/skills/recipe-debug/SKILL.md`: Stage 10 — repoint from the deprecated `lib/nutrition_lookup.py` / 3-source Nutritionix lookup → `lib/nutrition_engine.py` → `food_db.py`/`food_resolver.py` (USDA FoodData Central + Open Food Facts, `USDA_FDC_API_KEY`).
Edit `.claude/skills/finish-feature/SKILL.md`: standardize the commit footer Co-Authored-By string to `Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

- [ ] **Step 2: Fix the URI-handler README and .env.example**

Edit `scripts/kitchenos-uri-handler/README.md`: line ~16 Automator install path `/Users/chaseeasterling/KitchenOS` → `/Users/chaseeasterling/Dev/KitchenOS`.
Edit `.env.example`: add the missing real keys — `ANTHROPIC_API_KEY`, `USDA_FDC_API_KEY`, `GMAIL_APP_PASSWORD`, the second CSA Gmail (`GMAIL_ADDRESS_2`/`GMAIL_APP_PASSWORD_2`), and `NUTRITIONIX_APP_ID`/`NUTRITIONIX_API_KEY` labeled `# legacy/deprecated`; fix the vault-path comment to reference `KITCHENOS_VAULT` (do not quote a default path).

- [ ] **Step 3: Verify**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rniE '/Users/chaseeasterling/KitchenOS[^/]|nutrition_lookup|Opus 4\.5|Opus 4\.6' .claude scripts/kitchenos-uri-handler/README.md
for k in ANTHROPIC_API_KEY USDA_FDC_API_KEY GMAIL_APP_PASSWORD GMAIL_ADDRESS_2; do grep -q "$k" .env.example && echo "$k OK" || echo "$k MISSING"; done
```
Expected: **no** output from the stale grep; four `OK`, no `MISSING`.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git add .claude scripts/kitchenos-uri-handler/README.md .env.example
git commit -m "docs: fix agent/skill paths, nutrition module ref, Co-Authored-By, and .env.example keys

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Whole-tree verification sweep + finish the branch

**Files:**
- Modify: none (verification + integration)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean tree with zero stale references and a merged/PR'd branch.

- [ ] **Step 1: Run the full stale-reference sweep (must be near-empty)**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rniE 'n8n|nutrition_lookup|Opus 4\.5|Opus 4\.6|python 3\.9|/Users/chaseeasterling/KitchenOS[^/]|~/selene[^/]|HOW_TO_RUN|Ollama-only' \
  --include='*.md' . \
  | grep -v 'docs/superpowers/specs/2026-07-01-docs-reorg-design.md' \
  | grep -v 'docs/superpowers/plans/2026-07-01-docs-reorg-plan.md' \
  | grep -v 'docs/history/'
```
Expected: no output. (The recovered design spec, this plan, and `docs/history/` narrative legitimately mention n8n/old paths in historical context; everything else must be clean. Investigate and fix any other hit.)

- [ ] **Step 2: Confirm no dangling links to deleted/moved files remain**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
grep -rnE 'IMPLEMENTATION_SUMMARY|SESSION_SUMMARY|weekly-planning-session|docs/stories|BRANCH-STATUS|BUILD_LOG\.md' \
  --include='*.md' . \
  | grep -v 'docs/history/' | grep -v 'docs/superpowers/.*2026-07-01'
```
Expected: no output.

- [ ] **Step 3: Confirm the canonical set exists and CLAUDE.md is slim**

Run:
```bash
cd /Users/chaseeasterling/Dev/KitchenOS
for f in docs/ARCHITECTURE.md docs/API.md docs/OPERATIONS.md docs/ROADMAP.md docs/history/ORIGINS.md docs/history/SIRI_BUILD_LOG.md docs/plans/archive/INDEX.md; do
  [ -f "$f" ] && echo "OK  $f" || echo "MISSING  $f"; done
wc -l CLAUDE.md
```
Expected: seven `OK`; `CLAUDE.md` ≤ ~260 lines.

- [ ] **Step 4: Flag the out-of-repo side item**

The app-signing deploy commands have now been migrated into `docs/OPERATIONS.md`. Report to the user (do not silently edit memory): the `project-kitchenos-app-signing` memory note can be updated to point at `docs/OPERATIONS.md` as the canonical home. (The `project-kitchenos-worktrees` convergence note is already current — no action.)

- [ ] **Step 5: Finish the branch**

Use the **superpowers:finishing-a-development-branch** skill to choose merge vs PR. Suggested PR title: `docs: reorganize to one-home-per-type (slim CLAUDE.md, add ARCHITECTURE/API/OPERATIONS)`.

---

## Self-Review

**Spec coverage** — every disposition in the spec maps to a task:
- 71 legacy plans → archive + INDEX → **Task 2**
- Dead story system + HOW_TO_RUN delete → **Task 3**
- ARCHITECTURE / API / OPERATIONS new docs → **Tasks 4 / 5 / 6**
- BUILD_LOG → history (after OPERATIONS) → **Task 7**
- IMPLEMENTATION_SUMMARY salvage→ORIGINS + SESSION_SUMMARY delete → **Task 8**
- weekly-planning-session merge → end-to-end → **Task 9**
- ROADMAP rewrite → **Task 10**
- CLAUDE.md slim → **Task 11**
- README broaden → **Task 12**
- setup/superpowers fixes → **Task 13**
- .claude/scripts/.env.example fixes → **Task 14**
- All 19 doc↔code contradictions are folded into the task that owns the affected file (Global Constraints carry the cross-cutting ones); verification sweep in **Task 15** proves they're gone.
- Critic's flagged risks resolved: native build/deploy gets a live home in OPERATIONS **before** BUILD_LOG freeze (Tasks 6→7 ordering + guard step); all 7 LaunchAgents enumerated (Task 6 verify); story.sh given an explicit delete disposition (Task 3); two archive roots only (Tasks 2 + 7/8); env keys as NAMES-only in CLAUDE.md with .env.example authoritative (Task 11).

**Open questions from the spec** resolved by the locked-in decisions: story system → delete (Task 3); README → broaden (Task 12); native-app setup → covered by ARCHITECTURE + OPERATIONS + setup link (no separate NATIVE_APP.md, per finalized 3-new-doc decision); git-repo state → confirmed a repo (Task 1). Two remain genuinely deferred and are surfaced, not silently decided: `ingredient-data-cleaning.md` live-vs-done (kept in place, Task 2) and Nutritionix key retention (kept as labeled-legacy, Task 14) — flag both to the user during execution if a decision is wanted.

**Placeholder scan:** no "TBD"/"handle edge cases"/"similar to Task N" — each doc task names its exact sections, source files, and corrections. Doc-content tasks give a concrete section list rather than a vague instruction; verification steps use exact greps with expected output.

**Consistency:** file paths, the Co-Authored-By string, and the 7-LaunchAgent list are identical across all tasks (centralized in Global Constraints). Task ordering respects dependencies: new canonical docs (4–6) precede the deletions/moves that depend on them (7–8) and the CLAUDE.md slim (11) that points at them.
