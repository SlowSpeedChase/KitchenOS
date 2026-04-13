---
name: recipe-debug
description: Debug a failing or suspicious recipe extraction by running the pipeline with --dry-run, classifying which stage failed (metadata / transcript / description parse / recipe-link scrape / Ollama JSON / validator / seasonal match / nutrition), and surfacing the exact source file to investigate. Use when a YouTube URL produces a bad recipe, an empty recipe, or a parse error in KitchenOS.
---

# recipe-debug

Systematic debugging for the KitchenOS extraction pipeline. Replaces the
common manual loop of running `--dry-run`, scrolling output, and guessing
which stage went wrong.

## When to use

- User reports "this video gave a bad recipe" and provides a URL
- A failure log in `failures/` needs reproduction
- User asks "why did X not get extracted?"

## Pipeline stages (from CLAUDE.md → Architecture → Pipeline Flow)

| # | Stage | Owning file | Symptoms when it fails |
|---|-------|-------------|------------------------|
| 1 | Metadata fetch | `main.py::get_video_metadata` | Missing title/channel, YouTube API errors |
| 2 | Transcript | `main.py::get_transcript` | "Transcript unavailable", Whisper fallback noise |
| 3 | First comment | `main.py::get_first_comment` | Empty comments on pinned-recipe channels |
| 4 | Recipe link scrape | `recipe_sources.py::find_recipe_link` + `scrape_recipe_from_url` | JSON-LD parse error, 403 from website |
| 5 | Description parse | `recipe_sources.py::parse_recipe_from_description` | Regex miss on novel description formats |
| 6 | Creator website search | `recipe_sources.py::search_creator_website` | DuckDuckGo rate limit, wrong domain |
| 7 | Ollama extraction | `extract_recipe.py::extract_recipe_with_ollama` | Malformed JSON, Ollama timeout |
| 8 | Ingredient validator | `lib/ingredient_validator.py` | Repair leaves item empty |
| 9 | Seasonal match | `lib/seasonality.py` | Item is non-string (recent bug!) |
| 10 | Nutrition lookup | `lib/nutrition_lookup.py` | API keys missing, all three fallbacks fail |
| 11 | Image download | `lib/image_downloader.py` | Content-type mismatch, 404 |
| 12 | Template render | `templates/recipe_template.py` | Non-string tag field → `.lower()` crash |

## Workflow

### 1. Reproduce with --json first (fast, no Ollama)

```bash
.venv/bin/python main.py --json "URL" 2>&1
```

This returns metadata + transcript + description + first comment as JSON. If
this fails, the problem is stage 1-3 — no point running the full pipeline.

### 2. Run the full dry-run

```bash
.venv/bin/python extract_recipe.py --dry-run "URL" 2>&1 | tee /tmp/recipe_debug.log
```

### 3. Classify the failure

Walk the log top-to-bottom. Map any error, warning, or suspicious output to
the stage table above. If multiple stages misbehaved, prioritize the
**earliest** one — later failures are usually downstream.

Look for these specific patterns:

- `Transcript unavailable` → stage 2, check if Whisper fallback ran
- `Found recipe link:` followed by `Failed to scrape` → stage 4
- `Using description` followed by garbage ingredients → stage 5 regex miss
- `Ollama response:` followed by JSON parse error → stage 7, log the raw response
- `Ingredient validator repaired` on most ingredients → stage 7 extraction
  quality is poor, not stage 8's fault
- AttributeError on `.lower()` → stage 9 or 12, type guard missing
- `needs_review: true` in the output → check `confidence_notes`

### 4. Read the exact source

Use `Read` on the owning file to confirm the code path. **Don't** guess from
the stage table — it drifts from reality. Grep for the log message string to
find the exact line.

### 5. Report

Tell the user:

1. **Which stage failed** (e.g., "Stage 7 — Ollama returned invalid JSON")
2. **Why** (e.g., "description contained a colon inside an ingredient that
   broke the split")
3. **The file:line to fix** (e.g., `recipe_sources.py:142`)
4. **A reproducer** — the minimal input that triggers the bug
5. **Propose a fix** but do not edit yet. Let the user decide.

## Things to avoid

- Don't blindly rerun without `--dry-run` — you'll write garbage to the
  Obsidian vault.
- Don't assume Ollama is the problem just because the JSON is bad. Usually
  it's upstream data quality (empty transcript + empty description → Ollama
  has nothing to work with).
- Don't edit the recipe file in the vault to "fix" the output. Fix the
  source code.
