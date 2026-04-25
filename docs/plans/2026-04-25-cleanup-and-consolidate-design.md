# Cleanup & Consolidate Design

**Date:** 2026-04-25
**Status:** Design approved, awaiting implementation plan

## Goal

KitchenOS is becoming a fully integrated kitchen operating system (recipes → meal planning → inventory). Before adding inventory and other domains, the project needs a single, clean home: code, recipe data, and process docs cleanly separated under one repo.

Today there are **three** disconnected copies of the codebase on disk and the running production services point at the wrong one.

## Current state (the mess)

| Location | Role today | Status |
|---|---|---|
| `~/KitchenOS/` | The repo we actively edit (this conversation) | Newer; on commit `05c5721` |
| `~/Documents/GitHub/KitchenOS/` | A second clone of the same GitHub repo | 5 commits behind; **all four LaunchAgents point here** |
| iCloud `…/iCloud~md~obsidian/Documents/KitchenOS/` | Obsidian vault — also contains a duplicated copy of the code from the "consolidate vault + code repo" commit | Vault user data lives here; code copies are dead weight |

Effect: any feature work merged to `~/KitchenOS/` (smart meal planner Phase A docs, visual planner card fixes, seasonal logic) is **not** what the LaunchAgents are running.

## Target end state

Single repo at `~/KitchenOS/`, GitHub-tied, with three buckets cleanly separated:

```
~/KitchenOS/                                    ← single git repo, GitHub source of truth
├── api_server.py, extract_recipe.py, …        ← code stays at root (no app/ subdir)
├── lib/, prompts/, templates/, scripts/, config/, tests/
├── docs/                                       ← process docs, plans, CLAUDE.md, README.md
├── ops/                                        ← LaunchAgent plists move here
├── KitchenOSApp/                               ← stays at root
├── logs/                          (gitignored) ← server.log, batch_extract.log, etc.
├── failures/                      (gitignored, exists)
├── .venv/, __pycache__, .ruff_cache  (gitignored, exists)
└── vault/                         (gitignored) ← THE Obsidian vault
    ├── .obsidian/                              ← Obsidian opens vault/ as the vault root
    ├── Recipes/, Meal Plans/, Shopping Lists/
    ├── Inventory/                              ← empty placeholder; populated later
    ├── Dashboards/                             ← Home.md, Dashboard.md, *.canvas, *.base
    ├── Macro Worksheet.md
    └── meal_calendar.ics
```

The other two code copies are deleted.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Single root or split repos? | Single root | Simpler mental model; Obsidian-Sync handles iPad without iCloud |
| iCloud vs local vault? | Local (Obsidian Sync handles iPad) | No more iCloud thrash on `.venv/`, `__pycache__/`, logs |
| Code under `app/` subdir? | No — stays at root | Smallest possible diff; "app/" rename is churn for churn's sake |
| Code copies in iCloud? | Deleted | Pure dead weight from the consolidate commit |
| Recipe folder location? | Subfolder of unified root (`vault/`) | User stipulation: recipe DB is a sub-part of the system |
| Vault path in code? | Centralized via `KITCHENOS_VAULT` env var with `~/KitchenOS/vault/` default | One config helper replaces 12+ hardcoded iCloud paths |
| Plists location? | `~/KitchenOS/ops/` | Matches new structure; install via `cp ops/*.plist ~/Library/LaunchAgents/` |
| iCloud vault deletion? | Deferred 7 days | Rename to `KitchenOS.OLD-DELETE-AFTER-2026-05-02/` first; manual delete after |
| Inventory scaffolding included? | No (out of scope) | This cleanup is strictly mechanical; inventory is a separate brainstorm |

## Migration plan (12 steps)

### Phase 1: Preserve

1. Tarball iCloud vault → `~/Backups/kitchenos-icloud-2026-04-25.tar.gz`
2. Push current `~/KitchenOS/` to GitHub `main`

### Phase 2: Stop running services

3. Unload all four LaunchAgents (`com.kitchenos.api`, `…batch-extract`, `…calendar-sync`, `…mealplan`)

### Phase 3: Centralize the vault path in code

