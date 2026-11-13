# Command engine and gold-standard kitchen (Design Spec)

**Date:** 2026-11-12
**Status:** Proposed — awaiting user review. No implementation is authorized by this document alone.
**Covers:** pieces 0 and 1 of the touch-and-voice program below. Pieces 2–5 get their own specs.

## Goal

Say or type one sentence, on any page, and have KitchenOS carry it out:

> "I want this on the meal plan for this Wednesday, distribute the leftovers for lunch
> the next day, and freeze the rest."

The sentence plus *what is on screen* becomes a short list of typed actions, run through
the existing ledger and inventory code, with one Undo for the whole command.

## The program this belongs to

| # | Piece | What it is | Spec |
|---|-------|-----------|------|
| 0 | Gold-standard kitchen | A fixed fake kitchen and a command test set every feature is run through | **this doc** |
| 1 | Command engine | Sentence + screen context → validated actions → execute → Undo | **this doc** |
| 2 | "Tell it" bar | Mic/type bar on every web page that sends the page's context | later |
| 3 | App shell + Siri | Native app hosts the web pages; Siri uses the same engine and knows the screen | later |
| 4 | Touch pass | 44px targets, no hover-only controls, iPad layouts on every page | later |
| 5 | Signing without a paid licence | Automated re-sign/reinstall from the Mac mini; web fallback when lapsed | later |

Build order is 0 → 1 → 2 → 3, with 4 and 5 independent of the rest.

## Decisions the user made (2026-11-12)

- **The iPad app is home.** Pages are shown inside the KitchenOS app so the screen is always known.
- **Do it, then show Undo.** Commands run immediately; the engine stops to ask only when
  something is ambiguous, or would delete, overwrite, or leave the system.
- **v1 covers** meal plan and leftovers, cooking and freezer, inventory, shopping list, and navigation.
- **Models run on the Mac mini or on the device.** No cloud model tier.
- **Operationalize.** Code does everything it can; a model makes only small, typed decisions.
- **A gold standard** — a happy path and a test dataset — is run through every feature.
- **No paid Apple developer licence.** So nothing may exist *only* in the native app.

## Evidence (measured on the Mac mini, M4 16 GB, 16 seed commands)

| Approach | Model | Correct | Typical wait |
|----------|-------|---------|--------------|
| Model writes the whole plan as JSON | qwen2.5:3b | 3 / 16 | 1.7 s |
| Model writes the whole plan as JSON | mistral:7b | 6 / 16 | 4.0 s |
| Model writes the whole plan as JSON | granite4.1:8b | 11 / 16 | 3.4 s |
| **Code does the work; model picks one label per phrase** | **qwen2.5:3b** | **11 / 16** | **0.8 s** |

What the failures were:

- **Whole-plan generation** got dates wrong on every model, invented unrequested actions,
  and never once asked a question when the command was nonsense.
- **Label-picking** got every date right (code resolves them). All five misses were a choice
  between look-alike labels — `plan_cook` vs `move_cook`, `inventory_add` vs `shopping_add`.
- One call took 105 s. Cause not confirmed; a cold model load is the likely one.

Not measured: qwen3.5:9b and gemma4:12b (runs did not finish), larger models under the
label-picking approach, and the iPad's on-device Apple model (needs a device build).

## Architecture

One pipeline, in `lib/command/`, with no Flask imports below the route:

```
text + screen context
  1. split      sentence → phrases                      code
  2. extract    dates, meal, numbers, location, names   code
  3. classify   which action is this phrase?            rules → decider → ask
  4. resolve    names → real recipes / cooks / rows     code (+ decider on ties)
  5. validate   required slots, feasibility, policy     code
  6. execute    ledger / inventory functions            code, one command = one log entry
  7. respond    done | ask | confirm | failed           code
```

