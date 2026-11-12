# Weekly cooking packets in KitchenOS

Status: approved design, September 25, 2026. Implementation has not started.

## Intended outcome

Chase wants the successful four-page "Flavor-Forward Instant Pot Meals" packet to become a reusable KitchenOS workflow. A packet should be generated from the week's real cook cards, recipes, inventory and cooking schedule; remain useful on a phone while shopping and cooking; preserve reviewed edits; and print cleanly from the website. The existing compact weekly printout remains available as a separate view.

Success means a week with freezer-bound cooks can produce a packet that includes the production schedule, ingredients to pull by storage location, retailer-specific buying suggestions, shared preparation, phased recipe cards, freezing and reheating directions, and a paper layout comparable to the reference PDF. The same saved packet must drive the mobile and print views.

## Approved workflow

Extend **Plan your week** from three actions to four:

1. Fill the week.
2. Review nutrition.
3. Build cooking packet.
4. Print the existing weekly overview.

"Build cooking packet" opens `/cooking-packet?week=YYYY-Www`. The route renders a fast page shell. If no packet exists, the client starts the same background refresh used by the button and shows progress until the first draft is saved; otherwise it loads the saved packet. It has four primary actions:

- **Refresh from week** rebuilds generated content from current cooks, recipes, inventory and schedules, then reapplies saved edits.
- **Refresh store picks** looks up H-E-B and Costco products on demand and saves a dated snapshot.
- **Print cooking packet** opens `/print/cooking-packet?week=YYYY-Www`, which renders only saved data and performs no network or model work.
- **Mark reviewed** records that the current revision is ready to use.

Opening or printing a packet never invokes an LLM or retailer request. Expensive or network-dependent work happens only through an explicit refresh action. The page is a required-query-parameter route, so register it and its print view in `tests/test_web_dashboard.py` as non-bookmarkable rather than adding a broken generic bookmark.

## Mobile product surface

The website is the primary packet surface. It must work through the existing authenticated LAN/Tailscale access and fit a phone without horizontal scrolling. Show these collapsible sections in order:

1. Schedule
2. Pull from home
3. Buy at H-E-B
4. Consider at Costco
5. Shared prep
6. Recipe cards
7. Freeze and reheat

Use large touch targets, visible save state, ordinary form controls, and text labels in addition to color. Checkboxes save immediately and stay checked after reload. Text, quantity, date, time and duration edits use an explicit Save action per card or section so a partially typed change is not persisted accidentally. Provide keyboard focus states, semantic headings, field labels, status messages through an `aria-live` region, and a reduced-motion path.

Schedule edits have two ownership paths. Changing a cook's date, meal, start time or duration uses the existing serving-ledger schedule API and regenerates the affected week view; the packet must not create a second cook schedule. Packet-only preparation rows, wording and notes are stored as packet edits. When either source changes, the visible schedule explains whether the row comes from the cook schedule or the packet.

## Packet persistence

Add a `cooking_packets` table to `data/kitchenos.db`, keeping the database as the single source of truth for saved packets. One row exists per ISO week and contains:

- `week` as the primary key
- `generated_json`, the latest source-derived draft
- `edits_json`, sparse user changes keyed by stable item and field identifiers
- `store_snapshot_json`, the last retailer lookup result
- `status`, either `draft` or `reviewed`
- `generated_at`, `store_refreshed_at`, `reviewed_at` and `updated_at`
- a monotonic `revision`

Add a `retailer_preferences` table keyed by retailer. It stores the approved location ID, display name, address and preference rank. Seed it with H-E-B Hancock Center #425 and Costco Austin #681. The H-E-B-brand cashback preference and Costco bulk rule are named policy values read by the packet builder, not inferred from past purchases. Store selection editing is outside this first version, but the page displays the locations used so the lookup is never ambiguous.

The JSON documents are versioned and validated before writing. Set size and collection bounds so a malformed retailer response or client edit cannot create an unbounded database row. A write replaces the affected document transactionally. Renderers read the committed row back after every write.

Generated items carry stable identifiers based on source identity rather than display text. Cook-backed rows use cook ID; recipe cards use recipe identity; recipe phase rows include recipe identity plus the original instruction ordinal; inventory pulls include the credited inventory row IDs and normalized ingredient identity. Generated shared-prep rows hash their sorted source identifiers. Check states and text overrides attach to these identifiers.

