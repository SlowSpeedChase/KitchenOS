# KitchenOS

A local-first, home-kitchen operating system. KitchenOS extracts structured
recipes from YouTube, Instagram Reels, and recipe web pages into an Obsidian
vault; tracks pantry inventory and price history from grocery receipts and a
CSA subscription; generates weekly meal plans, pantry-aware shopping lists,
and a nutrition dashboard; and ships a native iOS/macOS app (Siri / App
Intents) as an on-device client. Everything lives on your own machine as
markdown plus one SQLite database — nothing is required to leave your Mac
except the video/web fetch itself and the AI calls you opt into.

AI is hybrid, not a single model: local Ollama (`mistral:7b`) handles recipe
extraction, seasonal matching, and receipt parsing as a fallback; the Claude
API is the **load-bearing** model for receipt parsing and meal suggestions
whenever `ANTHROPIC_API_KEY` is configured; OpenAI Whisper is the transcript
fallback; and the native app additionally uses on-device Apple Foundation
Models.

For deeper technical detail than this overview covers, see:

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — what exists: pipeline flow, web/API tier, background LaunchAgents, data model, native app tier
- **[docs/OPERATIONS.md](docs/OPERATIONS.md)** — the full command reference, LaunchAgent install/restart, deploy, maintenance
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — what's shipped and what's genuinely still open

## What It Does

- **Extracts recipes** from YouTube videos, Instagram Reels, and recipe web
  pages — including videos where someone is cooking and talking with no
  written recipe card, and descriptions buried in sponsor noise.
- **Tracks pantry inventory and price history** from grocery receipt emails,
  photo receipts, a CSA newsletter subscription, or manual entry, in a local
  SQLite database — with generated, read-only `Inventory.md` and
  `Price Tracker.md` views in Obsidian.
- **Generates weekly meal plans** and pantry-aware shopping lists that split
  each line into what you already have vs. what to buy.
- **Builds a nutrition dashboard** from a gram-based nutrition engine backed
  by USDA FoodData Central.
- **Ships a native iOS/macOS app** (`KitchenOSSiri` + shared `KitchenOSKit`)
  with Siri/App Intents, on-device Apple Foundation Models, and
  CoreSpotlight search, talking to the same API server as everything else.
- **Creates a searchable database** of all of the above in Obsidian,
  browsable with Dataview.

## Quick Start

```bash
cd /Users/chaseeasterling/Dev/KitchenOS

# Extract a recipe — YouTube, Instagram Reel, or recipe URL (auto-detected)
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"
.venv/bin/python extract_recipe.py "https://www.instagram.com/reel/REEL_ID/"
```

The recipe is saved to your Obsidian vault. See
[docs/OPERATIONS.md](docs/OPERATIONS.md) for the full command reference
(meal planning, shopping lists, receipt/CSA ingest, dashboards, the native
app build/deploy, and the 7 background LaunchAgents).

## Installation

### Prerequisites

