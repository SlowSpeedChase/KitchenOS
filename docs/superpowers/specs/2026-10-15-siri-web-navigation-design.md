# Siri opens recipes and meal-plan days on the web

**Status:** Proposed design for the user's requested plan. No implementation, installation, or service changes are authorized by this document alone.

## Intent

The user wants Siri to open the specific saved recipe or meal-plan day relevant to a request in KitchenOS's web app. Opening the dashboard does not satisfy this. The destination is a browser page, not a native recipe sheet or an Obsidian note.

Examples:

- “Ask KitchenOS: find a chicken recipe and show it to me” finds a real saved recipe, then opens that recipe's web page.
- “Ask KitchenOS: show Friday's meals” opens this week's Friday with its meal content visible.
- “Ask KitchenOS: open tomorrow's meal plan” resolves tomorrow on the invoking device, including a change of ISO week, and opens that date.
- “What's planned for Friday?” still receives a spoken answer under the proposed trigger policy.

## User decisions and proposed defaults

**User decisions:** plan the feature; target the web app; open a specific recipe or meal-plan day rather than its home page.

**Proposed defaults, not additional user decisions:**

- Navigate for an explicit “open” or “show” request. An ordinary question may mention that a page is available but must not unexpectedly switch apps. The user was offered an optional choice about automatic opening; no answer was received before drafting.
- Use the device's default browser and the existing KitchenOS connection configuration. Do not hardcode Safari or introduce another server-address constant.
- Land meal-plan requests in Calendar view, selecting the requested civil date and scrolling to its meals, not merely to its empty timeline. Keep Grid view and week-only links working.
- Browser access established by Siri is for viewing, lasts 15 minutes, and is visibly labeled. Editing through a new full browser login is outside this feature.
- Only the Siri voice surface gains the navigation tool in this version. Native chat and Spotlight's existing native recipe opening retain their current behavior.

## Observed starting point

Inspection on 2026-10-15 found:

- AskKitchenOSIntent creates a fresh MealPlanAssistant per invocation and returns spoken dialogs. Its five tools do not navigate.
- OpenRecipeIntent opens RecipeRouter's native sheet. RecipeEntityQuery's string matching searches ingredient text, so it is not a reliable recipe-name resolver.
- /recipe/<name> already exists. /meal-planner accepts week and view but does not consume a date. The current uncommitted calendar code initializes its mobile selection to Monday.
- Safari does not inherit KitchenOSKit's Keychain bearer header or the embedded planning WebView's authorization script. A live unauthenticated GET to the remote /api/recipes returned HTTP 401. A successful HTML-shell response alone does not prove a usable recipe or planner page.
- docs/API.md still says the token is unset; that assertion does not match the observed remote response. Correct it during implementation without exposing credentials.
- The checkout is codex/calendar-meal-planning and contains substantial unrelated tracked edits and untracked calendar files. The design uses that working-tree baseline, not a pristine HEAD checkout.

## Destination contract

Represent navigation as a typed recipe identity or meal-plan civil date. Never take an arbitrary URL, hostname, path, or JavaScript from the model.

| Destination | Canonical browser path |
| --- | --- |
| Recipe | /recipe/<canonical filename stem encoded as one path segment> |
| Meal-plan day | /meal-planner?week=2026-W42&date=2026-10-16&view=calendar |

Recipe names remain identity; short_title/display_name may help find a candidate but must resolve to exactly one canonical name. Match an exact canonical name first, then a unique case-insensitive name/display-name match. Reject unknown and ambiguous matches without opening a guessed page. Confirm the recipe still exists before minting the handoff.

Resolve today/tomorrow and weekdays deterministically with an injected clock and the invoking device's local calendar. A bare weekday means that weekday in the current ISO week, matching the current meal-plan behavior. Explicit “next week” means the following ISO week. Ambiguous wording such as “next Friday” must clarify the intended date rather than silently pick a convention. Exact dates are Gregorian YYYY-MM-DD civil dates, not instants; validate leap days and impossible dates. Speak the resolved date when opening a day. The selected date is authoritative: derive its ISO week, including ISO-year boundaries.

The web planner accepts a valid date with or without week; a conflicting week is replaced with the date's actual week. Invalid dates produce a visible explanation and preserve ordinary week navigation, never an unexplained Monday landing. Do not use new Date('YYYY-MM-DD') or local-midnight.toISOString() to recover a local date.

After asynchronous data arrives, mobile selects the requested day, desktop highlights it, and both expose the day's heading and meals visibly. Focus an accessible heading without activating an editor. Selection survives data refresh, view switches, and reload. Week navigation preserves the selected weekday in the new week and updates both week and date. Empty days show “No meals planned” for the requested date. Navigating never schedules, moves, saves, or cooks anything.

## Siri handoff

Add a voice-only navigation tool that resolves a real target and stores one typed destination for the current invocation. The model can choose a recipe from the same invocation's search results when the user asks it to find and show one. For a named recipe with multiple candidates, ask which one. Do not persist a global “last recipe.” A later Siri invocation saying only “open that” must ask for the recipe or day because the current implementation has no cross-invocation memory.

Tools perform lookups and record intent; they do not open UI. Clear pending navigation at the start of each reply and after consumption. Conflicting requested destinations produce a clarification instead of whichever tool happened to run last.

AskKitchenOSIntent returns a custom foreground OpenKitchenOSWebIntent only for a resolved open/show request. Ordinary answers and errors remain dialog-only. Keep native confirmation before a meal-plan write. If one request asks to add and then show, a successful confirmed write may be followed by navigation; decline/failure must not claim the write happened or automatically open an unrelated page.

The foreground intent obtains the short-lived browser handoff and opens it with UIApplication.open on iOS or NSWorkspace.open on macOS. Validate the destination and current configuration again. Report failure if the browser opener declines; successful URL dispatch means “opened in your browser,” not “the page loaded successfully.”

