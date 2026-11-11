# Phone surfaces and connectivity

Date: 2026-09-24

Status: Approved architectural direction, written specification awaiting user review.
Implementation and implementation planning have not begun for this design.

## Purpose and scope

Make the native iPhone app the primary place to answer “what do I need to do
in the kitchen now?” and complete short contextual actions. Access should work
at home and away without routinely editing a server URL. Loss of connectivity
should leave useful, honestly labeled information available without creating
another editable source of truth.

The approved division of responsibility is:

| Surface | Responsibility |
| --- | --- |
| iPhone app | Today, small planning edits, shopping, capture, recipe discovery and cooking |
| Siri / App Intents | Quick and hands-free actions using the same connection and domain rules |
| Mac / iPad | Full weekly planning, larger edits and maintenance |
| Obsidian | Durable recipe knowledge, authored notes and linked reference material |
| Advanced web surfaces | Dense or infrequent tools, reachable from relevant app contexts |

This is one architectural contract with staged delivery. It does not redesign
every destination or specify speculative Shop/Cook/Capture features. Those
later improvements depend on observed use. Flask, SQLite, the vault and the
existing extraction/AI stack remain in place.

## Current integration points

These observations refer to the current working tree, including existing
calendar work; they do not claim that all of that work has been committed.

- `KitchenOSSiri/Sources/KitchenOSSiriApp.swift` supplies iOS tabs for Assistant,
  Plan, Cook, Search and Settings. The Mac uses `Shell/AppShell.swift`.
- `KitchenOSKit/Sources/KitchenOSKit/KitchenOSConfig.swift` resolves a single
  saved `kitchenos.baseURL`, defaulting on iOS to `http://100.111.6.10:5001` and
  on macOS to the local server. Credentials come from Keychain.
- `KitchenOSClient.swift` binds a client to one configuration and uses a
  12-second request timeout. It collapses transport errors into `unreachable`,
  which is insufficient to distinguish cancellation from connectivity failure.
- Screens, intents, recipe entity queries, the indexer and the assistant contain
  independent client construction. `MealPlan/PlanningCalendarWebView.swift`
  also resolves configuration independently, with origin-scoped authorization
  supplied by `PlanningWebPolicy`.
- `api_server.py` exposes an unauthenticated `/health` returning
  `{"status": "ok"}`. This checks liveness, not authorization or data readiness.
- `lib/kitchen_today.py` already assembles useful web-home context. Existing
  plan, ledger, task, inventory, shopping and recipe services remain the source
  of domain behavior for native screens.

## Phone navigation and contextual behavior

The iPhone has four primary destinations, with Today selected on ordinary
launch. Explicit recipe links and App Intent navigation keep their destinations.

| Destination | Initial responsibility |
| --- | --- |
| Today | Current/next planned meal, prep, expiring food and immediate actions |
| Plan | Current week overview and focused edits to a meal or cook |
| Shop | Shopping list, inventory lookup and receipt capture |
| Cook | Recipe search, recent recipes, cooking view and pantry-based suggestions |

Settings and connection diagnostics are secondary destinations reachable from
the main navigation. Assistant and advanced tools remain accessible through
relevant contexts rather than taking additional primary phone tabs. Capture is
an action within the appropriate destination, not a fifth destination.

Today shows today's planned meals and identifies the current/next one only
when schedule data supports that distinction. With no reliable time, show
named meal slots rather than guessing what the user should be eating. With no
plan, offer planning or pantry-based discovery. Prep and expiring-food cards
link directly to the relevant task or food context. Missing data is an empty
or unavailable section, never a fabricated zero or a failure of the whole screen.

Plan keeps week identifiers as internal keys and shows human-readable date
ranges. Small edits use the domain API appropriate to the selected item:
cook and bundle changes go through the ledger API, preserving scales,
placements and bundle membership. A scale-less legacy plan PUT cannot replace
ledger-authored content. Mac/iPad retain access to full planning and maintenance;
the phone navigation change does not require rebuilding those surfaces.

Cook distinguishes recently opened recipes from recently added recipes.
Recipe filename/name remains identity; `short_title`/`display_name` remains
presentation only. Recipe knowledge stays in the vault, inventory/purchases/
trips stay in SQLite, and derived nutrition remains derived by existing rules.

