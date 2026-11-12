# Siri Web Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for sequential implementation, or superpowers:subagent-driven-development with explicit file ownership. Steps use checkbox syntax for tracking.

**Goal:** Let a Siri open/show request launch the exact saved recipe or meal-plan date in the KitchenOS web app, with its content visible and authenticated.

**Architecture:** Resolve a typed destination inside the existing voice assistant; hand it to a foreground browser-opening intent. A one-use server handoff establishes limited browser viewing access. Extend the existing planner's URL/date selection instead of creating a second meal planner.

**Tech Stack:** Existing Swift 6 package tooling in Swift 5 language mode, SwiftUI/App Intents/Foundation Models, UIKit/AppKit, Python 3.11 via .venv/bin/python, Flask, and vanilla JavaScript. No new third-party dependency. iOS/macOS 26 deployment floor.

**Spec:** [Siri opens recipes and meal-plan days on the web](../specs/2026-10-15-siri-web-navigation-design.md).

**Status:** Approved with “Go”; implementation is in progress in the managed `siri-web-navigation` worktree. The ledger under `.superpowers/sdd/2026-10-15-siri-web-navigation/progress.md` records verification and release state. Existing calendar/receipt changes are preserved as the feature baseline.

## Global constraints

- “The destination is a browser page, not a native recipe sheet or an Obsidian note.”
- “Navigate for an explicit ‘open’ or ‘show’ request.” Approved as part of this plan.
- “Use the device's default browser and the existing KitchenOS connection configuration.”
- “Recipe names remain identity”; never key navigation on short_title/display_name.
- “The selected date is authoritative: derive its ISO week, including ISO-year boundaries.”
- “Browser access established by Siri is for viewing, lasts 15 minutes, and is visibly labeled.”
- “Codes expire after 60 seconds.” Retain the restrictive browser cookie for 24 hours; its authorization still expires absolutely at minute 15.
- “Cap each store at 1,024 live entries”; no persistent credential or domain-data store is added.
- “No recipe, inventory, or plan mutation is performed merely to verify navigation.” Preserve all ledger save/drag guards and Siri confirmation before writes.
- No page render blocks on an LLM. Use existing server/vault/DB helpers and isolated test fixtures.
- Preserve the existing private HTTP deployment. Use Secure cookies for HTTPS; do not enable public hosting or configure new HTTPS infrastructure as an incidental step.

## Review focus

1. Cookie expiry/restart/token rotation must not turn a marked viewing browser into an unrestricted loopback client; the restrictive marker survives grant expiry (Tasks 2, 3, 5).
2. Legacy GET actions can mutate state; a global endpoint allowlist must deny them, not merely block POST/PUT (Tasks 2, 5).
3. Sunday, ISO-year rollover, DST, and UTC-positive offsets must not select the wrong date; async refresh must not restore Monday or repeatedly steal focus (Tasks 1, 3, 5).
4. Canonical recipe names with Unicode, percent signs, or colliding short titles must resolve once and encode once; missing/ambiguous references never open guesses (Tasks 1, 2, 4).
5. Browser dispatch can succeed while data loading fails; tests must assert rendered recipe/day content under remote bearer gating, not just a 200 page shell or successful native opener (Tasks 4, 5).

## Workspace and execution order

The inspected checkout is codex/calendar-meal-planning with many pre-existing tracked changes and untracked calendar files. Planning added only this document and its spec. Before implementation, establish an isolated workspace that includes the relevant current-working-tree baseline; a HEAD-only worktree omits static/planning-calendar.js, PlanningWebPolicy.swift, and other inputs used here. Record transferred baseline changes separately. Never stash, revert, or commit unrelated user changes.

Tasks 1 and 2 can be implemented independently. Task 3 depends on Task 2; Task 4 depends on Tasks 1–2; Task 5 integrates all four. Prefer sequential execution because the auth, browser, and native handoff contracts meet at the same endpoints. Run the repository's finish-feature checklist before feature commits, stage only owned files/hunks, and follow the commit convention. Deployment is a separate final step after review and validation.

## Task 1: Typed destinations and deterministic target resolution