Use the installed SDK's type-erased result(opensIntent:dialog:) overload for conditional handoff. Do not assume OpenURLIntent is a generic opener for a private HTTP site: Apple documents it in terms of universal links and this app has no associated-domain setup. Verify the custom foreground transition on a physical device before release.

## Browser viewing access

The observed 401 makes this part necessary for remote use, not optional polish. Reuse the native API credential solely in the request header. Do not put the long-lived bearer in URLs, HTML, browser storage, or logs, and do not weaken existing route authorization.

1. POST /api/browser-handoffs uses existing native authorization and accepts only a typed recipe/day target. The server validates the target and binds it to a 32-byte random one-use code, the request's validated origin, and the current API-token fingerprint. Codes expire after 60 seconds.
2. The response contains a relative /browser/open#code=... path. The native client combines it with its validated configured origin and rejects any cross-origin redirect. No other origin is inferred from a model answer.
3. The minimal first-party landing page immediately removes the fragment from history, then POSTs the code as JSON to /api/browser-handoffs/exchange on the same origin.
4. Exchange atomically consumes the code, returns the stored relative destination, and sets a host-only HttpOnly SameSite=Strict cookie. The server authorization expires absolutely after 15 minutes; retain the cookie for 24 hours so a reload after grant expiry still identifies a restricted viewing session instead of falling into anonymous/loopback behavior. The retained cookie grants no access after minute 15. Use Secure on HTTPS. The existing private-tailnet HTTP setup requires a non-Secure cookie; do not silently add HTTPS infrastructure or pretend Secure cookies work over HTTP. No public exposure is added.
5. The landing page uses location.replace for the stored destination. Bootstrap responses and private data use no-store; the landing page uses no-referrer and no third-party resources. Codes/session IDs are never logged.

Use bounded lock-protected process-memory stores containing hashes of codes/session IDs, not new DB domain records. Cap each store at 1,024 live entries, prune expirations, and reject new issuance with 429 when full. Restarts, token rotation, expiry, replay, and origin changes fail closed. This deliberately matches the current single-process server; a future multi-worker deployment needs shared session storage before reuse.

The grant authorizes GET/HEAD only for the existing recipe/planner data endpoints listed in the implementation plan. A global request guard restricts by Flask endpoint identity, not URL prefix or HTTP verb alone: existing GET routes such as /refresh, /refresh-nutrition, and /reprocess mutate state and must be denied too. It cannot mint more handoffs. A request bearing the viewing cookie without a valid explicit API bearer cannot invoke any endpoint outside the explicit page/static/data allowlist or an unsafe method, including legacy ungated mutations and loopback requests. A valid explicit native bearer retains its existing behavior. A presented but expired/invalid cookie does not fall through to a permissive local exemption. The exchange endpoint authenticates its own one-use code, verifies same-origin JSON requests, and is the sole unsafe-method exception for cookie-only requests. An expired/invalid grant may still load only the bootstrap, its static assets, and an explanatory expired page shell; it may not load private data. This restriction is for the marked viewing session and does not claim to repair unrelated pre-existing anonymous access if a user clears its marker.

The recipe and planner shells derive viewing mode from the server, label it “Viewing from Siri,” and keep browsing, scaling for display, day/week changes, filters, and previews usable. They disable persistence controls and drag/save initialization, including schedule/all-day classification. This is an explicit viewing session, not a claim that pre-existing unauthenticated web routes are secured globally. On session expiry, stop refresh loops and show “This view expired. Ask KitchenOS to open it again.” No refresh loop repeatedly retries unauthorized requests.

## Acceptance and release

- A physical Siri request opens the correct existing recipe in the default browser, with its data loaded through the viewing session.
- Tomorrow across Sunday/year/DST boundaries and a named weekday open the correct date. At phone and desktop sizes the date and its meals are actually visible.
- Unknown/ambiguous recipes, impossible dates, missing context, expired/replayed handoffs, and unavailable server/browser paths produce clear outcomes without guessing or writing.
- Unit/browser tests run with isolated data and no live LLM. Browser auth tests must exercise a remote address, not accidentally pass through the loopback exemption.
- Preserve recipe identity, ledger/card guards, current uncommitted calendar work, and existing Siri write confirmation. No recipe, inventory, or plan mutation is performed merely to verify navigation.
- Update native app and API/template/static assets together; restart the API only at deployment. Physical-device install, unlock behavior, Tailscale connectivity, and browser rendering are release checks, not assertions inferred from a compiler pass.

## Explicit non-goals

No Obsidian navigation, dashboard fallback, autonomous opening for ordinary answers, general vault search, full browser editing/login system, cross-invocation Siri memory, new native planning UI, public hosting, or reimplementation of the separately planned connection-profile system.

## Evidence

- Local source: KitchenOSKit/Sources/KitchenOSKit/Intents/AskKitchenOSIntent.swift; AI/MealPlanAssistant.swift; RecipeEntity.swift; KitchenOSConfig.swift; templates/meal_planner.html; templates/recipe_detail.html; static/planning-calendar.js; api_server.py require_token.
- [Apple: OpenURLIntent](https://developer.apple.com/documentation/appintents/openurlintent), [OpensIntent](https://developer.apple.com/documentation/appintents/opensintent), [UIApplication URL opening](https://developer.apple.com/documentation/uikit/uiapplication/open(_:options:completionhandler:)), [NSWorkspace](https://developer.apple.com/documentation/appkit/nsworkspace).
- The installed macOS 26.5 SDK gives result(opensIntent:dialog:) and result(dialog:) the same concrete container, supporting the mixed return branches on the app's OS 26 floor. Device behavior still requires the release check above.

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