## Shared connection architecture

`ConnectionResolver` belongs in `KitchenOSKit`, alongside the networking code,
so it can be used without SwiftUI or a foreground app. Its responsibilities are
endpoint selection, bounded liveness checks, invalidation and observable
connection state. It does not execute domain writes or own cached meal data.

A shared client provider owns resolver access, credentials and transport
construction. App screens receive it through dependency injection; App Intents,
entity queries, indexing and assistant tools use the same provider interface.
“Shared” means a single policy and configuration source, with one coordinated
resolver per process; it does not assume Siri and the app share process memory.
An intent invocation must work without first opening the app.

### Endpoint configuration

- Preferred phone/iPad endpoint: `http://Chases-Mac-mini.local:5001`.
- Remote fallback: `http://chases-mac-mini.taila69703.ts.net:5001`, the hostname
  already documented in `docs/API.md`.
- The Mac app keeps its same-machine local-server behavior through the shared
  provider; this design does not route local Mac operations through a VPN.
- Automatic selection is the normal phone mode. Keep an explicit advanced
  single-endpoint override for diagnostics and existing custom deployments.
  An override does not silently fall back to an unrelated default server.
- Migration maps an absent setting or a known built-in endpoint (the current
  iOS IP or either approved hostname) to automatic mode. Preserve other saved
  URLs as explicit overrides, visible in Settings. Invalid settings produce
  a configuration error instead of silently changing servers.
- Local and remote endpoints in an automatic profile represent the same server
  and data. Credentials and caches belong to that logical profile, not its URL.

### Resolution and invalidation

1. At cold start, after a network-path change, and after foregrounding, invalidate
   the previous reachability decision. An intent resolves on invocation when
   it has no valid in-process decision. Explicit connection testing also forces
   resolution.
2. Probe local `/health` first when a local network path is available. A network
   path is a hint; Wi-Fi availability alone does not prove the Mac is reachable.
   Skip the local probe on a known cellular-only path.
3. If local transport fails, probe the Tailscale endpoint. Accept a successful
   HTTP response with the expected health payload, not an arbitrary captive
   portal page. An HTTP error or malformed health payload is a service/config
   error and is reported as such rather than disguised as an offline state.
4. Use separate bounded probes: at most 2 seconds for local and 4 seconds for
   remote, including connection and response. These are initial design budgets
   to validate on device, not measured latency claims. Do not wait indefinitely
   for a VPN to start. A later network change or explicit retry can try again.
5. Reuse the selected endpoint while its decision remains valid. Coalesce
   concurrent resolution attempts and discard results from an older network
   generation so a late probe cannot replace a newer selection.

After a genuine transport failure on an established endpoint, a recovery
resolution excludes that failed endpoint for that recovery attempt and checks
the remaining candidate. Subsequent network changes or explicit connection
tests resume normal local-first selection. In override mode there is no second
candidate. Failed resolution yields an actionable state and cached reads where
available, not an endless sequence of probes.

### Request safety and error classification

Endpoint selection happens before dispatch. Once a request is dispatched it is
bound to that endpoint; network changes do not move an in-flight operation.

| Result | Client behavior |
| --- | --- |
| Verified read-only operation loses connectivity | Re-resolve and retry that operation at most once; a second failure ends the attempt |
| HTTP 401/403 | Show credential/authorization failure; no failover or replay |
| Other HTTP errors, invalid payload or decoding error | Report service/data error; no connectivity retry |
| User cancellation | Stop; no retry and no “server offline” diagnosis |
| Write fails after dispatch without a definitive outcome | Mark outcome unknown; never replay automatically |
| No endpoint before dispatch | Report that the action was not sent; a later user action can try again |

Retry eligibility is an explicit operation contract, not “every GET is safe.”
Existing GET routes include regeneration and creation behavior; a POST can also
be a read-only search. Audit the methods used by this flow and allow retry only
for verified read-only operations. Unclassified operations receive no automatic
retry. In this first design all dispatched writes receive zero automatic retries,
even if a particular endpoint may later support idempotency.