**Files:** Create KitchenOSKit/Sources/KitchenOSKit/WebDestination.swift, WebDayResolver.swift, RecipeNavigationResolver.swift; modify Models.swift only to decode optional RecipeSummary.displayName from display_name and extend its initializer with a default-nil argument; create KitchenOSKit/Tests/KitchenOSKitTests/WebDestinationTests.swift, WebDayResolverTests.swift, RecipeNavigationResolverTests.swift and extend ModelsTests.swift. Reuse WeekDate.swift; modify neither recipe identity nor its stored metadata.

**Interfaces:**

- WebDestination: Codable, Equatable, Sendable, with recipe(name: String) and mealPlan(date: String). JSON is exactly {"kind":"recipe","name":"Rice & Beans"} or {"kind":"meal_plan","date":"2026-10-16"}.
- WebDayReference: today, tomorrow, weekday(DayOfWeek, weekOffset: Int), exact(String). Support weekOffset 0 and 1; ambiguous “next Friday” is a clarification outcome, not a guessed offset.
- WebDayResolver.resolve(_:now:calendar:) throws -> String returns validated YYYY-MM-DD using an injected clock/local calendar; no UTC conversion of a civil date.
- RecipeNavigationResolver.resolve(name:recipes:) throws -> String returns the canonical recipe name. Prefer exact canonical identity, then unique case-insensitive canonical/display-name match. Errors distinguish missing and ambiguous candidates.
- WebDestination.handoffURL(relativePath:baseURL:) throws -> URL accepts only the Task 2 bootstrap shape at the configured HTTP(S) origin. Reject userinfo, missing host, base query/fragment, a non-root base path, protocol-relative input, and any destination outside /browser/open with one valid code fragment. Current deployment is at the origin root; surface unsupported proxy-prefix configurations rather than silently dropping them. Keep the configured scheme and port.

- [x] **Write failing tests** for the JSON contracts and deterministic resolution. Exact assertions include tomorrow from Sunday 2026-12-27 producing 2026-12-28 (ISO 2026-W53), tomorrow from 2027-01-03 producing 2027-01-04 (ISO 2027-W01), current-week Friday from 2026-10-15 producing 2026-10-16, and a UTC+14 calendar retaining the requested civil date. Test invalid 2026-02-29 and valid 2028-02-29.
- [x] Assert canonical exact match wins over a colliding display name; two display-name candidates throw ambiguity; missing names and slash/backslash/traversal candidates cannot yield a navigation target. Include Unicode, ampersand, hash, and percent characters in a valid canonical name. Pin decoding both old summaries without display_name and current summaries with it; canonical name remains the resolved result in both cases.
- [x] Run red: swift test --package-path KitchenOSKit --filter 'WebDestinationTests|WebDayResolverTests|RecipeNavigationResolverTests'. Expect failures for the missing implementation.
- [x] Implement the three focused helpers. Do not implement a second API-host resolver or persistent last-recipe memory.
- [x] Run the same tests green, plus existing ConfigTests and WeekDateTests. Add round-trip tests showing descriptor JSON has no model-supplied URL or credential.
- [x] Commit the helpers and tests after the required feature checklist.

## Task 2: One-use browser handoff and bounded viewing authorization

**Files:** Create lib/browser_handoff.py and tests/test_browser_handoff.py; modify api_server.py and tests/test_api_auth.py. Apply root AGENTS.md and recheck nested instructions at execution time; its referenced lib/AGENTS.md was absent during planning. Update docs/API.md for the new contracts and remove its stale assertion about the live token being unset. Task 3 supplies the bootstrap HTML/script.

**Interfaces and contracts:**

