# KitchenOS Web Home Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a KitchenOS home page at `/` listing every browsable page, and link back to it from every page KitchenOS serves.

**Architecture:** `SECTIONS` in `lib/web_dashboard.py` is already the single registry of browsable pages, feeding the vault launcher note and the Safari bookmark sync. This adds a third consumer — an HTML renderer — plus a `HOME` constant for the registry root. The `/` route serves a static template through the existing `_serve_page_with_claude_bar` helper, substituting rendered HTML into a `<!--SECTIONS-->` placeholder. The home link itself goes into `_CLAUDE_BAR_TEMPLATE`, which that helper injects into every page, so no per-page template edits are needed.

**Tech Stack:** Python 3.11, Flask, pytest. No new dependencies.

## Global Constraints

- **Run Python via `.venv/bin/python`** — never bare `python` or `python3`.
- **Work in the worktree:** `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/web-home-page`. All paths below are relative to it.
- **`lib/web_dashboard.py` render functions stay pure** — no I/O. `write_note()` is the only function there that touches the filesystem.
- **Never hardcode a vault path.** Use `lib/paths.py` helpers.
- **API restart caveat:** `com.kitchenos.api` holds `lib/*` in memory. After editing any `lib/` or `templates/` file, reload the LaunchAgent or the server serves stale code — this appears as 500s that look like data bugs.
- **Commit convention:** `type: short description`, then a blank line, then `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Design system for new templates:** the `:root` CSS-variable block shared by `system_health.html`, `nutrition_review.html`, and `receipt_paste.html` — `--bg: #f5f5f7`, `--card-bg: #ffffff`, `--border: #e5e5e7`, `--text: #1d1d1f`, `--text-muted: #86868b`, `--accent: #0071e3`; font stack `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`; `.card` at `border-radius: 14px`. Light-only. Do **not** copy `review.html` — it is the lone `Canvas` / `color-scheme: light dark` page and is the odd one out.
- **Registry invariant (CLAUDE.md):** every browsable page route must be in `SECTIONS` or in `NOT_BOOKMARKABLE` in `tests/test_web_dashboard.py`, or the suite fails. `/` is handled specially via `HOME` — see Task 2.

## File Structure

| File | Responsibility |
|---|---|
| `lib/web_dashboard.py` | Registry (`SECTIONS`, new `HOME`) + pure renderers (`render_markdown`, new `render_html`) |
| `scripts/sync_safari_bookmarks.py` | `desired_bookmarks()` must learn about `HOME` — it iterates `SECTIONS` alone today |
| `templates/home.html` | The page shell with a `<!--SECTIONS-->` placeholder |
| `api_server.py` | `GET /` route; home link inside `_CLAUDE_BAR_TEMPLATE` |
| `tests/test_web_dashboard.py` | `HOME`, `render_html`, registry accounting, Safari bookmark list |
| `tests/test_claude_bar.py` | Every page carries the home link |
| `tests/e2e/test_weekly_loop.py` | `/` added to the browsed surfaces |

**Task order rationale:** Task 1 adds the pure renderer with no route (safe, fully unit-testable). Task 2 adds `HOME` and fixes the two registry consumers that would otherwise silently drop it. Task 3 adds the page and route. Task 4 adds the global home link. Task 5 propagates to the vault note and Safari.

---

### Task 1: `render_html()` — the registry as HTML

**Files:**
- Modify: `lib/web_dashboard.py` (add after `render_markdown`, ~line 109)
- Test: `tests/test_web_dashboard.py` (add a `TestRenderHtml` class after `TestRenderMarkdown`, ~line 59)

**Interfaces:**
- Consumes: existing `SECTIONS` (list of `(section_title, [(emoji, title, path, desc), ...])`) from `lib/web_dashboard.py`.
- Produces: `render_html(base: str = "") -> str` — returns an HTML fragment (not a full document), one `<section>` per registry section. Task 3 substitutes its return value into `templates/home.html`.