For an unknown write outcome, offer a read refresh to inspect server state and
explain that the change may have completed. Do not report an unconfirmed save
as success, automatically resend it, or repeat the entire read-modify-write
workflow. A malformed success acknowledgement or server error after a possible
commit also leaves the outcome unknown unless the endpoint contract proves
otherwise; error classification alone does not prove a write was rolled back.
Existing Siri confirmation gates remain. No idempotency subsystem or
generic queued-write mechanism is introduced here.

### Embedded web views and authentication

Embedded web views obtain their initial endpoint and credentials from the same
provider. They retain the existing same-origin credential restrictions and
external-link handling. Tokens remain in Keychain and authorization headers;
they are excluded from URLs, cache payloads and diagnostics. Cross-origin
redirects must not carry authorization to a different host.

Do not transparently switch the origin of a live interactive web view after
network loss: it may hold unsaved edits or an uncertain write. Show connection
state and offer an explicit reload after the user has handled unsaved changes.
That reload rebuilds the view with the newly resolved origin. Never replay form
submissions or JavaScript mutations. Native read retry policy does not become a
blanket web-navigation retry policy.

Phone LAN requests still originate off-host and obey existing bearer-token
requirements. This design preserves those boundaries and does not claim to fix
all existing API authentication gaps. Any newly added read endpoint follows the
repository's authentication policy. The service remains private to the LAN and
tailnet; public hosting and public port forwarding are outside this scope.

### Tailscale and diagnostics

