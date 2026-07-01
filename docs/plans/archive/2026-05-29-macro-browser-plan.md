# Recipe Macro Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `Macro Browser.md` in the Obsidian vault — a single `dataviewjs` note that lists all recipes with sortable macro columns and range filters.

**Architecture:** One vault file containing a `dataviewjs` code block. All logic (filtering, sorting, rendering) lives inside that block as plain JavaScript. No Python changes, no API changes, no unit tests — verification is manual in Obsidian.

**Tech Stack:** Obsidian Dataview plugin (`dataviewjs`), vanilla JavaScript, Obsidian CSS variables for theming.

---

## Context

- **Vault root:** `~/KitchenOS/KitchenOS_Vault/`
- **Recipes folder:** `KitchenOS_Vault/Recipes/` (Dataview path: `"Recipes"`)
- **Cooking mode subdirectory to exclude:** `Recipes/Cooking Mode/` (files end in `.recipe.md`)
- Nutrition fields in frontmatter: `nutrition_calories`, `nutrition_protein`, `nutrition_carbs`, `nutrition_fat` (integers or null)
- `meal_occasion` is a YAML list (may be empty `[]`)
- `servings` is an integer or null

---

## Task 1: Write `Macro Browser.md` to vault root

This is the only task. No Python changes, no test file.

**Files:**
- Create: `KitchenOS_Vault/Macro Browser.md`

---

### Step 1: Write the file

Create `KitchenOS_Vault/Macro Browser.md` with the content below. Copy exactly — indentation and backtick fence must be preserved.

````markdown
# Macro Browser

