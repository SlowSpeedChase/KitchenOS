# Smart Meal Plan Design

**Date:** 2026-04-19
**Status:** Draft — awaiting user review
**Author:** Claude (brainstorming session)

## Goal

Build a goal-directed meal-planning layer on top of KitchenOS that:

1. Targets muscle gain + energy + heart health, within user-defined macros.
2. Biases toward recipes the user has rated highly.
3. Tracks calories and heart-health metrics on every planned day.
4. Runs a weekly vault review that surfaces patterns from user notes, rating changes, and what actually got cooked.
5. Supports multi-recipe menus as (a) batch-cook cascades and (b) day-level macro composition.

## Non-goals (explicit YAGNI)

- Main-plus-side pairings as a first-class concept (can be emergent via day composition)
- Themed reusable "menus" as a new object type
- Per-ingredient ratings
- Separate axes for taste vs energy vs ease (one rating field; split later only if evidence demands)
- Hard heart-health rule enforcement (deferred to Phase C; Phase A exposes the numbers only)
- Cloud dependencies beyond the existing Claude + Ollama + YouTube integrations
- Rewriting existing `generate_meal_plan.py` / shopping list / nutrition dashboard flows — all continue to work

## User decisions captured in brainstorm

| Topic | Decision |
|---|---|
| Macro targets source | Compute via Mifflin-St Jeor + muscle-gain surplus + heart-healthy split; worksheet already created in vault at `Macro Worksheet.md` |
| Feedback signal | Phase A: `rating` + free-form `## My Notes` with opt-in structured lines. Phase B: structured post-meal ratings via shortcut/UI |
| Planning modes | C (weekday auto-fill on Wed) + D (one-shot full-week builder with intent string) |
| Multi-recipe menus | B (batch-cook cascades) + D (day-as-menu scoring) |
| Heart-health scoring | Deferred — expose metrics on UI, don't auto-optimize. Activate in Phase C when user has medical guidance. |
| Review cadence | Wednesday digest (LaunchAgent). User reviews Wed–Fri. Shopping list generates Fri; week locks. Sat shop, Sun batch cook, Mon–Fri execute |
| Multi-week | System maintains ≥2 draft weeks ahead; user can trigger Mode D for any future week |
| Architecture | Approach 2 — planner engine + SQLite cache + Claude API for digest/one-shot + Ollama for per-slot scoring |

## Architecture

### Data flow

```
User adds/rates recipe (markdown edit)
        │
        ▼
Lazy cache rebuild on read (mtime check)
        │
        ▼
┌──────────────────────────────────────────────────────┐
│               planner_engine.py                        │
│                                                        │
│   meal_scorer.py  →  day_composer.py  →  output plan  │
│        │                   │                           │
│        └───────┬───────────┘                           │
│                ▼                                       │
│         batch_cascade.py                               │
│                │                                       │
│                ▼                                       │
│    cache.py (SQLite, disposable)                       │
└──────────────────────────────────────────────────────┘
        │                   │                       │
        ▼                   ▼                       ▼
  Mode C auto-fill     Mode D one-shot       Weekly digest
  (LaunchAgent Wed)    (CLI / UI button)    (LaunchAgent Wed)
```

### Source of truth

Markdown in the Obsidian vault. SQLite cache at `.kitchenos-cache.db` (project root, gitignored) is derived and disposable. Any divergence → delete cache, rebuild from vault.

## Components

### Data model extensions

**Recipe frontmatter** (new fields, all optional):

```yaml
rating: 4                # 1-5, null if unrated
last_cooked: 2026-04-15
times_cooked: 3
batch_cook: false        # true only for parent batch-cook recipes
batch_parent: null       # on child recipes, name of the batch recipe
produces:                # on batch recipes only: what the batch yields
  - "shredded carnitas meat"
  - "salsa verde"
```

**Recipe body** — existing `## My Notes` stays free-form. Opt-in structured lines parsed when present:

```markdown
## My Notes

- cooked 2026-04-15 ★★★★☆ — felt energized through evening lift
- cooked 2026-04-02 ★★★☆☆ — too salty; cut soy sauce in half next time

Free-form thoughts below...
```

Pattern: `- cooked YYYY-MM-DD ★[count] — reason`. Digest reads both structured lines and free-form prose (Claude parses the latter).

**Meal plan frontmatter** (new):

```yaml
status: draft            # draft | locked | archived
locked_at: null          # ISO timestamp, set when shopping list generates
intent: null             # optional free-text tag: "heavy lifting", "travel Tue-Thu"
```

**My Macros.md** extended with two new sections:

```markdown
## Training Days

- Monday: lifting
- Tuesday: cardio
- Wednesday: lifting
- Thursday: rest
- Friday: lifting
- Saturday: rest
- Sunday: rest

## Heart Health

<!-- Free-form until user has medical guidance. Phase C will parse structured rules here. -->
```

### SQLite cache schema

```sql
CREATE TABLE recipes (
  name TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  rating INTEGER,
  cuisine TEXT,
  protein TEXT,
  dish_type TEXT,
  difficulty TEXT,
  meal_occasion TEXT,        -- JSON array
  dietary TEXT,              -- JSON array
  calories INTEGER,
  protein_g INTEGER,
  carbs_g INTEGER,
  fat_g INTEGER,
  sat_fat_g REAL,
  sodium_mg INTEGER,
  fiber_g REAL,
  sugar_g REAL,
  times_cooked INTEGER DEFAULT 0,
  last_cooked DATE,
  batch_cook INTEGER DEFAULT 0,
  batch_parent TEXT,
  produces TEXT,             -- JSON array
  seasonal_ingredients TEXT, -- JSON array
  peak_months TEXT,          -- JSON array
  updated_at DATETIME
);

CREATE INDEX idx_recipes_rating ON recipes(rating);
CREATE INDEX idx_recipes_last_cooked ON recipes(last_cooked);
CREATE INDEX idx_recipes_batch_cook ON recipes(batch_cook);

CREATE TABLE recipe_notes (
  id INTEGER PRIMARY KEY,
  recipe_name TEXT NOT NULL REFERENCES recipes(name),
  added_date DATE NOT NULL,
  note TEXT NOT NULL,
  source TEXT NOT NULL,     -- 'user' | 'digest' | 'auto'
  UNIQUE(recipe_name, added_date, note)
);

CREATE TABLE meal_plan_entries (
  id INTEGER PRIMARY KEY,
  week TEXT NOT NULL,
  date DATE NOT NULL,
  meal_slot TEXT NOT NULL,
  recipe_name TEXT REFERENCES recipes(name),
  servings INTEGER DEFAULT 1,
  status TEXT,
  UNIQUE(week, date, meal_slot)
);

CREATE INDEX idx_mpe_week ON meal_plan_entries(week);
CREATE INDEX idx_mpe_recipe ON meal_plan_entries(recipe_name);

CREATE TABLE digests (
  week TEXT PRIMARY KEY,
  generated_at DATETIME,
  summary_path TEXT,
  patterns_json TEXT
);
```

Cache refresh: **lazy, on read.** Every entry-point script calls `cache.sync()` which stat()s vault files and re-indexes only changed ones. No background watcher.

### Scoring function (`lib/meal_scorer.py`)

Pure function: `score_candidate(recipe, slot_context, plan_state, targets, preferences) -> ScoreBreakdown`.

Returns a dict (for UI transparency) with weighted components:

| Component | Range | Notes |
|---|---|---|
| macro_fit | 0 to 40 | Sigmoid around hitting the day's running macro totals toward target |
| rating | -10 to +15 | 5★ = +15, 4★ = +8, 3★ = 0, 2★ = -5, 1★ = -10, unrated = 0 |
| rotation | -20 to 0 | -20 if cooked in last 7 days, linearly recovering to 0 at 14+ days |
| seasonality | 0 to 5 | +5 if current month in `peak_months` |
| training_day_bonus | 0 to 10 | +10 if lifting day and recipe is high-protein (≥30g) or high-carb (≥50g) |
| batch_coherence | 0 to 30 | +30 for a child recipe if its `batch_parent` is scheduled earlier this week with servings remaining |
| heart_health | 0 in Phase A | Reserved for Phase C penalties up to -30 |