4. Add `lib/paths.py` with `KITCHENOS_VAULT` env-var support and `~/KitchenOS/vault/` default. Replace hardcoded iCloud paths in:
   - `extract_recipe.py`, `api_server.py`, `migrate_recipes.py`, `migrate_cuisine.py`,
     `import_crouton.py`, `generate_meal_plan.py`, `generate_nutrition_dashboard.py`,
     `shopping_list.py`, `sync_calendar.py`,
     `lib/shopping_list_generator.py`, `scripts/add_button_to_meal_plans.py`
5. Commit: `refactor: centralize vault path config`

### Phase 4: Move the data

6. Create `~/KitchenOS/vault/`. Move from iCloud vault: `Recipes/`, `Meal Plans/`, `Shopping Lists/`, `.obsidian/`, `Macro Worksheet.md`, `Home.md`, `Dashboard.md`, `*.canvas`, `*.base`, `meal_calendar.ics`, `Quick Add Template.md`. Group dashboards under `vault/Dashboards/` if desired.
7. Create empty `~/KitchenOS/vault/Inventory/` placeholder
8. Reconfigure Obsidian Sync to track `~/KitchenOS/vault/`. Verify iPad pulls recipes.

### Phase 5: Repoint and restart

9. Rewrite four plists to reference `~/KitchenOS/`, move them into `ops/`, reinstall to `~/Library/LaunchAgents/`
10. Update `.gitignore` (add `vault/`, `logs/`). Update `CLAUDE.md` paths. Commit.

### Phase 6: Demolish duplicates

11. Delete `~/Documents/GitHub/KitchenOS/` entirely (including its `.venv`)
12. Rename iCloud vault to `KitchenOS.OLD-DELETE-AFTER-2026-05-02/`. Manual delete after 7 days.

## Verification gate (between steps 10 and 11)

Must all pass before deleting the secondary copies:

```bash
# 1. No hardcoded vault paths remain
grep -rn "Mobile Documents\|iCloud~md~obsidian" --include="*.py" --include="*.sh"
# expect: zero hits

# 2. Smoke test extraction
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=bJUiWdM__Qw"

# 3. API server health
curl -s http://localhost:5001/health

# 4. All four LaunchAgents loaded
launchctl list | grep kitchenos       # 4 entries, no negative exit codes

# 5. Vault contents intact
ls vault/Recipes | wc -l                # ~same count as old iCloud Recipes/
```

Plus manual: open Obsidian on Mac (vault loads), open Obsidian on iPad (Sync pulls recipes).

## Risks and rollback

| Risk | Mitigation |
|---|---|
| Missed hardcoded path | Verification gate grep at step 10 |
| Obsidian Sync confusion on relocation | Pause Sync before step 6, repoint before re-enabling; tarball is fallback |
| `.obsidian/` config drift between repo-root and iCloud copies | Use iCloud `.obsidian/` (real plugin config); discard repo-root copy from consolidate commit |
| LaunchAgents fail silently after path change | `launchctl list \| grep kitchenos` + `tail logs/server.log` after step 9 |
| Stale `.venv` in `~/Documents/GitHub/KitchenOS/` | Step 11 deletes the whole tree including its `.venv` |
| MCP / Claude Desktop still pointing at old path | Check `~/Library/Application Support/Claude/claude_desktop_config.json`; update if present |
| Obsidian URI handler script paths | `scripts/kitchenos-uri-handler/` refs may need updating if its registered handler points absolute |

**Rollback windows:**
- Before step 6 (data move): undo code commits; user data untouched
- Steps 6–11: tarball restore + revert plists; iCloud copy still present
- After step 12 (rename): tarball is the only recovery
- After +7 days (real delete): tarball is the only recovery

## What this cleanup explicitly does NOT do

- Rename code (no `app/` subdir, no module renames)
- Restructure imports
- Add inventory features or scaffolding (separate brainstorm)
- Add Claude API fallback for Ollama
- Touch the smart meal planner Phase A work in flight

## Next step

Hand off to `writing-plans` skill to produce a per-step implementation plan with exact commands, expected outputs, and review checkpoints.