`Refresh from week` computes a new `generated_json` and retains `edits_json`. Edits whose source identifiers still exist are reapplied. Edits for removed sources move to a visible "Needs review" list and remain recoverable until the user deletes them. Marking reviewed applies to one revision; a later source or store refresh returns the packet to draft.

This table stores a weekly presentation snapshot and edits. It does not duplicate inventory quantities, recipe bodies, cook schedules, serving placements or shopping purchases.

## Draft assembly

Create a focused packet builder, separate from HTML rendering. Its inputs are the ISO week, ledger cooks, cook schedules, recipe documents, pantry rows, storage-location rules and the optional saved retailer snapshot. Its output is the versioned generated packet document.

Unlike `lib.print_week`, the cooking packet starts from **cooks**, including unassigned yield intended for the freezer. It must not require serving placements. This is what makes the current four freezer cooks appear even though their produced servings are not assigned to meals.

### Production schedule

Use existing `cook_schedule` rows for cooking sessions. Derive prep and storage tasks from recipe phases and shared-prep results. The schedule may include lead-in dates before the ISO week's Monday, as the reference packet does for bean soaking and cooking. The packet's human-readable date range spans the earliest scheduled packet task through the week's Sunday; the ISO week remains the storage and URL key.

Tasks include durations with provenance: scheduled cook duration, recipe timing, explicit user value or clearly labeled estimate. Add cooling, freezing, unmolding and bagging only when the recipe or saved packet guidance calls for them. Never silently move a scheduled cook to make a prettier production plan.

### Pull from home

Reuse the pantry matcher and unit-compatibility rules used by the shopping workflow. Build explicit match decisions without mutating inventory. Group credited ingredients by their recorded storage location, including custom locations. Every line shows required quantity, credited on-hand quantity and the source location. Uncertain locations render as uncertain and are not promoted to a confident freezer, refrigerator or pantry label.

Packet generation does not decrement inventory. Shopping-list confirmation and cooking remain the existing authorized spend paths.

### Buy list

Aggregate only the uncovered amount after pantry matching. Preserve the existing shopping generator's recipe scaling and unit rules. Group products into H-E-B and Costco recommendations without changing the canonical ingredient requirement.

Retailer suggestions follow this policy:

1. Prefer an appropriate H-E-B-owned brand when available because Chase earns money back on those purchases.
2. Treat Costco as a candidate when the packet uses a meaningful part of the package or the remainder is reasonably shelf-stable or freezer-friendly.
3. Prefer H-E-B for ordinary quantities when a Costco package is likely to create waste.
4. Compare price only when both current prices and comparable package quantities are present.
5. Keep "where to buy" as a recommendation. A receipt remains the purchase record.

Each recommendation names the requested ingredient, product, brand, package size, price, normalized unit price when valid, source URL, lookup time and availability confidence. It also states why the retailer was preferred. Unknown prices and unavailable comparisons remain explicit.

## Store lookup

Use store adapters behind one packet-facing interface so retailer parsing and matching can change independently.

The configured stores are:

- H-E-B Hancock Center, corporate store #425, 1000 East 41st Street, Austin, Texas 78751.
- Costco Austin warehouse #681, 10401 Research Boulevard, Austin, Texas 78759.

The H-E-B adapter searches the selected store's public online catalog and recognizes H-E-B-owned brands separately from national brands. The Costco adapter uses official public product and warehouse information. Neither adapter receives credentials or attempts checkout.

"Refresh store picks" runs both lookups as one bounded background operation and reports per-retailer progress. Use strict timeouts and bounded result counts. Normalize product candidates, then match them to uncovered ingredients with deterministic ingredient and package rules. Store raw evidence needed to explain the selected candidate, but do not store arbitrary full web pages.

If one retailer fails, save the successful retailer's results and retain the previous snapshot for the failed one with a stale warning. A product absent from H-E-B's online catalog is "not found online," never "out of stock," because H-E-B documents that in-store products may be absent from the app. Costco products without verified warehouse pricing say "check warehouse price." A refresh with no trustworthy candidate leaves the ingredient unsourced instead of inventing a product or price.

## Recipe phases

Future extracted and user-authored recipes use optional level-three headings inside the existing `## Instructions` body section:

- `### Prep or Flavor Base`
- `### Cook`
- `### Finish and Taste`
- `### Freeze and Store`
- `### Reheat`

