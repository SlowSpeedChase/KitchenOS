# "Tell it" bar (Design Spec)

**Status:** Ready · **Date:** 2026-11-13 · **Branch:** `feature/tell-it-bar`
**Program:** piece 2 of [command engine and gold-standard kitchen](2026-11-12-command-engine-design.md)

## Goal

Every KitchenOS web page gets one way to say what you want — "put this on Wednesday and
freeze the rest" — and see it done, with Undo. The bar is a thin client of the shipped
`POST /api/command`: it sends the sentence plus what is on screen, and draws the four
responses. It adds **no** wording rules, no model calls, and no new write paths.

## Decisions the user made (2026-11-13)

- **A floating mic button**, not an always-visible bar or a header field. Dense pages
  (the planner board, whose bottom dock already covers rows) lose almost nothing.
- **Voice is the iPad keyboard's own dictation.** The sheet opens with the field focused;
  the keyboard mic is one tap away. No `webkitSpeechRecognition`, no audio leaves through
  code we own, and it behaves the same in Safari and later inside the app shell (piece 3).
- **One shared script injected by `_serve_page`**, not a per-template include or a web
  component.

## Architecture

| Unit | Does | Depends on |
|------|------|------------|
| `static/command-bar.js` | Button, sheet, request loop, rendering the four statuses, `kitchenos:changed` event | `/api/command*`, the page's context hook |
| `static/command-bar.css` | Sheet and button styles, using `kitchenos.css` tokens | `kitchenos.css` |
| `_serve_page` (api_server.py) | Injects the script/CSS on eligible pages | — |
| `lib/command/destinations.py` | `href_for(navigate) -> str \| None` — the only map from a typed destination to a same-origin path | `lib.safe_paths`, `paths.recipes_dir` |
| Page context hooks | `window.kitchenosContext = () => ({...})` on pages that know their screen | — |

### Injection

`_serve_page` already injects global chrome (the home link, the stale-code banner), so a
newly registered page opts in for free. It adds the bar after the stale banner **unless**:

- the template is a print page (`print_week.html`, `print_cooking_packet.html`,
  `recipe_card.html`), or
  `browser_open.html` (the Siri handoff page); or
- the request is a read-only browser-view session (`_browser_view_config()['readOnly']`) —
  those cannot write, so a bar would only ever fail.

The exclusion list is a named constant beside `_serve_page`, not inline conditions.

### Screen context

A page states what is on screen with a function, because the planner changes week and
day without reloading:

```js
window.kitchenosContext = () => ({screen: "planner", week: currentWeek, date: selectedDate});
```

The bar calls it at send time. A page with no hook sends `{screen: "other"}`. The server's
`lib/command/context.validate` remains the only authority — the client never trims or
"fixes" context, and never sends a URL or path (unknown keys are rejected server-side).

| Page | Context in v1 |
|------|---------------|
| `/recipe/<name>` | `{screen: "recipe", recipe}` |
| `/meal-planner` (board and calendar) | `{screen: "planner", week, date?}` |
| `/` home | `{screen: "home"}` |
| `/cook-now` | `{screen: "cook-now"}` |
| `/current/shopping-list` (note view) | `{screen: "shopping", week}` |
| `/review` (Inventory Review) | `{screen: "inventory"}` |
| everything else | `{screen: "other"}` |

`/review` (Inventory Review) is the inventory page: it states `{screen: "inventory"}`, and
`href_for({"page": "inventory"})` returns `/review`.

An `ask` with an **empty** `options` list means "say it differently" (per `docs/API.md`):
the sheet shows the question and keeps the sentence editable, with no buttons.

### The sheet

