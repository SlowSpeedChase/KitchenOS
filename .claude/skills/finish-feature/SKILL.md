---
name: finish-feature
description: Run the KitchenOS "Completing Work" checklist before committing - verifies with a dry-run extraction, compares changed lib/templates/prompts files against the Key Functions table in CLAUDE.md, flags missing doc updates, and proposes the commit message. Use when finishing a feature or fix in KitchenOS, before creating a commit.
---

# finish-feature

Enforces the checklist in `CLAUDE.md` → "Completing Work". KitchenOS docs drift
fast because the Key Functions table is maintained by hand — this skill closes
that loop.

## When to use

Invoke at the end of a feature or bugfix, **before** `git commit`. The user
will usually call it with `/finish-feature`.

## Workflow

Run these steps in order. Stop and ask the user if any step fails.

### 1. Gather context

```bash
git status
git diff --stat
git diff
```

Note which files are modified under `lib/`, `templates/`, `prompts/`,
`api_server.py`, and top-level scripts. These are the files that may need
documentation updates.

### 2. Verify imports and Ollama

```bash
.venv/bin/python -c "import extract_recipe, main, api_server" 2>&1
curl -sf http://localhost:11434/api/tags > /dev/null && echo "ollama ok" || echo "ollama DOWN"
```

If Ollama is down and the change touches extraction, warn the user but don't
block — they may be working on docs or unrelated code.

### 3. Run relevant tests

The existing PostToolUse hook runs one test file per edit. This step runs the
**full** suite to catch cross-module regressions.

```bash
.venv/bin/pytest -x -q 2>&1 | tail -30
```

### 4. Check CLAUDE.md Key Functions table for drift

For each modified `lib/*.py` or `templates/*.py`:

- Grep CLAUDE.md for the filename. If missing entirely, flag it.
- For each function added/renamed in the diff (look for `^+def ` in
  `git diff`), grep CLAUDE.md for the function name. If the function is
  top-level and public (no leading `_`) and not in the table, flag it.
- Print a punch list: "Missing from CLAUDE.md Key Functions: `lib/foo.py` →
  `bar_baz()`".

Do **not** auto-edit CLAUDE.md. The user may decide the change is
internal-only. Present the list and ask.

### 5. Feature-test if applicable

If the change touches `extract_recipe.py`, `main.py`, `recipe_sources.py`, or
prompts, ask the user for a test YouTube URL and run:

```bash
.venv/bin/python extract_recipe.py --dry-run "URL"
```

If the change touches `api_server.py` or `templates/meal_planner.html`, check
the server is up and surface the `/meal-planner` URL for manual iPad testing.
State explicitly: "I cannot verify iPad drag-and-drop from here — please test
on device before committing."

### 6. Propose the commit

Draft a commit message following the repo style (see `git log --oneline -10`):

- Prefix: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`
- First line under 70 chars
- Body explains the *why*, not the *what*
- Footer: `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

Present the draft and wait for approval. **Do not commit without explicit
user confirmation** — the CLAUDE.md guidance is firm on this.

## Skip conditions

- Pure doc-only changes → skip step 2, 3, 5
- Tests-only changes → skip step 4, 5
- Config/plist changes → skip step 3, 5
