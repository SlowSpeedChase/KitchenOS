# "Tell it" bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A floating mic button on every KitchenOS web page that sends a sentence plus
the page's screen context to `POST /api/command` and renders done / ask / confirm /
failed, with Undo.

**Architecture:** One shared client (`static/command-bar.js` + `.css`) injected by
`_serve_page`, the same way the stale-code banner is. Pages state their screen through a
`window.kitchenosContext()` hook. The server gains a typed-destination → path mapper
(`lib/command/destinations.py`), an `href` field on command responses, and a
fire-and-forget `POST /api/command/warm`.

**Tech Stack:** Python 3.11 / Flask (`api_server.py`), vanilla JS (no build step, no
framework — matches `static/*.js`), pytest + Playwright (`tests/e2e`).

**Spec:** [`docs/superpowers/specs/2026-11-13-tell-it-bar-design.md`](../specs/2026-11-13-tell-it-bar-design.md)

## Global Constraints

- Work in the worktree `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/tell-it-bar`,
  branch `feature/tell-it-bar`. Run Python as `.venv/bin/python` from the **main**
  checkout's venv: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python`.
- Unit tests: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest <path> -q`.
  E2E: add `-m e2e`. E2E data comes from the main checkout automatically (`tests/e2e/_paths.py`).
- Every control ≥ **44px**. Button is **56px**, round, bottom-right.
- The client **never builds a URL**; it follows only `href` from the server, and only if
  it starts with `/` and not `//`.
- The client **never sends a URL or path** in `context`. Allowed keys only:
  `screen, recipe, week, date, cook_id` (`lib/command/context.py` rejects others).
- No new phrasing rules or gold cases. `tests/gold/commands.json` is not touched.
- **No page render may block on an LLM.** Warm-up runs on a background thread and the
  route returns `202` immediately.
- Text shown to the user uses the server's `lines` / `reason` / `question` verbatim;
  never render a week id.
- Insert server text with `textContent`, never `innerHTML`.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|------|----------------|
| `lib/command/destinations.py` (new) | `href_for(navigate) -> str \| None` — the only typed-destination → path map |
| `api_server.py` (modify) | `href` on command payloads; `POST /api/command/warm`; bar injection in `_serve_page`; shopping-note context |
| `lib/command/decider.py` (modify) | `warm()` — load the Ollama decider model, never raises |
| `static/command-bar.js` (new) | Button, sheet, request loop, the four statuses, Undo, `kitchenos:changed` |
| `static/command-bar.css` (new) | Styles using `kitchenos.css` tokens |
| `templates/recipe_detail.html`, `meal_planner.html`, `home.html`, `cook_now.html`, `note_view.html` (modify) | `window.kitchenosContext` hooks; planner's in-place refresh listener |
| `tests/test_command_destinations.py` (new) | `href_for` |
| `tests/test_command_api.py` (modify) | `href` field, warm route |
| `tests/test_page_chrome.py` (modify) | injection + skip rules + context-hook registry |
| `tests/e2e/test_command_bar.py` (new) | browser flows |
| `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/plans/INDEX.md`, `CLAUDE.md` (modify) | docs |

---

### Task 1: `destinations.href_for`

**Files:**
- Create: `lib/command/destinations.py`
- Test: `tests/test_command_destinations.py`

**Interfaces:**
- Consumes: the `navigate` dict produced by `lib/command/executor._open_page`, which is
  one of `{"page": "recipe", "recipe": <name>}`, `{"page": "day", "date": "YYYY-MM-DD",
  "week": "YYYY-Www"}`, `{"page": "planner"}`, `{"page": "inventory"}`, `{"page": "home"}`.
- Produces: `href_for(navigate: dict | None) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
"""A typed destination becomes a same-origin path here, and nowhere else."""
import pytest

from lib import paths
from lib.command.destinations import href_for


@pytest.fixture
def recipes(tmp_path, monkeypatch):
    (tmp_path / "Chicken Caldo A.md").write_text("---\n---\n")
    (tmp_path / "Mac & Cheese.md").write_text("---\n---\n")
    monkeypatch.setattr(paths, "recipes_dir", lambda: tmp_path)
    return tmp_path


def test_recipe_is_quoted(recipes):
    assert href_for({"page": "recipe", "recipe": "Chicken Caldo A"}) == "/recipe/Chicken%20Caldo%20A"
    assert href_for({"page": "recipe", "recipe": "Mac & Cheese"}) == "/recipe/Mac%20%26%20Cheese"


def test_unknown_or_hostile_recipe_is_none(recipes):
    assert href_for({"page": "recipe", "recipe": "Nope"}) is None
    assert href_for({"page": "recipe", "recipe": "../secrets"}) is None
    assert href_for({"page": "recipe", "recipe": ""}) is None
    assert href_for({"page": "recipe"}) is None


def test_day_recomputes_the_week_from_the_date():
    # The passed week is ignored: the date alone decides it.
    assert href_for({"page": "day", "date": "2026-11-18", "week": "1999-W01"}) == \
        "/meal-planner?week=2026-W47&date=2026-11-18&view=calendar"


def test_bad_day_is_none():
    assert href_for({"page": "day", "date": "2026-13-40"}) is None
    assert href_for({"page": "day"}) is None


def test_fixed_pages():
    assert href_for({"page": "planner"}) == "/meal-planner"
    assert href_for({"page": "home"}) == "/"


def test_no_web_page_is_none():
    # Inventory is a native-app screen; there is no web page to go to.
    assert href_for({"page": "inventory"}) is None
    assert href_for({"page": "https://evil.example"}) is None
    assert href_for(None) is None
    assert href_for("recipe") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_command_destinations.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.command.destinations'`