- BrowserHandoffStore(clock=...): issue(destination, origin, token_fingerprint), exchange(code, origin, token_fingerprint), authorize(session_id, origin, token_fingerprint). Use a lock for atomic one-use exchange, secrets.token_urlsafe(32), hash-only keys, absolute expiries, opportunistic pruning, and separate 1,024-entry limits.
- POST /api/browser-handoffs (endpoint create_browser_handoff): existing native bearer/loopback authorization; body is exactly one Task 1 destination descriptor. Resolve saved recipe through existing contained-path helpers; validate civil date and derive ISO week. Return handoff_path and expires_at; handoff_path is /browser/open#code=<opaque code>. Return 400 for invalid input, 404 for absent recipe, 401 for missing native authorization remotely, and 429 for capacity exhaustion. A viewing cookie cannot authorize issuance.
- POST /api/browser-handoffs/exchange (exchange_browser_handoff): same-origin JSON {"code":"..."}; atomically consume code and set cookie kitchenos_view. Return redirect_path and expires_at. redirect_path is server-built /recipe/<encoded canonical name> or /meal-planner?week=<derived week>&date=<date>&view=calendar. No caller-controlled redirect URL. Invalid/expired/replayed code returns a generic 401 outcome; capacity exhaustion must not consume a still-valid code.
- Cookie: host-only, HttpOnly, SameSite=Strict, Path=/, Max-Age=86400; Secure when served on HTTPS. Server grant TTL=900 seconds, code TTL=60 seconds. Bind origin including port and current token fingerprint; do not trust forwarded headers without an existing trusted-proxy setup. Keep the stale cookie on grant expiry so the request guard can identify restricted viewing mode.
- Global before-request guard: with a presented viewing cookie and no valid explicit API bearer, allow only approved safe endpoints under a valid session; block every other endpoint or unsafe method with 403 read_only_browser_session. Apply before loopback and legacy-route exemptions. Exchange is the explicit code-authenticated exception. Expired/invalid cookies allow only bootstrap/static and an expired explanatory shell, and return 401 browser_session_expired for data; never fall through to normal authorization. A valid explicit native bearer retains existing behavior.

**Exact GET/HEAD data allowlist:** api_recipe_detail, api_recipes, api_meal_plan_get, api_week_board, api_meals_list, api_macro_targets, api_use_it_up, get_cooking_availability, get_planning_calendar. Never include api_meal_plan_put or api_meals_create just because they share a path. Allow page endpoints recipe_detail_page, meal_planner, browser_open_page and required static/serve_recipe_image resources; no general /api/ or GET wildcard.

Use Cache-Control: no-store and Vary: Cookie, Authorization for private responses. The bootstrap is no-store/no-referrer. Do not log bearer/code/session values. On restart the stores are empty and an existing cookie is treated as invalid, not as anonymous authorization. This does not widen or silently fix access for unrelated clients without the cookie.

- [x] **Write failing store and Flask tests:** 59-second code succeeds, 60-second code fails; two concurrent exchanges produce one success; authorization fails at 900 seconds while the restrictive cookie remains; replay, restart, token rotation, origin/port mismatch, external targets, and capacity bounds fail closed.
- [x] Assert remote unauthenticated recipe JSON remains 401; valid viewing cookie permits each exact data endpoint; a nonallowlisted GET is denied. Assert /refresh, /refresh-nutrition, /reprocess and a legacy ungated mutation are blocked, including with REMOTE_ADDR=127.0.0.1. Verify valid native bearer still reaches its existing route behavior. Use temporary DB/vault and handler spies to prove denied handlers never execute.
- [x] Assert recipe path encoding is single-pass, with Rice & Beans mapping to /recipe/Rice%20%26%20Beans; recipe names containing literal % are not decoded into new separators. Assert the date example produces the exact planner path above.
- [x] Run red: .venv/bin/python -m pytest tests/test_browser_handoff.py tests/test_api_auth.py -q.
- [x] Implement the store, destination validation, endpoint-specific authorization, and routes. Keep token validation shared with require_token rather than drifting into a second bearer rule. Do not disable existing gating or add a new persistence schema.
- [x] Run green with the same command plus tests/test_recipe_detail.py and tests/test_planning_calendar.py. Review headers/cookie attributes for both the current HTTP origin and HTTPS test origin.
- [x] Commit backend/contracts after the required checklist; do not deploy this partial state alone.

## Task 3: Browser bootstrap, viewing mode, and exact-day landing

**Files:** Create templates/browser_open.html, static/browser-handoff.js, static/browser-view.js, tests/e2e/test_siri_web_navigation.py; modify api_server.py, templates/recipe_detail.html, templates/meal_planner.html, static/planning-calendar.js, static/planning-calendar.css, tests/test_web_dashboard.py, tests/e2e/test_planning_calendar.py, and tests/e2e/conftest.py as necessary for isolated authenticated tests.

**Interfaces:**