The body structure avoids a second recipe representation and requires no recipe frontmatter key. Update extraction and authoring prompts to prefer these headings when the source supports them. Do not fabricate freezing or reheating claims when the source provides none.

Extend the recipe parser to return phase information while preserving its existing flat `instructions` result for every current consumer. Parsed instruction ordinals remain globally stable across headings so task IDs do not collide. Future recipes receive phase headings on first creation. Existing recipes are not rewritten automatically.

When a legacy recipe lacks headings, an explicit packet generation or refresh classifies its steps into the five phases through the existing LLM gate and its bounded timeout. If inference is unavailable, a conservative keyword classifier creates a review-marked draft and leaves uncertain steps in an unsorted Instructions group. This classification is packet draft data, not a recipe edit. A corrected packet phase is saved as an override. Repeated rendering uses the saved result and never calls a model. A later, separate user action may apply reviewed headings to the recipe, but that action is outside this feature.

Missing phases stay absent. The UI must not fill empty "Freeze" or "Reheat" cards with generic advice that could be unsafe for the food.

## Freezer-bag assembly is the primary workflow

The packet is first a freezer-prep guide for meals that will later go into the Instant Pot. A recipe card must never present one undifferentiated ingredient list that implies every ingredient belongs in the freezer bag. Every generated ingredient row has exactly one packet-only preparation stage:

- `bag_now`: put into the labeled freezer bag during this prep session
- `prep_then_bag`: complete the named preparation first, then add it to the freezer bag
- `freeze_separately`: prepare now and freeze in a separate labeled container
- `add_at_cook_time`: keep out of the bag and add when pressure cooking starts
- `finish_after_cooking`: keep out of the bag and add after pressure release
- `serve_separately`: keep out of the bag and serve alongside or as a garnish
- `needs_review`: keep out of the bag until its destination is confirmed

These stages are presentation data in the saved packet, keyed by the ingredient's stable source ID. They do not rewrite recipe ingredients. Source instructions or reviewed packet edits may establish a stage. Conservative deterministic rules may identify explicit phrases such as "reserve," "add after pressure release," or "serve with." An explicit background refresh may ask the bounded classifier for candidates, but deterministic validation accepts only known ingredient IDs and the closed stage vocabulary. When evidence is incomplete or contradictory, use `needs_review`; never guess that an ingredient belongs in the bag.

Each recipe leads with a **Freezer prep** block. It shows **Put in the freezer bag now** first, then **Prep before bagging** when present. A visually distinct **Keep out of the freezer bag** block separates add-at-cook-time, finish-after-cooking, serve-separately, freeze-separately and needs-review rows. Cook-day directions follow those blocks. Print and mobile views must state that an ingredient appears in one destination only and must not duplicate an ingredient across bag and keep-out lists.

The production schedule may include assembling and labeling each bag, but cook-day-only ingredients are not pull/prep tasks for the freezer session unless they require a separate preparation now. Shopping requirements still include every ingredient needed for the complete meal.

## Shared preparation

Shared prep reduces duplicate work without inventing cooking instructions. Create a shared step only when all contributing recipes agree on:

- normalized ingredient identity
- compatible units and summed quantity
- preparation outcome
- cooking method and parameters, when cooking is involved
- storage treatment before the ingredient enters each recipe

Never merge raw animal-protein handling across recipes. Do not merge pressure-cooking steps whose time, release method or liquid ratio differs. Acid-sensitive dry-bean steps remain before acidic recipe ingredients. If compatibility is uncertain, show separate steps.

The explicit packet refresh asks the same bounded classifier to propose candidates from phase text, then a deterministic validator decides whether they can be combined. If inference is unavailable, exact normalized ingredient-and-method matches remain eligible; ambiguous candidates stay separate. Every shared step links back to the recipes and amounts it serves. Editing or deleting a shared row affects the packet only and does not rewrite recipe instructions.

## Printing

The print view is HTML with print CSS and the existing web print action, allowing printing or PDF export from desktop and mobile browsers. It reads only the saved packet revision.

Reverse-engineer these characteristics from the reference PDF:

- US Letter pages with restrained navy, teal and gold accents
- a cover section with title, date range, production schedule, store picks and storage-location pull lists
- stage pages for shared preparation and recipe cards
- recipe cards divided into preparation, cooking, finishing, freezing and reheating phases
- final storage, label, substitution and food-safety guidance
- stable margins, repeated footer and page numbers
- page breaks that keep a recipe phase or guidance box together when possible

