# iPad dashboard home, chat bar, and meals on TRMNL

**TL;DR:** Replace the `/` home page with one iPad-landscape screen that shows the meal
calendar, the grocery list and the inventory side by side, with nothing to open or close.
Extend the existing "tell it" bar so it also answers questions through Claude, which removes
the need to open the Claude app. Publish meals to an Apple "Meals" calendar so they appear in
the TRMNL calendar screen. Three independently shippable pieces, built in that order.

Status: design approved by Chase on November 15, 2026. No product code has changed.

## Intended outcome

Chase dislikes clicking, tapping and waiting, and wants to see everything in the right
context. Today the home page is a set of "Kitchen Today" cards over a list of links; the
calendar, shopping list and inventory each live on their own page; and talking to the recipe
library means opening the Claude desktop app, because `mcp_server.py` is stdio-only.

Success means:

- Picking up the iPad answers "what am I eating, what do I buy, what do I have" with **zero taps**.
- Planning a week happens by talking to one box on that same screen, with the result visible
  as it lands.
- Dinner shows on the TRMNL beside the day's appointments.
- KitchenOS never requires the Claude app.

## One surface per context

| Context | Surface | Status |
|---|---|---|
| Glancing, walking past | TRMNL calendar screen | Piece 3 |
| Referencing while cooking or shopping | iPad dashboard at `/` | Piece 1 |
| Planning on Sunday | Same dashboard, Month view, chat bar | Pieces 1 and 2 |
| Hands busy, or away from the iPad | Siri (`AskKitchenOS`), Reminders | Already built |

The iPad is **handheld**, not wall-mounted: touch is acceptable, but a tap is for *acting*,
never for *finding*.

## Decisions made

| Question | Decision |
|---|---|
| Layout weight | Three equal columns (use is an even mix of plan, buy, have) |
| Web page or native app | The web page at `/`. The native app is out of scope |
| "Native elements" | System fonts and controls, browser-native `popover`/`<dialog>`/`<details>`, the OS dictation key. No custom modal or mic code |
| Visual language | The existing `static/tokens.css` (Dawn light, Ink dark, coral accent, serif titles). No new tokens, no local edits to the copy |
| Chat writes | Act immediately with one Undo. No confirm step |
| Chat location | Inside the dashboard, not a remote Claude connector (the gateway is tailnet-only; a claude.ai connector would need public exposure) |
| TRMNL | Meals inside the existing calendar screen, not a dedicated plugin screen |

## Piece 1 — Dashboard home

> **Revised November 15, 2026, after Chase used the first build.** He cares most about what is
> planned and what he could make, and less about what to buy, and asked for the calendar to be
> the whole page. What shipped therefore differs from the three-column layout described below:
>
> - **The calendar fills the page**: seven day columns in Week, a full grid in Month.
> - **Meals drag between days** (through the ledger move endpoints). A day-picker inside the
>   expanded meal does the same move without a drag. Month cells are not draggable; tapping one
>   opens its week.
> - **Every day has "Add meal"**, which opens **Could make** with that day chosen. Could make
>   ranks dinners by how much is already on hand (`/api/cook-now`), flags the ones that use
>   expiring food, and plans one with a single tap.
> - **Could make, On hand and To buy are header buttons** that open native popovers. On hand
>   and To buy show a live count on the button. None of them holds a column.
> - The grocery list is flat (the saved list has no aisle data) and its inventory-match lines
>   are reached through "Full list".
>
> The text below is kept as the record of the original decision.

### Layout

Landscape iPad, one screen, no page scroll. Each column scrolls on its own only if its
content overflows, and lets the next row peek past the edge so the overflow is visible.

- **Header:** today's date in the display serif, the existing verdict line when there is one,
  a Week/Month segmented control, and one menu button.
- **Meals column:** Week view lists seven days with each day's meals, today highlighted, cook
  days distinguished from leftovers, unplanned days shown muted as "open". Month view replaces
  this column's content with a month grid, dinner title per day. Grocery and inventory do not
  move when the toggle flips.