**Hard filters** (applied before scoring):
- Recipe's `meal_occasion` must include the target slot (e.g., "breakfast", "weeknight-dinner")
- Recipe's `dietary` must not conflict with user `dietary` exclusions from `My Macros.md`
- Recipe must not already appear elsewhere in the same week (unless explicitly batch child)

Weights live in `config/scoring_weights.json` — tunable without code changes.

### Day composer (`lib/day_composer.py`)

For a given date D and user targets:

1. Generate top-K candidates per slot (K=5) via scorer.
2. Enumerate 5⁴ = 625 combinations.
3. Score each combination as `sum(individual_scores) + day_fit_bonus`.
4. `day_fit_bonus`: up to +20 based on how close the combined day hits daily macro targets.
5. Return the highest-scoring combination, plus the top-3 alternatives.

Training-day logic is embedded in `day_fit_bonus`:
- Lifting day: reward ≥1g protein per lb bodyweight for the day, skew carbs higher.
- Rest day: reward balanced macros with slightly reduced calories.

Tolerance: if no combination lands within ±15% of daily targets, surface the top 3 with explicit macro gaps and require user pick (no auto-fill).

### Batch cascade (`lib/batch_cascade.py`)

- When a batch recipe is placed, look up its `batch_children`.
- For each child, score it for remaining slots in the week with the batch_coherence bonus active.
- Auto-suggest placing the top-scoring N children (N = `batch_servings / batch_child_servings`).
- In UI: modal on batch drop asks "also schedule children?" with checkboxes.

Shopping list integration (`lib/shopping_list_generator.py`):
- When child recipe is in the plan AND its `batch_parent` is also in the plan: child's ingredients that match any item in parent's `produces` field are suppressed (using existing `normalizer.py` for fuzzy match).
- Parent's full ingredient list is shopped for once.

### Planning modes

**Mode C — weekday auto-fill** (`planner_engine.plan_weekday_fills(week)`)

Triggered by `com.kitchenos.weekly-digest.plist` on Wednesday 6am.