**Note on `base`:** it defaults to `""` so the served page emits **relative** links (`/review`), which keep you on whatever host you loaded the page from. `render_markdown` needs absolute tailnet URLs because the vault note is opened from Obsidian on other devices; the home page does not, and a hardcoded absolute base would send a laptop's clicks to the Mac mini's hostname unnecessarily.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_dashboard.py`:

```python
class TestRenderHtml:
    def test_renders_every_section_and_page(self):
        html = wd.render_html()
        for section_title, items in wd.SECTIONS:
            assert section_title in html
            for _emoji, title, path, _desc in items:
                assert title in html
                assert f'href="{path}"' in html

    def test_links_are_relative_by_default(self):
        html = wd.render_html()
        assert 'href="/review"' in html
        assert "ts.net" not in html

    def test_base_prefixes_links_when_given(self):
        html = wd.render_html("http://box.tailnet.ts.net:5001")
        assert 'href="http://box.tailnet.ts.net:5001/review"' in html

    def test_is_a_fragment_not_a_document(self):
        html = wd.render_html()
        assert "<!doctype" not in html.lower()
        assert "<body" not in html.lower()

    def test_escapes_text_so_prose_cannot_inject_markup(self, monkeypatch):
        monkeypatch.setattr(
            wd, "SECTIONS",
            [("S & T", [("x", "A<b>Title", "/p", 'desc "quoted" & <i>')])],
        )
        html = wd.render_html()
        assert "A&lt;b&gt;Title" in html
        assert "<b>" not in html
        assert "<i>" not in html
        assert "S &amp; T" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_dashboard.py::TestRenderHtml -v`
Expected: FAIL — `AttributeError: module 'lib.web_dashboard' has no attribute 'render_html'`

- [ ] **Step 3: Write minimal implementation**

At the top of `lib/web_dashboard.py`, add to the imports (the file currently imports only `os` and `typing.Optional`):

```python
from html import escape
```

Then add after `render_markdown()`:

```python
def render_html(base: str = "") -> str:
    """Render SECTIONS as an HTML fragment for the home page. Pure — no I/O.

    ``base`` defaults to empty so the served page emits relative links and you
    stay on whatever host you loaded it from. ``render_markdown`` needs absolute
    tailnet URLs because the vault note is opened from other devices; a page
    already being served over the tailnet does not.
    """
    base = base.rstrip("/")
    out = []
    for section_title, items in SECTIONS:
        out.append(f"<section><h2>{escape(section_title)}</h2>")
        for emoji, title, path, desc in items:
            out.append(
                f'<a class="card" href="{escape(base + path)}">'
                f'<span class="emoji">{escape(emoji)}</span>'
                f'<span class="text"><span class="title">{escape(title)}</span>'
                f'<span class="desc">{escape(desc)}</span></span></a>'
            )
        out.append("</section>")
    return "\n".join(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_dashboard.py -v`
Expected: PASS — all of `TestRenderHtml` plus the pre-existing classes still green.

- [ ] **Step 5: Commit**

```bash
git add lib/web_dashboard.py tests/test_web_dashboard.py
git commit -m "feat: render the page registry as HTML

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `HOME` and the two registry consumers that would drop it

**Files:**
- Modify: `lib/web_dashboard.py` (add `HOME` beside `SECTIONS`, ~line 30; emit it in `render_markdown`)
- Modify: `scripts/sync_safari_bookmarks.py:62-69` (`desired_bookmarks`)
- Test: `tests/test_web_dashboard.py`

**Interfaces:**
- Consumes: `render_html` from Task 1 (unchanged here).
- Produces: `HOME: tuple[str, str, str, str]` — the same `(emoji, title, path, desc)` shape as a `SECTIONS` item, with `HOME[2] == "/"`. Task 3's registry test and Task 5's propagation both rely on it.

**Why `HOME` is not just an entry in `SECTIONS`:** the home page renders `SECTIONS`, so an entry inside it would make the page list itself. But keeping it outside has a cost that must be paid explicitly — `desired_bookmarks()` iterates `SECTIONS` and nothing else, so without the change below the single most useful bookmark on the phone is the one that never syncs.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_dashboard.py`:

```python
class TestHome:
    def test_home_is_the_registry_root_not_a_section_entry(self):
        assert wd.HOME[2] == "/"
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        assert "/" not in registered, "HOME in SECTIONS would make the page list itself"

    def test_markdown_note_links_home_first(self):
        md = wd.render_markdown("http://box.tailnet.ts.net:5001")
        assert "http://box.tailnet.ts.net:5001/" in md
        assert md.index(wd.HOME[1]) < md.index("Meal Planner")


class TestSafariBookmarks:
    """desired_bookmarks() builds from SECTIONS, so HOME must be added explicitly."""

    @staticmethod
    def _wanted():
        from scripts.sync_safari_bookmarks import desired_bookmarks
        return desired_bookmarks("http://box.tailnet.ts.net:5001")

    def test_home_is_bookmarked_first(self):
        wanted = self._wanted()
        assert wanted[0] == (wd.HOME[1], "http://box.tailnet.ts.net:5001/")

    def test_every_section_page_still_bookmarked(self):
        urls = {url for _title, url in self._wanted()}
        for _s, items in wd.SECTIONS:
            for _e, _t, path, _d in items:
                assert f"http://box.tailnet.ts.net:5001{path}" in urls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_web_dashboard.py::TestHome tests/test_web_dashboard.py::TestSafariBookmarks -v`
Expected: FAIL — `AttributeError: module 'lib.web_dashboard' has no attribute 'HOME'`

- [ ] **Step 3: Write minimal implementation**

In `lib/web_dashboard.py`, add immediately above `SECTIONS` (before its explanatory comment):

```python
# The registry *root* — deliberately not a SECTIONS entry, because the home page
# renders SECTIONS and would otherwise list itself. Anything that walks SECTIONS
# to build a link list must add this explicitly (see scripts/sync_safari_bookmarks.py).
HOME = ("🏠", "KitchenOS Home", "/", "every page, one tap away")
```

In `render_markdown()`, insert the home link right after the generated-banner block — i.e. after the `"",` that closes the initial `lines = [...]` list and before the `for section_title, items in SECTIONS:` loop:

```python
    emoji, title, path, desc = HOME
    lines += [f"- {emoji} **[{title}]({base}{path})** — {desc}", ""]
```

In `scripts/sync_safari_bookmarks.py`, replace `desired_bookmarks` (lines 62-69) with:

```python
def desired_bookmarks(base: str | None = None) -> list[tuple[str, str]]:
    """[(title, url)] for the home page, then every page in the registry."""
    base = (base if base is not None else web_dashboard.base_url()).rstrip("/")
    home_title, home_path = web_dashboard.HOME[1], web_dashboard.HOME[2]
    return [(home_title, f"{base}{home_path}")] + [
        (title, f"{base}{path}")
        for _section, items in web_dashboard.SECTIONS
        for _emoji, title, path, _desc in items
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_web_dashboard.py -v`
Expected: PASS — including the pre-existing `TestRenderMarkdown::test_no_localhost_links`, which still holds because `HOME` contributes a path, not a host.

- [ ] **Step 5: Commit**

```bash
git add lib/web_dashboard.py scripts/sync_safari_bookmarks.py tests/test_web_dashboard.py
git commit -m "feat: add HOME as the registry root, and bookmark it

desired_bookmarks() built its list from SECTIONS alone, so a HOME kept
outside SECTIONS would have silently never reached Safari.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The `/` page

**Files:**
- Create: `templates/home.html`
- Modify: `api_server.py` (add the route beside the other page routes, after `receipt_paste_page` at ~line 2698)
- Test: `tests/test_web_dashboard.py` (registry accounting), `tests/test_api_endpoints.py` (route)

**Interfaces:**
- Consumes: `web_dashboard.render_html()` (Task 1), `web_dashboard.HOME` (Task 2), and the existing `_serve_page_with_claude_bar(template_filename, extra_replacements)` at `api_server.py:163`.
- Produces: `GET /` returning 200 HTML. Task 4 asserts this page also carries the home link.

**Registry invariant:** `TestPageRegistryIsComplete::test_every_browsable_route_is_registered_or_exempt` collects every GET route with no path arguments that is not under `/api/` or `/static/`. `/` will be collected and will fail the suite until accounted for. Account for it via `wd.HOME` — **not** `NOT_BOOKMARKABLE`, which would assert `/` is not bookmarkable while Task 2 bookmarks it.

- [ ] **Step 1: Write the failing test**

In `tests/test_web_dashboard.py`, update the two registry tests to treat `HOME` as registered. Replace the body of `test_every_browsable_route_is_registered_or_exempt`:

```python
    def test_every_browsable_route_is_registered_or_exempt(self):
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        registered.add(wd.HOME[2])  # the registry root, rendered by the page itself
        unaccounted = self._candidate_routes() - registered - set(NOT_BOOKMARKABLE)
        assert not unaccounted, (
            f"new page route(s) {sorted(unaccounted)} are neither in "
            "lib/web_dashboard.py SECTIONS nor in NOT_BOOKMARKABLE. Add a page to "
            "SECTIONS (then run scripts/generate_web_dashboard.py and "
            "scripts/sync_safari_bookmarks.py --apply), or list it as "
            "unbookmarkable here with a reason."
        )
```

and `test_registry_has_no_dead_routes`:

```python
    def test_registry_has_no_dead_routes(self):
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        registered.add(wd.HOME[2])
        assert not registered - self._candidate_routes(), (
            "SECTIONS lists route(s) api_server no longer serves — the launcher "
            "note and the Safari bookmarks would 404."
        )
```

Add to `tests/test_api_endpoints.py` (it already has a `client` fixture — reuse it, do not define a second):

Note the `escape()` calls: `render_html` escapes its text, and real registry titles contain characters that change under escaping — `"Plan & cook"` becomes `Plan &amp; cook`, `"This week's meal plan"` becomes `This week&#x27;s meal plan`. Asserting the raw title would fail.

```python
def test_home_page_lists_every_registered_page(client):
    from html import escape

    from lib import web_dashboard as wd

    response = client.get('/')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for _section, items in wd.SECTIONS:
        for _emoji, title, path, _desc in items:
            assert escape(title) in body
            assert f'href="{path}"' in body


def test_home_page_has_no_unsubstituted_placeholder(client):
    body = client.get('/').get_data(as_text=True)
    assert "<!--SECTIONS-->" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py::test_home_page_lists_every_registered_page tests/test_web_dashboard.py::TestPageRegistryIsComplete -v`
Expected: FAIL — the API test 404s on `/` (no route yet).

- [ ] **Step 3: Write minimal implementation**

Create `templates/home.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KitchenOS</title>
    <style>
        :root {
            --bg: #f5f5f7;
            --card-bg: #ffffff;
            --border: #e5e5e7;
            --text: #1d1d1f;
            --text-muted: #86868b;
            --accent: #0071e3;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 24px;
            max-width: 820px;
            margin: 0 auto;
        }
        header { margin-bottom: 20px; }
        h1 { font-size: 24px; font-weight: 700; }
        .sub { color: var(--text-muted); font-size: 14px; margin-top: 4px; }
        section { margin-bottom: 24px; }
        h2 {
            font-size: 13px; font-weight: 600; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: .04em; margin-bottom: 10px;
        }
        .card {
            display: flex; align-items: center; gap: 14px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 10px;
            text-decoration: none;
            color: inherit;
        }
        .card:hover { border-color: var(--accent); }
        .emoji { font-size: 26px; line-height: 1; }
        .text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
        .title { font-size: 16px; font-weight: 600; }
        .desc { font-size: 13px; color: var(--text-muted); }
    </style>
</head>
<body>
    <header>
        <h1>KitchenOS</h1>
        <div class="sub">Every page, one tap away.</div>
    </header>
    <!--SECTIONS-->
</body>
</html>
```

In `api_server.py`, add after the `receipt_paste_page` route (~line 2698), before the `if __name__ == '__main__':` block:

```python
@app.route('/', methods=['GET'])
def home_page():
    """The web home page: every browsable KitchenOS page, from the registry."""
    from lib import web_dashboard

    return _serve_page_with_claude_bar(
        'home.html', [('<!--SECTIONS-->', web_dashboard.render_html())]
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_endpoints.py tests/test_web_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/home.html api_server.py tests/test_api_endpoints.py tests/test_web_dashboard.py
git commit -m "feat: serve a home page at / listing every KitchenOS page

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Home link on every page

**Files:**
- Modify: `api_server.py:96` (`_CLAUDE_BAR_TEMPLATE`)
- Test: `tests/test_claude_bar.py:40` (extend the existing parametrized test), `tests/e2e/test_weekly_loop.py:23`

**Interfaces:**
- Consumes: `GET /` from Task 3.
- Produces: an `id="ko-home-link"` anchor to `/` present in every page served through `_serve_page_with_claude_bar`.

**Why this covers everything:** `/review`, `/system-health`, `/nutrition-review`, `/meal-planner`, `/receipt-paste`, `/recipe/<name>`, and now `/` all render through that one helper. `/current/meal-plan` and `/current/shopping-list` are `obsidian://` redirects, not HTML pages, so there is nothing to inject into.

- [ ] **Step 1: Write the failing test**

In `tests/test_claude_bar.py`, add `'/'` to the existing parametrize list and add a home-link assertion to `test_page_has_claude_bar`, then add a unit test beside `test_bar_html_has_ssh_and_endpoint`:

```python
def test_bar_html_has_home_link():
    bar = _claude_bar_html()
    assert 'id="ko-home-link"' in bar
    assert 'href="/"' in bar
```

Replace the route-level test with the following. Note the shared `PAGES` constant — both tests cover the same set, and two literal copies would drift the moment a page is added:

```python
# Every HTML page served through _serve_page_with_claude_bar.
PAGES = ['/', '/review', '/system-health', '/nutrition-review',
         '/meal-planner', '/receipt-paste']


@pytest.mark.parametrize('path', PAGES)
def test_page_has_claude_bar(client, path):
    r = client.get(path)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="ko-claude-bar"' in body
    assert 'ssh://' in body
    assert '/api/claude-notes' in body


@pytest.mark.parametrize('path', PAGES)
def test_every_page_links_home(client, path):
    body = client.get(path).get_data(as_text=True)
    assert 'id="ko-home-link"' in body
```

In `tests/e2e/test_weekly_loop.py:23`, add `"/"` to `SURFACES`:

```python
SURFACES = ["/", "/meal-planner", "/nutrition-review", "/system-health", "/review"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_claude_bar.py -v`
Expected: FAIL — `test_bar_html_has_home_link` and every `test_every_page_links_home` case fail on the missing `ko-home-link`.

- [ ] **Step 3: Write minimal implementation**

In `api_server.py`, inside `_CLAUDE_BAR_TEMPLATE`, add the home anchor immediately before the existing `ko-claude-launch` anchor, so it is the leftmost control in the bar:

```html
    <a id="ko-home-link" href="/" title="KitchenOS home" style="color:#e8e8f0;text-decoration:none;padding:7px 10px;border:1px solid #44445a;border-radius:8px;white-space:nowrap;">&#127968;</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_claude_bar.py -v`
Expected: PASS

Then the whole unit suite:

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 1386 pre-existing tests plus the new ones, 15 deselected.

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_claude_bar.py tests/e2e/test_weekly_loop.py
git commit -m "feat: link every page back to the KitchenOS home page

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Document the route

**Files:**
- Modify: `docs/API.md` (page-route table)

**Interfaces:**
- Consumes: the `/` route from Task 3.
- Produces: nothing other tasks depend on.

**Why this task no longer does the propagation.** It originally also restarted the API LaunchAgent and verified `/` over curl. That cannot work from this branch: `com.kitchenos.api.plist` runs `/Users/chaseeasterling/Dev/KitchenOS/api_server.py` with `WorkingDirectory` set to the **main** repo, not this worktree. Restarting it reloads main's code, which has no `/` route — verified during execution, `GET /` returns 404 against the live service while `/health` returns 200. Deployment therefore moves to the post-merge section below, where it actually applies.

- [ ] **Step 1: Document the route**

In `docs/API.md`, the HTML page routes sit together in the main routes table at lines 82-86 (`/system-health`, `/nutrition-review`, `/review`, `/receipt-paste`), whose columns are `| Route | Method | Purpose |`. Add this row directly after the `/receipt-paste` row:

```markdown
| `/` | GET | The web home page — every browsable KitchenOS page as tappable cards, rendered from the `SECTIONS` registry in `lib/web_dashboard.py`. Every page's Claude bar links back here. |
```

Unrelated staleness worth noting but **not** fixing in this branch: the `/review` row still describes only "Remove (with Undo), +3d, +7d quick-extend buttons, and Refresh", predating the per-item kebab menu added in `f87fa17`. Leave it — it belongs to the bulk-inventory work.

- [ ] **Step 2: Verify the docs render and nothing else changed**

Run: `git diff --stat`
Expected: `docs/API.md` only, one line added.

- [ ] **Step 3: Commit**

```bash
git add docs/API.md
git commit -m "docs: document the / home page route

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Post-merge deployment

**These steps run against `main` after the branch merges — not on the branch.** The API LaunchAgent serves the main checkout, so the new page does not exist to the running service until then.

- [ ] Restart the API so it stops serving pre-merge code. `com.kitchenos.api` holds `lib/*` and templates in memory.

  ```bash
  cd /Users/chaseeasterling/Dev/KitchenOS
  launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
  launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
  sleep 2
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/health
  ```

  Expected: `200`.

- [ ] Verify the live page.

  ```bash
  curl -s http://localhost:5001/ | grep -c 'class="card"'
  curl -s http://localhost:5001/ | grep -c 'ko-home-link'
  curl -s http://localhost:5001/review | grep -c 'ko-home-link'
  ```

  Expected: the first prints the number of pages in `SECTIONS` (6 at time of writing), the other two print `1` each.

- [ ] Regenerate the vault note and sync Safari — the CLAUDE.md "new page → new bookmark" obligation. The Safari sync quits and relaunches Safari; that is pre-authorized per CLAUDE.md, it restores tabs, and it no-ops if Safari isn't running.

  ```bash
  .venv/bin/python scripts/generate_web_dashboard.py
  .venv/bin/python scripts/sync_safari_bookmarks.py --apply
  ```

  Expected: the generator prints the written note path and base URL; the sync reports the home bookmark added.

---

## Verification

Full suite from the worktree:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/web-home-page
.venv/bin/python -m pytest tests/ -q
```

Expected: all pass, 15 deselected.

End-to-end from a phone on the tailnet (`http://chases-mac-mini.taila69703.ts.net:5001`):

1. Open `/` — every section heading and page card from `SECTIONS` renders, and each card taps through to the right page.
2. From `/review`, `/system-health`, and `/meal-planner`, tap the 🏠 in the bar and land back on `/`.
3. Confirm the KitchenOS Safari bookmarks folder now leads with **KitchenOS Home**.
4. Open `Dashboards/KitchenOS Web.md` in Obsidian — the home link is the first entry, above the section groups.