- [ ] **Step 3: Implement**

```python
"""Turn a command's typed destination into a same-origin path.

The engine returns *what* to open (a recipe, a day, a page), never a URL. This
is the only place that becomes a path, so the client never builds one. Shaped
like api_server._handoff_destination, which does the same job for Siri.
"""
from datetime import date
from urllib.parse import quote

from lib import paths
from lib.safe_paths import contained_markdown

_FIXED = {"planner": "/meal-planner", "home": "/"}


def href_for(navigate) -> str | None:
    if not isinstance(navigate, dict):
        return None
    page = navigate.get("page")
    if page in _FIXED:
        return _FIXED[page]
    if page == "recipe":
        name = navigate.get("recipe")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            return None
        try:
            if not contained_markdown(paths.recipes_dir(), name + ".md").is_file():
                return None
        except ValueError:
            return None
        return "/recipe/" + quote(name, safe="")
    if page == "day":
        try:
            day = date.fromisoformat(navigate.get("date"))
        except (TypeError, ValueError):
            return None
        iso = day.isocalendar()
        return (f"/meal-planner?week={iso.year:04d}-W{iso.week:02d}"
                f"&date={day.isoformat()}&view=calendar")
    return None
```

- [ ] **Step 4: Run to verify they pass**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_command_destinations.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add lib/command/destinations.py tests/test_command_destinations.py
git commit -m "feat(command): map typed destinations to same-origin paths

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `href` on responses + `POST /api/command/warm`

**Files:**
- Modify: `api_server.py` — `_command_respond` (the `done` payload, ~line 2347) and add a
  route after `api_command_undo` (~line 2426)
- Modify: `lib/command/decider.py` — add `warm()`
- Modify: `docs/API.md` lines 175–177
- Test: `tests/test_command_api.py`

**Interfaces:**
- Consumes: `href_for` (Task 1).
- Produces: every `done` payload carries `"href": str | None`. `POST /api/command/warm`
  → `202 {"status": "warming"}` (or `{"status": "skipped"}` when the gate refuses).
  `decider.warm() -> None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_command_api.py`)

```python
def test_done_carries_href_for_navigation(client):
    body = _say(client, "open the planner", {"screen": "home"})
    assert body["status"] == "done"
    assert body["href"] == "/meal-planner"


def test_done_without_navigation_has_null_href(client):
    case = next(c for c in CASES if c["expect"]["status"] == "done"
                and all(a["type"] != "open_page" for a in c["expect"].get("actions", [])))
    body = _say(client, case["say"], case["context"])
    assert body["status"] == "done"
    assert body["href"] is None


def test_warm_returns_immediately_and_skips_under_no_llm(client, monkeypatch):
    called = []
    monkeypatch.setattr("lib.command.decider.warm", lambda: called.append(1))
    resp = client.post("/api/command/warm")
    assert resp.status_code == 202
    assert resp.get_json() == {"status": "skipped"}
    assert called == []


def test_warm_starts_a_background_load(client, monkeypatch):
    monkeypatch.delenv("KITCHENOS_NO_LLM")
    started = []
    monkeypatch.setattr(api_server, "_start_background",
                        lambda fn: started.append(fn))
    resp = client.post("/api/command/warm")
    assert resp.status_code == 202
    assert resp.get_json() == {"status": "warming"}
    assert len(started) == 1
```

(Gold case fields are `id`, `context`, `say`, `expect` — `expect.status` and
`expect.actions[].type` — verified 2026-11-13. Do not edit the JSON.)

- [ ] **Step 2: Run to verify they fail**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_command_api.py -q -k "href or warm"`
Expected: FAIL — `KeyError: 'href'` and 404 on `/api/command/warm`

- [ ] **Step 3: Implement `decider.warm`** (append to `lib/command/decider.py`)

```python
def warm(model: str = DEFAULT_MODEL) -> None:
    """Ask Ollama to load the decider model so the first command isn't a cold load.

    Called off-request from a background thread. Never raises: a warm-up that
    fails just means the first command pays the load, which it did anyway.
    """
    if not llm_gate.allowed():
        return
    try:
        requests.post(OLLAMA_CHAT_URL.replace("/api/chat", "/api/generate"),
                      json={"model": model, "keep_alive": "30m"}, timeout=60)
    except requests.RequestException:
        pass