- **To buy column:** the current week's purchase items as real checkboxes, grouped by aisle,
  with the count in the label. "Inventory matches — verify" lines render as plain text below,
  never as checkboxes.
- **On hand column:** "Use soon" first (soonest expiry first), then Fridge, Freezer, Pantry.
  Staples are collapsed into a single `<details>` line so they do not bury perishable stock.
- **Chat bar:** docked at the bottom, always visible (Piece 2; until then it is the existing
  command bar).

Grouping is done with space, not rules or card borders: the gap between columns is at least
twice the gap within one. Columns carry a small mono label rather than a heading.

### Interaction

- Tapping a meal expands it **in place** inside its column (ingredients on hand vs missing,
  open recipe, move, remove). It never covers the other columns.
- Dragging a cook card between days goes through the ledger API (`moveCookCard` /
  `moveBundleCard`), per the existing cook-card invariant. The dashboard must not introduce a
  path that reaches the legacy `PUT /api/meal-plan/<week>`.
- Ticking a grocery checkbox posts to the existing completion endpoint.
- Anything needing more room than an in-place expansion uses a native `popover`, which
  dismisses on an outside tap.

### What happens to the current home page

- The **page registry** (`web_dashboard.SECTIONS`) stays fully reachable from the header menu
  button as a native popover, so no page becomes unreachable. `/` remains `HOME`, outside
  `SECTIONS`.
- The **verdict prompt** stays, in the header.
- The **Kitchen Today cards** are retired from `/`: their content is now the three columns.
  `lib/kitchen_today` remains for `/prep` and the briefing endpoint.

### Data

All existing endpoints; the page is rendered as a shell and fills itself with `fetch`, so the
render never waits on anything slow.

| Column | Source |
|---|---|
| Meals, week | `GET /api/week-board/<week>` |
| Meals, month | The same endpoint for each ISO week the month touches, requested in parallel. If measured load is slow on the Mac mini, add one `GET /api/month-board/<YYYY-MM>` that returns dinner titles only |
| To buy | `GET /api/shopping-list/saved/<week>`, completion via `POST …/completion` |
| On hand | `GET /api/inventory`, `GET /api/use-it-up` |

The page listens for `kitchenos:changed`, calls `preventDefault()`, and refetches only the
affected column. It sets `window.kitchenosContext` (visible week, view mode) so commands are
interpreted against what is on screen.

### Behaviour at the edges

- **No shopping list for the week:** the column shows one button, "Build this week's list",
  which calls the existing generate path (compare only; never spends inventory).
- **Empty week:** days render as "open"; nothing is hidden.
- **A column's fetch fails:** that column shows a one-line message and a retry; the other two
  still render.
- **Portrait or phone width:** columns stack in the order Meals, To buy, On hand. The breakpoint
  is where three columns stop fitting, not a device preset.
- **Dark mode:** Ink tokens, automatically.
- Week ids appear only in URLs and values; text shows the date range.

## Piece 2 — Chat bar

One input, no mode switch.

1. The sentence and screen context go to `POST /api/command`, exactly as today.
2. If the command engine produces an action, it runs: local, fast, with Undo. Unchanged.
3. If the engine finds **no** action in the sentence (a question, or an open-ended planning
   request), the sentence goes to a new `POST /api/chat`, which runs a Claude tool loop.

The command engine's rule is unchanged: it never guesses. Claude is reached only when the
engine has nothing, never as a tiebreaker for an ambiguous command — that case still returns
buttons.

### `/api/chat`

- Runs Claude with the same operations `lib/mcp_tools` exposes (search and read recipes, read
  and change the plan, inventory, shopping list, use-it-up). It calls them in-process rather
  than through the stdio MCP server.
- Streams the answer; the reply renders directly above the bar. There is no chat window and
  no history sidebar. The current exchange is kept in page memory so follow-ups work; a reload
  starts clean.
