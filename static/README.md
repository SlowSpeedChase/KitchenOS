# `static/` — vendored front-end assets

Served by Flask's default static route at `/static/<name>` (`app = Flask(__name__)`
in `api_server.py`), so nothing needs registering here.

**These are vendored on purpose.** KitchenOS is local-first — "no cloud dependency,
works offline" — and the pages are reached over a private tailnet from phones that
may have no usable route to the public internet. A page that needs a CDN to render
is a page that fails in exactly the situation it exists for.

## Contents

| File | Version | Source | sha256 |
|------|---------|--------|--------|
| `sortable.min.js` | 1.15.6 | `https://cdn.jsdelivr.net/npm/sortablejs@1.15.6/Sortable.min.js` | `6d0a831fc19b4bae851797ad3393157e861afb7862459c11226359b27e2c4337` |
| `tokens.css` | v1.1 (`~/Dev/design-system` @ `140881e`) | `~/Dev/design-system/tokens.css` | `e81400c434b630f4a5b46bf9fdd32927790298ab740ee66d7340871d16fe2bf4` |

## `tokens.css`

The personal design language (Ink dark / Dawn light, one accent per app —
KitchenOS is 🍳 coral `#e8895f` / `#d1663b`). Copied from the `design-system`
repo rather than imported, for the same offline reason as everything else here.

It is a **copy, not a fork** — style through the variables and never edit the
values locally, or KitchenOS drifts away from the other apps. To pull an
update, re-run the copy below and refresh the row above.

```bash
cp ~/Dev/design-system/tokens.css static/tokens.css
shasum -a 256 static/tokens.css
```

## Why `sortable.min.js` is here rather than on a CDN

`templates/meal_planner.html` used the jsDelivr copy. `setupEventListeners()` calls
`Sortable.create(...)` unguarded, and it runs **before** `init()` reaches its first
`fetch` — so when the script didn't load, the page threw `ReferenceError: Sortable
is not defined` and died having rendered nothing and requested nothing. The server
log showed the tell: `GET /meal-planner 200` followed by no `/api/week-board` call
at all.

## Updating a vendored file

```bash
curl -sS -o static/sortable.min.js https://cdn.jsdelivr.net/npm/sortablejs@<version>/Sortable.min.js
shasum -a 256 static/sortable.min.js     # update the table above
.venv/bin/python -m pytest tests/test_no_external_assets.py
```

`tests/test_no_external_assets.py` fails if any template reintroduces an external
`http(s)` script or stylesheet, so this can't silently regress.
