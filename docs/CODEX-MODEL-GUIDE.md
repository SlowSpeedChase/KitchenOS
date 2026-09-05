# Codex model and effort guide

**Default for Selene and KitchenOS: GPT-5.6 Sol with high effort.**

Use this page when starting a Codex task or when a task becomes more difficult than expected. The model selected in Codex controls the coding agent; it does not change Selene's Ollama models or KitchenOS's runtime LLM configuration.

## Quick choice

| Work | Model | Effort |
| --- | --- | --- |
| Explain, inspect, review, or make a bounded documentation change | GPT-5.6 Terra | Medium |
| Implement a normal feature, bug fix, test, or refactor | GPT-5.6 Sol | High |
| Make an obvious mechanical edit with easy verification | GPT-5.6 Luna or GPT-5.3 Codex Spark | Medium |
| Change architecture, data invariants, security, or several connected systems | GPT-6 Astra | High |
| Resolve a deeply ambiguous problem or recover after a serious failed attempt | GPT-6 Astra | xHigh |

When uncertain, choose **GPT-5.6 Sol with high effort**.

## Model examples

### GPT-6 Astra

Use Astra for the hardest end-to-end work, especially when a subtle mistake could corrupt data or break several connected systems.

Selene examples:

- Redesign the capture, SQLite, Ollama, and Obsidian pipeline.
- Diagnose missing notes across ingestion, processing, export, and launchd.
- Change database schemas while preserving workflow compatibility.
- Audit development and production privacy boundaries.
- Reconcile conflicting architectural or product requirements.

KitchenOS examples:

- Change the relationship between meal plans, cooks, bundles, and generated views.
- Diagnose an iOS-to-API-to-SQLite failure with several plausible causes.
- Change recipe identity, inventory accounting, or nutrition calculations.
- Design a migration across the recipe corpus.
- Review authentication, AppleScript, or untrusted-input security.

Start with **high** effort. Use **xHigh** when the problem is unusually ambiguous or a strong earlier attempt failed. Reserve **max** for a genuinely difficult problem that remains unresolved after xHigh.

### GPT-5.6 Sol

Use Sol for most implementation work. This is the default for both repositories.

Selene examples:

- Add a workflow, tests, documentation, and launchd integration.
- Fix ingestion, synthesis, or Obsidian-export behavior.
- Add an API route or refactor a TypeScript subsystem.
- Improve an Ollama prompt and its response contract.
- Implement an approved design document.

KitchenOS examples:

- Add a planner interaction and its API endpoint.
- Fix shopping-list or ingredient aggregation.
- Add or change an App Intent.
- Improve recipe or receipt parsing.
- Build a feature spanning Python, templates, and tests.
- Deploy and verify an iOS change on the physical device.

Use **medium** for a small, fully specified implementation. Use **high** for normal work. Use **xHigh** for difficult debugging when the overall architecture is already understood.

### GPT-5.6 Terra

Use Terra for bounded work that does not require understanding the entire system.

Examples:

- Explain one workflow, route, class, or module.
- Trace where a configuration value is used.
- Review a change confined to one subsystem.
- Add tests for existing behavior.
- Update a guide to match verified source code.
- Investigate a straightforward test failure.
- Make a contained validation, template, or layout fix.

Use **low** for narrow inspection and **medium** for a bounded change. Use **high** only when the task remains contained but has tricky edge cases.

### GPT-5.6 Luna

Use Luna for fast, precise, easily verified work.

Examples:

- Fix spelling, links, labels, or a version number.
- Apply an exact rename across known files.
- Add a test case that closely follows an existing test.
- Summarize a log or locate symbol references.
- Make a small CSS change with an exact specification.

Do not use Luna for database changes, architecture, security, production debugging, or ambiguous requirements. If Luna needs high or greater effort, switching to Terra or Sol is usually a better choice.

### GPT-5.3 Codex Spark

Use Spark for immediate coding micro-tasks whose results can be checked quickly.

Examples:

- Fix an obvious syntax error or missing import.
- Change one label or fixture value.
- Explain a short function.
- Try a small, reversible visual adjustment.

Do not use Spark for long autonomous tasks or cross-system debugging.

### GPT-5.5 and GPT-5.4 Mini

These are mainly useful for reproducing older work, comparing model behavior, or continuing a task already tuned for them. Prefer Sol, Terra, or Luna for new work.

## Effort examples

| Effort | Use it when |
| --- | --- |
| Low | Finding, explaining, or summarizing something narrow |
| Medium | Completing one clearly bounded change |
| High | Implementing and verifying a normal feature or bug fix |
| xHigh | Debugging ambiguity, reconciling several systems, or recovering from a failed attempt |
| Max | Addressing an exceptional unresolved problem after xHigh |

Higher effort gives the selected model more room to reason. It does not compensate reliably for choosing a model below the task's required capability.

## Codex startup check

At the first substantive turn, Codex should classify the requested work using the quick-choice table.

- If the current model and effort are visible and sufficient, continue without announcing the check.
- If the setting is visible and underpowered, stop before making changes and provide switch instructions.
- If the setting is not visible, do not claim it was verified. Recommend a setting only when the task warrants interrupting the user.
- Reassess when the scope expands materially or a serious attempt fails.
- Load this full guide only when classification is unclear or the user asks about the choice.

When a switch is needed, provide:

1. The exact model and effort.
2. The repository and starting location for the new task.
3. A complete copy-and-paste prompt with no placeholders.

The prompt must preserve the user's request. If work has already begun, it must also include the branch or worktree, completed work, changed files, verification results, remaining work, and the next concrete action.

## Source and maintenance

OpenAI currently describes Astra as its most capable model for the hardest end-to-end work, Sol as a flagship model for complex professional work, Terra as the intelligence-and-cost balance, and Luna as the cost-sensitive option. Recheck the [official OpenAI model catalog](https://developers.openai.com/api/docs/models) when model names or availability change.