- GET /browser/open (browser_open_page) serves only the minimal first-party bootstrap. Add it to NOT_BOOKMARKABLE with reason “requires an ephemeral one-use fragment”; do not add a dead permanent dashboard/Safari bookmark.
- Server-derived browser-view config contains only state active/expired, expires_at, and readOnly. No credentials enter page markup. browser-view.js centralizes the banner, expiry timer, and unauthorized-response handling; paused refreshes do not keep issuing failed requests.
- Planner URL state adds date alongside week/view. A valid date derives week and takes precedence over a conflicting week. Canonicalize with history.replaceState. Invalid dates show a visible error while retaining functional week navigation.
- Extend KitchenPlanningCalendar.mount with date and readOnly; return setSelection({week,date}) alongside existing lifecycle methods. Keep pending date through snapshot loads and stale-response races; update URL when day navigation changes it.
- Add a focusable heading immediately beside each day's meal list, with stable data-date and an accessible date label. First navigation selects that date, focuses its meal heading once, and scrolls its meal content visibly. Refresh maintains selection without stealing keyboard focus. Desktop highlights the chosen day; mobile selects its existing single-day layout.
- Grid view handles the same date when switching views: highlight/focus that date and scroll its actual container into view. Week navigation carries the weekday into the new week and updates date, so a stale date never sends navigation back to the old week.

- [x] **Write failing browser tests** at 390x844 and desktop sizes with fixture recipes/meals. Assert exact recipe body loaded, selected date text and meal content visible in the viewport, correct empty-day message, reload persistence, Calendar/Grid switch preservation, next-day/week URL updates, and late old responses not replacing the selected day.
- [x] Add expiry/reload tests: the marker remains beyond 900 seconds, both pages show the expiry outcome, no private fetch or old mutation handler becomes authorized through loopback fallback, and repeated refreshes stop.
- [x] Use a dedicated test-only server fixture with a synthetic token and WSGI remote-address wrapper so browser requests exercise remote auth even when the test browser connects locally. Keep production behavior unchanged. Copy vault/DB/config using the existing harness, use KITCHENOS_NO_LLM=1, and bind the test server to 0.0.0.0. Do not test against live kitchen records.
- [x] Mark the new file e2e. The existing test_planning_calendar.py is currently missing its e2e mark; add it so explicit -m e2e selects those tests rather than silently skipping them.
- [x] Run red: .venv/bin/python -m pytest tests/e2e/test_siri_web_navigation.py -m e2e -v.
- [x] Implement fragment removal before any network request, same-origin exchange, and location.replace of the server destination. Display missing/expired-code errors; never put the code into a query string, browser storage, third-party request, or a rendered error message.
- [x] Implement selected-date handling using civil-date arithmetic and the current uncommitted calendar as the baseline. A meal list below the timeline must be scrolled into view; a visible calendar header alone does not satisfy the test.
- [x] Implement viewing controls: allow local recipe scaling, previews, filters, and date/week changes; disable saved servings/add-to-week, Sortable/save initialization, scheduling, and all-day classification. Derive mode from the server, not a query flag. Do not change native bearer-authenticated functionality or remove cook-card ledger guards.
- [x] Run green: .venv/bin/python -m pytest tests/e2e/test_siri_web_navigation.py tests/e2e/test_planning_calendar.py tests/e2e/test_planner_touch.py -m e2e -v; then .venv/bin/python -m pytest tests/test_web_dashboard.py -q. Verify the browser tests record zero mutation requests during navigation and expiry.
- [x] Commit the integrated web surface after the required checklist.

## Task 4: Voice tools and foreground browser handoff

**Files:** Create KitchenOSKit/Sources/KitchenOSKit/AI/Tools/OpenWebDestinationTool.swift, KitchenOSClient+BrowserHandoff.swift, WebBrowserOpener.swift, Intents/OpenKitchenOSWebIntent.swift; modify AI/MealPlanAssistant.swift and Intents/AskKitchenOSIntent.swift. Add NavigationToolsTests.swift, BrowserHandoffClientTests.swift, WebBrowserOpenerTests.swift under KitchenOSKit/Tests/KitchenOSKitTests; extend existing ToolsTests.swift/MealPlanEditTests.swift only where needed.

**Interfaces:**