The layout expands to the number of recipes and omits empty sections. Screen controls and edit affordances disappear in print. Links print as readable text only when the URL itself matters. The existing `/print/week` output remains unchanged.

## API and module boundaries

Use these server contracts, all protected by the existing token behavior:

- `GET /api/cooking-packets/<week>` returns the merged saved packet and freshness metadata.
- `POST /api/cooking-packets/<week>/refresh` starts background draft assembly and returns `202` with an operation ID. A caller-supplied request ID makes retries idempotent.
- `GET /api/cooking-packets/<week>/refresh/<operation-id>` returns pending, complete or failed. Completion returns the committed packet revision.
- `PATCH /api/cooking-packets/<week>` validates and saves sparse edits, checkbox state or review status with optimistic revision checking.
- `POST /api/cooking-packets/<week>/store-picks/refresh` starts the bounded on-demand lookup and returns `202` with an operation ID. A caller-supplied request ID makes retries idempotent.
- `GET /api/cooking-packets/<week>/store-picks/refresh/<operation-id>` returns pending, complete or failed plus per-retailer status. Completed operations return the committed packet revision.
- Existing `POST /api/cooks/<id>/schedule` remains the only writer for cook timing edits.

Keep persistence and document migration in a packet repository module, draft assembly in a packet builder, retailer adapters in a store-lookup package, and HTML rendering in a packet renderer. The route layer validates requests and coordinates these units. No renderer reads the database, performs network calls or invokes a model.

The web page polls the applicable refresh-status endpoint while draft assembly or a store lookup is running and stops after success, failure or a fixed timeout. Operation state is bounded and temporary; the saved packet and retailer snapshot are the durable results. If the API restarts during a refresh, the operation becomes failed and the same request ID may be retried without creating conflicting snapshots.

## Error handling

- Invalid week keys, document versions, revisions, edit paths or oversized values fail before writes.
- A concurrent edit returns a conflict with the current revision and never overwrites newer work silently.
- A missing recipe produces a named warning and leaves the other packet sections usable.
- Inventory or shopping match uncertainty stays visible; it is never converted into a confident store or quantity.
- Retail failures retain usable saved results and their original timestamps.
- Packet generation failure leaves the previously committed packet intact.
- A print request with no saved packet links back to Build cooking packet rather than generating during render.
- Escaped text and DOM text nodes handle recipe, product, note and retailer strings as untrusted input.

## Validation

### Pure and persistence tests

- Packet document versioning, size bounds, transactions and optimistic revisions.
- Stable IDs, edit reapplication, orphaned-edit review and review-status invalidation.
- Cook-derived schedule rows, lead-in dates, packet date range and unassigned freezer cooks.
- Pantry credits by exact storage location, uncertain location behavior and no inventory mutation.
- H-E-B brand preference, Costco bulk threshold, storage-friendly remainder, unavailable price, comparable unit price and no-waste fallback.
- Retail partial failure, stale snapshot preservation, retry idempotence and bounded normalization.
- Recipe headings plus legacy flat instructions, globally stable ordinals and missing optional phases.
- Shared bean preparation, incompatible pressure times, acid ordering and raw-protein refusal.

### Route and browser tests

- Token enforcement, invalid payloads, revision conflicts and source-refresh behavior.
- Mobile section editing, checkbox persistence, schedule edits through the ledger, save feedback and reload.
- Keyboard and screen-reader names, touch target sizes, narrow viewport behavior and reduced motion.
- Store-refresh progress, one-retailer failure, stale timestamps and no-results copy.
- Print action, hidden controls, Letter pagination, repeated footer, recipe-card breaks and variable recipe counts.

### Real-system verification

Run against isolated copies of the real W40 cooks, recipes and inventory. Confirm the packet includes all four freezer cooks despite zero serving placements; groups the credited ingredients by their real locations; produces the shared bean preparation; preserves a manual edit across refresh; and prints a visually reviewed packet comparable to the reference. Verify the phone page and printer flow over the normal Tailscale address. Restart the API after changing library or template files.

## Scope limits

This feature does not replace the compact weekly overview, decrement inventory, record purchases, place a retailer order, write to Apple Calendar, assign freezer servings, calculate missing nutrition, or rewrite legacy recipes automatically. It does not claim local stock or warehouse pricing without evidence. Store adapters cover only the configured H-E-B and Costco locations in the first version.