```

- [ ] **Step 4: Implement `href` and the route in `api_server.py`**

In `_command_respond`, change the `done` payload (currently
`"warnings": result.warnings, "navigate": result.navigate, "actions": actions}`) to:

```python
    from lib.command.destinations import href_for
    payload = {"status": "done", "command_id": command_id,
               "undo": executor.undoable(result.undo), "lines": result.lines,
               "warnings": result.warnings, "navigate": result.navigate,
               "href": href_for(result.navigate), "actions": actions}
```

After `api_command_undo`, add:

```python
def _start_background(fn):
    """Run fn on a daemon thread. A seam so tests can observe it without threads."""
    threading.Thread(target=fn, daemon=True).start()


@app.route('/api/command/warm', methods=['POST'])
@require_token
def api_command_warm():
    """Load the decider model when the command bar opens. Never waits, never errors."""
    from lib import llm_gate
    from lib.command import decider
    if not llm_gate.allowed():
        return jsonify({"status": "skipped"}), 202
    _start_background(decider.warm)
    return jsonify({"status": "warming"}), 202
```

Add `import threading` to the imports at the top of `api_server.py` if it is not already
there (`grep -n "^import threading" api_server.py`).

- [ ] **Step 5: Run to verify they pass, then the whole command suite**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_command_api.py tests/test_command_destinations.py -q`
Expected: all pass (existing gold cases included)

- [ ] **Step 6: Document** — in `docs/API.md`, in the `/api/command` row, change
`{status:"done", command_id, undo, lines, warnings, navigate, actions}` to
`{status:"done", command_id, undo, lines, warnings, navigate, href, actions}` and append to
that row: `` `href` is the same-origin path for `navigate` (from `lib/command/destinations.href_for`), or null when there is no web page to open. `` Then add a row after `/api/command/<id>/undo`:

```markdown
| `/api/command/warm` 🔒 | POST | Load the local decider model in the background so the first command isn't a cold load. Returns `202 {status:"warming"}` immediately, or `202 {status:"skipped"}` when `KITCHENOS_NO_LLM` refuses inference. Never errors. Called by the command bar when its sheet opens. |
```

- [ ] **Step 7: Commit**

```bash
git add api_server.py lib/command/decider.py tests/test_command_api.py docs/API.md
git commit -m "feat(command): href on responses and a background warm-up route

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Inject the bar from `_serve_page`

**Files:**
- Modify: `api_server.py` — `_serve_page` (~line 433) plus a constant beside it
- Test: `tests/test_page_chrome.py`

**Interfaces:**
- Produces: `COMMAND_BAR_SKIP: frozenset[str]` and `_command_bar_html() -> str`. Every
  other page served by `_serve_page` contains
  `<script src="/static/command-bar.js" defer></script>` exactly once, plus
  `<link rel="stylesheet" href="/static/command-bar.css">`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_page_chrome.py`)

```python
from api_server import COMMAND_BAR_SKIP

BAR = '<script src="/static/command-bar.js" defer></script>'


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_page_gets_the_command_bar_except_print_and_handoff(template):
    html = _serve_page(template)
    expected = 0 if template in COMMAND_BAR_SKIP else 1
    assert html.count(BAR) == expected


def test_skip_list_names_real_templates():
    assert COMMAND_BAR_SKIP <= set(TEMPLATES)
    assert {"print_week.html", "print_cooking_packet.html", "recipe_card.html",
            "browser_open.html"} == COMMAND_BAR_SKIP


def test_read_only_browser_session_gets_no_bar(monkeypatch):
    import api_server
    monkeypatch.setattr(api_server, "_browser_view_config",
                        lambda: {"state": "active", "readOnly": True, "expires_at": None})
    with app.test_request_context("/"):
        assert BAR not in _serve_page("home.html")
```

- [ ] **Step 2: Run to verify they fail**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_page_chrome.py -q`
Expected: FAIL — `ImportError: cannot import name 'COMMAND_BAR_SKIP'`

- [ ] **Step 3: Implement** — above `_serve_page` in `api_server.py`:

```python
#: Pages that never get the command bar: printouts (nothing to tap) and the
#: Siri handoff page (it exists only to redirect). Read-only browser sessions
#: are skipped at request time in _serve_page — they cannot write anyway.
COMMAND_BAR_SKIP = frozenset({
    "print_week.html", "print_cooking_packet.html", "recipe_card.html",
    "browser_open.html",
})


def _command_bar_html() -> str:
    return ('<link rel="stylesheet" href="/static/command-bar.css">'
            '<script src="/static/command-bar.js" defer></script>')
```

Then replace the last line of `_serve_page`
(`return _inject_after_body(html, _stale_banner_html())`) with:

```python
    html = _inject_after_body(html, _stale_banner_html())
    read_only = has_request_context() and _browser_view_config()['readOnly']
    if template_filename not in COMMAND_BAR_SKIP and not read_only:
        html = html.replace('</body>', _command_bar_html() + '</body>', 1) \
            if '</body>' in html else html + _command_bar_html()
    return html