```dataviewjs
// ── State ──────────────────────────────────────────────────────────────
let sortCol  = null;
let sortDir  = 'desc';
let filterName = '';
const filterMin = {};
const filterMax = {};

// ── Config ─────────────────────────────────────────────────────────────
const MACROS = [
  { key: 'nutrition_calories', label: 'Calories'    },
  { key: 'nutrition_protein',  label: 'Protein (g)' },
  { key: 'nutrition_carbs',    label: 'Carbs (g)'   },
  { key: 'nutrition_fat',      label: 'Fat (g)'     },
];
const COLUMNS = [
  { key: 'name',          label: 'Name',     sortable: false },
  { key: 'meal_occasion', label: 'Meal',     sortable: false },
  { key: 'servings',      label: 'Servings', sortable: true  },
  ...MACROS.map(m => ({ key: m.key, label: m.label, sortable: true })),
];

// ── Data ───────────────────────────────────────────────────────────────
const allPages = dv.pages('"Recipes"')
  .where(p => !p.file.folder.endsWith('Cooking Mode') && p.file.ext === 'md')
  .array();

// ── Styles (injected once) ─────────────────────────────────────────────
const STYLE_ID = 'macro-browser-style';
if (!document.getElementById(STYLE_ID)) {
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `
    .macro-filter-bar { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; align-items:flex-end; }
    .macro-filter-group { display:flex; flex-direction:column; gap:4px; }
    .macro-filter-group label { font-size:11px; font-weight:600; text-transform:uppercase; opacity:0.6; }
    .macro-filter-group input[type="text"] { width:160px; padding:4px 8px; border-radius:4px; border:1px solid var(--background-modifier-border); background:var(--background-secondary); color:var(--text-normal); }
    .macro-range { display:flex; align-items:center; gap:4px; }
    .macro-range-input { width:64px; padding:4px 6px; border-radius:4px; border:1px solid var(--background-modifier-border); background:var(--background-secondary); color:var(--text-normal); }
    .macro-count { font-size:12px; opacity:0.6; margin:4px 0 8px; }
    .macro-table { width:100%; border-collapse:collapse; }
    .macro-table th { text-align:left; padding:6px 10px; border-bottom:2px solid var(--background-modifier-border); white-space:nowrap; font-size:13px; }
    .macro-table th.sortable { cursor:pointer; user-select:none; }
    .macro-table td { padding:5px 10px; border-bottom:1px solid var(--background-modifier-border); font-size:13px; }
    .macro-table tr:hover td { background:var(--background-secondary); }
  `;
  document.head.appendChild(s);
}

// ── Render ─────────────────────────────────────────────────────────────
function render() {
  dv.container.empty();

  // Filter bar
  const bar = dv.container.createEl('div', { cls: 'macro-filter-bar' });

  const nameGroup = bar.createEl('div', { cls: 'macro-filter-group' });
  nameGroup.createEl('label', { text: 'Search' });
  const nameInput = nameGroup.createEl('input', { type: 'text', placeholder: 'Recipe name…' });
  nameInput.value = filterName;
  nameInput.addEventListener('input', e => { filterName = e.target.value; render(); });

  for (const macro of MACROS) {
    const group = bar.createEl('div', { cls: 'macro-filter-group' });
    group.createEl('label', { text: macro.label });
    const rangeDiv = group.createEl('div', { cls: 'macro-range' });
    const minInput = rangeDiv.createEl('input', { type: 'number', placeholder: 'min', cls: 'macro-range-input' });
    rangeDiv.createEl('span', { text: '–' });
    const maxInput = rangeDiv.createEl('input', { type: 'number', placeholder: 'max', cls: 'macro-range-input' });
    if (filterMin[macro.key] != null) minInput.value = filterMin[macro.key];
    if (filterMax[macro.key] != null) maxInput.value = filterMax[macro.key];
    minInput.addEventListener('input', e => {
      filterMin[macro.key] = e.target.value !== '' ? Number(e.target.value) : null;
      render();
    });
    maxInput.addEventListener('input', e => {
      filterMax[macro.key] = e.target.value !== '' ? Number(e.target.value) : null;
      render();
    });
  }

  // Filter
  let rows = allPages.filter(p => {
    if (filterName && !p.file.name.toLowerCase().includes(filterName.toLowerCase())) return false;
    for (const macro of MACROS) {
      const val = p[macro.key];
      if (val == null) continue;
      if (filterMin[macro.key] != null && val < filterMin[macro.key]) return false;
      if (filterMax[macro.key] != null && val > filterMax[macro.key]) return false;
    }
    return true;
  });

  // Sort
  if (sortCol) {
    rows.sort((a, b) => {
      const av = a[sortCol] ?? (sortDir === 'desc' ? -Infinity : Infinity);
      const bv = b[sortCol] ?? (sortDir === 'desc' ? -Infinity : Infinity);
      return sortDir === 'desc' ? bv - av : av - bv;
    });
  }

  // Count
  dv.container.createEl('p', { cls: 'macro-count', text: `Showing ${rows.length} of ${allPages.length} recipes` });

  // Table
  const table = dv.container.createEl('table', { cls: 'macro-table' });
  const thead  = table.createEl('thead');
  const hrow   = thead.createEl('tr');

  for (const col of COLUMNS) {
    const th = hrow.createEl('th');
    if (col.sortable) {
      th.addClass('sortable');
      const indicator = sortCol === col.key ? (sortDir === 'desc' ? ' ▼' : ' ▲') : ' ⬍';
      th.textContent = col.label + indicator;
      th.addEventListener('click', () => {
        if (sortCol === col.key) {
          if (sortDir === 'desc') { sortDir = 'asc'; }
          else { sortCol = null; sortDir = 'desc'; }
        } else {
          sortCol = col.key;
          sortDir = 'desc';
        }
        render();
      });
    } else {
      th.textContent = col.label;
    }
  }

  const tbody = table.createEl('tbody');
  for (const p of rows) {
    const tr = tbody.createEl('tr');

    // Name — internal link
    const nameTd = tr.createEl('td');
    const link = nameTd.createEl('a', { cls: 'internal-link' });
    link.textContent = p.file.name;
    link.setAttribute('data-href', p.file.path);
    link.setAttribute('href', p.file.path);

    // Meal occasion
    const meal = p.meal_occasion;
    const mealText = Array.isArray(meal) && meal.length > 0
      ? meal.join(', ')
      : (meal && !Array.isArray(meal) ? String(meal) : '—');
    tr.createEl('td', { text: mealText });

    // Servings
    tr.createEl('td', { text: p.servings != null ? String(p.servings) : '—' });

    // Macros
    for (const macro of MACROS) {
      tr.createEl('td', { text: p[macro.key] != null ? String(p[macro.key]) : '—' });
    }
  }
}

render();
```
````

---

### Step 2: Verify in Obsidian

Open `Macro Browser.md` in Obsidian. Confirm:

- [ ] Table renders with all 7 columns (Name, Meal, Servings, Calories, Protein, Carbs, Fat)
- [ ] "Showing X of Y recipes" count appears above table
- [ ] Typing in Search box filters rows live
- [ ] Entering a min/max for Calories filters rows live (try min=500)
- [ ] Clicking "Calories ⬍" header sorts descending (shows ▼, highest calories first)
- [ ] Clicking "Calories ▼" sorts ascending (shows ▲)
- [ ] Clicking "Calories ▲" clears sort (shows ⬍)
- [ ] Recipes with null nutrition show `—` in macro cells and are not excluded by range filters

---

### Step 3: Commit

```bash
git add KitchenOS_Vault/Macro\ Browser.md
git commit -m "feat: add Macro Browser dataviewjs note — sortable, filterable recipe macro table"
```

---

## Notes

- **No Python changes.** This is purely a vault file.
- **Style persistence:** The `<style>` tag is injected into `document.head` once (guarded by `STYLE_ID`). Styles persist until Obsidian reloads the page — normal Obsidian behavior.
- **Null nutrition pass-through:** Recipes with `nutrition_calories: null` appear in results and show `—` but are never excluded by range filters, so they're always visible when no range is set.
- **Cooking Mode excluded:** `.where(p => !p.file.folder.endsWith('Cooking Mode'))` strips the simplified cooking view files from results.