- Invocation-local PendingWebDestinationStore with set/clear/take; conflicting distinct destinations return a clarification. Consume exactly once and clear at each reply start/error.
- OpenWebDestinationTool consumes structured recipe/day arguments, uses Task 1 resolvers plus existing client reads, and records one WebDestination. Register only when AssistantSurface.voice. It never launches UI or invokes a write endpoint.
- KitchenOSClient.createBrowserHandoff(destination:) async throws -> BrowserHandoffResponse, whose only fields are handoffPath and expiresAt. POST the Task 2 JSON through the existing authenticated transport. Forbid cross-origin redirects and validate the returned bootstrap path with Task 1 before opening.
- WebBrowserOpener.open(_ url: URL) async -> Bool has platform implementation and an injected test double. Use UIApplication.open on iOS, NSWorkspace.open on macOS; never hardcode a browser application.
- OpenKitchenOSWebIntent is a custom, non-discoverable foreground handoff with supportedModes .foreground(.immediate). Define WebNavigationKind: String, AppEnum with recipe and mealPlan cases, and App Intent parameters kind, recipeName: String?, date: String?; init(destination:) maps Task 1's descriptor to these supported parameter types. Validate exactly the fields required by the kind; do not declare a raw associated-value Swift enum as an App Intent parameter. Revalidate current config/target, mint the handoff, launch the browser, and return concise status or actionable failure. No URL or bearer is an intent parameter.
- AskKitchenOSIntent.perform returns some IntentResult & ProvidesDialog & OpensIntent. Use result(opensIntent:dialog:) only when navigation is resolved; plain result(dialog:) for ordinary answers/errors. The installed OS 26 SDK has matching concrete containers; verify by compilation. No dummy home-page opener.

- [x] **Write failing behavioral tests** for explicit open/show intent instructions, correct canonical target and date resolution, missing/ambiguous recipe, ambiguous weekday, no-context “open that,” one-target consumption, and cancellation/error cleanup. A fresh invocation must not inherit another invocation's selection.
- [x] Assert the tool makes lookup requests only and never presents UI. Assert the foreground handoff POST has its bearer only in the header, rejects a poisoned absolute/cross-origin response, and calls the injected opener once with a validated bootstrap URL. An opener rejection returns failure rather than a success claim.
- [x] Assert ordinary questions produce no pending navigation. A combined add-and-show flow opens only after a successful confirmed write; decline/failure does not perform the write or automatically open. Existing independent write confirmation tests must stay green.
- [x] Run red: swift test --package-path KitchenOSKit --filter 'NavigationToolsTests|BrowserHandoffClientTests|WebBrowserOpenerTests|MealPlanEditTests'.
- [x] Implement voice-only registration, structured resolution/store, authenticated handoff transport, platform opener, and conditional foreground result. Provide the local current date/week to the voice session for interpreting requests, but let the deterministic resolver own calendar arithmetic.
- [x] Run the focused tests green, then swift test --package-path KitchenOSKit. Keep native chat and OpenRecipeIntent/Spotlight behavior unchanged.
- [x] Build both supported targets: xcodegen generate; xcodebuild build -scheme KitchenOSSiri -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO; xcodebuild build -scheme KitchenOSSiri -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO. This verifies compilation/metadata, not real Siri or installation.
- [x] Commit after the feature checklist. Native changes are not active on devices until the verified app is installed.

## Task 5: Integration review, documentation, and release gate

**Files:** Update docs/API.md, docs/ARCHITECTURE.md, docs/OPERATIONS.md, README.md and this plan's checkboxes. Extend Task 3's browser tests and Task 4's native tests for any issues discovered in review. No new UI surface or capability is added in this step.