- Python 3.11
- [Ollama](https://ollama.ai/) with the `mistral:7b` model — required for
  extraction, seasonal matching, and as the receipt-parsing fallback
- YouTube API key
- OpenAI API key (for Whisper transcript fallback)
- Anthropic API key (`ANTHROPIC_API_KEY`) — optional but recommended; when
  set, Claude does the load-bearing work for receipt parsing and meal
  suggestions instead of the Ollama fallback

### Setup

1. **Clone and enter directory:**
   ```bash
   cd /Users/chaseeasterling/Dev/KitchenOS
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure API keys** (create `.env` file). Names only — see
   `.env.example` for the full, authoritative list with descriptions and
   defaults:
   ```bash
   YOUTUBE_API_KEY="your_youtube_api_key"
   OPENAI_API_KEY="your_openai_api_key"
   ANTHROPIC_API_KEY="your_anthropic_api_key"   # optional; enables Claude for receipts + meal suggestions
   USDA_FDC_API_KEY="your_usda_fdc_api_key"     # optional; nutrition engine
   ```

4. **Install Ollama model:**
   ```bash
   ollama pull mistral:7b
   ollama serve  # Run in background
   ```

5. **Create Obsidian vault folder and set `KITCHENOS_VAULT`** in `.env`:
   ```bash
   mkdir -p ~/Dev/KitchenOS/vault/KitchenOS/Recipes
   ```
   `KITCHENOS_VAULT` is required in practice — every path in the codebase
   resolves through `lib/paths.py`, and its fallback default is not
   meaningful for a real deployment.

## Recipe Extraction

KitchenOS extracts recipes using a priority chain, in order:

1. **Webpage** — if a description (or first comment) links a recipe page,
   scrapes JSON-LD structured data from it
2. **Description** — if the description (or comment) has an inline recipe
   (ingredients + method), parses it directly
3. **Creator website** — falls back to searching the creator's own site
4. **Transcript** — falls back to AI extraction from the video/audio
   transcript via Ollama

Instagram Reels get metadata and audio via `yt-dlp` and feed the caption
plus a Whisper transcript into the same pipeline. When using a webpage,
description, or comment source, KitchenOS also extracts practical cooking
tips from the video that aren't in the written recipe.

Batch processing is available via an iOS Reminders queue
(`batch_extract.py`, also run hourly as a LaunchAgent) — see
[docs/OPERATIONS.md](docs/OPERATIONS.md) for setup and usage.

## Grocery Receipts, CSA & Price Tracking

KitchenOS tracks pantry inventory and grocery price history in a local
SQLite database (`data/kitchenos.db`), the single source of truth for that
data. Items enter automatically or manually:

- **Email (automatic)** — an hourly LaunchAgent checks Gmail for HEB receipt
  emails, parses them with the **Claude API** (falling back to Ollama if
  `ANTHROPIC_API_KEY` isn't set), validates the totals, and records the
  trip, line-item prices, and inventory updates. Re-ingesting the same
  email is always a no-op.
- **CSA newsletter (automatic)** — a weekly Central Texas Farmers Co-op
  newsletter is parsed deterministically and the subscriber's produce is
  added, rolled to the Wednesday pickup date.
- **Photo receipt** — share a receipt photo with Claude (Desktop, web, or
  iOS Share Sheet); Claude normalizes the cryptic receipt strings and adds
  the items — with prices — via the MCP tools.
- **Manual** — add items via the MCP tools or the `/api/inventory/add`
  endpoint.

Two markdown views are generated in the Obsidian vault and are **read-only**
(regenerated from the database on every change — don't hand-edit them):

- `Inventory.md` — current pantry stock, with expiry status
- `Price Tracker.md` — spending for the last 4 weeks, by-category totals,
  average trip cost, and per-item price trends with history

Setup (Gmail credentials, sender-domain config, the receipt-ingest
LaunchAgent) is covered in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Meal Planning, Shopping Lists & Nutrition

A daily LaunchAgent generates weekly meal-plan templates two weeks ahead;
recipes and composite meals (`[[Meal: Name]]`) are scheduled into them, with
a servings multiplier (`[[Recipe Name]] x2`) supported directly in the
plan. From a plan, KitchenOS can:

- Generate a **pantry-aware shopping list** that splits each line into what
  you already have vs. what to buy
- Extract **cross-recipe prep tasks** (prep/active/passive, with do-ahead
  flags) so today's cooking tasks and "get ahead" prep surface together
- Build a **nutrition dashboard** against your macro targets, using a
  gram-based nutrition engine backed by USDA FoodData Central

Full commands live in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Native App (iOS / macOS)

`KitchenOSSiri` (the app) and `KitchenOSKit` (a shared Swift package) build
a single, multiplatform Xcode project targeting iOS 26 and macOS 26. The
app talks to the same Flask API server as everything else — over Tailscale
when off the local network — and adds:

- **Siri / App Intents** (`AppShortcutsProvider`) for finding recipes,
  checking the meal plan, getting nutrition info, and more, hands-free
- **On-device AI** via Apple Foundation Models for an in-app chat assistant
  and recipe summarization, independent of Ollama/Claude
- **CoreSpotlight search** so recipes are findable system-wide by meaning,
  not just exact title

Build/sign/deploy commands and how the app connects to the API server live
in [docs/OPERATIONS.md](docs/OPERATIONS.md) and [docs/setup/](docs/setup/).

## Output Format

### Recipe Markdown

Each recipe is saved as a markdown file with YAML frontmatter for Dataview
queries:

```markdown
---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=..."
source_channel: "Binging with Babish"
date_added: 2026-01-07
prep_time: "10 min"
cook_time: "15 min"
servings: 2
difficulty: "easy"
cuisine: "Italian"
protein: null
dish_type: "Pasta dish"
dietary: []
equipment: ["Large pot", "Sauté pan"]
tags:
  - italian
  - pasta-dish
needs_review: false
---

# Pasta Aglio e Olio

> A simple Roman pasta with garlic and olive oil.

## Ingredients
- 1/2 lb dry linguine
- 1/2 head garlic, thinly sliced
...

## Instructions
1. Heavily salt a large pot of water and bring to a boil.
2. Cook pasta to al dente.
...
```

### File Naming

```
{YYYY-MM-DD}-{recipe-name-slugified}.md
```

Example: `2026-01-07-pasta-aglio-e-olio.md`

## Dataview Queries

Once you have recipes in Obsidian, use Dataview to browse them:

### All Recipes Table

```dataview
TABLE source_channel, cuisine, difficulty, date_added
FROM "Recipes"
SORT date_added DESC
```

### By Cuisine

```dataview
LIST
FROM "Recipes"
WHERE cuisine = "Italian"
```

### Needs Review

```dataview
LIST
FROM "Recipes"
WHERE needs_review = true
```

## Troubleshooting

### "Cannot connect to Ollama"

Make sure Ollama is running:
```bash
ollama serve
```

### "No transcript available"

The video may not have captions. The script will:
1. Try YouTube's auto-generated captions
2. Fall back to Whisper transcription (requires OpenAI API key)
3. Proceed with description only if both fail

### "Failed to parse JSON"

The LLM may have returned malformed JSON. Try running again — LLM outputs
can vary.

More troubleshooting, health checks, and log locations are in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Project Structure

```
KitchenOS/
├── extract_recipe.py      # Recipe extraction entry point
├── main.py                # Video/page data fetcher
├── api_server.py          # Flask API (com.kitchenos.api LaunchAgent)
├── mcp_server.py           # MCP server exposing KitchenOS to Claude Desktop
├── lib/                    # Core modules (paths, inventory DB, nutrition, tasks, ...)
├── prompts/                 # AI prompts
├── templates/                # Markdown formatters
├── ops/                    # LaunchAgent plists
├── config/                 # Receipt senders, pantry staples, etc.
├── data/                   # kitchenos.db (SQLite — single source of truth)
├── KitchenOSKit/            # Shared Swift package (native app)
├── KitchenOSSiri/           # Native iOS/macOS app target
├── docs/
│   ├── ARCHITECTURE.md      # System architecture
│   ├── OPERATIONS.md        # Command reference / runbook
│   ├── ROADMAP.md           # What's next
│   ├── API.md                # HTTP routes / MCP tools
│   └── setup/                # iOS Shortcut and related setup guides
├── .env                    # API keys (not in git)
├── .venv/                  # Python virtual environment
└── requirements.txt        # Dependencies
```

## Documentation

- **Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Operations / command reference**: [docs/OPERATIONS.md](docs/OPERATIONS.md)
- **Roadmap**: [docs/ROADMAP.md](docs/ROADMAP.md)
- **API routes & MCP tools**: [docs/API.md](docs/API.md)
- **iOS Shortcut Setup**: [docs/setup/iOS_SHORTCUT_SETUP.md](docs/setup/iOS_SHORTCUT_SETUP.md)
- **Development Guide**: `CLAUDE.md`

## License

MIT License - see LICENSE file.