Tailscale VPN On Demand is the remote safety net, configured in Tailscale rather
than by a custom KitchenOS VPN integration. Enable connection on cellular and
Wi-Fi so fallback remains possible even when the phone is on home Wi-Fi but
local discovery fails. Local-first routing is still decided by the resolver.
On Demand does not guarantee instantaneous tunnel readiness or a running Mac.
See [Tailscale's VPN On Demand documentation](https://tailscale.com/docs/features/client/ios-vpn-on-demand).

Diagnostics show automatic/override mode, selected endpoint and route, last
successful contact, most recent probe results and classified failure. Separate
server liveness from authorization success. Provide a “Test connection” action
through the real resolver and guidance for local-network permission, server
availability, credentials and Tailscale as appropriate. Do not assert that the
VPN is off solely because its endpoint could not be reached. Review the iOS
local-network permission description and transport configuration during delivery.

## Read caching and freshness

The first offline capability is a disposable, read-only snapshot cache containing:

- Today data for its dated context.
- The current week's plan.
- The current week's shopping list.
- The 20 most recently opened recipes, including ingredients and instructions;
  images are optional and cannot gate offline reading.

Persist only successfully decoded server data, with profile identity, schema
version, fetch time and date/week/recipe key. Record server-provided generation
or revision metadata when available; a fetch timestamp alone is not a claim
that every underlying source changed at that time. Do not cache credentials.
Replace each snapshot atomically, discard incompatible/corrupt entries, and
evict obsolete week/day entries when their current replacements arrive.

On entry, display a matching cached snapshot immediately with its last-updated
time and refresh online. Until refresh succeeds, identify it as cached/stale;
if transport is unavailable, identify it as offline. On other failures, retain
the snapshot with the actual service/auth error rather than calling it offline.
Independently loaded sections retain their own freshness. Empty and unavailable
are distinct states. With no matching cache, show an explicit unavailable state.

Use the server's kitchen date/time zone for Today and week context, and retain
that context in the cache. A previous day's Today or previous week's plan/list
may remain available with its actual label but must not appear to be current.
Foregrounding across a day/week boundary requests the new context.

Local/Tailscale switching within a profile shares the cache. A change of server
profile or credentials invalidates it so data cannot cross configuration
boundaries. A confirmed mutation marks affected snapshots stale and refreshes
them from the server; an uncertain mutation also marks them stale and prompts
read reconciliation. Do not manufacture a confirmed server snapshot from a
pending local write.

Offline mutation controls are unavailable with a clear reason. Shopping
checkbox changes, plan edits, task completion, cooking/inventory mutations and
receipt submission do not queue or silently persist as pending work. Reading a
cached shopping list is supported; checking purchases offline is not part of
this phase. SQLite remains authoritative for its domain records, and recipe and
plan notes retain their existing server-side roles. The device cache is neither
an editable inventory nor a synchronization database.

## Backend composition and latency

Reuse existing domain logic for Today, plan, prep, expiry, shopping and recipes.
Where measured phone request fan-out warrants it, add a narrowly scoped JSON
read endpoint that composes those results. This spec does not require a new
endpoint merely to introduce a new screen.

Any such read returns stable identifiers, dated context, available freshness
metadata and per-section availability. It must not mutate inventory, regenerate
a shopping list, create a plan as a side effect, or start LLM work. Existing
helpers with those side effects require a read-only path before reuse. Read
cached prep or use an immediate deterministic fallback with its origin visible;
do not synchronously extract tasks to satisfy Today.

No initial screen or page render waits on an LLM. Preserve `lib/llm_gate.py`
budget and refusal rules, and do not cache a request-budget fallback as a
durable AI answer. Explicit user-requested AI work remains a separate action.
Share expensive inventory/index reads within a composition, and degrade a
failed section independently, following the existing web-home approach.

Existing domain invariants remain binding: generated views read committed DB
rows, pantry staples are real inventory, inventory consumption follows existing
confirmation rules, and meal macros are derived through the shared eligibility
gate. The native surface does not duplicate these calculations.

## Delivery sequence

1. **Connection resolver:** endpoint profiles, migration, bounded probes,
   network/foreground invalidation and explicit retry classification.
2. **Centralized client creation:** adopt the provider across screens, intents,
   entity queries, indexing, assistant tools and embedded web views.
3. **Connection diagnostics:** expose real resolver state and recovery actions;
   document and verify device permissions and VPN On Demand setup.
4. **Today and focused iPhone navigation:** ship the four destinations and reuse
   existing workflows; add read composition only where latency justifies it.
5. **Read caching and stale-state UI:** persist the defined snapshots, enforce
   date/profile boundaries and keep offline writes unavailable.
6. **Shop/Cook/Capture improvements:** use observed friction to choose subsequent
   bounded changes. This stage does not pre-approve an unspecified feature set.

Each stage must remain usable and preserve the existing Mac/iPad and Siri
workflows. Record concrete implementation tasks only after written-spec review.

## Acceptance and verification strategy

These are requirements for later implementation, not claims of tests run now.

- Resolver tests cover local success, local failure/remote success, both down,
  cellular-only paths, foreground/network invalidation, cancellation, bounded
  probes, concurrent callers and late results from obsolete network generations.
- Client tests use injected transport: safe reads retry at most once; HTTP and
  decoding errors do not fail over; dispatched writes, including a server commit
  followed by a lost response, are sent exactly once. Audit redirects and other
  transport behavior for unintended mutation replay or credential forwarding.
- Integration checks cover screens and cold-start Siri, configuration migration,
  credential errors, explicit overrides and web-view reloads with unsaved edits.
  No production consumer independently chooses its own default endpoint.
- Cache tests cover cold offline launch, valid offline snapshots, corruption,
  schema changes, recipe eviction, date/week rollover, profile changes, partial
  refresh and confirmed/uncertain writes. Stale values never appear live.
- Backend checks verify new composition paths reuse domain logic, perform no
  domain writes and start no LLM work. Missing prep or a failing card must not
  block the rest of Today.
- Device checks exercise home Wi-Fi, cellular, another Wi-Fi network, return
  home, foregrounding, denied local-network permission, VPN unavailable and the
  server asleep/down. Validate the probe budgets and record observed fallback
  latency; simulated transport alone cannot prove VPN or permission behavior.
- Phone checks confirm direct access to the current meal, prep, list, receipt
  capture and recipe cooking view, with explicit freshness and truthful errors.
  Mac/iPad full planning and existing Siri confirmations remain functional.

## Review boundary

The approved direction has been written down and self-reviewed for missing
content, internal contradictions, scope and ambiguous retry/cache behavior.
Review this written specification before creating an implementation plan.
Approval of this document permits planning; it does not by itself begin
implementation. No product code, device settings or services are changed by
this documentation task.
