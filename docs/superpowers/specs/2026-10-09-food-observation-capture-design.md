# Food observations from Siri and Selene

Status: Draft for review

## Intended outcome

Chase can speak or write a brief account of what he wants to eat, what he ate or is considering, and anything that made an appealing meal hard to reach. The original account is saved immediately. KitchenOS accumulates these observations and brings evidence about recurring needs into later food planning.

Success means one short utterance or note is enough. There is no required questionnaire, daily streak, calorie entry, outcome follow-up, or classification step. Conversation remains optional. Capture must work even when inference is unavailable.

## Recommended capture flow

1. Run a Siri Shortcut named **Food note**. It asks for the note once, accepts spoken text, and sends it through Selene's existing authenticated capture path. The Shortcut supplies the food marker, timestamp, and a unique capture ID; Chase does not have to dictate metadata.
2. From Drafts or another Selene capture surface, use **Send food note**, which supplies the same marker automatically. An ordinary Selene note carrying `#food` also qualifies. Automatic classification of every unmarked Selene note is outside this first slice.
3. Selene durably saves the original and records its routing eligibility before acknowledging receipt. Siri says **Food note saved** only after that receipt. If the phone cannot reach Selene, preserve the note locally for retry and say **Saved on this device; waiting to send**. The implementation must prove a durable local retry path on the actual device before promising this behavior.
4. A persistent delivery job sends the eligible capture to KitchenOS. KitchenOS can be offline without losing the capture. Its acknowledgement means the imported record has committed, independently of any later analysis or vault rendering.

This builds on Selene's capture funnel and its existing KitchenOS recipe integration. A direct KitchenOS Siri App Intent is an alternative entry point if the Shortcut cannot meet the receipt and retry contract with acceptable friction. A new chat interface and a remote Claude or ChatGPT connector are unnecessary for this slice.

## What a record means

Keep the original food-related words, capture time with timezone, source ID, source application, and any user-stated event time. Store a derived reading separately:

- Food or experience wanted.
- Reported behavior, if stated.
- Current intention, if stated.
- Reported context, availability, effort, or obstacle, if stated.
- Possible support gap, clearly marked as an interpretation.

Unknown fields remain unknown. “I will probably get it” cannot become an eating or purchase event. “Most mornings this week” remains one retrospective report with an approximate period; it cannot become five invented dated events. Later corrections and outcomes link to the original while preserving it.

Food preferences include pleasure, convenience, variety, routine, and effort. An observation is useful even when it identifies no problem. Any later suggestion should explain what need it might satisfy and show the observation supporting it.

## Separate food experience from system discussion

Food Notes contain food experiences, stated preferences, relevant circumstances, and actual or intended choices. Feature requests, capture instructions, software behavior, design decisions, and discussion of how KitchenOS should work belong in repository design documents. This boundary applies to quoted source text as well as summaries.

A mixed conversation keeps its complete original in the source archive. The food observation quotes only the relevant food passages, with provenance back to that original. For example, “I want a pastry. Add a Siri command to log that” contributes the pastry craving; the request for a Siri command belongs to system design. An observation must not acquire a permanent food preference or an asserted cause merely because the same conversation proposed one for the software to investigate.

Food retrieval, pattern generation, and future planning context consume the food observations and their food-specific derivations. They exclude repository documents, system discussion, complete mixed-conversation archives, and backup history such as `.history`. A provenance link permits deliberate source inspection; it does not pull that entire source into subsequent food context.

Local extraction enforces this boundary before an observation becomes available for food retrieval. If extraction fails or cannot distinguish food content from system discussion, retain the source with processing pending; never populate Food Notes with the complete mixed source as a fallback. A source containing only system discussion produces no food observation. Reprocessing replaces the derived selection while preserving the archived original and source identity.

## Durable storage and delivery

Selene's precious fact store owns the original capture. Food routing eligibility survives derived-store rebuilds. A reconstructible delivery queue may live in the derived store, provided replay is safe and pending captures are rediscovered after a restart or rebuild.

Use a stable source capture ID for idempotency across Selene and KitchenOS. Retries of the same capture must return the same receipt. A new utterance on another occasion must be a new record even if its text is identical. Selene's current general title/content deduplication needs an explicit food-capture identity rule; the implementation plan must address both named capture actions and ordinary `#food` notes.

