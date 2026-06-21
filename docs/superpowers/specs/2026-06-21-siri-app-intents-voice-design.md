# KitchenOS — Siri Voice Access via App Intents (Design Spec)

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Subsystem:** A — Siri / voice access (calorie tracking is a separate subsystem, deferred)

## Goal

Let the user talk to the new iOS 27 (Apple Intelligence) Siri about KitchenOS:
ask which recipes contain a given ingredient, hear what's on the meal plan, get a
suggestion for something to add, and — with spoken confirmation — add a recipe to
the plan. Target devices are **Mac and iPad** (no iPhone). The new Siri's strength
is App Intents: entity resolution, parameter disambiguation, and action chaining.

## Scope

**In scope:** a voice front door over the *existing* KitchenOS backend. Five App
Intents, one shared recipe entity type, a thin shared Swift module, and small
additive backend changes.

**Out of scope (deferred to subsystem B):** calorie input, meal logging, daily
calorie estimation/tracking. The one nutrition touchpoint here is a read-only
"how many calories in X" intent, included because it is nearly free.

**Non-goals:** reworking the vault, databases, meal-plan parser, suggestion engine,
or the existing macOS extraction app. We add a front door, not a remodel.

## Constraints & context

- **Devices:** Mac (Apple Silicon) and iPad (M-series / A17 Pro) — both Apple
  Intelligence capable, required for the new conversational Siri. On older hardware
  the intents still work via classic Siri/Shortcuts, without chaining.
- **Connectivity:** Mac mini is always on and reachable via **Tailscale**. The Mac
  app calls Flask over **localhost**; the iPad calls it over the Tailscale MagicDNS
  hostname. No on-device data sync or offline write queue is needed.
- **Existing backend (`api_server.py`, Flask) already provides:**
  - `GET /api/recipes` (search by name/cuisine/protein), `GET /api/recipes/<name>`
    (full detail incl. nutrition + ingredients)
  - `GET` and `PUT /api/meal-plan/<week>` (read and write the plan)
  - `POST /api/suggest-meal` (suggestion engine), `GET /api/pantry`, `GET /api/inventory`
  - Recipes carry frontmatter: `nutrition_calories`, `protein`, `cuisine`,
    `seasonal_ingredients`, plus an `## Ingredients` table.
- **The one real backend gap:** arbitrary-ingredient search. Today search filters by
  protein/cuisine/name, not "contains harissa".

## Architecture

```
Mac / iPad (iOS 27, Apple Intelligence)
  └ Siri ──► App Intents (in KitchenOSKit, the shared module)
               └ KitchenOSClient (async URLSession, bearer auth)
                    ├ Mac:  http://localhost:<port>      ─┐
                    └ iPad: http://<magicdns-host>:<port> ┘──► api_server.py (Flask)
                                                                 └ vault + DBs (unchanged)
```

- **`KitchenOSKit`** — a shared Swift module (SwiftPM target) holding the client,
  the entity type, the five intents, and the `AppShortcutsProvider`. Included by:
  - the **existing macOS `KitchenOSApp`** target, and
  - a **new iPadOS app** target.
- All recipe / AI / nutrition logic stays in Python. Swift relays requests and turns
  JSON into spoken dialogue. The Swift layer stays thin and testable.

## Components

### iOS/macOS (Swift, in `KitchenOSKit`)

- **`KitchenOSClient`** — typed `async throws` client over `URLSession`. Reads base
  URL + bearer token from **Keychain**. Attaches `Authorization: Bearer …`. Short
  request timeouts so Siri never hangs. Platform picks base URL (localhost on Mac,
  MagicDNS host on iPad) from stored settings.
- **`RecipeEntity`** (`AppEntity`) — `id` = recipe name; display name + optional
  subtitle (cuisine/protein). Backed by an `EntityQuery` that calls `/api/recipes`
  so Siri can resolve and disambiguate recipe names. This entity is what enables
  cross-intent chaining (find → add).
- **Five App Intents** (each `async throws`, returns `IntentResult & ProvidesDialog`):
  1. `FindRecipesByIngredient(ingredient: String)`
  2. `GetMealPlan(week: String?, day: DayOfWeek?)`
  3. `SuggestForMealPlan(day: DayOfWeek?)`
  4. `AddRecipeToMealPlan(recipe: RecipeEntity, day: DayOfWeek, meal: MealSlot?)` — write
  5. `GetRecipeNutrition(recipe: RecipeEntity)` — read-only
- **`AppShortcutsProvider`** — registers natural trigger phrases for each intent.
- **Settings UI** — a minimal SwiftUI screen: base host + API token (saved to
  Keychain). The only UI the app needs.

### Backend (Python, additive — `api_server.py` + `lib/`)

- **Ingredient search:** add an `ingredient=` query param to `GET /api/recipes` that
  matches against each recipe's `## Ingredients` table (combine with existing
  protein/cuisine/name filters). Build/extend a parsed ingredient index as needed.
- **Siri-friendly suggestion wrapper:** an endpoint that composes `/api/suggest-meal`
  with `/api/pantry` so "what can I add given what I have?" returns a short,
  speakable result.
- **Bearer-token auth:** a static shared secret required on the Siri-facing
  endpoints. Token stored in `.env`; validated in Flask. Defense-in-depth on top of
  Tailscale's network-level restriction.