- **Writes act immediately.** Every mutation in one reply is recorded as one undoable unit
  using the command engine's snapshot mechanism, and the reply ends with a single Undo. Undo
  keeps its existing refusal when a touched row has changed since.
- Plan changes go through the cooks/bundles ledger, never the legacy meal-plan PUT.
- The dislike filter and other deterministic guards apply to Claude's writes exactly as they
  do elsewhere; they are not re-expressed as prompt text.
- Recipe names in a reply are links that expand in place, with "add to a day".
- After any write, the endpoint emits what changed so the page refetches the right column.

### LLM gate

`lib/llm_gate` bounds every LLM call made inside a Flask request to `WEB_BUDGET_S`, keyed on
`has_request_context()`. A streamed chat reply legitimately outlives that budget, and it is
not a page render. The chat route therefore needs a **deliberate, named** exemption in
`llm_gate` (not a raised global budget), covered by a test, and must still honour
`KITCHENOS_NO_LLM`.

### Failure and cost

- Claude unavailable, credits exhausted, or `KITCHENOS_NO_LLM` set: the bar says so in one
  line and commands keep working. The existing System Health credit check is the pointer.
- A tool error mid-reply is reported in the reply; completed writes remain undoable.
- Questions spend Anthropic API credits; commands do not.

## Piece 3 — Meals on TRMNL

Extend the existing EventKit bridge (the Mac Apple integration that already syncs scheduled
cook sessions) with a **Meals** domain that publishes planned meals to a dedicated Apple
calendar. TRMNL's calendar screen already reads that account, so meals appear beside
appointments with no TRMNL plugin and nothing exposed to the public internet.

- One event per planned dinner by default (other slots are a setting), titled with the
  recipe's `display_name`, linking back to the recipe page.
- **One-way** (KitchenOS to Calendar). Editing a meal event in Calendar does not move the
  meal; the cook-session domain keeps its existing two-way behaviour.
- Reuses the bridge's destination selection, ownership generations and duplicate prevention.
  A missing or read-only destination pauses the domain; it never substitutes another calendar.
- Reconciles on plan change, so a chat or drag edit reaches TRMNL at TRMNL's next refresh.

**Assumption to confirm before building:** TRMNL reads Chase's iCloud/Apple calendar. If it
reads Google instead, the Meals calendar must live in a Google account configured on the Mac,
or TRMNL must be pointed at an ICS feed, which would require a public URL.

**Limit inherited from the bridge:** sync runs only while the Mac app and server are running.

A dedicated KitchenOS TRMNL screen (week of dinners, use-soon, grocery count, pushed by
webhook) is a possible later add-on and is out of scope here.

## Out of scope

- Changes to the native iOS/macOS app UI.
- A remote MCP server or claude.ai connector.
- Persistent chat history.
- A dedicated TRMNL plugin screen.
- Retiring `/meal-calendar`, `/meal-planner` or `/current/shopping-list`; they stay as the
  deep surfaces behind the dashboard.

## Testing

- **Piece 1:** `tests/test_web_dashboard.py` and `tests/test_page_chrome.py` keep passing
  (registry reachable, `kitchenosContext` set). `tests/test_no_external_assets.py` keeps
  passing. E2E at iPad landscape, iPad portrait and phone widths: three columns visible
  without page scroll in landscape; a grocery tick persists; a dragged cook keeps its scale;
  one failed column does not blank the others; both themes.
- **Piece 2:** unit tests for routing (command hit never reaches Claude; ambiguous command
  returns buttons, not Claude), for the single-Undo grouping, and for the gate exemption.
  The tool loop is tested with a stubbed model; `tests/gold/commands.json` WRONG stays 0.
- **Piece 3:** bridge tests for publish, update, removal and no-duplicate on re-sync, plus the
  paused state for a missing destination.
- **Design:** a layout, typography, colour and accessibility review pass on the built page
  before it ships.

## Delivery

Each piece ships as its own PR to `main`, then onto the deployed release branch per
`docs/OPERATIONS.md` "Reviewed API releases". Editing templates or `lib/` needs the API
LaunchAgent restart.
