# Inventory Scan & Extend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a phone-friendly `/review` web page — inventory sorted by soonest-expiring, tap to Remove (with Undo) or add time (+3d/+7d) — reachable in one tap from the top of `Inventory.md`.

**Architecture:** One new backend primitive (`extend_expiry`) funnels through the existing `write_inventory()` path so the vault views regenerate for free. A new ungated `POST /api/inventory/extend` route exposes it, matching the sibling `remove`/`update` routes. A self-contained `templates/review.html` (served at `GET /review`, same-origin so it uses relative `fetch`) is the edit-first UI. `render_inventory_md()` gains one link at the top pointing at the live page.

**Tech Stack:** Python 3.11 (Flask), SQLite via `lib/inventory_db.py`, vanilla HTML/CSS/JS (no external deps), pytest.

## Global Constraints

- **Python 3.11** — always run via `.venv/bin/python`.
- **Single DB truth** — all mutations funnel through `lib/inventory.py::write_inventory()`; never write inventory anywhere else. `Inventory.md` is a generated, do-not-edit view.
- **API restart caveat** — after editing any `lib/*`, `api_server.py`, or `templates/*` file, reload the LaunchAgent or the server serves stale code:
  `launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist && launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist`
- **Ungated inventory routes** — `/api/inventory/add|remove|update` carry no `@require_token`; the new `extend` route matches them (no decorator).
- **Web base URL** — the Tailscale base is `os.environ.get("KITCHENOS_API_BASE", "http://chases-mac-mini.taila69703.ts.net:5001")` (same convention as `lib/web_dashboard.py:19` / `templates/recipe_template.py:16`). Never hardcode a raw IP.
- **Commit convention:**
  ```
  type: short description

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **Tests** run with `.venv/bin/python -m pytest`.

---

### Task 1: `extend_expiry()` primitive in `lib/inventory.py`

**Files:**
- Modify: `lib/inventory.py` (add function after `update_quantity`, ~line 378; ensure `timedelta` imported)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: existing `read_inventory()`, `write_inventory()`, `InventoryItem`; `from datetime import date, timedelta`.
- Produces: `extend_expiry(name: str, days: int, location: str | None = None, today: date | None = None) -> InventoryItem | None` — sets the matched item's `expires` to `(today or date.today()) + timedelta(days=days)`, persists via `write_inventory()`, returns the updated item (or `None` if no row matched). Matching mirrors `remove_item`: `name` lowercased/stripped, optional `location` lowercased/stripped.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_inventory.py`. Every test in this file takes the
`(self, tmp_vault, tmp_db)` fixture pair (see `tests/conftest.py` — they
redirect `KITCHENOS_VAULT` and `KITCHENOS_DB` to temp paths); follow that
exact convention:

```python
class TestExtendExpiry:
    def test_extends_from_today_not_old_date(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Milk", quantity=1, unit="ct",
                                 category="dairy", location="fridge",
                                 expires="2026-07-15")])
        item = extend_expiry("Milk", days=3, location="fridge",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-15"  # today(07-12) + 3 days

    def test_sets_fresh_expiry_on_no_expiry_item(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Rice", quantity=1, unit="lb",
                                 category="pantry", location="pantry",
                                 expires=None)])
        item = extend_expiry("Rice", days=7, location="pantry",
                             today=date(2026, 7, 12))
        assert item is not None
        assert item.expires == "2026-07-19"

    def test_returns_none_when_not_found(self, tmp_vault, tmp_db):
        assert extend_expiry("Nonexistent", days=3) is None

    def test_preserves_other_fields(self, tmp_vault, tmp_db):
        from datetime import date
        add_items([InventoryItem(name="Yogurt", quantity=2, unit="ct",
                                 category="dairy", location="fridge",
                                 for_recipe="Smoothie", expires="2026-07-14")])
        item = extend_expiry("Yogurt", days=5, location="fridge",
                             today=date(2026, 7, 12))
        assert item.quantity == 2
        assert item.unit == "ct"
        assert item.for_recipe == "Smoothie"
```

