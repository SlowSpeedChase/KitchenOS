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
- **`data/kitchenos.db` is the single source of truth** for inventory/purchases/trips. `Inventory.md`, `Price Tracker.md`, `Use It Up.md`, `Cook Now.md`, `Dashboards/On Track.md`, and similar files are **generated, read-only views** — they carry a do-not-edit banner, are rewritten on every relevant change, and hand edits are silently overwritten.
- **Generated views render from the DB, never from a caller's list.** `write_inventory()` re-reads the committed rows before rendering `Inventory.md`, because `cook_now.write_note()` re-reads the DB too — rendering one view off the argument and the other off the database let the two notes disagree, and once shipped an empty `Inventory.md` beside a populated `Cook Now.md`. Any new generated view must read the DB after the commit.
- **Pantry staples are real inventory rows.** `seed_pantry_staples()` writes the `config/pantry_staples.json` entries into inventory with `source: staple` and no `expires`, so they never age out and never appear in Use-It-Up. Staples are still credited as on-hand by `_is_staple`, but they are now visible stock rather than an invisible assumption — don't reintroduce a matcher that assumes a staple that isn't in the DB.
- **`My Meal System.md` is hand-authored and grows.** `lib/profile.py` parses only the sections with structural consumers and passes the rest as prose to LLM prompts — so adding a section to that note must never require a code change. Don't "tidy" it into a config file.
- **`fit_*` recipe frontmatter is inference, not measurement.** Written by `backfill_fit.py` from an ingredient list; `fit_heart`/`fit_steady` cannot currently be computed (no fibre or saturated fat in `NutritionData` or `fdc_foods`). Always carries `fit_needs_review: true`. Don't present these as facts.
- **Task-ID stability**: `lib/task_extractor.py` IDs are `sha1(recipe|day|slot|step)[:12]` so `done` flags survive plan regeneration. The tasks-cache sidecar (`<week>.tasks.json`) is fresh only when `sidecar_mtime >= plan_mtime`; pass `force=True`/`?force=1` to recompute otherwise.
- **API restart caveat**: `com.kitchenos.api` LaunchAgent holds `lib/*` in memory. Editing any `lib/`, template, or prompt file requires a LaunchAgent restart (see below) or the server keeps serving stale code — this shows up as 500s / wrong behavior that looks like a data bug.
- **Process lookup**: LaunchAgent python services self-rename via `setproctitle`. `pgrep -f <script>.py` will NOT match a running service — search `kitchenos-*` instead.
- **`/extract` API endpoint shells out** to `extract_recipe.py` as a subprocess rather than importing the pipeline in-process; don't assume in-process state (env, caches) is shared between the API server and an extraction it triggers.
- **A new browsable page must be registered and bookmarked.** Any new HTML page route (one served through `_serve_page_with_claude_bar`) goes in `SECTIONS` in `lib/web_dashboard.py` — the single registry feeding the vault launcher note, the `/` home page, and Safari. Then propagate it: `scripts/generate_web_dashboard.py` and `scripts/sync_safari_bookmarks.py --apply`. **The sync quits and relaunches Safari — that is pre-authorized, do it without asking**; Safari restores its tabs, and it no-ops if Safari isn't running. Pages that can't be bookmarked (path params like `/recipe/<name>`, required query params like `/add-to-meal-plan?recipe=`) go in `NOT_BOOKMARKABLE` in `tests/test_web_dashboard.py` with a reason instead. `/` itself is neither: it's `HOME` in `lib/web_dashboard.py`, the registry root, kept out of `SECTIONS` because the home page renders `SECTIONS` and would otherwise list itself. Skipping all three (`SECTIONS`, `NOT_BOOKMARKABLE`, or `HOME` for `/`) fails the test suite.
- **`dish_type` is a closed vocabulary.** `normalizer.VALID_DISH_TYPES` is derived from `DISH_TYPE_MAP`'s targets, and every value must map to a chip group in `lib/cook_now.py` `DISH_TYPE_GROUPS` — a dish type with no group is unreachable in the `/cook-now` filter, and `tests/test_cook_now.py` fails if one appears. Don't add a `DISH_TYPE_MAP` variant pointing at a brand-new target without adding that target to a chip group. Note that mapping a *savory* item to `dessert` (as `"biscuit"` once did) silently hides it from meal-type filtering.
- **Inventory rows are containers, not counts — a cook may reduce a row but never delete one.** 188 of 198 count-family rows sit at quantity 1.0 because that is the ingest default meaning "one package", and 15 of 17 `oz` rows are a `1.0 oz` package. So `lib/cook.py` use-stamps (`last_used`, `use_count`) rather than decrementing in **four** cases, not just the obvious one: quantity exactly `1.0`; the smallest of several rows sharing `(name, unit)` being 1.0; more than one such row existing at all (`load_pantry` sums them across locations, so the total hides the parts — and `save_pantry` collapses duplicates on write, which would drop a row outright); and any volume/weight decrement that would zero the row out (`_convert_would_empty`), since a `5 oz` row matched by a `250 g` line is a unit-of-sale mismatch, not five ounces running out. Removing any of these deletes a whole jar of bay leaves for a recipe calling for three, and a wrongly deleted row does not self-heal the way a missed depletion does (the expiry prune covers that). Count-family full depletion *is* legitimate and still happens — 5 whole limes against a 5 ct row empties it.
- **`unit_compatibility` is the authority on whether two units can be subtracted.** `lib/ingredient_aggregator.unit_compatibility` decides; `apply_decisions` delegates to it entirely, and `split_against_pantry` delegates for the count family. They once hand-wrote different rules and the shopping list credited limes the cook then refused to spend. Note the delegation is not yet total: `split_against_pantry`'s volume/weight branch keeps its own cross-family precheck that treats the `other` family as a wildcard, so a *unitless* recipe line against a weight row can still be credited by the shopping list and refused by the cook. Zero occurrences in the current corpus (the extractor almost always supplies a unit) — but don't read this invariant as "already fully delegated".
- **`location_source` is provenance, not address.** `InventoryItem.merge_key()` is `(name, unit, location)`; adding `location_source` to it would fragment a row into one copy per provenance. A NULL or unrecognised value normalizes to `default`, which renders as unsure — the failure direction is always toward being asked again, never toward posing as confirmed. Note that `by_category` covers all ten values of `CATEGORIES`, so the bare `pantry` fallback in `place_item` is unreachable for any row with a real category; a hit on the catch-all `other` category reports `default`, and that is the only thing making the tier reachable at all. Don't "simplify" that back into a plain category hit.
- **Teaching the storage table is a write, so tests must be isolated from it.** `move_item` and a bulk move call `save_item_override`, which rewrites `config/storage_locations.json` wholesale with sorted keys. Two isolation layers exist because there are two ways to reach it: `tests/conftest.py::_isolate_storage_table` (autouse) copies the table for in-process tests, and `storage_locations.table_path()` honours `KITCHENOS_STORAGE_TABLE` so the e2e harness — which runs `api_server.py` as a *subprocess* an in-process patch can't reach — points its server at a copy. Both were added after the real config was observed being rewritten: the in-process tests flipped `bread` from counter to pantry, and the browser tests injected their fixture item names. If you add a code path that teaches, check both layers still cover it.

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
- `KITCHENOS_STORAGE_TABLE` — overrides the path of `config/storage_locations.json`. Test infrastructure only: the e2e harness sets it so its out-of-process server teaches a throwaway copy instead of the real config. Unset in normal operation.

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