- [x] Review all five Review Focus conditions against code/tests. Check the global viewing guard precedes local exemptions and excludes legacy state-changing GETs. Verify every bootstrap resource is allowlisted while the cookie is active and expired, and a renewal exchange still works with an old cookie present.
- [x] Run .venv/bin/python -m pytest -q for the normal suite and report any failures by name; run the focused e2e command from Task 3 explicitly because normal pytest excludes e2e. Run the full Swift suite and both app builds after the last code change. Do not assert physical-device behavior from these results.
- [x] Document the request examples, current-week weekday convention, absent cross-invocation memory, 15-minute viewing grant/24-hour restriction marker, current HTTP-cookie tradeoff, restart/token-rotation behavior, and rebuild/install requirement. Document the bootstrap route as ephemeral and non-bookmarkable. Do not claim the wider browser auth gap is solved for clients without a handoff.
- [x] Obtain a fresh code review covering Swift foreground dispatch, Python auth/store, and browser focus/read-only integration before deployment. Apply necessary fixes and rerun affected verification.
- [x] Deploy only after implementation review: preserve existing unrelated working-tree changes; follow docs/OPERATIONS.md for coordinated API/template/static update and native app install. Restart com.kitchenos.api for deployed Python/template changes. Do not replace the separate Safari web app with the native app bundle.
- [ ] On an authorized physical iPhone/iPad and Mac, verify a named recipe, find-and-show recipe, a current-week day, tomorrow crossing a week, and an empty day. Verify default-browser selection, unlock behavior, Tailscale reachability, and actual content loading. Use existing data for reads; do not create a real meal merely to test.
- [ ] Verify server-unreachable, expired/replayed code, missing/ambiguous target, and “open that” in a new invocation. If the custom foreground handoff is not accepted on-device, do not claim success; investigate the foreground continuation API before changing the approved product behavior.
- [x] Record what was actually tested, any remaining device limitation, and the precise release state. Completion requires the requested recipe/day content to load visibly in the browser, not merely the dashboard or an empty HTML shell.

## Review and execution choice

The user approved this plan with “Go”. Implementation uses workers with separate ownership and a fresh integration review. Feature changes are compared with the copied working-tree baseline; unrelated calendar/receipt edits are not staged or committed.

## Release integration correction

Implementation inspection found that the active API is release
`a166f39ce6ca9195fd1c44bca03fcb9a2070c391`, already behind the shared HTTPS gateway,
while the planning checkout predates those fixes. The release candidate is
therefore based on that live commit, preserving its proxy authentication,
canonical-origin config migration, deployment tool, and Obsidian fallback.
Only calendar prerequisites required by this feature are included from the
working-tree baseline; receipt parsing, inventory configuration, and unrelated
inference changes are excluded. The feature still follows the native app's
configured origin, including existing private HTTP settings. No gateway or
network infrastructure is added. Verification and review use this integrated
candidate before activation.

## Verification before deployment

- Release candidate preserves live commit `a166f39` and the calendar prerequisites.
- Python: 4,468 passed, 1 skipped; 162 browser tests excluded by the default marker.
- Explicit affected browser suite: 56 passed, including true touch, complete legacy
  meals, local/foreign leftovers, expiry, and existing Obsidian failure recovery.
- Swift: 131 passed. Signed macOS and paired-iPad builds succeeded without warnings.
- Imports, Ollama health check, and diff whitespace checks passed.
- Nine existing EPUB XML parser warnings remain in the Python suite.
- Review corrections cover cancellation, trusted HTTPS proxy origin, complete day
  content, touch browsing, and visible meal-first landing. Physical Siri invocation
  and unlock/default-browser behavior remain separate device checks.

## Actual release state

- Code commit: `e5299e93d15f0e47e7cc005b40fee0a2e2319c4a`, branch
  `codex/siri-web-navigation`. All task commits were consolidated into this
  reviewed release; the primary checkout's existing work remains untouched.
- API staged and activated through the existing deployer under
  `~/Library/Application Support/KitchenOS API/rollouts/siri-web-navigation`.
  The active HTTPS health response reports this exact commit; remote unauthenticated
  recipe access remains 401. The previous API and a SQLite backup are retained.
- Signed Mac app installed and running at `~/Applications/KitchenOS Native.app`.
  The previous native bundle is backed up; the separate Safari app is preserved.
- Signed iPad app installed on the paired iPad Air. First launch is blocked by
  iPadOS's signing/trust gate. Signature verification, current profile validity,
  matching app/team identity, registered-device inclusion, and enabled Developer
  Mode all pass. Developer-profile trust must be checked on the iPad itself.
- Live HTTPS browser acceptance loaded an existing recipe and tomorrow's day at
  phone size, verified Secure/HttpOnly/Strict cookie, code replay denial, write
  denial, and zero domain-mutation requests. Tomorrow's real plan is empty and
  correctly displays that state. No recipes or meals were created for testing.
- Physical spoken Siri, unlock behavior, and actual default-browser continuation
  remain unverified. Next device action: trust the developer under Settings →
  General → VPN & Device Management, open KitchenOS, then say “Siri, ask KitchenOS”
  and request “Show tomorrow's meal plan.”
