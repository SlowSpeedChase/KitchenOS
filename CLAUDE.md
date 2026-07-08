# CLAUDE.md

Always-on quick reference for Claude Code when working in this repository. For anything
beyond invariants and primary commands, follow the pointers in "Where things live" below.

## Project Overview

**KitchenOS** is a home-kitchen system built around a YouTube/Instagram/web-to-Obsidian
recipe extraction pipeline, backed by a native iOS/macOS app (Siri/App Intents) and a
hybrid AI stack: local Ollama for extraction, seasonal matching, and receipt parsing;
Claude (API) as the load-bearing model for meal suggestions and receipt parsing when a key
is configured. It captures cooking videos and recipe pages, extracts structured recipe
data, tracks pantry inventory from receipts, and generates meal plans, shopping lists, and
a nutrition dashboard — all stored as markdown in an Obsidian vault plus one SQLite
database for anything that needs to be queried or mutated.

## Design Principles & Constraints

| Principle | Rationale |
|-----------|-----------|
| **Local-first** | Privacy, no cloud dependency, works offline (except YouTube/web fetch) |
| **Obsidian-native** | YAML frontmatter for Dataview, flat folder structure |
| **Honest about inference** | Mark uncertain data, set `needs_review` flag |
| **Graceful degradation** | Missing transcript → try Whisper → use description only |
| **Additive, never a chore** | Inventory/waste features must self-clean (auto-age-out) — never require manual upkeep |

Constraints that change how code is written:
- **Python 3.11** — full f-string support including backslashes. Always run via `.venv/bin/python`.
- **Ollama required** for extraction, seasonal matching, and receipt parsing (Ollama fallback when Claude isn't configured/available).
- **Claude (Anthropic API) is load-bearing**, not optional-nice-to-have, for receipt parsing (when `ANTHROPIC_API_KEY` is set) and meal suggestions.
- **Single DB truth**: inventory and price history live only in `data/kitchenos.db`; never reintroduce a parallel JSON/markdown source of truth for that data.

## Key Paths & Non-Negotiable Invariants

| Path | Purpose |
|------|---------|
| `/Users/chaseeasterling/Dev/KitchenOS/` | Project root |
| `.venv/` | Python virtual environment |
| `Recipes/` in Obsidian vault | Main recipe files (title case, e.g., `Butter Biscuits.md`) |
| `Recipes/Images/` in Obsidian vault | Recipe images |
| `data/kitchenos.db` | SQLite — inventory, purchases, trips, nutrition cache. Single source of truth. |

Invariants — violating these causes real bugs, not just style drift:

- **Vault path**: always resolve via `lib/paths.py` helpers (`vault_root()`, `recipes_dir()`, `meal_plans_dir()`, `meals_dir()`), which read `KITCHENOS_VAULT` from `.env`. Never hardcode a vault path, and never quote or rely on the `lib/paths.py` fallback default — `.env` always overrides it in this repo, so treat the default as dead code, not documentation.
- **`data/kitchenos.db` is the single source of truth** for inventory/purchases/trips. `Inventory.md`, `Price Tracker.md`, `Use It Up.md`, `Cook Now.md`, and similar files are **generated, read-only views** — they carry a do-not-edit banner, are rewritten on every relevant change, and hand edits are silently overwritten.
- **Task-ID stability**: `lib/task_extractor.py` IDs are `sha1(recipe|day|slot|step)[:12]` so `done` flags survive plan regeneration. The tasks-cache sidecar (`<week>.tasks.json`) is fresh only when `sidecar_mtime >= plan_mtime`; pass `force=True`/`?force=1` to recompute otherwise.
- **API restart caveat**: `com.kitchenos.api` LaunchAgent holds `lib/*` in memory. Editing any `lib/`, template, or prompt file requires a LaunchAgent restart (see below) or the server keeps serving stale code — this shows up as 500s / wrong behavior that looks like a data bug.
- **Process lookup**: LaunchAgent python services self-rename via `setproctitle`. `pgrep -f <script>.py` will NOT match a running service — search `kitchenos-*` instead.
- **`/extract` API endpoint shells out** to `extract_recipe.py` as a subprocess rather than importing the pipeline in-process; don't assume in-process state (env, caches) is shared between the API server and an extraction it triggers.

## Primary Commands

```bash
cd /Users/chaseeasterling/Dev/KitchenOS

# Extract a recipe (YouTube, Instagram Reel, or web URL — auto-detected)
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
.venv/bin/python extract_recipe.py --dry-run "VIDEO_URL"   # preview without saving

# Batch-extract from the "Recipies to Process" Reminders list
.venv/bin/python batch_extract.py

# API server health check
curl http://localhost:5001/health

# Restart the API LaunchAgent (required after editing lib/, templates/, or prompts/)
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

Everything else — meal planning, shopping lists, receipt/CSA ingest, calendar sync,
nutrition dashboard, dedupe, migrations, all other LaunchAgents — is in `docs/OPERATIONS.md`.

## Environment / API Keys

Names only — `.env.example` is the authoritative reference for descriptions, defaults, and
which are optional:

- `KITCHENOS_VAULT` — Obsidian vault path
- `ANTHROPIC_API_KEY` — Claude API (receipt parsing, meal suggestions)
- `USDA_FDC_API_KEY` — USDA FoodData Central (nutrition engine)
- `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` (+ `_2` for the CSA-newsletter account) — receipt/CSA email ingest
- `OPENAI_API_KEY` — Whisper transcript fallback
- `YOUTUBE_API_KEY` — YouTube Data API
- `KITCHENOS_API_TOKEN` — bearer token gating remote (non-localhost) calls to the Siri-facing API routes; see `docs/API.md` for the exact gated-route list

## Where things live

| Topic | Doc |
|-------|-----|
| System architecture, pipeline flow, module map | `docs/ARCHITECTURE.md` |
| API routes, MCP tools, Siri/App Intents | `docs/API.md` |
| Full command reference, LaunchAgents, deploy, maintenance | `docs/OPERATIONS.md` |
| Planned work / priorities | `docs/ROADMAP.md` |
| End-to-end weekly workflow walkthrough | `docs/workflows/end-to-end.md` |
| Spec-driven-development process docs | `docs/superpowers/` |
| Project history, origin decisions, lessons learned | `docs/history/` (see `docs/history/ORIGINS.md`) |
| Archived/superseded design docs | `docs/plans/archive/INDEX.md` |
| `lib/` module conventions | `lib/CLAUDE.md` |
| User-facing install/usage guide | `README.md` |

## Commit Convention

```
type: short description

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

Before committing a feature or fix, check whether the change needs a doc update per the
table above (architecture change → ARCHITECTURE.md, new endpoint contract → API.md, new
command/LaunchAgent → OPERATIONS.md, new invariant → this file).
