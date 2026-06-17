# Weekly Planning Session

A practical walkthrough of a full planning week in KitchenOS — from collecting recipes to checking off the last prep task on Friday.

The pipeline has six stages. Most are automated or take under two minutes. The one that takes real time is Stage 2 (planning the week), and that's intentional — it's the part where you make decisions.

---

## Before you start: make sure the server is up

Everything runs through the API server. Confirm it's alive:

```bash
curl http://localhost:5001/health
```

If it doesn't respond, restart it:

```bash
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

The meal planner UI is at `http://localhost:5001/meal-planner` on your Mac, or `http://chases-mac-mini.taila69703.ts.net:5001/meal-planner` from your iPad over Tailscale.

---

## Stage 1 — Capture: add recipes throughout the week

You don't need to do this during planning — it's a running habit. There are three ways to add a recipe.

**From your iPhone (easiest):** Share a YouTube video to the KitchenOS shortcut. The recipe appears in your vault within a minute or two.

**Via Reminders (fire and forget):** Drop YouTube links into the `Recipies to Process` Reminders list (note the typo — that's the real list name). The batch extractor runs every hour at :10 past and processes whatever's in there. A completed reminder means the recipe was saved; an uncompleted one means it failed (check `failures/` for details).

**From the command line:**
```bash
cd /Users/chaseeasterling/KitchenOS
.venv/bin/python extract_recipe.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Preview without saving:
.venv/bin/python extract_recipe.py --dry-run "https://www.youtube.com/watch?v=VIDEO_ID"
```

Each extracted recipe gets a full markdown file in `Recipes/`, an image in `Recipes/Images/`, and three Obsidian buttons baked into the body (Reprocess, Refresh, Add to Meal Plan).

---

## Stage 2 — Plan: fill the week (Sunday evening, ~10–15 min)

This is the main session. Open the meal planner:

- **Mac:** `http://localhost:5001/meal-planner`
- **iPad:** `http://chases-mac-mini.taila69703.ts.net:5001/meal-planner`

The layout is a recipe sidebar on the left and a 7-day × 4-slot board on the right (Breakfast / Lunch / Snack / Dinner per day). The week selector at the top lets you jump between weeks; use `?week=2026-W19` in the URL to land directly on a specific week.

### Filling slots

**Option A — drag from sidebar:** Browse or search the sidebar. Filter by cuisine, protein type, dietary restriction, or seasonal produce using the chips above the search box. Drag a recipe card onto any empty slot; it saves automatically.

**Option B — use Suggest:** Click the lightning bolt on any empty slot. KitchenOS ranks your library by ingredient overlap with what's already on the plan (less grocery variety needed) plus seasonal freshness (Texas calendar), and suggests the top matches.

**Option C — from a recipe page in Obsidian:** Open any recipe and click the **Add to Meal Plan** button. A form opens in your browser with three branches:

1. **Schedule directly** — pick week / day / slot → inserted immediately.
2. **Add to existing meal** — if you have a composite meal defined (e.g. `[[Meal: Salmon Dinner]]`), you can append this recipe to it.
3. **Create new meal** — name a bundle of recipes (e.g. a "taco night" with carnitas + rice + beans), save it as a reusable meal, and optionally schedule it immediately.

### Servings and composite meals

To scale a recipe, type `x2` (or any `xN`) directly after the wikilink in the markdown:

```
[[Carnitas]] x2
```

The `xN` lives outside the `[[]]` so Obsidian links still resolve.

Composite meals reference a meal definition file:
```
[[Meal: Salmon Dinner]]
```

Downstream tools (shopping list, nutrition, prep tasks) expand these automatically via `flatten_to_recipes()`.

### When the week looks right

Save is automatic on every drag. Nothing extra needed.

---

## Stage 3 — Shop: generate the grocery list (Sunday evening, ~2 min)

From the meal planner, click **Shopping List** for the active week. (Or run it from the command line: `.venv/bin/python shopping_list.py --week 2026-W18`.)

### Pantry confirmation modal

If any ingredient overlaps with the pantry inventory (`data/kitchenos.db`), a confirmation modal appears per line:

- **Use pantry** — pulls from your pantry stock; the quantity is decremented in the inventory DB.
- **Buy fresh** — adds it to the shopping list regardless.

Cross-unit-family conflicts (e.g., "need 2 cups, pantry has 8 oz") surface as a warning rather than a guess — you decide.

### Send to Reminders

After confirming, click **Send to Reminders**. KitchenOS pushes all unchecked items into the macOS "Shopping" Reminders list, which syncs to your iPhone. You're done planning.

> **Note on pantry vs. inventory:** they're the same thing now — one unified store in `data/kitchenos.db`. Receipts (email ingest or Claude photo parse) increment it; confirming a shopping list decrements it. `Inventory.md` is just a generated read-only view of the DB.

---

## Stage 4 — Prep: today's tasks (each morning, ~1 min check-in)

Open the meal planner on any day within the active week. The **Today's Prep** panel appears automatically when the loaded week contains today's date.

The panel has two sections:

- **Today** — tasks for today's scheduled meals: prep steps, active steps, passive steps (e.g., "let dough rest 1 hour"). Each has an estimated time and a checkbox.
- **Get ahead** — tasks from later this week that can be done today (`can_do_ahead = true`): marinating, par-cooking, making a sauce.

Check off tasks as you go. The done state is tied to a stable task ID, so it survives if you edit the meal plan later.

To force a fresh task classification (e.g., after swapping a recipe mid-week), append `?force=1` to the tasks endpoint or reload the page with that query param.

---

## Stage 5 — Cook: at the stove

**Calendar:** Every meal plan is compiled into `meal_calendar.ics` daily at 6:05 AM. Apple Calendar (or Obsidian Full Calendar plugin) can subscribe to `http://localhost:5001/calendar.ics`.

**If the AI got a recipe wrong:** Click **Reprocess** on the recipe in Obsidian. Full re-extraction from YouTube. Your `## My Notes` section is preserved.

**If the template changed but the data is fine:** Click **Refresh template** instead. Re-renders from the existing extracted data without hitting YouTube.

---

## Stage 6 — Inventory: log what you bought (after shopping, ~5 min)

Take a photo of your receipt (or forward an HEB / Whole Foods email) and share it with Claude Desktop. Claude parses the items, normalizes receipt shorthand (`GV WHL MLK 1G` → `Whole milk, 1 gal`), assigns category and storage location, and calls the `add_to_inventory` MCP tool. Items land in `Inventory.md` in your vault.

You can inspect or edit `Inventory.md` directly in Obsidian, or use MCP tools in Claude:

- `list_inventory` — filter by category or location
- `update_inventory_item` — adjust a quantity (e.g., 0.5 for half-used)
- `remove_from_inventory` — mark something as used up

---

## Stage 7 — Review: nutrition dashboard (end of week)

A nutrition dashboard for the active week is regenerated daily at 6:15 AM. Find it in `Nutrition Dashboard/<week>.md`.

It shows per-day calorie and macro totals, weighted by servings multipliers and composite meal expansion. Targets come from `My Macros.md` in your vault.

To rebuild manually:

```bash
.venv/bin/python generate_nutrition_dashboard.py --week 2026-W18

# Preview without saving:
.venv/bin/python generate_nutrition_dashboard.py --dry-run
```

---

## Quick reference: the happy path

| When | What |
|---|---|
| Throughout the week | Share YouTube videos to the KitchenOS shortcut as you watch them |
| Sunday evening | Open meal planner → drag recipes onto the week → click Shopping List → Send to Reminders |
| After shopping | Photo the receipt → share with Claude Desktop → `Inventory.md` updates |
| Each morning | Open meal planner → check Today's Prep panel → mark tasks done |
| At the stove | Open the recipe on iPad |
| End of week | Check the Nutrition Dashboard against macro targets |

---

## Troubleshooting

| Symptom | First thing to check |
|---|---|
| Recipe didn't save | `failures/` for the latest JSON; `tail -f logs/batch_extract.log` |
| iOS Shortcut hangs | `curl http://localhost:5001/health`; restart `com.kitchenos.api` |
| Meal planner won't save | Open browser DevTools — is `PUT /api/meal-plan/<week>` returning 200? |
| Shopping list missing items | Does `Meal Plans/<week>.md` have valid wikilinks? A missing `Meals/<Name>.meal.md` silently skips that meal |
| Today's Prep panel is empty | Sidecar may be stale — add `?force=1` to the URL |
| Reminders push did nothing | Check macOS Reminders permission for the API; `tail -f logs/server.log` |
| Server not responding | `launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist` |

---

## Background services (for reference)

These run automatically. You don't need to manage them unless something breaks.

| Service | Schedule | What it does |
|---|---|---|
| `com.kitchenos.api` | Always on | Flask server on port 5001 |
| `com.kitchenos.batch-extract` | Hourly at :10 | Processes URLs from "Recipies to Process" Reminders list |
| `com.kitchenos.mealplan` | 6:00 AM daily | Creates empty meal-plan template two weeks ahead |
| `com.kitchenos.calendar-sync` | 6:05 AM daily | Regenerates `meal_calendar.ics` |
| `com.kitchenos.dashboard-update` | 6:15 AM daily | Regenerates this week's nutrition dashboard |

Logs: `~/KitchenOS/logs/<service>.log`

Reload all services at once: `scripts/reload_launch_agents.sh`