```

(The bar goes before `</body>`, not after `<body>`, so it never precedes the stale banner
or the home link in tab order.)

- [ ] **Step 4: Run to verify they pass**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_page_chrome.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_page_chrome.py
git commit -m "feat(command): inject the command bar on every served page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The client — `static/command-bar.js` and `.css`

**Files:**
- Create: `static/command-bar.js`, `static/command-bar.css`

**Interfaces:**
- Consumes: `POST /api/command`, `/api/command/<id>/answer`, `/api/command/<id>/undo`,
  `/api/command/warm` (Task 2); optional page hook `window.kitchenosContext(): object`.
- Produces: DOM ids used by the e2e tests in Task 6 — `#ko-tell-button`,
  `#ko-tell-sheet` (role `dialog`), `#ko-tell-input`, `#ko-tell-send`,
  `#ko-tell-result`, `#ko-tell-undo`, `.ko-tell-option` buttons, `#ko-tell-confirm`,
  `#ko-tell-cancel`, `#ko-tell-close`. Fires a **cancelable** `kitchenos:changed`
  `CustomEvent` on `window` with `detail` = the response. If no listener calls
  `preventDefault()`, the page reloads **when the sheet closes** — never immediately,
  because reloading at once would wipe the Done card and its Undo button.

This task has no unit test of its own (the repo has no JS test runner). It is verified by
the e2e tests in Task 6. Do Step 3's manual check before committing.

- [ ] **Step 1: Write `static/command-bar.css`**

```css
/* The "tell it" command bar. Tokens come from kitchenos.css. */
#ko-tell-button {
  position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom) + var(--ko-dock-offset, 0px));
  z-index: 2147482000; width: 56px; height: 56px; border-radius: 50%;
  border: none; background: var(--app-kitchenos); color: var(--text-on-accent);
  font-size: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.25); cursor: pointer;
}
#ko-tell-button:focus-visible { outline: 3px solid var(--text); outline-offset: 3px; }
#ko-tell-backdrop { position: fixed; inset: 0; z-index: 2147482001; background: rgba(0,0,0,.3); }
#ko-tell-sheet {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147482002;
  max-height: 70vh; overflow-y: auto; box-sizing: border-box;
  padding: 16px 16px calc(16px + env(safe-area-inset-bottom));
  background: var(--surface); color: var(--text);
  border-top: 1px solid var(--line); border-radius: 16px 16px 0 0;
  font: 16px/1.4 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
#ko-tell-sheet[hidden], #ko-tell-backdrop[hidden] { display: none; }
.ko-tell-row { display: flex; gap: 8px; align-items: center; }
#ko-tell-input {
  flex: 1; min-height: 44px; font-size: 16px; /* 16px stops iOS zooming on focus */
  padding: 0 12px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--bg); color: var(--text);
}
.ko-tell-btn {
  min-height: 44px; min-width: 44px; padding: 0 14px; border-radius: 10px;
  border: 1px solid var(--line); background: var(--bg); color: var(--text);
  font: inherit; cursor: pointer;
}
.ko-tell-btn.primary { background: var(--app-kitchenos); color: var(--text-on-accent); border-color: transparent; }
.ko-tell-btn:disabled { opacity: .5; cursor: default; }
#ko-tell-result { margin-top: 12px; }
#ko-tell-result:empty { display: none; }
#ko-tell-result ul { margin: 0 0 8px; padding-left: 1.2em; }
.ko-tell-warning { color: var(--alert); }
.ko-tell-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
```

- [ ] **Step 2: Write `static/command-bar.js`**