| Module | Does | Depends on |
|--------|------|------------|
| `phrases.py` | Split a sentence into phrases | nothing |
| `slots.py` | Pull dates, meal, quantity, scale, location out of a phrase | injected clock |
| `resolve.py` | Match words to recipe names, planned cooks, freezer rows, inventory rows | `recipe_index`, `serving_ledger`, `inventory` (read only) |
| `intents.py` | The closed action list, each with its slots, feasibility test and policy | nothing |
| `decider.py` | `decide(question, options) -> Decision` and its backends | `llm_gate` |
| `planner.py` | Runs steps 1–5 and returns a `Plan` or a `Question` | the five above |
| `executor.py` | Runs a `Plan` through ledger/inventory functions and records it | `serving_ledger`, `inventory`, `pantry`, `cook` |
| `log.py` | `command_log` table, snapshots, Undo | `inventory_db` |

### The model makes only typed decisions

```python
decide(question: str, options: list[Option], context: str) -> Decision(choice, source)
```

Exactly two questions are ever asked of a decider:

1. **Which action is this phrase?** — one label from a pruned list.
2. **Which of these candidates did you mean?** — only when code finds 2+ matches it cannot separate.

Three things shrink each decision before a model sees it:

- **Rules first.** Known phrasings ("we're out of …", "open …", "freeze the rest",
  "add … to the shopping list") map straight to an action. No model call.
- **Feasibility pruning.** An action is offered only if it could run: `move_cook` needs a
  planned cook of that recipe; `thaw` needs it in the freezer; `plan_cook` needs a recipe
  and a date in the phrase. This removes the measured `plan`/`move` confusion.
- **Screen pruning.** A recipe page offers recipe actions; the inventory page offers inventory actions.

If one option survives, it is taken with no model call.

**Backends, tried in order:** `RulesDecider` → `OllamaDecider` (output constrained to an
enum) → **the user** (the options become tap buttons). A future on-device or Jev backend
implements the same two-method interface; nothing else changes.

**The user is always the last tier.** A model that is slow, absent, or disabled never
blocks a command — the same options are shown as buttons instead.

### LLM gate compliance

`/api/command` is a Flask request, so every decider call asks `llm_gate.allowed()` and
takes its timeout from `llm_gate.budget_s()`; the whole request shares `WEB_BUDGET_S`.
On a refused or exhausted budget the engine returns `ask`, never an error. Under
`KITCHENOS_NO_LLM` the engine is rules + tap buttons only, which is what the e2e harness runs.
The decider model is kept loaded (`keep_alive`) and warmed when a command bar opens, so
the cold-load case is the exception.

## Actions (closed list, v1)

| Action | Slots (required in bold) | Runs through | Policy |
|--------|--------------------------|--------------|--------|
| `plan_cook` | **recipe**, **date**, meal (default dinner), scale | `serving_ledger.create_cook` | auto |
| `place_leftovers` | **date**, **meal**, count (default 1) | `add_placement` on the cook this command just planned, or the named planned cook | auto |
| `freeze_rest` | — | `add_placement(cook, "freezer", unassigned)` | auto |
| `move_cook` | **recipe**, **date**, meal | `move_cook` / `move_bundle` | auto |
| `remove_cook` | **recipe**, **date** | `delete_cook` | **confirm** |
| `mark_cooked` | **recipe**, servings | `cook.consume_recipe` | auto |
| `thaw` | **recipe**, **date**, **meal**, count (default 1) | `move_servings` from the freezer placement | auto |
| `inventory_add` | **item**, quantity, unit | `inventory` additive merge; **no `location` unless spoken** | auto |
| `inventory_remove` | **item** | inventory remove | **confirm** when it matches more than one row |
| `inventory_move` | **item**, **location** | inventory move (teaches the storage table, as today) | auto |
| `shopping_generate` | week (default current) | existing generator; compares, never spends inventory | auto |
| `shopping_send` | week | existing Reminders handoff | **confirm** — leaves the system, cannot be undone |
| `shopping_add` | **item** | manual row on the saved list | auto |
| `open_page` | page + recipe or date | returns a typed destination; changes nothing | auto |

A phrase that fits nothing, or is missing a required slot, becomes a **question**, never a guess.

### Date rules (code, with an injected clock)

- `today`, `tonight`, `tomorrow` — the obvious civil dates. `tonight` implies dinner.
- **A weekday name, when writing to the plan:** its next occurrence starting today.
  On Thursday Nov 12, "Wednesday" is Nov 18.