For the nearest `status: draft` week:
- Mon–Fri: fill empty slots via day composer.
- Sat, Sun: left empty (user's execution days).
- Existing filled slots are respected.
- Writes markdown; status stays `draft`.

**Mode D — one-shot week builder** (`planner_engine.build_full_week(week, intent)`)

Triggered by CLI (`plan_week.py --week 2026-W20 --intent "heavy lifting"`) or API endpoint `POST /api/plan-next-week`.

Single Claude API call with bounded context:
- Macro targets + heart-health notes + training days + dietary restrictions
- Last 4 weeks of meal plans (for rotation awareness)
- Top-rated 30 recipes + any rated in last 14 days
- All batch-cook recipes in the vault
- Open batch cascades (batch placed, children unscheduled)
- The user's `intent` string

Claude returns structured JSON (validated against a schema) → written to meal plan file, overwriting empty slots and optionally existing slots (user opts in to overwrite).

### Weekly digest (`weekly_digest.py` + `lib/weekly_digest.py`)

LaunchAgent `com.kitchenos.weekly-digest.plist` runs Wed 6am.

Steps:
1. Target week = just-ended week (last Mon–Sun).
2. Query cache:
   - Meals planned vs. inferred-cooked (Phase A: assume planned = cooked; Phase B: use cook log)
   - Notes added in last 7 days
   - Ratings changed in last 7 days
   - Macros adherence per day
3. Build Claude API prompt with above + targets.
4. Claude returns markdown with 5 sections.
5. Write to `Vault Review/YYYY-W##.md`.
6. After the digest, run Mode C for the next unlocked week.
7. Log result to `digests` table.

Digest markdown structure:

```markdown
# Vault Review — Week YY-W##

## Last week at a glance
Adherence table (calories/protein/carbs/fat per day, target vs. actual).

## What worked
Notes + 4-5★ ratings. Patterns across cuisines, prep time, ingredients.

## What didn't
Skipped meals, low ratings, notes mentioning friction.

## Patterns spotted
Claude-generated observations across 4+ weeks of data (min 8 weeks for "patterns" section, else skipped).

## Proposed next week
A pre-filled plan for the next unlocked week (same format as Mode D output) with short rationale per slot. Shown as diff if slots were already filled.

## Suggested swaps
Slots in the upcoming plan where a higher-rated alternative exists.
```

### Week state machine

States: `draft` → `locked` → `archived`

- **draft**: default for new/unfilled weeks. Mutable.
- **locked**: set automatically when shopping list generates for that week. Edits allowed but flagged; generate a shopping list delta if edited.
- **archived**: set automatically on Monday of the following week. Read-only. Fuels digest.

State transitions live in `lib/planner_engine.py`. Read by `shopping_list.py`, meal planner UI, digest.

Multi-week: system always has ≥2 drafts ahead. When current locks, next draft becomes current and a new `status: draft` week is generated via Mode C for the week after.

### New LaunchAgents

- `com.kitchenos.weekly-digest.plist` — Wed 6am — runs `weekly_digest.py` → also triggers Mode C for the nearest unlocked week.

Existing `com.kitchenos.mealplan.plist` continues generating blank template weeks N weeks out (safety net; new engine fills them).

## File additions and changes

### New files

| Path | Purpose |
|---|---|
| `lib/planner_engine.py` | Orchestrator for Mode C and Mode D |
| `lib/meal_scorer.py` | Per-candidate scoring (pure function) |
| `lib/day_composer.py` | Day-level combination optimizer |
| `lib/batch_cascade.py` | Batch-cook placement + child suggestion |
| `lib/cache.py` | SQLite cache layer |
| `lib/weekly_digest.py` | Digest generation logic + Claude API call |
| `weekly_digest.py` | CLI entry and LaunchAgent target |
| `plan_week.py` | Mode D CLI entry |
| `prompts/weekly_digest.py` | Claude prompt template |
| `prompts/week_builder.py` | Claude prompt template for Mode D |
| `templates/vault_review_template.py` | Digest markdown skeleton |
| `config/scoring_weights.json` | Tunable weights for meal_scorer |
| `com.kitchenos.weekly-digest.plist` | Wednesday LaunchAgent |
| `migrate_schema_v2.py` | One-time migration: add new frontmatter fields to 207 recipes |

### Modified files

| Path | Change |
|---|---|
| `lib/macro_targets.py` | Parse `## Training Days` and `## Heart Health` sections |
| `lib/recipe_parser.py` | Extract opt-in `- cooked DATE ★[count] — reason` lines |
| `lib/meal_plan_parser.py` | Parse new `status`, `locked_at`, `intent` frontmatter |
| `lib/shopping_list_generator.py` | Batch-parent ingredient suppression; transition week to `locked` on generate |
| `lib/recipe_index.py` | Hydrate cache when stale |
| `api_server.py` | New endpoints: `POST /api/plan-next-week`, `GET /api/digest-preview`, `POST /api/score-candidates`, `PATCH /api/recipe-rating` |
| `templates/meal_planner.html` | Day-score panel (macros + heart-health metrics), inline rating stars on recipe cards, "Build Full Week" button |
| `templates/meal_plan_template.py` | Emit `status: draft` in frontmatter on new plans |
| `templates/my_macros_template.py` | Add `## Training Days` and `## Heart Health` sections |
| `generate_meal_plan.py` | Emit `status: draft`; remain the blank-template safety net |
| `CLAUDE.md` | Update Key Functions, Architecture, and new sections for digest/cache/scoring |

### Dependencies

- `anthropic` — already in project
- `sqlite3` — stdlib, no install

## Rollout (phased)

### Phase A — core system (first ship)

**Prerequisite:** user completes `Macro Worksheet.md`; Claude computes and writes `My Macros.md`.

1. `migrate_schema_v2.py` — add new frontmatter fields to all 207 recipes (dry-run first, then apply).
2. `lib/cache.py` — build and initial index from vault.
3. `lib/meal_scorer.py` + `lib/day_composer.py` + `lib/batch_cascade.py`.
4. `lib/planner_engine.py` with Mode C + Mode D.
5. `lib/weekly_digest.py` and LaunchAgent.
6. API endpoints + meal planner UI updates (day-score panel, rating stars, Build Week button).
7. End-to-end test on 2 real weeks.

Phase A gate: user can run Mode D for a sample week and get a plan that hits macros ±15% and explains its choices.

### Phase B — structured feedback

1. iOS Shortcut: "I cooked [recipe]" → prompts for 1–5 star + optional one-liner → appends structured line to the recipe file.
2. `recipe_cook_log` SQLite table (per-cook history).
3. Frontmatter `rating` becomes a weighted rolling average of the last 3 cooks (most recent weighted 3×, second 2×, third 1×).
4. Digest reads cook log directly for true adherence (planned vs. cooked).

Phase B gate: two full weeks of shortcut-logged cooks; digest accurately reports adherence.

### Phase C — heart-health scoring activation

Triggered by user adding structured rules to `## Heart Health` in `My Macros.md`:

```markdown
## Heart Health
sat_fat_max_g: 15
sodium_max_mg: 2000
fiber_min_g: 30
fish_min_per_week: 2
```

1. `lib/macro_targets.py` parses rules.
2. `lib/meal_scorer.py` applies penalties (up to -30 total).
3. Day composer rejects day combinations that violate hard caps.
4. Digest adds a "heart-health adherence" section.

Phase C gate: user has medical or informed guidance. Not time-bound.

## Testing strategy

- `tests/test_cache.py` — cache build, mtime-based invalidation, query correctness
- `tests/test_meal_scorer.py` — each scoring component isolated (macro_fit, rating, rotation, seasonality, training_day, batch_coherence)
- `tests/test_day_composer.py` — combination enumeration, day_fit_bonus, tolerance thresholds
- `tests/test_batch_cascade.py` — parent-child placement, shopping list ingredient suppression
- `tests/test_planner_engine.py` — Mode C and Mode D integration (Ollama/Claude mocked)
- `tests/test_weekly_digest.py` — digest generation with Claude mocked; markdown schema validated

## Open questions (low-priority, resolvable at implementation time)

1. How many weeks of meal-plan history does Mode D include in context? Default 4; tune after first real digests.
2. Top-K candidates per slot: 5 feels right but can flex to 7 if quality is poor.
3. When Claude returns a plan that fails macro tolerance, does Mode D retry with a feedback prompt or surface the gap? Default: retry once, then surface.
4. Should `Vault Review` notes themselves get ratings/notes? No — archiving only.
5. Cache version / migration story if schema changes. Simple `schema_version` table; on mismatch, delete and rebuild.

## Decisions made without explicit user input

Every design decision in Sections 3–10 was made by Claude after the user said "You decide" and "Fully execute all the phases and make your own decisions." These are flagged here for review:

1. Adding `produces: [list]` field on batch-cook parents — needed for shopping list ingredient suppression
2. Top-K = 5, combination space = 625 per day — balance between quality and compute
3. Week state machine simplified to 3 states (draft/locked/archived), not 4
4. Lock triggered automatically on shopping list generate (no manual lock button)
5. Scoring weights live in `config/scoring_weights.json` for tuning without code changes
6. Heart-health component has a placeholder weight of 0 in Phase A (matches user's "defer" decision)
7. Rolling-average rating formula in Phase B (3-2-1 weighting of last 3 cooks)
8. Digest "Patterns spotted" section suppressed until ≥8 weeks of data exist
9. Mode C doesn't touch Sat/Sun slots (matches user's execution-day constraint)
10. Phase B unlock = two full weeks of real cook-logged data before rolling-average replaces manual rating