```js
/* The "tell it" bar: say what you want, see it done, Undo.
 *
 * A thin client of POST /api/command (docs/API.md). It sends the sentence plus
 * whatever the page says is on screen (window.kitchenosContext), and draws the
 * four responses. It decides nothing, builds no URLs, and never uses innerHTML
 * for server text.
 */
(() => {
  if (document.getElementById('ko-tell-button')) return;

  const el = (tag, attrs = {}, text) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (id, label, primary, cls) => {
    const b = el('button', {type: 'button', class: 'ko-tell-btn' + (primary ? ' primary' : '') + (cls ? ' ' + cls : '')}, label);
    if (id) b.id = id;
    return b;
  };

  const fab = el('button', {id: 'ko-tell-button', type: 'button', 'aria-label': 'Tell KitchenOS',
                            'aria-haspopup': 'dialog', 'aria-expanded': 'false'}, '🎙️');
  const backdrop = el('div', {id: 'ko-tell-backdrop', hidden: ''});
  const sheet = el('div', {id: 'ko-tell-sheet', role: 'dialog', 'aria-modal': 'true',
                           'aria-label': 'Tell KitchenOS', hidden: ''});
  const form = el('form', {class: 'ko-tell-row'});
  const input = el('input', {id: 'ko-tell-input', type: 'text', autocomplete: 'off',
                             enterkeyhint: 'send', 'aria-label': 'What do you want to do?',
                             placeholder: 'Put this on Wednesday…'});
  const send = button('ko-tell-send', 'Send', true);
  send.type = 'submit';
  const close = button('ko-tell-close', 'Close');
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✕';
  const result = el('div', {id: 'ko-tell-result', 'aria-live': 'polite'});
  form.append(input, send, close);
  sheet.append(form, result);
  document.body.append(fab, backdrop, sheet);

  let busy = false;
  // Set when a change happened on a page that can't refresh itself. The reload
  // waits for the sheet to close so the Done card and its Undo stay visible.
  let reloadOnClose = false;

  const context = () => {
    try {
      const ctx = typeof window.kitchenosContext === 'function' ? window.kitchenosContext() : null;
      return ctx && typeof ctx === 'object' ? ctx : {screen: 'other'};
    } catch (_) {
      return {screen: 'other'};
    }
  };

  const setBusy = (on) => {
    busy = on;
    sheet.querySelectorAll('button:not(#ko-tell-close)').forEach(b => { b.disabled = on; });
  };

  const show = (...nodes) => { result.replaceChildren(...nodes); };
  const lines = (items, cls) => {
    const ul = el('ul');
    for (const line of items || []) ul.append(el('li', cls ? {class: cls} : {}, line));
    return ul;
  };

  async function call(path, body) {
    let resp;
    try {
      resp = await fetch(path, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    } catch (_) {
      return {status: 'failed', reason: "Couldn't reach KitchenOS — nothing was changed."};
    }
    if (resp.status === 401) return {status: 'failed', reason: 'Session expired — reopen this page from the app.'};
    let data = null;
    try { data = await resp.json(); } catch (_) { /* fall through */ }
    if (resp.status >= 500 || !data) return {status: 'failed', reason: "Couldn't reach KitchenOS — nothing was changed."};
    if (data.error) return {status: 'failed', reason: data.error};
    return data;
  }

  function changed(data) {
    const event = new CustomEvent('kitchenos:changed', {detail: data, cancelable: true});
    reloadOnClose = window.dispatchEvent(event);  // true = nobody refreshed in place
  }

  function render(data) {
    if (data.status === 'done') {
      const nodes = [lines(data.lines)];
      if (data.warnings && data.warnings.length) nodes.push(lines(data.warnings.map(String), 'ko-tell-warning'));
      const actions = el('div', {class: 'ko-tell-actions'});
      if (data.undo) {
        const undo = button('ko-tell-undo', 'Undo');
        undo.addEventListener('click', () => run(`/api/command/${data.command_id}/undo`, null, true));
        actions.append(undo);
      }
      nodes.push(actions);
      show(...nodes);
      input.value = '';
      const href = typeof data.href === 'string' ? data.href : null;
      if (href && href.startsWith('/') && !href.startsWith('//')) location.assign(href);
      else changed(data);
      return;
    }
    if (data.status === 'undone') {
      show(el('p', {}, 'Undone.'));
      changed(data);
      return;
    }
    if (data.status === 'ask') {
      const actions = el('div', {class: 'ko-tell-actions'});
      for (const opt of data.options || []) {
        const b = button(null, opt.label, false, 'ko-tell-option');
        b.addEventListener('click', () => run(`/api/command/${data.command_id}/answer`, {option: opt.id}));
        actions.append(b);
      }
      show(el('p', {}, data.question), actions);
      if (!(data.options || []).length) input.focus();
      return;
    }
    if (data.status === 'confirm') {
      const yes = button('ko-tell-confirm', 'Do it', true);
      const no = button('ko-tell-cancel', 'Cancel');
      yes.addEventListener('click', () => run(`/api/command/${data.command_id}/answer`, {confirm: true}));
      no.addEventListener('click', async () => {
        await call(`/api/command/${data.command_id}/answer`, {confirm: false});
        close_();
      });
      const actions = el('div', {class: 'ko-tell-actions'});
      actions.append(yes, no);
      show(lines(data.lines), actions);
      return;
    }
    // failed, refused, or anything unexpected: say why, keep the sentence.
    show(el('p', {}, data.reason || 'That didn’t work — nothing was changed.'));
    input.focus();
  }

  async function run(path, body) {
    if (busy) return;
    setBusy(true);
    const data = await call(path, body);
    setBusy(false);
    render(data);
  }

  function open() {
    sheet.hidden = false;
    backdrop.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    input.focus();
    call('/api/command/warm');  // fire and forget
  }
  function close_() {
    sheet.hidden = true;
    backdrop.hidden = true;
    result.replaceChildren();
    fab.setAttribute('aria-expanded', 'false');
    if (reloadOnClose) { reloadOnClose = false; location.reload(); return; }
    fab.focus();
  }

  fab.addEventListener('click', open);
  close.addEventListener('click', close_);
  backdrop.addEventListener('click', close_);
  sheet.addEventListener('keydown', e => { if (e.key === 'Escape') close_(); });
  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    run('/api/command', {text, context: context()});
  });

  // Keep the sheet above the on-screen keyboard.
  if (window.visualViewport) {
    const fit = () => {
      const gap = window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop;
      sheet.style.bottom = Math.max(0, gap) + 'px';
    };
    window.visualViewport.addEventListener('resize', fit);
    window.visualViewport.addEventListener('scroll', fit);
  }
})();
```