Add `extend_expiry` to the import block at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestExtendExpiry -v`
Expected: FAIL with `ImportError: cannot import name 'extend_expiry'`

- [ ] **Step 3: Write the implementation**

Ensure the datetime import at the top of `lib/inventory.py` includes `timedelta` (it currently imports `date`):

```python
from datetime import date, timedelta
```

Add after `update_quantity` (~line 378):

```python
def extend_expiry(
    name: str,
    days: int,
    location: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[InventoryItem]:
    """Set a matched item's expiry to today + `days`. Works on no-expiry items.

    Matches by lowercased name (+ optional location), like remove_item.
    Returns the updated item, or None if no row matched.
    """
    items = read_inventory()
    target = name.lower().strip()
    target_loc = location.lower().strip() if location else None
    base = today or date.today()
    new_expires = (base + timedelta(days=days)).isoformat()

    updated: Optional[InventoryItem] = None
    for it in items:
        if it.name.lower().strip() == target and (
            target_loc is None or it.location == target_loc
        ):
            it.expires = new_expires
            updated = it
            break

    if updated is not None:
        write_inventory(items)
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestExtendExpiry -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "feat: add extend_expiry inventory primitive

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `POST /api/inventory/extend` route

**Files:**
- Modify: `api_server.py` (add route immediately after `api_inventory_update`, ~line 2138)
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: `extend_expiry` (Task 1); `from lib.expiry import expiry_status` (signature `expiry_status(expires, today=None)`); `InventoryItem.to_dict()`.
- Produces: route `POST /api/inventory/extend`. Success → `200 {"status": "extended", "item": {<item.to_dict()>, "expiry_status": <str|None>}}`. Missing/invalid `name`/`days` → `400 {"error": ...}`. No match → `404 {"status": "not_found"}`. Ungated (no `@require_token`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_endpoints.py` (uses the existing `client` fixture at the top of the file):

```python
def test_inventory_extend_requires_name_and_days(client):
    response = client.post('/api/inventory/extend', json={})
    assert response.status_code == 400

def test_inventory_extend_not_found(client):
    response = client.post('/api/inventory/extend',
                           json={'name': 'ZzzNope', 'days': 3})
    assert response.status_code == 404
    assert response.get_json()['status'] == 'not_found'

def test_inventory_extend_success(client):
    client.post('/api/inventory/add', json={'items': [
        {'name': 'ExtendTestKale', 'quantity': 1, 'unit': 'ct',
         'category': 'produce', 'location': 'fridge'}]})
    response = client.post('/api/inventory/extend',
                           json={'name': 'ExtendTestKale', 'days': 7,
                                 'location': 'fridge'})
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'extended'
    assert body['item']['name'] == 'ExtendTestKale'
    assert body['item']['expires']  # a date string is now set
    assert 'expiry_status' in body['item']
    # cleanup
    client.post('/api/inventory/remove',
                json={'name': 'ExtendTestKale', 'location': 'fridge'})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k inventory_extend -v`
Expected: FAIL (404 route not found / 405)

- [ ] **Step 3: Write the route**

Add after `api_inventory_update` (~line 2138), matching the sibling routes' idiom:

```python
@app.route('/api/inventory/extend', methods=['POST'])
def api_inventory_extend():
    """Add time to an item's expiry. Body: {name, days, location?}.

    Sets expires = today + days (works on no-expiry items too). Ungated,
    like the sibling add/remove/update routes.
    """
    from lib.inventory import extend_expiry
    from lib.expiry import expiry_status

    data = request.get_json(force=True, silent=True)
    if not data or not data.get('name') or 'days' not in data:
        return jsonify({"error": "'name' and 'days' are required"}), 400
    try:
        days = int(data['days'])
    except (ValueError, TypeError):
        return jsonify({"error": "'days' must be an integer"}), 400

    item = extend_expiry(data['name'], days, data.get('location'))
    if item is None:
        return jsonify({"status": "not_found"}), 404
    d = item.to_dict()
    d["expiry_status"] = expiry_status(d.get("expires"))
    return jsonify({"status": "extended", "item": d})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k inventory_extend -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_api_endpoints.py
git commit -m "feat: add POST /api/inventory/extend route

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Review link at the top of `Inventory.md`

**Files:**
- Modify: `lib/inventory.py::render_inventory_md()` (~lines 218-233, the returned header block)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `os.environ` (ensure `import os` present at top of `lib/inventory.py`).
- Produces: the generated note contains a `▶ [Open Review](<base>/review)` link in the header block, above the Expiring-Soon section, where `<base>` = `os.environ.get("KITCHENOS_API_BASE", "http://chases-mac-mini.taila69703.ts.net:5001")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inventory.py`:

```python
class TestReviewLink:
    def test_inventory_md_has_review_link(self):
        from lib.inventory import render_inventory_md
        md = render_inventory_md([])
        assert "/review" in md
        assert "Open Review" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestReviewLink -v`
Expected: FAIL (`assert "/review" in md`)

- [ ] **Step 3: Add the link to the header block**

Ensure `import os` is at the top of `lib/inventory.py`. In `render_inventory_md`, insert the link line into the returned string, between the do-not-edit banner and the `_expiry_warning_section(flagged)` call:

```python
    base = os.environ.get(
        "KITCHENOS_API_BASE", "http://chases-mac-mini.taila69703.ts.net:5001"
    )
    return (
        "---\n"
        "type: inventory\n"
        f"last_updated: {today.isoformat()}\n"
        "---\n\n"
        "# Pantry Inventory\n\n"
        "> ⚠️ This file is **generated** from the KitchenOS database. "
        "Do not edit here — changes will be overwritten. "
        "Update inventory via Claude (MCP tools) or the API.\n\n"
        f"**▶ [Open Review]({base}/review)** — remove or add time, tap-to-act\n\n"
        + _expiry_warning_section(flagged)
        + "\n".join(rows)
        + "\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_inventory.py::TestReviewLink -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "feat: link Inventory.md to the /review page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `/review` page — route + `templates/review.html`

**Files:**
- Create: `templates/review.html`
- Modify: `api_server.py` (add route near the other page routes, e.g. after `system_health_dashboard` ~line 2444)
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Consumes: existing `GET /api/inventory` (returns `[{...to_dict(), expiry_status}]`), `POST /api/inventory/remove`, `POST /api/inventory/add`, `POST /api/inventory/extend` (Task 2). Page is same-origin → uses relative `fetch` (no base URL in JS).
- Produces: route `GET /review` returning the HTML page.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_endpoints.py`:

```python
def test_review_page_served(client):
    response = client.get('/review')
    assert response.status_code == 200
    assert b'Inventory Review' in response.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k review_page -v`
Expected: FAIL (404)

- [ ] **Step 3: Create `templates/review.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Inventory Review</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.4 -apple-system, system-ui, sans-serif;
         background: Canvas; color: CanvasText; padding: env(safe-area-inset-top) 0 4rem; }
  header { position: sticky; top: 0; background: Canvas; padding: 12px 16px;
           display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #8884; }
  header h1 { font-size: 1.1rem; margin: 0; flex: 1; }
  button { font: inherit; border: 1px solid #8886; border-radius: 10px;
           padding: 8px 12px; background: #8882; color: inherit; cursor: pointer; }
  button:active { background: #8884; }
  #refresh { padding: 8px 10px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { display: flex; align-items: center; gap: 10px; padding: 12px 16px;
       border-bottom: 1px solid #8883; }
  .emoji { font-size: 1.4rem; width: 1.6rem; text-align: center; }
  .meta { flex: 1; min-width: 0; }
  .name { font-weight: 600; }
  .sub { font-size: 0.8rem; opacity: 0.7; }
  .badge-expired { color: #d33; } .badge-soon { color: #e69500; }
  .actions { display: flex; gap: 6px; }
  .actions button { padding: 8px 10px; }
  .rm { color: #d33; border-color: #d3355; }
  .err { color: #d33; font-size: 0.8rem; }
  #toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
           background: #222d; color: #fff; padding: 10px 14px; border-radius: 12px;
           display: none; align-items: center; gap: 12px; z-index: 10; }
  #toast.show { display: flex; }
  #toast button { background: #fff3; color: #fff; border-color: #fff5; }
  #empty { padding: 3rem 1rem; text-align: center; opacity: 0.6; }
</style>
</head>
<body>
<header>
  <h1>Inventory Review</h1>
  <button id="refresh" aria-label="Refresh">↻</button>
</header>
<ul id="list"></ul>
<div id="empty" hidden>Nothing in inventory.</div>
<div id="toast"><span id="toast-msg"></span><button id="undo">Undo</button></div>

<script>
const EMOJI = { produce:"🥬", dairy:"🥛", meat:"🥩", seafood:"🐟", pantry:"🥫",
  frozen:"🧊", bakery:"🍞", beverages:"🧃", household:"🧽", other:"📦" };
const RANK = { expired:0, soon:1, ok:2 };
const list = document.getElementById('list');
const empty = document.getElementById('empty');
const toast = document.getElementById('toast');
let lastRemoved = null, toastTimer = null;

function rankOf(it){
  const r = RANK[it.expiry_status]; return r === undefined ? 3 : r;
}
function sortItems(items){
  return items.slice().sort((a,b)=>{
    const dr = rankOf(a) - rankOf(b); if (dr) return dr;
    const ax = a.expires || "9999", bx = b.expires || "9999";
    if (ax !== bx) return ax < bx ? -1 : 1;
    return (a.name||"").localeCompare(b.name||"");
  });
}
function badge(it){
  if (it.expiry_status === "expired") return ` <span class="badge-expired">🔴 expired</span>`;
  if (it.expiry_status === "soon") return ` <span class="badge-soon">🟡 soon</span>`;
  return "";
}
function subline(it){
  const exp = it.expires ? "exp " + it.expires : "no expiry";
  return exp + badge(it);
}
async function load(){
  list.innerHTML = "";
  let items;
  try { items = await (await fetch('/api/inventory')).json(); }
  catch(e){ empty.hidden = false; empty.textContent = "Couldn't load inventory. Tap ↻ to retry."; return; }
  empty.hidden = items.length > 0;
  for (const it of sortItems(items)) list.appendChild(row(it));
}
function row(it){
  const li = document.createElement('li');
  li.innerHTML =
    `<span class="emoji">${EMOJI[it.category] || "📦"}</span>` +
    `<span class="meta"><div class="name"></div><div class="sub">${subline(it)}</div></span>` +
    `<span class="actions">` +
    `<button class="rm">Remove</button>` +
    `<button data-d="3">+3d</button><button data-d="7">+7d</button></span>`;
  li.querySelector('.name').textContent = it.name;
  li.querySelector('.rm').onclick = () => remove(it, li);
  li.querySelectorAll('button[data-d]').forEach(b =>
    b.onclick = () => extend(it, li, parseInt(b.dataset.d, 10)));
  return li;
}
function rowError(li, msg){
  let e = li.querySelector('.err');
  if (!e){ e = document.createElement('div'); e.className = 'err';
           li.querySelector('.meta').appendChild(e); }
  e.textContent = msg;
}
async function remove(it, li){
  try {
    const r = await fetch('/api/inventory/remove', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name: it.name, location: it.location }) });
    if (!r.ok){ rowError(li, "Couldn't remove — tap ↻"); return; }
    lastRemoved = it; li.remove(); showToast(`Removed ${it.name}`);
  } catch(e){ rowError(li, "Network error — tap ↻"); }
}
async function extend(it, li, days){
  try {
    const r = await fetch('/api/inventory/extend', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name: it.name, location: it.location, days }) });
    if (!r.ok){ rowError(li, "Couldn't extend — tap ↻"); return; }
    const { item } = await r.json();
    it.expires = item.expires; it.expiry_status = item.expiry_status;
    li.querySelector('.sub').innerHTML = subline(it);
    const e = li.querySelector('.err'); if (e) e.remove();
  } catch(e){ rowError(li, "Network error — tap ↻"); }
}
function showToast(msg){
  document.getElementById('toast-msg').textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.classList.remove('show'); lastRemoved = null; }, 5000);
}
document.getElementById('undo').onclick = async () => {
  if (!lastRemoved) return;
  const it = lastRemoved; lastRemoved = null; toast.classList.remove('show');
  await fetch('/api/inventory/add', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ items: [ {
      name: it.name, quantity: it.quantity, unit: it.unit, category: it.category,
      location: it.location, purchased: it.purchased, expires: it.expires,
      for_recipe: it.for_recipe } ] }) });
  load();
};
document.getElementById('refresh').onclick = load;
load();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the route**

Add near the other page routes in `api_server.py` (e.g. after `system_health_dashboard`, ~line 2447), matching the `open('templates/<x>.html').read()` pattern:

```python
@app.route('/review')
def review_page():
    return open('templates/review.html').read()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py -k review_page -v`
Expected: PASS

- [ ] **Step 6: Full suite + reload the LaunchAgent**

Run: `.venv/bin/python -m pytest tests/test_inventory.py tests/test_api_endpoints.py -q`
Expected: all pass.

Reload so the running server picks up the new lib/route/template code:
```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
curl -s http://localhost:5001/health
```

- [ ] **Step 7: Manual verification (verify skill)**

- Open `http://chases-mac-mini.taila69703.ts.net:5001/review` on the phone (or the localhost URL on the Mac).
- Confirm: rows sorted expired → soon → ok → no-expiry; category emoji shows; `+3d`/`+7d` update the date/badge in place; `Remove` drops the row and shows a 5s Undo that restores the exact item; `↻` re-pulls.
- Regenerate a note (any inventory write) and confirm `Inventory.md` shows the `▶ Open Review` link at the top and it opens the page.

- [ ] **Step 8: Commit**

```bash
git add templates/review.html api_server.py tests/test_api_endpoints.py
git commit -m "feat: add /review inventory scan page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs update

**Files:**
- Modify: `docs/API.md` (add `/api/inventory/extend` + `/review` to the route list)

**Interfaces:** none (documentation only). Per the repo's commit convention, a new endpoint contract requires an API.md update.

- [ ] **Step 1: Add the entries**

In `docs/API.md`, alongside the other `/api/inventory/*` routes, add:
- `POST /api/inventory/extend` — body `{name, days, location?}`; sets `expires = today + days` (works on no-expiry items); ungated. Returns `{status, item}`.
- `GET /review` — self-contained inventory scan/edit page (remove + add-time), same-origin, linked from the top of `Inventory.md`.

- [ ] **Step 2: Commit**

```bash
git add docs/API.md
git commit -m "docs: document /api/inventory/extend and /review

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- extend_expiry primitive (today+N, no-expiry items) → Task 1 ✓
- `POST /api/inventory/extend`, ungated → Task 2 ✓
- `/review` page: expiry-sorted, emoji rows, Remove+Undo, +3d/+7d in-place, Refresh → Task 4 ✓
- Inventory.md link via `KITCHENOS_API_BASE` → Task 3 ✓
- Error handling (not-found → row error + refresh; API down → load error) → Task 4 html ✓
- Testing (unit for extend, route test, render-link test, manual verify) → Tasks 1,2,3,4 ✓
- API.md doc update (repo convention) → Task 5 ✓

**Placeholder scan:** none — every code/step is concrete. Test isolation uses the real `tmp_vault`/`tmp_db` fixtures from `tests/conftest.py` (verified against the file's existing convention).

**Type consistency:** `extend_expiry(name, days, location=None, today=None) -> InventoryItem | None` used identically in Task 1 (def), Task 2 (route call). Route response `{"status":"extended","item":{...,"expiry_status"}}` matches what the page's `extend()` reads (`item.expires`, `item.expiry_status`). `expiry_status(expires, today=None)` signature matches Task 2 usage.

**Note for implementer:** Tasks 1→2→3→4→5 are ordered; Task 2 depends on Task 1, Task 4 depends on Task 2. Tests use the `tmp_vault, tmp_db` fixture pair from `tests/conftest.py`.
