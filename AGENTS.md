# AGENTS.md

All project rules live in `CLAUDE.md`. Read that file in full before working here.

## Codex model and effort check

Before substantial work, classify the task with `docs/CODEX-MODEL-GUIDE.md`. Use this compact rule without loading the full guide unless the choice is unclear: **Terra + medium** for bounded inspection or documentation; **Sol + high** for normal implementation; **Luna or Spark + medium** for obvious mechanical edits; **Astra + high** for architecture, data invariants, security, or cross-system work; **Astra + xHigh** for deep ambiguity or recovery after a serious failed attempt.

If the current model and effort are visible and sufficient, proceed quietly. If they are underpowered, stop before editing and give the operator the exact model, effort, repository, and a complete copy-and-paste prompt for a new Codex task with no placeholders. If work has begun, include the branch or worktree, completed work, changed files, verification state, remaining work, and next action. If the current setting is not visible, never claim it was verified. Reassess only when scope expands materially or a serious attempt fails.