Note on Undo: the undo route returns `{"status":"undone"}` on success, and a 409 with
`{"status":"refused","reason":...}` or `{"error":"Nothing to undo."}` otherwise. `call()`
returns the parsed body for 409, so a refusal renders its `reason` and "Nothing to undo."
renders through the `data.error` branch.

- [ ] **Step 3: Manual check** — start a server on a free port from the worktree and open
a page:

```bash
PORT=5099 HOST=0.0.0.0 KITCHENOS_NO_LLM=1 /Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python api_server.py
```

Open `http://<tailscale ip -4>:5099/` (in-app browser pane is fine). Check:
the button is visible, tapping it opens the sheet with the field focused, "open the
planner" navigates to `/meal-planner`, Escape closes the sheet and focus returns to the
button. Stop the server afterwards.

- [ ] **Step 4: Commit**

```bash
git add static/command-bar.js static/command-bar.css
git commit -m "feat(command): the tell-it bar client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Page context hooks + the context registry test

**Files:**
- Modify: `templates/recipe_detail.html`, `templates/meal_planner.html`,
  `templates/home.html`, `templates/cook_now.html`, `templates/note_view.html`
- Modify: `api_server.py` — `_render_note_page` (~line 3041) and its two callers
  (~lines 3075, 3092)
- Test: `tests/test_page_chrome.py`

**Interfaces:**
- Consumes: the client's `window.kitchenosContext` and `kitchenos:changed` (Task 4).
- Produces: `CONTEXT_OTHER: dict[str, str]` in `tests/test_page_chrome.py`;
  `_render_note_page(subdir, week, title, empty_html, screen="other")`.

- [ ] **Step 1: Write the failing registry test** (append to `tests/test_page_chrome.py`)

```python
#: Templates that deliberately send {screen: "other"}: the engine has no screen
#: for them, so stating none is the decision. A new template must either set
#: window.kitchenosContext or be listed here with a reason.
CONTEXT_OTHER = {
    "meal_calendar.html": "read-only agenda list; commands here act on no particular week",
    "nutrition_review.html": "fixes food matches; no command acts on it",
    "plan_week.html": "the weekly front door; planner commands run from the planner",
    "prep.html": "today's tasks; no command acts on prep steps",
    "receipt_paste.html": "a paste form",
    "recent.html": "a list of new recipes",
    "review.html": "recipe review queue",
    "system_health.html": "operator page",
    "cooking_packet.html": "a printable week view",
}


@pytest.mark.parametrize("template", sorted(set(TEMPLATES) - COMMAND_BAR_SKIP))
def test_every_bar_page_states_its_context_or_says_why_not(template):
    source = (REPO / "templates" / template).read_text()
    assert ("window.kitchenosContext" in source) != (template in CONTEXT_OTHER), (
        f"{template}: set window.kitchenosContext in the template, or add it to "
        "CONTEXT_OTHER with a reason — not both."
    )


def test_shopping_note_states_its_week(monkeypatch):
    import api_server
    with app.test_request_context("/current/shopping-list"):
        html = api_server._render_note_page("Shopping Lists", "2026-W47", "Shopping list",
                                            "<p>none</p>", screen="shopping")
    assert '{"screen": "shopping", "week": "2026-W47"}' in html
```

Before running, list the templates (`ls templates/*.html`). Any template that is neither
in `COMMAND_BAR_SKIP`, given a hook in Steps 3–7, nor in `CONTEXT_OTHER` above must be
added to `CONTEXT_OTHER` with a one-line reason.

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_page_chrome.py -q -k context`
Expected: FAIL for `recipe_detail.html`, `meal_planner.html`, `home.html`, `cook_now.html`, `note_view.html`

- [ ] **Step 3: Recipe page** — in `templates/recipe_detail.html`, directly after the
`const recipeName = decodeURIComponent(...)` statement (~line 360), add:

```js
        window.kitchenosContext = () => ({screen: 'recipe', recipe: recipeName});
```

If `recipeName` is declared inside a function rather than at script top level, put this
line in that same scope right after it, so the hook can see it.

- [ ] **Step 4: Planner** — in `templates/meal_planner.html`, directly after
`let currentWeek = '';` (~line 2217), add:

```js
        // The tell-it bar asks what's on screen at send time; the week changes without a reload.
        window.kitchenosContext = () => {
            const ctx = {screen: 'planner'};
            if (currentWeek) ctx.week = currentWeek;
            if (selectedDate) ctx.date = selectedDate;
            return ctx;
        };
        // A command changed something: refetch the board in place instead of reloading.
        window.addEventListener('kitchenos:changed', event => {
            event.preventDefault();
            loadWeekBoard(currentWeek);
        });
```

Also set a dock offset so the button sits above the planner's bottom dock: find the dock
element's CSS rule (`grep -n "dock" templates/meal_planner.html | head`) and add to the
planner's `:root` or `body` rule `--ko-dock-offset: <dock height>px;` using the dock's
actual height from that rule.

- [ ] **Step 5: Home and Cook Now** — add before `</body>` in each:

`templates/home.html`:
```html
<script>window.kitchenosContext = () => ({screen: 'home'});</script>
```

`templates/cook_now.html`:
```html
<script>window.kitchenosContext = () => ({screen: 'cook-now'});</script>
```

- [ ] **Step 6: Note view** — in `templates/note_view.html`, add before `</body>`:

```html
<script>window.kitchenosContext = () => (/*KO_CONTEXT*/{"screen": "other"});</script>
```

In `api_server.py`, change `_render_note_page` to accept and inject the screen:

```python
def _render_note_page(subdir: str, week: str, title: str, empty_html: str,
                      screen: str = "other") -> str:
```

and add to its `_serve_page('note_view.html', [...])` replacement list:

```python
        ('/*KO_CONTEXT*/{"screen": "other"}',
         json.dumps({"screen": screen, "week": week} if screen != "other"
                    else {"screen": "other"}).replace('<', '\\u003c')),
```

In the shopping-list caller (~line 3092), pass `screen="shopping"`. Leave the meal-plan
caller (~line 3075) on the default.

- [ ] **Step 7: Run the chrome tests**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/test_page_chrome.py tests/test_web_dashboard.py -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add templates api_server.py tests/test_page_chrome.py
git commit -m "feat(command): pages state their screen to the tell-it bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Browser tests

**Files:**
- Create: `tests/e2e/test_command_bar.py`

**Interfaces:**
- Consumes: `live_server`, `page`, `page_errors` fixtures (`tests/e2e/conftest.py`), the
  DOM ids from Task 4. The server runs with `KITCHENOS_NO_LLM=1` and a copy of the real
  vault and DB, so every write here is throwaway.

- [ ] **Step 1: Write the tests**

```python
"""The tell-it bar, driven in a real browser against a throwaway server.

These cover what unit tests can't: the button is on the page, the sheet draws
each status, Undo really reverses, and the planner refreshes without a reload.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import requests

pytestmark = pytest.mark.e2e


def _a_recipe(live_server) -> str:
    resp = requests.get(live_server.url("/api/recipes"), timeout=60).json()
    recipes = resp if isinstance(resp, list) else resp["recipes"]
    return recipes[0]["name"]


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _next(weekday: int) -> date:
    """Next occurrence of weekday (Mon=0) starting today — the engine's rule."""
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _cooks(live_server, recipe, day):
    board = requests.get(live_server.url(f"/api/week-board/{_iso_week(day)}"), timeout=30).json()
    return [c for c in board["cooks"] if c["recipe"] == recipe and c["date"] == day.isoformat()]


def _tell(page, text):
    page.click("#ko-tell-button")
    page.fill("#ko-tell-input", text)
    page.click("#ko-tell-send")


def test_plan_from_recipe_page_then_undo(live_server, page, page_errors):
    name = _a_recipe(live_server)
    wednesday = _next(2)
    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    _tell(page, "put this on wednesday")
    page.wait_for_selector("#ko-tell-undo")
    assert wednesday.strftime("%a") in page.inner_text("#ko-tell-result")
    assert _cooks(live_server, name, wednesday)

    # The recipe page has no in-place refresh, so the reload waits for close:
    # Undo must still be on screen and must still work.
    page.click("#ko-tell-undo")
    page.wait_for_selector("#ko-tell-result >> text=Undone.")
    assert not _cooks(live_server, name, wednesday)
    with page.expect_navigation():
        page.click("#ko-tell-close")
    assert page_errors == []


def test_undo_on_the_planner_reverses_without_reload(live_server, page, page_errors):
    name = _a_recipe(live_server)
    friday = _next(4)
    page.goto(live_server.url(f"/meal-planner?week={_iso_week(friday)}"), wait_until="networkidle")
    page.evaluate("window.__noReload = true")
    _tell(page, f"put {name} on friday")
    page.wait_for_selector("#ko-tell-undo")
    assert page.evaluate("window.__noReload") is True, "planner reloaded instead of refetching"
    assert _cooks(live_server, name, friday)

    page.click("#ko-tell-undo")
    page.wait_for_selector("#ko-tell-result >> text=Undone.")
    assert not _cooks(live_server, name, friday)
    assert page_errors == []


def test_ambiguous_recipe_asks_with_buttons(live_server, page, page_errors):
    page.goto(live_server.url("/"), wait_until="networkidle")
    _tell(page, "put chicken caldo on saturday")
    page.wait_for_selector(".ko-tell-option")
    labels = page.locator(".ko-tell-option").all_inner_texts()
    assert len(labels) >= 2
    page.locator(".ko-tell-option").first.click()
    page.wait_for_selector("#ko-tell-undo")
    page.click("#ko-tell-undo")
    page.wait_for_selector("#ko-tell-result >> text=Undone.")
    assert page_errors == []


