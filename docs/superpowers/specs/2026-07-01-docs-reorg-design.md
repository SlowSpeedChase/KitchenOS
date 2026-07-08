# KitchenOS Docs Reorganization — Design Spec

**Date:** 2026-07-01  
**Status:** Approved design, pending implementation plan  
**Origin:** Recovered from the 2026-07-01 ultracode docs-audit session (`kitchenos-doc-audit` workflow, 13 agents, ~598K tokens). This session produced the design as chat output only and ended before writing it to disk; this file restores it verbatim from the workflow output + session transcript.

---

## Problem (headline)

Verified — all the destructive-action assumptions hold:

- **It IS a git repo** (HEAD `30f0620`); all four delete-candidates are tracked, so anything removed stays recoverable. (The env banner "not a git repo" is just because I'm sitting in the parent `~/Dev`.)
- **`HOW_TO_RUN.md` is literally the wrong project** — "How to Run the YouTube Video Info Fetcher" (the old `yt_vid_info`), yet `CLAUDE.md` advertises it as the quick-start.
- **7 LaunchAgent plists, not 4–5** (the critic was right, the synthesis undercounted) — the runbook must enumerate all 7.
- `scripts/story.sh` and `requirements-ml.txt` exist and need explicit dispositions; `ingredient-data-cleaning.md` has no status header → keep for individual review.

Here's what the audit found and the plan I want your sign-off on before I write anything.

## What's actually wrong (headline)

1. **Three generations of docs disagree with reality.** The code is now a local-first kitchen OS — synchronous **Flask** API (~50 routes) on the Mac mini, SQLite as single source of truth, receipt/CSA email ingest, gram-based nutrition engine, MCP server, **plus a real iOS 26 / macOS 26 SwiftUI app** (9 App Intents, on-device Apple Foundation Models), and the two forked branches are **already converged on main**. But the docs still describe an **n8n/Ollama-only, iOS-Shortcut-only, no-native-app** world that was never built or is long gone.
2. **`CLAUDE.md` is a 50KB/905-line hybrid** (design doc + runbook + roadmap + a 75-row module index) loaded into *every* turn — the single most expensive pile of bad context, and it contradicts itself (a "no maintained function index" line sitting above a hand-maintained function index).
3. **`ROADMAP.md` omits the entire native/Siri effort** and misstates several statuses (ML parser, timed events shipped but listed as gaps).
4. **Dead weight:** `SESSION_SUMMARY.md` + `IMPLEMENTATION_SUMMARY.md` (Jan-7 n8n time capsules), `HOW_TO_RUN.md` (wrong project), a never-run user-story system (`docs/stories/`, `BRANCH-STATUS.md`, `story.sh`), and ~72 legacy `docs/plans/` for shipped features.
5. **One genuinely at-risk asset** (the critic's best catch): the **native-app build/sign/deploy know-how** (xcodegen team-pinning, 7-day free-team re-sign, deploy commands) lives *only* in `BUILD_LOG.md` + your global memory. Any reorg must give it a **live** home, not freeze it into history.

The full audit (19 doc↔code contradictions, per-file dispositions, canonical-source map) is captured and will go into the design doc.

## The strategy

"One home per kind of information." Slim `CLAUDE.md` to always-on invariants + a pointer index; put each kind of info in exactly one canonical doc; correct every stale claim in place; archive frozen history out of the active surface. Before I lock the target structure, four decisions genuinely change the shape — and they're yours to make:

---

## Audit overview

The core problem is not correctness of any single doc but placement and drift: three generations of documentation have accreted (day-one time capsules, a growing auto-loaded CLAUDE.md, a superpowers plan system, and a now-shipped native app that almost no doc mentions), so the same information lives in 3-4 places and disagrees with itself. CLAUDE.md has become a 50KB design-doc/runbook/roadmap/module-index hybrid loaded into every turn; README is frozen in the recipe-extraction era; ROADMAP tracks only salvaged Python branch ideas and omits the entire Siri/App-Intents/native-app effort; and a large tail of dated plans, session summaries, and a dead user-story system add pure noise. Meanwhile the code reality has moved decisively: it is a local-first "kitchen OS" (synchronous Flask API on the Mac mini, ~50 routes, SQLite single-source-of-truth DB, receipt/CSA email ingest, gram-based nutrition engine, MCP server, and a real iOS 26 + macOS 26 SwiftUI app with 9 App Intents and on-device Apple Foundation Models), with hybrid AI (Ollama for extraction, Claude for receipts/suggestions), and the two forked app branches are already converged onto main.

The reorg strategy is "one home per information-type." Establish a small canonical set: README (human overview), a slim always-on CLAUDE.md (invariants + pointers only), docs/ARCHITECTURE.md (the single "what exists" technical reference), docs/API.md (interface surface), docs/OPERATIONS.md (runbook), docs/ROADMAP.md (single "what's next"), docs/workflows/end-to-end.md (user workflow), docs/setup/* (integration guides), docs/superpowers/{specs,plans} (live per-feature design/execution), docs/plans/archive (frozen legacy plans), docs/history (preserved build/design history), and the functional .claude/agents + .claude/skills. Everything else is merged into one of those, archived, or deleted. The load-bearing correctness fixes ride along: kill the n8n/Ollama-only/iOS-Shortcut-only framing, pin Python 3.11, stop quoting phantom vault-path defaults, point nutrition at nutrition_engine.py, and delete the self-contradicting 75-row module index and the duplicate Future-Enhancements table from CLAUDE.md.

---

## Canonical source map (one home per information-type)

- **Project overview & scope (human front door)** → `README.md`  
  _Human-readable 'what KitchenOS is / install / primary usage'. CLAUDE.md carries only a one-paragraph condensed version that links here, so the full scope narrative lives once._
- **Always-on agent operating context (principles, constraints, key paths, invariants, env keys, pointer index)** → `CLAUDE.md`  
  _The only doc auto-loaded every turn; must be the minimal set an agent needs before touching code, and the index that points at everything else._
- **lib/ module coding conventions** → `lib/CLAUDE.md`  
  _Already accurate and correctly scoped to lib/; root CLAUDE.md should link to it, not restate the full conventions._
- **Current architecture / 'what exists' (Flask API, pipeline, LaunchAgents, MCP, native app, data model, receipt→inventory design)** → `docs/ARCHITECTURE.md`  
  _Today this lives implicitly inside CLAUDE.md and is the biggest source of bloat/drift; it needs one detailed technical home that CLAUDE.md and README both link to._
- **API & MCP interface reference (HTTP endpoints, MCP tools, Siri-facing intents/surface)** → `docs/API.md`  
  _Currently duplicated and stale in CLAUDE.md (MCP tools listed twice, missing use_it_up/cook_recipe); one endpoint/tool reference kept in sync with @app.route and mcp_server.py._
- **Operations runbook (all one-off CLI commands, LaunchAgent install/logs/restart, health checks, failure-analysis agent, QuickAdd setup)** → `docs/OPERATIONS.md`  
  _~20 CLI subsections + 5 near-identical LaunchAgent boilerplate blocks in CLAUDE.md are runbook material, not always-on context; ops/*.plist remain the canonical plist definitions this doc references._
- **Roadmap / what's next** → `docs/ROADMAP.md`  
  _Single 'what's next' doc; delete the competing Future-Enhancements tables in CLAUDE.md and IMPLEMENTATION_SUMMARY that currently contradict it._
- **End-to-end user workflow (capture→plan→shop→prep→cook→review)** → `docs/workflows/end-to-end.md`  
  _The most accurate workflow doc; absorb weekly-planning-session's tutorial voice so the stage model exists once._
- **Setup / integration guides (native app, iOS Shortcut, Drafts→Selene)** → `docs/setup/`  
  _Per-integration how-tos, one file per distinct endpoint/flow, kept out of always-on context._
- **Per-feature design specs + executable plans (new/active work)** → `docs/superpowers/{specs,plans}/`  
  _Already the live convention (design in specs/, TDD execution in plans/); keep for all post-convergence work._
- **Legacy feature plans (pre-superpowers, 2026-01..06-15, completed)** → `docs/plans/archive/`  
  _Frozen build records; keep provenance local under plans/ with a generated INDEX rather than at active-doc surfaces._
- **Project & build history (Siri build log, n8n-vs-standalone rationale, lessons learned)** → `docs/history/`  
  _Preserve the sole written record of the Siri effort and the origin-story rationale in one clearly-historical place, not at repo root implying the Swift app lives there._
- **Contributor workflow (completing-work checklist + which-doc-to-update table)** → `docs/CONTRIBUTING.md`  
  _Process material currently wedged into CLAUDE.md 'Completing Work'; move it so CLAUDE.md stays lean._
- **Agent & skill definitions (functional tooling)** → `.claude/agents/ and .claude/skills/`  
  _These are executable tool contracts, each its own home; only surgical path/module fixes needed, no consolidation._
- **Copyable environment/config template** → `.env.example`  
  _The single onboarding env template; must be completed to match the real required keys so setup docs stop under-provisioning._

---

## Per-file dispositions

| Path | Disposition | Target | Reason |
|---|---|---|---|
| `CLAUDE.md` | rewrite | — | 50KB/905-line design-doc+runbook+roadmap+75-row module-index hybrid loaded every turn; slim to a ~150-250 line always-on quick reference (invariants + pointer index), move reference/runbook/design/roadmap material to the new canonical docs. Delete the self-contradicting Core Components table and the Future Enhancements table outright. |
| `README.md` | update | — | Fix wrong claims (receipts=Claude default not Ollama-only; Python 3.11 not 3.9+; broken iOS_SHORTCUT_SETUP.md link → docs/setup/; add Instagram Reels) and broaden scope to the full kitchen-OS + native app, or explicitly rescope to the extraction core (recommend broaden). |
| `lib/CLAUDE.md` | keep | — | Verified current and correctly scoped; root CLAUDE.md should link to it for lib conventions rather than duplicate them. |
| `BUILD_LOG.md` | archive | docs/history/SIRI_BUILD_LOG.md | Sole written record of the Siri/App-Intents build; valuable history but orphaned at repo root implying the Swift app lives there. Relocate verbatim under docs/history/, preserving per-session STOP notes and on-device fix narrative. |
| `docs/ROADMAP.md` | rewrite | — | Accurate as a salvaged-branch backlog but omits the entire (now-shipped) Siri/App-Intents/native-app/convergence effort, frames a native inventory screen as speculative though it shipped, and misstates ML-parser/timed-events status. Make it the single 'what's next' with a Done/Shipped section and corrected statuses. |
| `docs/IMPLEMENTATION_SUMMARY.md` | merge-into | docs/history/ORIGINS.md | Day-one (2026-01-07) n8n-vs-standalone time capsule; salvage only the 'why standalone over n8n' rationale + Lessons Learned into a short history note, then remove the CLAUDE.md checklist rows routing updates here. Everything else is superseded by ARCHITECTURE.md. |
| `docs/SESSION_SUMMARY.md` | delete | — | Transient 2026-01-07 session handoff, near-pure subset of IMPLEMENTATION_SUMMARY with stale n8n webhook steps and wrong worktree/vault paths; no unique lasting value and not referenced by any live doc. |
| `docs/weekly-planning-session.md` | merge-into | docs/workflows/end-to-end.md | ~80% duplicate of end-to-end (same stage model, background-services and troubleshooting tables); fold the tutorial voice into end-to-end and fix the ~/KitchenOS repo-root/log path bugs during the merge. |
| `docs/workflows/end-to-end.md` | update | — | Merge target and most-accurate workflow doc; fix /extract response field ('recipe' not 'recipe_name') and add the native Siri/App-Intents app as a first-class capture/query surface alongside the Shortcut. |
| `docs/setup/HOW_TO_RUN.md` | delete | — | Not KitchenOS at all — it documents the old yt_vid_info project (AppleScript/Automator, files that do not exist here) yet CLAUDE.md advertises it as the quick-start. Delete and drop the CLAUDE.md reference; quick-start lives in README/OPERATIONS. |
| `docs/setup/iOS_SHORTCUT_SETUP.md` | update | — | /extract Share-Sheet flow is still valid, but note it is now a legacy/alternate path to the primary native app; drop the vestigial 'find Tailscale IP' step, and replace the inlined LaunchAgent plist with a link to OPERATIONS.md/ops/*.plist. |
| `docs/setup/DRAFTS_RECIPE_ACTION.md` | update | — | Flow is current (/api/recipes/import-text exists); only fix the stale Selene cross-reference paths (~/selene → ~/Dev/selene per post-rebuild reality). |
| `docs/stories/INDEX.md` | archive | docs/archive/stories/ | Dead-on-arrival all-zeros dashboard for a user-story workflow that produced zero stories and is never referenced by CLAUDE.md; a frozen all-zeros dashboard actively misleads. Archive the whole cluster together (or delete — see open questions). |
| `docs/stories/templates/STORY-TEMPLATE.md` | archive | docs/archive/stories/ | Template for the never-run story system; move with INDEX.md. |
| `templates/BRANCH-STATUS.md` | archive | docs/archive/stories/ | Per-branch status template for the same never-followed workflow; never instantiated. Move with the stories cluster (also relocate/retire scripts/story.sh, which is orphaned and would fail its own status command). |
| `docs/plans/` | archive | docs/plans/archive/ | ~71 dated (2026-01-07 → 2026-06-15) pre-superpowers design/impl pairs; one-shot executable plans for features that all shipped on main. Bulk-move to docs/plans/archive/ and generate INDEX.md (date | feature | design/impl | shipped-on-main? one-liner). Do NOT delete (cheap history) and do NOT touch docs/superpowers/. |
| `docs/plans/ingredient-data-cleaning.md` | keep | — | Anomaly: only file without a date prefix and the only one with a genuinely recent mtime (2026-06-24), tied to a script that exists; may still be a live plan. Exclude from the bulk archive move and review individually before deciding keep-in-place vs archive-as-done. |
| `docs/superpowers/specs/` | update | — | Three design specs are accurate records of shipped work but carry stale 'pending implementation plan / pending per-phase plans' headers, and the Subsystem-C spec's App-Schemas C3 approach was superseded by IndexedEntity in its own plan. Flip Status lines to Implemented and annotate the C3 pivot; otherwise keep. |
| `docs/superpowers/plans/` | keep | — | Seven executed TDD plans; accurate historical records of shipped work. Keep in place and add a short docs/superpowers/README.md mapping each spec→plan→merge-commit and marking them all as completed (fix minor stale worktree references ~/Dev/KitchenOS-siri, retired at convergence). |
| `.claude/agents/failure-pattern-analyzer.md` | keep | — | Verified fully current against lib/failure_logger.py, scripts/analyze_failures.sh, and the error_category vocab; no changes. |
| `.claude/agents/meal-plan-reviewer.md` | update | — | Hard breakage: line 22 `cd /Users/chaseeasterling/KitchenOS` is a dead pre-rebuild path (→ /Users/chaseeasterling/Dev/KitchenOS); also fix vault-relative inputs to include the KitchenOS/ subfolder (vault/KitchenOS/Meal Plans/..., vault/KitchenOS/My Macros.md). |
| `.claude/skills/finish-feature/SKILL.md` | update | — | Commit footer says Opus 4.6 while CLAUDE.md says 4.5 and the environment is 4.8; standardize the Co-Authored-By string to the current model across all three. |
| `.claude/skills/recipe-debug/SKILL.md` | update | — | Stage 10 points debuggers at the DEPRECATED lib/nutrition_lookup.py and describes the old 3-source Nutritionix lookup; repoint to lib/nutrition_engine.py → food_db/food_resolver (USDA FoodData Central + Open Food Facts, USDA_FDC_API_KEY). Rest of the stage table is accurate. |
| `scripts/kitchenos-uri-handler/README.md` | update | — | Line 16 Automator install path uses the pre-rebuild /Users/chaseeasterling/KitchenOS location; update to /Users/chaseeasterling/Dev/KitchenOS. Handler behavior (port 5001, /health, two actions) is otherwise accurate. |
| `.env.example` | update | — | Incomplete vs the real .env: add ANTHROPIC_API_KEY, USDA_FDC_API_KEY, GMAIL_APP_PASSWORD, the second CSA Gmail (GMAIL_ADDRESS_/GMAIL_APP_PASSWORD_), and NUTRITIONIX keys (or drop them if deprecating), and fix the vault-path comment to reference KITCHENOS_VAULT reality. Setup docs rely on this template. |

---

## Doc ↔ code contradictions (19)

1. n8n architecture is fiction: CLAUDE.md 'Design Principles' ('standalone script beats n8n orchestration'), IMPLEMENTATION_SUMMARY 'Original Plan (n8n-based)', and SESSION_SUMMARY's n8n workflow/webhook steps all imply an n8n stack that was never built. Reality = standalone synchronous Flask (app.run port 5001). Only vestige is a 'JSON output mode for n8n integration' comment in main.py (~line 476); strike all n8n framing.
2. 'Ollama-only / fully local, no cloud' is false. Receipt parsing DEFAULTS to Claude (claude-opus-4-8) when ANTHROPIC_API_KEY is set, Ollama only fallback (lib/receipt_parser.py); meal suggestions use Claude (claude-haiku-4-5); food_resolver/task_extractor use Haiku; Whisper (OpenAI) is the transcript fallback; the native app uses Apple Foundation Models on-device. Ollama mistral:7b remains only for recipe extraction/nutrition/seasonality/resolver-fallback. Fix README line 163 and ingest_receipts.py docstring ('parsed with Ollama').
3. 'iOS Shortcut only / Share Sheet only' is stale. There is a real native SwiftUI app (KitchenOSSiri, iOS 26 + macOS 26) + KitchenOSKit with 9 App Intents, an AppShortcutsProvider, Apple Foundation Models, and CoreSpotlight indexing — a full API client, not a Shortcut. Fix iOS_SHORTCUT_SETUP.md, end-to-end.md, weekly-planning-session, README scope, and the CLAUDE.md omission (it never mentions the Swift app).
4. Python floor disagrees: README says 3.9+, CLAUDE.md says 3.11, IMPLEMENTATION_SUMMARY documents a 3.9 f-string-backslash workaround. The venv is python3.11; pin 3.11 everywhere and drop the obsolete workaround note.
5. Nutrition source is stale in recipe-debug SKILL stage 10: it names the DEPRECATED lib/nutrition_lookup.py and the old 3-source Nutritionix lookup. Live path = lib/nutrition_engine.py → food_db.py/food_resolver.py over USDA FoodData Central + Open Food Facts, keyed on USDA_FDC_API_KEY. Nutritionix and nutrition_lookup.py are deprecated.
6. Vault path is quoted three inconsistent (all wrong) ways: lib/paths.py code default ~/KitchenOS/KitchenOS_Vault, its docstring ~/KitchenOS/KitchenOSApp/, .env.example ~/KitchenOS/vault, and IMPLEMENTATION_SUMMARY an iCloud path. Actual live vault = /Users/chaseeasterling/Dev/KitchenOS/vault/KitchenOS via KITCHENOS_VAULT. Docs must say 'resolved via lib/paths.py / KITCHENOS_VAULT', never quote a default.
7. Post-rebuild repo-root path drift breaks copy-paste instructions: meal-plan-reviewer.md line 22 `cd /Users/chaseeasterling/KitchenOS`, uri-handler README line 16, weekly-planning-session cd + log paths, and SESSION_SUMMARY's GitHub/worktree paths all predate the move to /Users/chaseeasterling/Dev/KitchenOS.
8. Broken link: README line 369 points to iOS_SHORTCUT_SETUP.md at repo root; the file is at docs/setup/iOS_SHORTCUT_SETUP.md.
9. CLAUDE.md self-contradiction: 'There is no maintained function index — it drifts' sits directly below a hand-maintained 75-row Core Components file→purpose table that drifts. Delete the table.
10. CLAUDE.md MCP tools table is stale and duplicated: it omits use_it_up and cook_recipe (both registered in mcp_server.py) and is listed twice; the server actually exposes 15 tools. Regenerate once in API.md.
11. Co-Authored-By model version drifts: CLAUDE.md 'Opus 4.5', finish-feature SKILL 'Opus 4.6', environment 'Opus 4.8'. Standardize to the current model.
12. CLAUDE.md Future Enhancements contradicts ROADMAP: ML ingredient parser is BUILT/opt-in in code (lib/ingredient_ml.py) but ROADMAP lists it a GAP; timed calendar events shipped (lib/ics_generator.py MEAL_TIMES) but ROADMAP lists PARTIAL/GAP. Keep one roadmap and correct the statuses.
13. Inventory source-of-truth: any doc implying Inventory.md or config/pantry.json is editable truth is stale — truth is data/kitchenos.db; Inventory.md is a generated read-only view and config/pantry.json is gone. ARCHITECTURE.md must state this.
14. ARCHITECTURE.md must state the framework is synchronous Flask (not FastAPI/async) and that /extract and /reprocess subprocess out to extract_recipe.py (extraction is not in-process).
15. .env.example under-provisions vs the real .env: missing ANTHROPIC_API_KEY, USDA_FDC_API_KEY, GMAIL_APP_PASSWORD, the second CSA Gmail (GMAIL_ADDRESS_/GMAIL_APP_PASSWORD_), and NUTRITIONIX keys; setup docs built on it will fail receipts/nutrition/CSA.
16. DRAFTS_RECIPE_ACTION.md cross-references ~/selene; Selene moved to ~/Dev/selene after the rebuild.
17. end-to-end.md Stage 1a says /extract returns {status, recipe_name}; the endpoint returns key 'recipe' (api_server.py).
18. superpowers specs still say 'Approved design, pending implementation plan / pending per-phase plans' though all shipped; the Subsystem-C spec's C3 'App Schemas' approach was superseded by IndexedEntity in its own plan; and several plans reference the retired worktree ~/Dev/KitchenOS-siri.
19. migrate_*.py (migrate_recipes/migrate_cuisine/migrate_inventory_db) are completed one-time migrations (migrate_inventory_db refuses once inventory has rows); docs listing them as setup/run steps mislead.

---

## Target structure (from audit)

```
Root
  README.md                         # Human front door: full scope, install, primary usage, links out (one home for overview)
  CLAUDE.md                         # Slim always-on agent context: principles/constraints, key paths+invariants, env keys, primary commands, pointer index (~150-250 lines)
  lib/CLAUDE.md                     # lib/ coding conventions (paths.py, vocab, atomic writes, DB access) — unchanged, linked from CLAUDE.md
  requirements.txt                  # Canonical dependency list (CLAUDE.md/README stop hand-copying deps)
  .env.example                      # Canonical copyable env template (completed to match real required keys)
  ops/*.plist                       # Canonical LaunchAgent definitions (referenced by OPERATIONS.md, not re-embedded elsewhere)

docs/
  ARCHITECTURE.md                   # NEW canonical 'what exists': Flask (synchronous) API + subprocess extraction pipeline + 5 LaunchAgents + MCP server + native app tier + SQLite-single-source data model + receipt→inventory design + feature semantics (servings/composite/pantry/prep)
  API.md                            # NEW interface reference: ~50 HTTP routes + 15 MCP tools (incl. use_it_up, cook_recipe) + Siri-facing intent surface, kept in sync with @app.route & mcp_server.py
  OPERATIONS.md                     # NEW runbook: all one-off CLI commands, per-LaunchAgent install/logs/restart, health checks, failure-analysis agent, QuickAdd setup, API-restart caveat, setproctitle note
  CONTRIBUTING.md                   # NEW completing-work checklist + which-doc-to-update table (moved out of CLAUDE.md)
  ROADMAP.md                        # Single 'what's next' (Python backlog + native/Siri roadmap + Done/Shipped section)
  setup/
    NATIVE_APP.md                   # NEW (or a section appended to iOS_SHORTCUT_SETUP): how KitchenOSSiri connects (baseURL, Tailscale 100.111.6.10:5001, KITCHENOS_API_TOKEN, Apple Intelligence requirement)
    iOS_SHORTCUT_SETUP.md           # Legacy/alternate Share-Sheet /extract shortcut (updated; native app is primary; plist → link)
    DRAFTS_RECIPE_ACTION.md         # Drafts→Selene free-text import via /api/recipes/import-text (Selene path fixed)
  workflows/
    end-to-end.md                   # Canonical stage-by-stage user workflow (absorbs weekly-planning-session tutorial voice)
  superpowers/
    README.md                       # NEW index: these are shipped; map each spec→plan→merge-commit
    specs/                          # Live per-feature design specs (Status lines corrected to Implemented)
    plans/                          # Live executable TDD plans (completed records)
  plans/
    archive/                        # ~71 frozen pre-superpowers dated design/impl plans
      INDEX.md                      # NEW: date | feature | design/impl | shipped-on-main? one-liner
    ingredient-data-cleaning.md     # KEPT pending individual review (may still be live; no date prefix)
  history/
    SIRI_BUILD_LOG.md               # Relocated BUILD_LOG.md — sole verbatim record of the Siri/App-Intents build
    ORIGINS.md                      # NEW: salvaged n8n-vs-standalone rationale + Lessons Learned from IMPLEMENTATION_SUMMARY
  archive/
    stories/                        # (If archived vs deleted) dead user-story system: INDEX.md, STORY-TEMPLATE.md, BRANCH-STATUS.md (+ retired scripts/story.sh)

.claude/
  agents/                           # Subagent contracts: failure-pattern-analyzer (keep), meal-plan-reviewer (path fixes)
  skills/                           # Skill contracts: finish-feature (footer fix), recipe-debug (nutrition module fix)

scripts/kitchenos-uri-handler/README.md   # URI-handler install guide (repo-root path fixed to ~/Dev/KitchenOS)

Deleted: docs/SESSION_SUMMARY.md, docs/setup/HOW_TO_RUN.md, docs/weekly-planning-session.md (merged), docs/IMPLEMENTATION_SUMMARY.md (after salvage into docs/history/ORIGINS.md).
```

---

## CLAUDE.md slimming plan

Goal: turn the ~905-line/50KB auto-loaded file into a ~150-250 line always-on quick reference that is invariants + a pointer index, nothing else.

STAYS (always-on, load-bearing before touching code):
1. One-paragraph overview: local-first kitchen OS = synchronous Flask API on the Mac mini (port 5001, com.kitchenos.api) + Obsidian vault + SQLite DB + a native iOS 26/macOS 26 app; hybrid AI (Ollama for extraction, Claude for receipts/suggestions, Apple Foundation Models on-device). Explicitly mentions the native app (CLAUDE.md currently never does).
2. Design principles/constraints that change how code is written: local-first + honest-about-inference; Python 3.11 (full f-string support); Ollama required for extraction; Claude API load-bearing for receipts/suggestions (ANTHROPIC_API_KEY); single-DB source of truth. Drop the 'standalone script beats n8n orchestration' origin-story framing.
3. Key Paths + non-negotiable invariants (the genuinely load-bearing bullets, folding in the useful parts of today's 'Function Reference'): vault resolved ONLY via lib/paths.py/KITCHENOS_VAULT (never quote a default); data/kitchenos.db is the single source of truth for inventory/price; Inventory.md / Price Tracker.md / Use It Up.md are generated read-only views; tasks-cache freshness rule; KITCHENOS_API restart caveat (launchctl reload or it serves stale lib/*); services self-rename via setproctitle (search kitchenos-*, not pgrep -f <script>.py); /extract subprocesses out to extract_recipe.py (extraction is not in-process).
4. Primary commands only: extract_recipe.py <url>, batch_extract.py, the health check, and how to restart the API LaunchAgent. (All other CLI/ops → OPERATIONS.md.)
5. Env-var / API-key list (always-on): KITCHENOS_VAULT, ANTHROPIC_API_KEY, USDA_FDC_API_KEY, GMAIL_ADDRESS/GMAIL_APP_PASSWORD (+ _ second account for CSA), OPENAI_API_KEY, YOUTUBE_API_KEY, KITCHENOS_API_TOKEN. Point to .env.example.
6. 'Where things live' pointer table linking ARCHITECTURE.md, API.md, OPERATIONS.md, ROADMAP.md, CONTRIBUTING.md, workflows/end-to-end.md, docs/superpowers/, docs/history/, lib/CLAUDE.md.
7. Commit convention (fixed to the current model string, replacing Opus 4.5).

MOVES OUT:
- 'Running Commands' (lines ~44-249, ~20 subsections: crouton import, migrate_*, dedupe, migrate_inventory_db, price/nutrition dashboards, CSA ingest) → docs/OPERATIONS.md.
- Four LaunchAgent sections + API Server cp/launchctl/tail boilerplate → docs/OPERATIONS.md (reference ops/*.plist).
- 'Receipt → Inventory Workflow' (lines ~479-544), item schema, storage tables, price tracker, and the feature paragraphs (servings multiplier, composite meals, pantry-aware shopping, cross-recipe prep) → docs/ARCHITECTURE.md.
- MCP 'Available Tools' table + endpoint tables → docs/API.md, regenerated COMPLETE (15 MCP tools incl. use_it_up + cook_recipe; ~50 routes) and de-duplicated (currently listed twice).
- 'QuickAdd Setup (Obsidian)' → docs/OPERATIONS.md (or docs/setup).
- 'Completing Work' checklist + which-doc-to-update table → docs/CONTRIBUTING.md.

DELETES:
- 'Core Components' ~75-row module index — self-contradicting drift magnet; the doc already tells agents to grep + read docstrings. Remove outright.
- 'Future Enhancements' table — duplicates/contradicts ROADMAP.md; replace with a link to ROADMAP.md.
- Inlined 'Dependencies' list — point to requirements.txt.
- The 'no maintained function index — it drifts' self-contradiction wording (keep only the real invariant bullets it contained).
- 'Obsidian Sync (not iCloud)' constraint — unverified and not load-bearing.

lib/CLAUDE.md RECONCILIATION: leave it as-is (verified current). Root CLAUDE.md links to it for lib coding conventions and only restates the small load-bearing invariant subset (vault via paths.py, sidecar freshness, KITCHENOS_DB/tmp_db fixture) — that overlap is intentional and scoped. Remove any lib-internal detail from root that duplicates lib/CLAUDE.md beyond those pointers.

---

## ROADMAP rewrite plan

Current ROADMAP.md is a correct-but-narrow salvaged-branch backlog (Python-side unbuilt ideas, tagged with source branch+commit). It has three problems: (1) it omits the entire Siri/App-Intents/native-app/convergence effort — BUILD_LOG was the sole record; (2) it frames a native Mac/iOS inventory screen as speculative future though one shipped; (3) its statuses drift against code and against CLAUDE.md's competing Future-Enhancements table.

Concrete steps:
1. Make ROADMAP.md the single 'what's next' doc. Delete the Future-Enhancements tables from CLAUDE.md and IMPLEMENTATION_SUMMARY and repoint both here. Add a short header: ROADMAP = what's next; shipped design history lives in docs/superpowers/specs + docs/plans/archive; build history in docs/history.
2. Add a 'Done / Shipped since last update' section recording the now-complete native tier so the gap closes: KitchenOSSiri single XcodeGen target building iOS 26 + macOS 26 (bundle com.kitchenos.siri), KitchenOSKit Swift package, 9 App Intents + AppShortcutsProvider, on-device Apple Foundation Models (RecipeAI, MealPlanAssistant + 5 tools), CoreSpotlight/IndexedEntity semantic search (Subsystem C: C1/C2/C3), backend Phase 0 (ingredient filter + bearer-token auth + /api/recipes/by-ingredients), the inventory-cleanup screen (expiry_status), and the convergence merge (both forked branches gone; both surfaces coexist on main).
3. Reconcile statuses against verified code: move the ML ingredient parser (lib/ingredient_ml.py, KITCHENOS_ML_INGREDIENTS) from GAP → Done/opt-in; move timed calendar events (lib/ics_generator.py MEAL_TIMES) from PARTIAL/GAP → Done; keep flat-inventory-locations and rule-based ingredient parsing as accurately described.
4. Refresh the 'native equivalent / inventory screen' bullets: the cleanup screen shipped, so reframe the remaining native inventory work — specifically the still-pending zone+shelf richer layout and the item→(zone,shelf,location) router reconciliation (per memory) — as the concrete next step, added as a first-class roadmap entry rather than 'a native app could do this someday'.
5. Add the genuinely-pending native/Siri polish surfaced by the superpowers plans: CoreSpotlight ingredient-keyword enrichment + reindex cadence (C3 follow-up), and the AppShell ComingSoonView placeholder sections not yet native.
6. Preserve the branch+commit provenance convention for salvaged Python ideas.
7. Flag (not a doc edit): the auto-memory note 'KitchenOS worktrees … convergence planned — drive when user says converge' is now stale; convergence is complete on main — recommend updating that memory entry.

---

## Open questions (9)

- Dead user-story system (docs/stories/INDEX.md, STORY-TEMPLATE.md, templates/BRANCH-STATUS.md, scripts/story.sh): archive to docs/archive/stories/ (recommended) or delete outright? It was never run and is referenced by no live doc.
- docs/plans/ingredient-data-cleaning.md: is this still a LIVE plan? Its '~34% of 3,254 ingredient rows have problems' and 'JSON-LD/Crouton skip validate_ingredients()' claims need confirmation against current lib/ingredient_parser.py / lib/ingredient_cleaner.py before we decide keep-in-place-as-current vs archive-as-done. Exclude it from the bulk plans/ archive move regardless.
- IMPLEMENTATION_SUMMARY.md: salvage only the n8n-vs-standalone rationale + Lessons Learned into docs/history/ORIGINS.md and delete the rest (recommended), or preserve the full file verbatim under docs/history/?
- README direction: broaden it to document the full kitchen-OS + native app (recommended), or deliberately rescope it to just the recipe-extraction core and let ARCHITECTURE.md own the rest?
- Native-app setup: create a new docs/setup/NATIVE_APP.md, or append a native-app section to the existing iOS_SHORTCUT_SETUP.md?
- History/archive naming: confirm docs/history/ (build log + ORIGINS) and docs/plans/archive/ + docs/archive/stories/ as the archive locations, vs a single top-level docs/archive/ or a CHANGELOG.md.
- VCS state: the environment reports this is NOT a git repo, yet the audit assumes 'git preserves deleted docs' and the code ground-truth cites git log/branches. Confirm the real VCS state before we delete SESSION_SUMMARY.md / HOW_TO_RUN.md / weekly-planning-session.md, so nothing is lost.
- Auto-memory update: the MEMORY note 'KitchenOS worktrees … convergence planned — drive when user says converge' is now stale (convergence is complete on main). Update that memory entry? (Edits ~/.claude memory, outside the repo.)
- Nutritionix: NUTRITIONIX_APP_ID/API_KEY are still present in .env but the code path is deprecated. Keep the keys documented as legacy, or remove them from .env/.env.example entirely?

---

## Completeness critic — flagged gaps (verdict: needs-revision)

```json
{
 "unassigned_docs": [
  "All 24 docs in the mandated 'MUST account for' list DO have a disposition (verified counts match: 71 dated plans + ingredient-data-cleaning.md = 72 files; 7 superpowers plans; 3 specs; exactly 2 agents; exactly 2 skills). The only true loose ends are non-.md-doc files the plan pulls into scope but never formally dispositions:",
  "scripts/story.sh (exists, 5179 bytes): the plan only says 'relocate/retire' it parenthetically under BRANCH-STATUS.md, with no target and no delete/move decision. Left orphaned it is a broken tool tied to the dead story system (it would fail its own status command against the new paths).",
  "requirements-ml.txt (exists, separate from requirements.txt): the ML opt-in dependency file. Plan declares requirements.txt the canonical dependency home and CLAUDE.md 'point to requirements.txt', but never accounts for the ML extras file or the KITCHENOS_ML_INGREDIENTS flag it backs.",
  "Native-app build config (project.yml, KitchenOSSiri.xcodeproj, KitchenOSKit) at repo root: not docs, but they carry a build/sign/deploy procedure that no disposition or target doc captures (see homeless_info_types)."
 ],
 "homeless_info_types": [
  "Native-app build / signing / deploy procedure. xcodegen project.yml regeneration, DEVELOPMENT_TEAM XZJ6358HHF pinning (xcodegen wipes the GUI-set team), free-team 7-day expiry re-sign, and the actual deploy commands. grep confirms this knowledge lives ONLY in BUILD_LOG.md (which the plan freezes to docs/history/SIRI_BUILD_LOG.md), the superpowers plans (frozen 'completed records'), and the auto-memory note. The target structure gives it NO LIVE home: OPERATIONS.md is scoped to Python/Flask/LaunchAgent ops, and the proposed NATIVE_APP.md covers only how the app CONNECTS (baseURL, Tailscale, token, Apple Intelligence), not how to build/sign/redeploy it. When the app next needs a re-sign this workflow is undiscoverable.",
  "How to run the test suite / test conventions. lib/CLAUDE.md notes the KITCHENOS_DB/tmp_db fixture and CONTRIBUTING gets the completing-work checklist, but 'how to run pytest / test layout' has no stated canonical home (tests/ has ~70 files).",
  "ML opt-in dependency + feature flag (requirements-ml.txt, KITCHENOS_ML_INGREDIENTS). Only requirements.txt is homed.",
  "MCP server client setup/registration. .mcp.json exists at root; API.md is scoped to the tool surface, not how a client connects to/launches the server.",
  "Vault folder taxonomy (Recipes/, Meals/, Meal Plans/, My Macros.md, generated Inventory.md/Use It Up.md/Price Tracker.md) as a single map. Referenced by agents and many CLAUDE.md lines; ARCHITECTURE.md touches the data model but no canonical vault-layout reference is called out.",
  "QuickAdd setup is given TWO candidate homes ('docs/OPERATIONS.md (or docs/setup)') \u2014 ambiguous rather than one-home."
 ],
 "contradictions_in_plan": [
  "Archive-root inconsistency: plans go to docs/plans/archive/, the story system to docs/archive/stories/, and narrative history to docs/history/ \u2014 three different archive conventions. Acknowledged in open-question 6 but left unresolved in the target structure, and it undercuts the 'one home per type' thesis.",
  "Env keys in two homes: claude_md_plan item 5 keeps a full always-on env-var/API-key list inside CLAUDE.md while canonical_sources declares .env.example the single env template. Same key set in two files = the exact drift pattern the reorg is trying to kill (only partially mitigated by 'point to .env.example').",
  "Native-app 'what exists' now spans four homes: ARCHITECTURE.md (native tier) + ROADMAP.md Done/Shipped section + docs/superpowers/{specs,plans} + docs/history/SIRI_BUILD_LOG.md. The plan re-creates multi-home drift for the newest, fastest-moving subsystem \u2014 the very failure it diagnoses elsewhere.",
  "LaunchAgent count is internally inconsistent and wrong: ARCHITECTURE says '5 LaunchAgents', claude_md_plan MOVES-OUT says 'Four LaunchAgent sections', OPERATIONS says '5 near-identical blocks' \u2014 but ops/ actually contains 7 plists (api, batch-extract, calendar-sync, cleanup-icloud-old, dashboard-update, mealplan, receipt-ingest).",
  "SESSION_SUMMARY.md is deleted as a 'near-pure subset of IMPLEMENTATION_SUMMARY', yet IMPLEMENTATION_SUMMARY is itself being gutted (only the n8n-vs-standalone rationale + Lessons Learned survive into ORIGINS.md). Any SESSION_SUMMARY content that isn't also in that thin salvage is defended by a doc that no longer exists.",
  "Co-Authored-By model string is standardized to 'the current model' without pinning a value; it has already drifted three ways (CLAUDE.md 4.5, finish-feature 4.6, env 4.8). Hardcoding any version string re-arms the same drift at the next model bump."
 ],
 "risks": [
  "Native-app build/deploy workflow becomes undiscoverable: freezing BUILD_LOG.md and the superpowers plans to 'historical' with no live successor doc means the redeploy procedure (7-day free-team expiry re-sign, xcodegen team pinning) has no home an agent would find. Confirmed by grep \u2014 those are the only files carrying it.",
  "OPERATIONS.md may omit LaunchAgents: because the plan believes there are 4-5, the runbook risks dropping cleanup-icloud-old, calendar-sync, or dashboard-update. All 7 ops/*.plist need per-agent install/logs/restart coverage.",
  "Deleted content stays recoverable but becomes invisible: it IS a git repo (verified HEAD 30f0620, delete-targets tracked), so SESSION_SUMMARY/HOW_TO_RUN/weekly-planning-session/IMPLEMENTATION_SUMMARY deletions are reversible \u2014 but 'safe in git history' is not the same as discoverable by a future agent; any salvage misjudgment is silently lost from the working tree.",
  "Merge losses: folding weekly-planning-session into end-to-end on an '~80% duplicate' estimate risks dropping its background-services/troubleshooting tables; consolidating two Future-Enhancements tables into ROADMAP risks dropping any item the rewrite misses.",
  "Dangling pointers after the rewrite: CLAUDE.md currently points at HOW_TO_RUN.md (line 900), IMPLEMENTATION_SUMMARY.md (lines 861, 901), and docs/plans/ (line 902); README line 369 mislinks iOS_SHORTCUT_SETUP.md. Every one must be repointed or the slim CLAUDE.md ships broken links.",
  "Module-index deletion removes a navigation aid: dropping the 75-row file->purpose table in favor of 'grep + read docstrings' is slower for agents; the drift problem could be solved by auto-generation or a curated short map in ARCHITECTURE.md instead of outright deletion.",
  "Orphaned tool left live: if scripts/story.sh isn't given a real disposition it remains a shipping command that fails against the new paths.",
  "ingredient-data-cleaning.md live-vs-done is unresolved (open question); correctly excluded from the bulk move, but if mis-archived a still-live plan gets buried."
 ],
 "additional_recommendations": [
  "Close open-question 7 as RESOLVED: this is a git repo (HEAD 30f0620; all delete-targets tracked). The env banner 'Is directory a git repo: No' is stale/wrong. Do not let that open question block the deletions.",
  "Before freezing BUILD_LOG.md, extract a LIVE native-app build/deploy section (OPERATIONS.md 'Native app' or a build subsection of NATIVE_APP.md) capturing xcodegen regenerate, DEVELOPMENT_TEAM XZJ6358HHF, the 7-day re-sign, and the deploy commands from the auto-memory 'app signing' note \u2014 that memory entry is currently the only home for the deploy commands and should be migrated into the repo.",
  "Fix the LaunchAgent count to 7 and enumerate every ops/*.plist in OPERATIONS.md.",
  "Pick ONE archive convention (e.g. docs/archive/{plans,stories} + docs/history for narrative, or keep docs/plans/archive but move stories under it) and state it, rather than three parallel roots.",
  "Give scripts/story.sh and requirements-ml.txt explicit dispositions.",
  "If the always-on CLAUDE.md keeps an env list, restrict it to key NAMES only and label .env.example authoritative, to bound the two-home drift.",
  "Prefer auto-generating (or curating a short) module index over deleting it outright.",
  "Standardize the Co-Authored-By string to the harness value 'Claude Opus 4.8 (1M context)' and note it will need a rule/hook, since a hardcoded version drifts again.",
  "Verify the LIVE claims in ingredient-data-cleaning.md against lib/ingredient_parser.py/ingredient_cleaner.py before deciding keep-vs-archive, and update the stale auto-memory worktrees/convergence note as the plan already flags."
 ],
 "verdict": "needs-revision"
}
```

---

## Verified before sign-off


(See Problem section above — git-repo status, HOW_TO_RUN wrong-project, 7 plists, story.sh/requirements-ml dispositions all verified.)

---

## FINALIZED DESIGN (your four locked-in decisions)

Decisions: **pragmatic consolidation** (3 new docs) · **broaden README** · **delete dead docs outright** · **plan-then-execute in phases on a branch**.

All four locked in: **pragmatic consolidation** (3 new docs), **broaden README**, **delete dead docs outright**, **plan-then-execute in phases on a branch**. Here's the finalized design shaped by those answers.

## Target structure

```
Root
  README.md            REWRITE → human front door for the whole kitchen OS
  CLAUDE.md            REWRITE → slim always-on (~150-250 lines): overview para,
                       invariants/key-paths, primary commands, env key NAMES
                       (→ .env.example authoritative), pointer index, commit rule
  lib/CLAUDE.md        KEEP (verified current; linked from root)
  .env.example         UPDATE → add ANTHROPIC/USDA_FDC/GMAIL(+2nd CSA acct)/etc.
  ops/*.plist          canonical LaunchAgent defs (all 7), referenced by OPERATIONS

docs/
  ARCHITECTURE.md      NEW → the single "what exists": synchronous Flask API +
                       subprocess extraction + SQLite-as-truth + vault taxonomy +
                       MCP + native app tier (+ how it connects) + receipt→inventory
  API.md               NEW → routes + MCP tools (incl. use_it_up, cook_recipe) +
                       Siri intents; generated from @app.route & mcp_server.py
  OPERATIONS.md        NEW → runbook: all CLI, all 7 LaunchAgents (install/logs/
                       restart), API-restart + setproctitle caveats, health checks,
                       failure agent, QuickAdd, pytest fixture, AND native-app
                       build/sign/deploy (xcodegen team-pin, 7-day re-sign) +
                       "completing work / which doc to update" checklist
  ROADMAP.md           REWRITE → single what's-next + Done/Shipped (native tier),
                       corrected statuses, branch+commit provenance kept
  setup/
    iOS_SHORTCUT_SETUP.md   UPDATE → marked legacy/alternate to the native app
    DRAFTS_RECIPE_ACTION.md UPDATE → fix ~/selene → ~/Dev/selene
  workflows/
    end-to-end.md      UPDATE → absorbs weekly-planning-session; fix /extract field
                       ('recipe'); add native app as capture/query surface
  superpowers/
    specs/  UPDATE (flip Status→Implemented; note C3 IndexedEntity pivot)
    plans/  KEEP (fix stale ~/Dev/KitchenOS-siri worktree refs)
  history/
    SIRI_BUILD_LOG.md  ← BUILD_LOG.md moved (AFTER extracting live build/deploy → OPERATIONS)
    ORIGINS.md         NEW → salvaged n8n-vs-standalone rationale + Lessons Learned
  plans/
    archive/           ← 71 legacy plans + generated INDEX.md
    ingredient-data-cleaning.md  KEEP pending live-vs-done check during execution

.claude/  meal-plan-reviewer.md (fix dead cd + vault paths), recipe-debug (→ nutrition_engine),
          finish-feature (standardize Co-Authored-By); failure-pattern-analyzer KEEP
scripts/kitchenos-uri-handler/README.md  UPDATE (repo-root path)

DELETE (git-preserved): docs/SESSION_SUMMARY.md, docs/setup/HOW_TO_RUN.md (wrong project),
  docs/weekly-planning-session.md (after merge), docs/IMPLEMENTATION_SUMMARY.md (after salvage),
  docs/stories/**, templates/BRANCH-STATUS.md, scripts/story.sh
```

This resolves the critic's flags: only **two** archive locations remain with a clear split (`docs/plans/archive/` = frozen shipped-feature provenance; `docs/history/` = curated readable narrative), the at-risk **native build/deploy knowledge gets a live home in OPERATIONS.md** before BUILD_LOG is frozen, all 7 plists are covered, and `story.sh`/`requirements-ml.txt` get explicit dispositions.

**Cross-cutting correctness fixes** applied during the rewrites: kill n8n/Ollama-only/iOS-Shortcut-only framing; pin Python 3.11; "vault resolved via `lib/paths.py`/`KITCHENOS_VAULT`, never a quoted default"; nutrition → `nutrition_engine.py`; fix the broken README link; standardize the `Co-Authored-By` string.

## Phased execution (on a branch, checkpoints between)

1. **Safety net + reversible moves** — branch; delete dead docs; move BUILD_LOG→history *after* extracting build/deploy; archive 71 plans + INDEX.
2. **New canonical docs** — ARCHITECTURE, API, OPERATIONS, ORIGINS (grounded in verified code reality).
3. **Slim CLAUDE.md** — reduce to always-on + pointer index.
4. **ROADMAP + README rewrite.**
5. **In-place fixes** — setup/workflows/superpowers/.claude/scripts corrections; `.env.example`.

Two **out-of-repo side items** I'll flag (not do silently): your global memory note says convergence is *planned* — it's **complete on main**; and the app-signing deploy commands currently live only in memory — I'll migrate them into OPERATIONS.md and can update those memory entries to point at the repo, with your OK.

If this looks right, I'll write it up as the design spec at `docs/superpowers/specs/2026-07-01-docs-reorg-design.md` (matching your existing convention), self-review it, and hand it to you to read before I generate the implementation plan. Anything you want changed first?