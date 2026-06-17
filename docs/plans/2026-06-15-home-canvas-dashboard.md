# Home Canvas Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a Home canvas in the Obsidian vault with a two-week Kanban-style meal grid and a recipe discovery card.

**Architecture:** Three vault files — `Weekly Grid.md` (DataviewJS reads and parses meal plan markdown, renders Mon–Sun columns for this week and next), `Discover.md` (Dataview queries for recent/seasonal/quick recipes), and `Home.canvas` (JSON canvas embedding both notes side-by-side). No Python code changes; everything is vault-native Obsidian markdown.

**Tech Stack:** Obsidian DataviewJS (async `app.vault.read`), Dataview TABLE queries, Obsidian Canvas JSON format.

---

### Task 1: Create `Dashboards/Weekly Grid.md`

**Files:**
- Create: `~/KitchenOS/KitchenOS_Vault/Dashboards/Weekly Grid.md`

No unit tests — verify visually in Obsidian after creation.

**Step 1: Create the file with this exact content**

```markdown
```dataviewjs
// ISO week number for any date → [year, week]
function isoWeek(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const jan1 = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return [d.getUTCFullYear(), Math.ceil((((d - jan1) / 86400000) + 1) / 7)];
}

const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
const MEALS = ['Breakfast','Lunch','Dinner'];