def test_remove_asks_first_and_cancel_keeps_the_cook(live_server, page, page_errors):
    name = _a_recipe(live_server)
    sunday = _next(6)
    created = requests.post(live_server.url("/api/cooks"), timeout=30, json={
        "recipe": name, "date": sunday.isoformat(), "meal": "dinner"}).json()
    page.goto(live_server.url(f"/recipe/{name}"), wait_until="networkidle")
    _tell(page, "take this off sunday")
    page.wait_for_selector("#ko-tell-confirm")
    page.click("#ko-tell-cancel")
    assert page.is_hidden("#ko-tell-sheet")
    assert _cooks(live_server, name, sunday)
    requests.delete(live_server.url(f"/api/cooks/{created['id']}"), timeout=30)
    assert page_errors == []


def test_open_the_planner_navigates(live_server, page, page_errors):
    page.goto(live_server.url("/"), wait_until="networkidle")
    _tell(page, "open the planner")
    page.wait_for_url("**/meal-planner*")
    assert page_errors == []


def test_print_page_has_no_button(live_server, page):
    page.goto(live_server.url("/print/week"), wait_until="networkidle")
    assert page.locator("#ko-tell-button").count() == 0
```

Before running, check two things against the real code and adjust **only the tests**:
- `POST /api/cooks` body and response: `grep -n "def api_cook_create" -A30 api_server.py`
  — use its real field names and the id key it returns; and the delete route
  (`grep -n "/api/cooks/<int" api_server.py`).
- `"put chicken caldo on saturday"` must produce `ask` under `KITCHENOS_NO_LLM`. Check
  with `curl -s -X POST localhost:<port>/api/command -H 'Content-Type: application/json'
  -d '{"text":"put chicken caldo on saturday","context":{"screen":"home"}}'` against the
  Task 4 manual server. If the corpus resolves it without asking, pick another recipe
  pair from `ls "$KITCHENOS_VAULT/Recipes" | sort` that shares a prefix.

- [ ] **Step 2: Run**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest tests/e2e/test_command_bar.py -m e2e -q`
Expected: 6 passed

- [ ] **Step 3: Run the whole suite**

Run: `/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest -q` then
`/Users/chaseeasterling/Dev/KitchenOS/.venv/bin/python -m pytest -m e2e -q`
Expected: no new failures vs `main` (note any pre-existing failures in the PR body).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_command_bar.py
git commit -m "test(command): browser tests for the tell-it bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Docs and status

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/plans/INDEX.md`, `CLAUDE.md`

- [ ] **Step 1: ARCHITECTURE.md** — find the command-engine section
(`grep -n -i "command" docs/ARCHITECTURE.md | head`) and add one paragraph: the bar is
`static/command-bar.js`, injected by `_serve_page` except `COMMAND_BAR_SKIP` and read-only
sessions; pages state context via `window.kitchenosContext`; `destinations.href_for` is
the only navigate → path map; `kitchenos:changed` lets a page refresh in place.

- [ ] **Step 2: CLAUDE.md** — add one invariant bullet after the "A command runs the
wrong thing never" bullet:

```markdown
- **The command bar decides nothing and builds no URLs.** `static/command-bar.js` sends the sentence plus `window.kitchenosContext()` and draws what `/api/command` returns; it follows only the server's `href`, produced by `lib/command/destinations.href_for` — the one map from a typed destination to a path. Every page served through `_serve_page` gets the bar unless it is in `COMMAND_BAR_SKIP` or a read-only browser session, and `tests/test_page_chrome.py` fails unless each such template sets `window.kitchenosContext` or is listed in `CONTEXT_OTHER` with a reason. A page that can refresh in place listens for `kitchenos:changed` and calls `preventDefault()`; otherwise the bar reloads.
```

- [ ] **Step 3: ROADMAP.md** — in the 2026-11 command-engine "Still open" line, remove
"the in-page "tell it" bar" and add a Done entry above it:
`**2026-11 — "Tell it" bar.** A floating mic button on every web page sends the sentence plus the page's screen to /api/command, with Undo. See docs/superpowers/specs/2026-11-13-tell-it-bar-design.md.`

- [ ] **Step 4: INDEX.md** — move the tell-it bar row from **Ready** to **Done** with
today's date and the PR link (fill the link once the PR exists).

- [ ] **Step 5: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: tell-it bar architecture, invariant, roadmap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks

1. Push the branch and open a PR (ask the user first).
2. After merge, **deploy through a release rollout**, not a launchctl restart:
   `scripts/deploy_api.py --runtime-root "$HOME/Library/Application Support/KitchenOS API/rollouts/<new-name>" stage --sha <sha> ...` then `activate`, and confirm the
   `X-KitchenOS-Release` header on `/health`. See `docs/OPERATIONS.md` "Reviewed API releases".
3. On the iPad: open `/meal-planner` from the tailnet URL, tap the mic button, dictate
   "put <recipe> on friday", and confirm the board updates and Undo reverses it.