Tapping the 56px round button (bottom-right, offset above the planner's dock) opens a
bottom sheet: one text field, focused, and a Send button. Opening the sheet fires
`POST /api/command/warm` without waiting for it, so the first command rarely pays a cold
model load. The engine spec promised this warm-up but no route exists yet; this spec adds
it: `@require_token`, returns `202` immediately, and asks the Ollama decider to load
(`keep_alive`) on a background thread. It is a no-op under `KITCHENOS_NO_LLM` or when
`llm_gate.allowed()` refuses, and never returns an error the bar has to show.

| Response | The sheet shows |
|----------|-----------------|
| `done` | `lines` (and `warnings`, e.g. dislike hits, styled as warnings) + **Undo** |
| `ask` | `question` + one 44px button per option → `POST /api/command/<id>/answer {option}` |
| `confirm` | `lines` + **Do it** / **Cancel** → `/answer {confirm: true}`; Cancel closes, changes nothing |
| `failed` | `reason`, with the sentence kept in the field so it can be edited and resent |

`ask` and `confirm` can chain (an answer may return another `ask`); the sheet renders
whatever comes back until a terminal `done` or `failed`.

### After a `done`

1. **`navigate` present** → the route has already turned it into `href` via
   `destinations.href_for`. The bar follows it only if it is a relative path starting
   with `/` and same-origin. It never builds a URL itself. A `done` that also changed
   something (it has Undo) navigates **when the sheet closes**, so Undo stays reachable;
   a successful Undo cancels that navigation. A pure navigation (no Undo) goes at once,
   and a late `done` that arrives after the sheet closed follows its `href` instead of
   reloading.
2. **Otherwise** → the bar dispatches `kitchenos:changed` on `window` with the response.
   If a listener calls `event.preventDefault()`, it has refreshed in place; if not, the
   bar reloads the page **when the sheet closes** — not at once, which would wipe the
   Done card and its Undo. In v1 only the planner listens (it refetches its week board).

API changes, both additive: the `/api/command` (and `/answer`) response gains `href`
alongside the existing `navigate`, and `POST /api/command/warm` is new. Both are
documented in `docs/API.md` in the same commit.

### Undo

**Undo** stays on the Done card until the sheet is closed — no auto-dismiss timer, since a
wrong date is often noticed a few seconds later. It calls `POST /api/command/<id>/undo`.
If the server refuses (a touched row changed since), the sheet shows the server's line
naming what changed. A successful Undo fires `kitchenos:changed` exactly like a `done`.

## Error handling

- **One request in flight.** Send and every option button disable while a request runs.
- **401** (`browser_session_expired` or `Unauthorized`) → "Session expired — reopen this
  page from the app." No raw JSON reaches the user.
- **Network failure / 5xx** → "Couldn't reach KitchenOS — nothing was changed." with the
  sentence kept. (A command either commits whole or not at all, per the engine spec.)
- **Shopping phrases** are still unsupported by the engine; its `failed` reason is shown
  as is. The client has no special case.
- **Never raises in page chrome.** If the script throws while building the button, the
  page still works; the injection itself, like the stale banner, cannot 500 a page.

## Touch and layout

Every control ≥ 44px. The sheet sizes itself to `visualViewport` so it stays above the
iPad keyboard. Escape, tapping outside, or a close button dismisses it. The button has an
accessible name ("Tell KitchenOS"), and the sheet is a labelled dialog that returns focus
to the button on close.

## Testing

- **Unit:**
  - `_serve_page` injects the bar on a normal page and skips print, handoff and
    read-only-session pages.
  - `destinations.href_for` returns only allowlisted same-origin paths
    (`/recipe/<quoted name>`, `/meal-planner?...`, `/`, registered `SECTIONS` paths), and
    `None` for an unknown recipe or anything else.
- **Registry:** a test walks `SECTIONS` and fails unless each page either installs a
  context hook or is listed in `CONTEXT_OTHER` with a reason — a new page's context is a
  decision, not an omission (same pattern as `NOT_BOOKMARKABLE`).
- **E2E (Playwright, `KITCHENOS_NO_LLM`, gold-standard kitchen):**
  - recipe page: "put this on wednesday" → Done line names the date → Undo removes it;
  - an ambiguous recipe phrase shows option buttons; tapping one completes the command;
  - `remove_cook` shows Do it / Cancel; Cancel leaves the cook in place;
  - "open the planner" navigates to the planner;
  - on the planner, a change refreshes the board in place (no full reload).
- **Gold set:** unchanged. The bar adds no phrasing rules, so `score_command_models`'s
  WRONG column is untouched.

## Out of scope

Siri and the native app shell (piece 3), the touch pass on existing pages (piece 4), the
engine's shopping actions, a built-in mic button, command history, and multi-turn
conversation beyond the engine's single question.

## Invariants this design must not break

- **No page render may block on an LLM.** The bar loads no model on render; warm-up is a
  fire-and-forget call on sheet open.
- **A cook card moves only through the ledger API.** The bar writes nothing itself — every
  change goes through `/api/command`, which runs the ledger functions.
- **A new browsable page must be registered.** Injection rides on `_serve_page`, so the
  registry stays the single list; the context-hook test extends it rather than adding a
  second one.
- **Request paths have one decode authority.** `href_for` builds paths from validated
  names; nothing in the bar decodes or constructs URLs.
