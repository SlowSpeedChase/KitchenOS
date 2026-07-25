# Vendored: watch (claude-video)

- **Source:** https://github.com/bradautomates/claude-video (`skills/watch/`)
- **Pinned commit:** `83da59fa78c3eee9e20f515fe75c438bb5166efd`
- **Vendored:** 2026-07-20
- **Scope:** KitchenOS **only** (per-project skill under `.claude/skills/`).

## What & why
Gives the agent visual video understanding — reads on-screen cooking details (measurements,
steps, ingredients shown but not spoken) that KitchenOS's transcript-based `extract_recipe.py`
pipeline misses. Complementary agent-assist for the recipe-debug flow, **not** a pipeline stage
(the skill hands frames to Claude's context; it isn't a library the batch pipeline imports).

## Deliberate deviations from upstream
1. **No global hook.** Upstream ships a `hooks/` `SessionStart` hook that fires in *every* repo
   once the plugin is enabled. We vendored **only** `skills/watch/` — no hook — so it's active
   solely inside KitchenOS.
2. **Captions-only policy.** A policy block was prepended to `SKILL.md` forcing `--no-whisper`
   on every run and forbidding any `GROQ_API_KEY`/`OPENAI_API_KEY` use or prompt. This is the
   airtight guarantee that a caption-less video's audio never egresses to Groq/OpenAI — important
   because `KitchenOS/.env` carries an `OPENAI_API_KEY` for the pipeline's own Whisper path.
3. **Not installed via `npx skills add` / marketplace** — avoids the third-party installer and
   auto-update writing vendor-controlled content into agent config.

## Dependencies
`yt-dlp` (pipx, on PATH) + `ffmpeg`/`ffprobe` (brew) are pre-installed, so `setup.py` never
triggers an uncontrolled `brew install`. Upstream source verified non-malicious (list-arg
subprocess, `shell=False`, no covert exfil).

## Update procedure
Re-clone upstream at a new pinned commit, diff, re-copy `skills/watch/` (SKILL.md + scripts/),
**re-apply the captions-only policy block**, bump the hash above. Never copy `hooks/`.