## The Siri capabilities

| # | Intent | Example phrases | Backend |
|---|--------|-----------------|---------|
| 1 | `FindRecipesByIngredient` | "Which KitchenOS recipes use chicken?" / "…that have harissa" | `GET /api/recipes?ingredient=` *(new)* |
| 2 | `GetMealPlan` | "What's on my meal plan this week?" / "What's for dinner Thursday?" | `GET /api/meal-plan/<week>` |
| 3 | `SuggestForMealPlan` | "Help me find something to add to the meal plan" / "What can I make with what I have?" | `POST /api/suggest-meal` + `GET /api/pantry` |
| 4 | `AddRecipeToMealPlan` *(write)* | "Add Butter Chicken to Thursday" / after #1: "add the first one to Friday" | `PUT /api/meal-plan/<week>` |
| 5 | `GetRecipeNutrition` *(read-only)* | "How many calories in Butter Chicken?" | `GET /api/recipes/<name>` |

**Chaining:** #1 returns `RecipeEntity` values and #4 accepts a `RecipeEntity`, so the
new Siri can run "find me a chicken recipe… add that to Thursday" as one conversation.

## AI placement (where the models live, and why)

There are two distinct "Apple LLM" surfaces; this design uses one and deliberately
defers the other.

- **Apple's model via the new Siri (in use, no code).** The iOS 26+/macOS 26 Apple
  Intelligence model is what parses speech, selects the right App Intent, and resolves
  parameters against `RecipeEntity`. The whole design rides on it by exposing
  well-formed App Intents — we write no model code to get this.
- **Server-side Claude/Ollama stays the brain (unchanged).** All data-grounded
  intelligence — meal suggestions (`lib/meal_suggester.py`: ingredient-overlap scoring
  over the full recipe corpus + pantry DB, then Claude/Ollama) — stays in Python. It
  has the data and a stronger model than the on-device LLM, and the always-on Mac mini
  is always reachable over Tailscale, so there is no offline gap to fill.
- **Apple Foundation Models framework (`import FoundationModels`) — deferred, optional
  Phase 3.** Calling the ~3B on-device model directly (`LanguageModelSession`,
  `@Generable` guided generation, tool calling; free, offline, private; requires an
  Apple Intelligence device, which the target Mac + iPad both are). **Not in v1:** it
  has none of the KitchenOS data and is weaker than Claude, so on-device suggestions
  would be redundant and worse. Spoken result phrasing uses simple string templating in
  the intents, not an LLM. Revisit later only for narrow on-device wins: instant recipe
  summarization ("give me the gist"), fuzzy voice→param normalization ("something spicy
  and quick"), or a true offline suggestion fallback.

## Data flow (chained find → add, with confirm gate)

1. *"Which recipes use chicken?"* → `FindRecipesByIngredient(ingredient: "chicken")`
   → `GET /api/recipes?ingredient=chicken` → `[RecipeEntity]` → Siri speaks the top few.
2. *"Add the first to Thursday"* → `AddRecipeToMealPlan(recipe:, day: .thursday)` →
   intent calls `requestConfirmation` → Siri speaks *"Add Butter Chicken to Thursday
   dinner?"* → on **yes**: resolve current week → `PUT /api/meal-plan/<week>` → speak
   result. On **no**: nothing is written.

## Error handling

All errors are spoken, graceful, and never reported as false success.

- Server unreachable → *"I can't reach KitchenOS right now."*
- No matches → *"I didn't find any recipes with harissa."*
- Ambiguous recipe on add → defer to the App Intents framework's disambiguation
  ("which one?") via the entity query.
- Write failure → *"I couldn't update the meal plan."* (no success claim).
- Missing day/week → default to the current week; validate the spoken day name.

## Testing

- **Backend (pytest, existing `tests/`):** the new `ingredient=` search and the
  bearer-token check.
- **Swift:** `KitchenOSClient` against a mock `URLProtocol`; each intent's `perform()`
  with an injected fake client.
- **Manual Siri:** every intent appears as an action in the **Shortcuts app** — test
  there first (no voice), then verify by voice on Mac, then iPad.

## Security

- Flask bound so it is reachable only via localhost + Tailscale — never exposed
  publicly.
- Bearer token is the second layer of defense.

## Build order (phased)

- **Phase 0 — Backend:** `ingredient=` param on `/api/recipes`, the suggest wrapper,
  bearer-token auth + config. With tests.
- **Phase 1 — Shared module + Mac:** build `KitchenOSKit` (client, `RecipeEntity`,
  five intents, `AppShortcutsProvider`, settings UI); wire into the existing macOS
  app; verify on Mac via Shortcuts, then Siri.
- **Phase 2 — iPad:** new iPadOS target that includes `KitchenOSKit`; Tailscale
  config; signing; verify on iPad.

## Open questions for implementation planning

- Exact Tailscale MagicDNS hostname and Flask port to bake into iPad settings.
- Whether `KitchenOSKit` is a new SwiftPM target inside the existing `KitchenOSApp`
  package or a separate package both apps depend on.
- Meal-slot model (`MealSlot`: breakfast/lunch/dinner) — confirm against how the
  meal-plan markdown represents slots in `lib/meal_plan_parser.py`.