KitchenOS stores its imported snapshot and source reference in `data/kitchenos.db`. The raw snapshot is an immutable provenance archive, excluded from food retrieval; food excerpts and interpretations are separate, replaceable, versioned derivations. No independent editable copy of the same fact is introduced. A failed model call cannot prevent or roll back capture.

The KitchenOS vault contains a readable **Food Notes** collection generated from committed food observations, plus a **Food Patterns** summary. Generated notes carry a source reference and a read-only banner; corrections arrive as another short note. These views follow the food/system boundary above. The manually saved first observation is retained and imported once during setup with a stable identity before being linked from this collection.

## Reflection and planning

After delivery, local background processing extracts only what the account supports and refreshes a compact summary of recent observations. Each pattern names its evidence and distinguishes the number of reports from the number of explicitly reported occasions. Silence is not evidence that a behavior stopped.

Kitchen context is supporting evidence. If inventory is sampled, retain its timestamp and label it as inventory known at capture receipt, which may differ from the event time. Stocked ingredients do not prove that an appealing, ready-to-eat option existed. Missing or stale context stays unknown.

The summary should help answer questions such as: What keeps sounding good in the morning? What was ready or easy enough? What could we stock or prepare to meet that need? Possible stocking, prep, or recipe ideas appear beside their evidence for later planning. Capturing a thought does not create a shopping item, change inventory, mark a cook, or rewrite a meal plan.

The first slice delivers reliable capture, the readable record, and a grounded recent-pattern summary. Automatic changes to recipe ranking are a later extension; several current suggestion branches return before reading the personal-profile prompt. The capture feature must not claim those branches learn from the notes until that integration is implemented and verified.

Selene-derived private notes and their summaries stay on the local processing path. KitchenOS's existing cloud-backed suggestion prompt must not receive them implicitly through `My Meal System.md`. A later user-led handoff can deliberately supply selected context.

## Existing code and constraints

- Selene `src/workflows/ingest.ts` is the shared capture funnel, with precious fact writes and source UUIDs. Keep capture available when optional processing fails.
- Selene `src/routes/recipe.ts` demonstrates authenticated capture followed by KitchenOS delivery, but its fire-and-forget delivery has only logged failures. Food observations require durable retry and idempotent receipts.
- Selene `docs/VISION.md` requires preservation of original thoughts, local processing, and no conversion of possibilities into commitments.
- KitchenOS already exposes Siri through `KitchenOSShortcuts.swift` and `AskKitchenOSIntent.swift`; the latter is a meal-planning assistant, not a food-note writer.
- KitchenOS vault paths resolve through `lib/paths.py`; DB access uses `lib/inventory_db.py`. Generated views reread committed DB state.
- `lib/profile.py` currently truncates prompt context to 4,000 characters. Appending observations to the growing hand-authored profile would not provide reliable recall.

## Acceptance checks

Use synthetic content in isolated tests and Selene's development environment. Device checks must distinguish a successful local queue from a successful server receipt.

1. One spoken or typed note is saved without an LLM call or required follow-up.
2. A retry after a lost response creates one record; identical text captured on two occasions creates two records.
3. KitchenOS downtime, a process restart, and a Selene derived-store rebuild do not lose pending delivery.
4. Failed inference leaves the original readable through its source reference and can be retried independently, without exposing mixed source text as a food observation.
5. Intentions, approximate repeated behavior, and unverified availability remain qualified in the note and summary.
6. Every pattern links to its source observations; retries and generated summaries cannot increase its evidence count.
7. No capture mutates food inventory, cooks, shopping lists, the meal plan, or the hand-authored profile.
8. No private Selene content is sent to an external model by this feature.
9. A real phone check proves the Siri invocation, receipt wording, error behavior, and retrieval of the saved note before release.
10. A mixed food-and-system capture contributes only its food passages to Food Notes and Food Patterns. A system-only capture contributes no food evidence. Full-source quotes, linked-source expansion, old derivations, and backup history cannot reintroduce system discussion into food context.

## Review decision

Review the capture flow and record semantics before preparing the implementation plan. The key scope is **Siri or a quick Selene note → durable food observation → readable record and evidence-backed patterns**.