// Parse raw meal plan markdown → { Monday: { Breakfast: "...", Lunch: "...", Dinner: "..." }, ... }
function parsePlan(content) {
    const plan = {};
    for (const day of DAYS) plan[day] = { Breakfast: '—', Lunch: '—', Dinner: '—' };

    // Split on day headings; odd indices = day name, even = body after it
    const parts = content.split(/^## (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[^\n]*/m);
    for (let i = 1; i < parts.length; i += 2) {
        const day = parts[i];
        const body = parts[i + 1] || '';
        for (const meal of MEALS) {
            const re = new RegExp(`### ${meal}\\s*([\\s\\S]*?)(?=###|##|$)`);
            const m = body.match(re);
            if (m) {
                const lines = m[1].split('\n')
                    .map(l => l.trim())
                    .filter(l => l && !l.startsWith('```') && !l.startsWith('name ') && !l.startsWith('type ') && !l.startsWith('action '));
                if (lines.length) plan[day][meal] = lines.join(', ');
            }
        }
    }
    return plan;
}

async function renderWeek(weekStr, label) {
    dv.header(3, label);
    const file = app.vault.getAbstractFileByPath(`Meal Plans/${weekStr}.md`);
    if (!file) {
        dv.paragraph(`*No plan found for ${weekStr}.*`);
        return;
    }
    const content = await app.vault.read(file);
    const plan = parsePlan(content);
    dv.table(
        ['', ...DAYS],
        MEALS.map(meal => [`**${meal}**`, ...DAYS.map(d => plan[d][meal])])
    );
}

const today = new Date();
const [yr, wk] = isoWeek(today);
const nextDate = new Date(today); nextDate.setDate(today.getDate() + 7);
const [nyr, nwk] = isoWeek(nextDate);

const thisWeek = `${yr}-W${String(wk).padStart(2,'0')}`;
const nextWeek = `${nyr}-W${String(nwk).padStart(2,'0')}`;

await renderWeek(thisWeek, `This Week — ${thisWeek}`);
await renderWeek(nextWeek, `Next Week — ${nextWeek}`);
```
```

**Step 2: Open in Obsidian and verify**

- Open `Dashboards/Weekly Grid.md` in Obsidian (reading view)
- Should show two tables, each with 8 columns (row-label + 7 days) and 3 rows (Breakfast/Lunch/Dinner)
- Days with planned meals show recipe names; empty days show `—`
- Week 25 has `[[Cherry Hibiscus Lemonade]]` on Wednesday Breakfast and `[[Watermelon Feta Salad]]` on Wednesday Lunch — confirm those appear

**Step 3: Commit**

```bash
git -C ~/KitchenOS add -f -- "KitchenOS_Vault/Dashboards/Weekly Grid.md" 2>/dev/null; echo "vault is gitignored — no commit needed for vault files"
```

Vault files are gitignored, so no git commit for this task.

---

### Task 2: Create `Dashboards/Discover.md`

**Files:**
- Create: `~/KitchenOS/KitchenOS_Vault/Dashboards/Discover.md`

**Step 1: Create the file with this exact content**

```markdown
## Recently Added

```dataview
TABLE WITHOUT ID
  link(file.name, default(title, file.stem)) AS "Recipe",
  cuisine AS "Cuisine",
  total_time AS "Time"
FROM "Recipes"
WHERE !contains(file.name, ".recipe")
SORT file.mtime DESC
LIMIT 5
```

## In Season Now

```dataviewjs
const month = new Date().getMonth() + 1;
const recipes = dv.pages('"Recipes"')
  .where(p => p.peak_months && p.peak_months.includes(month) && !p.file.name.includes(".recipe"))
  .sort(p => p.file.mtime, 'desc')
  .slice(0, 5);

if (recipes.length === 0) {
  dv.paragraph("*Nothing at peak season this month.*");
} else {
  dv.table(
    ["Recipe", "In Season"],
    recipes.map(p => [p.file.link, (p.seasonal_ingredients || []).slice(0, 3).join(", ")])
  );
}
```

## Quick Meals

```dataview
TABLE WITHOUT ID
  link(file.name, default(title, file.stem)) AS "Recipe",
  cuisine AS "Cuisine",
  total_time AS "Time"
FROM "Recipes"
WHERE total_time != null
  AND !contains(file.name, ".recipe")
  AND number(replace(string(total_time), " minutes", "")) <= 30
SORT file.mtime DESC
LIMIT 5
```
```

**Step 2: Open in Obsidian and verify**

- Open `Dashboards/Discover.md` in reading view
- **Recently Added**: should show 5 recipes, sorted newest first
- **In Season Now**: for June (month 6), any recipe with `6` in `peak_months` should appear; if empty, shows the italic message
- **Quick Meals**: recipes under 30 min should appear (check a known one like any recipe with `total_time: "20 minutes"`)

---

### Task 3: Create `Home.canvas`

**Files:**
- Create: `~/KitchenOS/KitchenOS_Vault/Home.canvas`

**Step 1: Create the canvas JSON file**

```json
{
	"nodes":[
		{
			"id":"weekly-grid-node",
			"type":"file",
			"file":"Dashboards/Weekly Grid.md",
			"x":0,
			"y":0,
			"width":920,
			"height":680
		},
		{
			"id":"discover-node",
			"type":"file",
			"file":"Dashboards/Discover.md",
			"x":960,
			"y":0,
			"width":420,
			"height":680
		}
	],
	"edges":[]
}
```

**Step 2: Open in Obsidian and verify**

- Open `Home.canvas` — both cards should appear side-by-side
- Weekly Grid on the left (wide), Discover on the right (narrower)
- Both cards should render their Dataview content (may need to click into them to trigger rendering)
- Resize cards in the canvas if needed — width/height can be adjusted by dragging in Obsidian

**Step 3: Add to Obsidian bookmarks**

In Obsidian: right-click `Home.canvas` in the file explorer → **Bookmark** (or drag to the bookmarks panel). This makes it a one-click home screen.

---

### Task 4: Update existing canvas to fix stale shopping list reference

**Files:**
- Modify: `~/KitchenOS/KitchenOS_Vault/Dashboards/KitchenOS Dashboard.canvas`

The existing canvas still points to `Shopping Lists/2026-W04.md` — stale since January. Update it to point to the current week.

**Step 1: Read the current canvas**

```bash
cat ~/KitchenOS/KitchenOS_Vault/Dashboards/KitchenOS\ Dashboard.canvas
```

**Step 2: Update the shopping list node to current week**

Find the node with `"file":"Shopping Lists/2026-W04.md"` and update to `"file":"Shopping Lists/2026-W26.md"` (or whichever is the current week's shopping list — check `ls ~/KitchenOS/KitchenOS_Vault/Shopping\ Lists/`).

Also update the meal plan node from `"file":"Meal Plans/2026-W27.md"` to the current week.

**Step 3: Verify**

Open `KitchenOS Dashboard.canvas` — shopping list and meal plan cards should show current-week content.

---

## Verification Checklist

- [ ] `Weekly Grid.md` renders two 8-column tables in Obsidian reading view
- [ ] Filled-in meal slots show recipe names (check W25, Wednesday has entries)
- [ ] Empty slots show `—` without errors
- [ ] `Discover.md` renders all three sections without Dataview errors
- [ ] `Home.canvas` opens with both cards visible and rendering
- [ ] `Home.canvas` is bookmarked for quick access