- **A weekday name on the planner screen:** that weekday in the week being shown.
- **A weekday name for `open_page`:** unchanged from the Siri web-navigation spec
  (that weekday in the current ISO week).
- `the next day`, `the day after` — one day after the previous phrase's date.
- `next week` — the following ISO week. "Next Friday" asks which Friday.
- Every summary line states the resolved date in words ("Wed Nov 18"), so a wrong
  resolution is visible on the Done card where Undo is one tap away.

## API

All three routes are `@require_token` gated and absent from `KNOWN_UNGATED`.

`POST /api/command`
```json
{"text": "put this on wednesday and freeze the rest",
 "context": {"screen": "recipe", "recipe": "Chicken Caldo A"}}
```
`context` is typed and validated server-side: `screen` is one of a closed set; `recipe`
must be an existing recipe name; `week` must pass `parse_iso_week`; `date` must be a real
civil date; `cook_id` must exist. Unknown keys are rejected. It never carries a URL or path.

Response, one of:
```json
{"status": "done", "command_id": 41, "undo": true,
 "lines": ["Wed Nov 18 dinner — Chicken Caldo A", "Freezer — 5 servings"],
 "warnings": [], "navigate": null}
{"status": "ask", "command_id": 41, "question": "Which caldo?",
 "options": [{"id": "a", "label": "Chicken Caldo A"}, {"id": "b", "label": "Chicken Caldo B"}]}
{"status": "confirm", "command_id": 41, "lines": ["Remove Black Bean Chili from Tue Nov 17"]}
{"status": "failed", "reason": "That would place 7 servings but the recipe makes 6."}
```

`POST /api/command/<id>/answer` `{"option": "a"}` or `{"confirm": true}` — continues a
paused command. `POST /api/command/<id>/undo` — reverses a done command.

`lines` use `display_name` for recipes and `format_week_range` for weeks; ids and week
keys never appear in text. `warnings` carries `dislike_hits` (warn, never block).

## Undo

A new `command_log` table (`data/kitchenos.db`): the sentence, the context, the plan,
the status, and — for each action — a **before-snapshot** of every row it touched plus
the ids it created.

- Undo restores the snapshots and deletes the created rows, in reverse order, inside one
  `write_transaction`, then regenerates the affected weeks and inventory views post-commit.
- Undo is **refused** if any touched row has changed since the command ran, with a line
  saying which. It never overwrites later work.
- `shopping_send` cannot be undone (Reminders is outside the system); that is why it confirms first.
- `shopping_generate` rewrites a generated note; its Undo line says "regenerate to refresh" and restores nothing.
- A command's actions run in order; if one fails, the earlier ones are rolled back by the
  same snapshot path and the response is `failed`. No half-applied commands.

## Gold standard (piece 0 — built first)

**1. Gold kitchen** — `tests/gold/kitchen/`: a small fixed vault (about ten recipes,
including the look-alike pair `Chicken Caldo A` / `B`, a bundle plate, and one recipe with
`servings: null`), a seeded database (inventory with duplicate rows and a 1.0-quantity
package, a freezer row, one planned week), and a frozen clock (Thursday 2026-11-12).
One pytest fixture builds it into a temp directory; nothing reads live kitchen data.

**2. Gold commands** — `tests/gold/commands.json`: `{id, screen context, say, expect}`.
Seeded with the 16 commands in the appendix. **Every new action or phrasing adds cases in
the same commit.**

**3. Three ways it is run**

| Tier | What runs | Model | When |
|------|-----------|-------|------|
| Unit | phrases, slots, dates, resolve, feasibility | none | every test run |
| Happy path | each gold command → `/api/command` → assert DB rows → Undo → assert DB identical to before | scripted fake decider | every test run |
| Scorecard | each gold command against real local models; prints pass rate, wrong-action count, latency | real | on demand, and before changing model or prompt |

**The ship gate is wrong-action count = 0.** A gold command may end in `ask` when a model
is unsure; it may never run the wrong thing. Pass rate is tracked, wrong actions block.

The default decider model is whichever local model scores best on the scorecard under
the final pipeline; it is one constant in `decider.py`.

## Invariants this design must not break

- **Ledger only.** No path through `PUT /api/meal-plan`. (Siri's existing
  `AddRecipeToMealPlanIntent` still uses it; moving it is piece 3.)
- **Recipe name is identity.** Resolution may *search* `short_title`/`display_name` but
  must land on exactly one canonical name, or ask.
- **Bundles are sets of cooks.** `move_cook`/`remove_cook` on a plate act on the bundle.
- **Inventory rows are containers.** `mark_cooked` goes through `cook.consume_recipe` unchanged.
- **`location` is omitted unless the user said it.**
- **Generating a shopping list compares; only confirming spends.** The engine never calls `apply_decisions`.
- **Untrusted text.** Item names reach Reminders only via the existing argv path.
- **Inventory mutations are transactions; generated views render from the DB after commit.**
- **New index on a migrated column goes in `_migrate`.** `command_log` is a new table, so its own indexes may sit in `_SCHEMA`.

## Error handling

| Situation | Result |
|-----------|--------|
| Model slow, missing, or disabled | `ask` with tap options |
| Nothing recognised | `ask`: "What should I do with that?" plus the screen's actions |
| Required slot missing | `ask` for that slot only |
| Ledger rejects (over-placement, bad date) | `failed` with the ledger's reason; nothing applied |
| Action 2 of 3 fails | roll back action 1; `failed` |
| Undo after later edits | refused, naming the changed row |
| Same command sent twice within seconds | second call returns the first command's result |

## Out of scope for this spec

The command bar UI, Siri and the app shell, the touch pass, signing automation, any
cloud model, multi-turn conversation beyond answering one question, and editing recipes.

## Parked (not scoped, not dropped)

- **Jev as a decider backend.** Fits the two-question interface exactly, but is cloud-hosted
  and waitlist-only. Needs: access, and a decision to allow sentences off the network.
- **Embedding-based classification** using the gold set as exemplars (`nomic-embed-text` is installed).
  Needs: a larger gold set, held-out cases.

## Open questions for review

1. **Weekday rule.** Planning uses "next occurrence from today"; opening a day keeps
   "this ISO week". Confirm that split is what you expect.
2. **`inventory_remove` on one clear match runs without confirming** (Undo covers it). Confirm.

## Appendix — seed gold commands (today = Thu 2026-11-12)

| id | Screen | Say | Expect |
|----|--------|-----|--------|
| plan-leftovers-freeze | recipe: Chicken Caldo A | I want this on the meal plan for this Wednesday and to distribute the leftovers for lunch the next day and freeze the rest | plan_cook 11-18 dinner · place_leftovers 11-19 lunch · freeze_rest |
| plan-simple | recipe | put this on friday dinner | plan_cook 11-13 dinner |
| plan-double | recipe | add this for tomorrow lunch, double batch | plan_cook 11-13 lunch ×2 |
| plan-default-meal | recipe | lets do this sunday | plan_cook 11-15 dinner |
| move-cook | planner W47 | move the caldo from wednesday to saturday | move_cook Chicken Caldo A → 11-21 |
| remove-cook | planner W47 | take the chili off tuesday | remove_cook Black Bean Chili 11-17 (confirm) |
| cooked | recipe | I cooked this tonight | mark_cooked Chicken Caldo A |
| thaw | home | pull a caldo out of the freezer for friday dinner | thaw Chicken Caldo A 11-13 dinner |
| inv-out | home | we're out of eggs | inventory_remove eggs |
| inv-add-two | home | add two cans of chickpeas and a bag of rice | inventory_add chickpeas ×2 · inventory_add rice ×1 |
| inv-move | home | move the bread to the freezer | inventory_move bread → freezer |
| shop-make-send | home | make the shopping list for next week and send it to reminders | shopping_generate W47 · shopping_send W47 (confirm) |
| shop-add | home | add olive oil to the shopping list | shopping_add olive oil |
| open-day | home | open saturday | open_page day 11-14 |
| open-recipe | home | show me the black bean chili | open_page recipe Black Bean Chili |
| unclear | home | put that thing on whenever | ask |
