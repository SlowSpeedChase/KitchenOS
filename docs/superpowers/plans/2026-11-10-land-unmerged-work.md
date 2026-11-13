# Land Unmerged Work & Repair Silent Failures — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get every finished-but-unlanded KitchenOS feature safely onto `main`, fix the two production jobs that are failing silently, and leave the repo with one clean checkout and an honest backlog.

**Architecture:** This is an integration plan, not a feature build. Work proceeds in strict order: (A) make nothing losable, (B) repair production, (C) merge finished branches smallest-first through GitHub PRs, (D) clean up, (E) queue the remaining unbuilt features as separate plans. Every merge goes through a PR and the full unit suite; nothing is pushed straight to `main`.

**Tech Stack:** Python 3.11 (Flask, pytest, ruff) in `.venv/`; Swift package `KitchenOSKit` + XcodeGen app `KitchenOSSiri`; SQLite at `data/kitchenos.db`; macOS LaunchAgents in `ops/`; git worktrees; GitHub repo `SlowSpeedChase/KitchenOS` via `gh`.

**Written:** 2026-11-10, from a read-only review. Commit SHAs below were true at that time — **re-verify each one with the command given before acting on it.**

> **Revised 2026-11-10 (late):** a parallel session landed PR #82 (`fix/recipe-add-to-plan`) and PR #83 (`feat/print-recipes`) on `main`, and created the **live release branch** `release/mac-apple-plus-recipe-add` @ `80e8908`, which contains `21bf60b` (Mac Apple + calendar) and is what the production API runs. The map and tasks below reflect that. The API server is confirmed online.

## Global Constraints

- **Production does not run `main` or the main checkout.** The live API runs a staged release of branch `release/mac-apple-plus-recipe-add` under `~/Library/Application Support/KitchenOS API/rollouts/<name>/releases/<sha>` (runbook: `docs/OPERATIONS.md` → "Reviewed API releases"). That branch is ~50 commits ahead of `main`. **Deploying plain `main` would roll back live features.** Until Task C3 makes `main` contain the release branch, every fix that must reach the user goes: PR → `main`, then `git merge origin/main` into the release branch, then a HUMAN-run stage + activate. Read-only checks of `rollouts/*/activation-state.json` are allowed; nothing else under that directory is.

- **Repo root (main checkout):** `/Users/chaseeasterling/Dev/KitchenOS`. The folder `/Users/chaseeasterling/KitchenOS` is an unrelated orphan vault — never work there.
- **Never run a destructive git command** (`reset --hard`, `clean -fd`, `checkout -- .`, `stash drop`, `branch -D`, `worktree remove --force`, `push --force`) unless a step in this plan says so explicitly, and never before Phase A is complete.
- **Never touch live data:** do not write to `data/kitchenos.db`, `vault/`, or `.env`. Tests isolate the DB through the `tmp_db` fixture; if you run any script by hand from a worktree, set `KITCHENOS_DB` to a temp path first (a past incident created an empty DB and corrupted three recipes).
- **Never restart, load, or unload a LaunchAgent, and never run `scripts/deploy_api.py`.** Production activation is a HUMAN GATE.
- **All code changes happen in a linked worktree under `.worktrees/<name>`**, never in the main checkout.
- **Unit suite command:** `.venv/bin/python -m pytest -q` (e2e is deselected by default; expected baseline is roughly 4,200 passing, 0 failing — record the real number in Task A0).
- **Lint:** `.venv/bin/ruff check .` — the rule is *zero new errors versus `main`*, not zero errors.
- **Swift tests:** `cd KitchenOSKit && swift test`.
- **Read `CLAUDE.md` and `lib/CLAUDE.md` before any code change.** The invariants in `CLAUDE.md` § "Key Paths & Non-Negotiable Invariants" override this plan if they conflict.
- **Commit format:** `type: short description` (types: feat, fix, docs, test, refactor, chore), plus the co-author trailer your harness specifies.
- **Docs are part of done:** follow `docs/OPERATIONS.md` § 10 "Completing work" before each commit that changes behaviour.
- **STOP and report to the human** (do not improvise) when: a SHA in this plan does not match reality; a merge has conflicts you cannot resolve by reading both sides; the unit suite fails for a reason you did not cause; or a step is marked HUMAN GATE.

## Map of what exists (verified 2026-11-10)

| Work | Where | State |
|---|---|---|
| Main checkout | `Dev/KitchenOS`, branch `codex/calendar-meal-planning` @ `9a04e67` | 27 modified + ~30 untracked files. Most untracked files are **already committed** in `21bf60b`. Not what production runs |
| **Live release** | `.worktrees/release-recipe-add`, branch `release/mac-apple-plus-recipe-add` @ `80e8908` (pushed) | 50 ahead / 1 behind `origin/main`. Contains `21bf60b`, PR #82, PR #83. **Deployed** as rollout `print-recipes` |
| Mac Apple integration + calendar planning | `~/.codex/worktrees/mac-apple-integration/KitchenOS`, **detached HEAD** `21bf60b` | No longer at risk: `21bf60b` is an ancestor of the pushed release branch. Worktree still detached |
| Recipe Obsidian link fix | branch `fix/recipe-obsidian-link` @ `a166f39` | 1 commit, clean |
| Siri web navigation | branch `codex/siri-web-navigation` @ `40656fc` | stacked on `a166f39`; tip commit `40656fc` (docs) is NOT in `21bf60b` |
| Restore browser access | branch `codex/restore-browser-access` @ `4ba76c0` | stacked on `e5299e9`; fully inside `21bf60b` |
| Weekly cooking packet | `.worktrees/weekly-cooking-packet`, branch `codex/weekly-cooking-packet` @ `dedab44` | 15 commits + **11 modified, 9 untracked files uncommitted** |
| Recipe add-to-plan | `.worktrees/recipe-add-to-plan`, branch `fix/recipe-add-to-plan` @ `b948587` | **DONE** — committed, merged as PR #82, deployed. Clean |
| Print recipes | `.worktrees/print-recipes`, branch `feat/print-recipes` @ `88c046d` | **DONE** — merged as PR #83, deployed |
| OpenAI receipt parsing | `.worktrees/receipt-openai`, branch `codex/receipt-openai` | 0 commits ahead; **8 modified + 1 untracked uncommitted** (also duplicated in main checkout) |
| iOS 27 new Siri | `.worktrees/ios27-new-siri`, branch `ios27-new-siri` @ `e3e264b` | 17 commits, 33 behind `main`, awaiting on-device verification |
| Food density gaps | branch `food-density-gaps` @ `49625b0` | 1 commit, 33 behind |
| Kitchen briefing endpoint | branch `kitchen-briefing-endpoint` @ `1810334` | feature is live on `main` (squash-merged, PR #72); branch is leftover |
| Merged leftovers | `codex/receipt-openai`*, `feat/epub-import-compose-plates`, `freezer-rotation`, `home-web-gateway`, `home-web-gateway-launchd-wait`, `ingredient-text-fidelity`, `ios-print-share`, `move-cook-by-drag`, `pantry-spice-rack`, `phase-2/close-the-loops`, `plates`, `plates-ledger-native` | 0 commits ahead of `main` (*receipt-openai has uncommitted work — see above) |

Dry-run merges of every unmerged branch against the *earlier* `main` (`e72aafb`) reported **0 conflicts**. They were not re-run against the current `origin/main` (`6e9f482`) or against the release branch, and conflicts *between* branches were not checked — expect some in `api_server.py` and `templates/meal_planner.html`.

---

# Phase A — Make nothing losable

No task in Phase A changes any file's content. Finish all of Phase A before starting Phase B.

### Task A0: Record the baseline

**Files:** Create `docs/plans/2026-11-10-landing-log.md` (in the main checkout; it stays untracked until Task D3).

- [ ] **Step 1: Confirm the map is still true**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git fetch origin
git worktree list
git rev-parse main origin/main
git -C ~/.codex/worktrees/mac-apple-integration/KitchenOS rev-parse HEAD
```

Expected: `origin/main` is `6e9f482` or later (local `main` may lag behind it — that is fine, always use `origin/main`); the last command prints a SHA starting `21bf60b`. Also run `git rev-parse origin/release/mac-apple-plus-recipe-add` and `cat ~/Library/Application\ Support/KitchenOS\ API/rollouts/*/activation-state.json`, and record the release SHA and the active rollout name in the log. If `21bf60b` is not found, STOP and report.

- [ ] **Step 2: Record the unit-suite baseline on `main`**

```bash
git worktree add .worktrees/baseline origin/main --detach
cd .worktrees/baseline && ../../.venv/bin/python -m pytest -q 2>&1 | tail -5
../../.venv/bin/ruff check . 2>&1 | tail -1
cd ../.. && git worktree remove .worktrees/baseline
```

Expected: a line like `4207 passed, N deselected`. Write the exact pass count and the ruff error count into the landing log under a heading `## Baseline (main @ <sha>)`. These two numbers are the bar for every later task.

- [ ] **Step 3: Start the log**

The landing log has one section per task: task id, date, what was done, the SHA or PR URL produced, and anything surprising. Append to it at the end of every task in this plan.

### Task A1: Put the detached Mac Apple work on a branch

Low urgency now (the commits are reachable from the pushed release branch), but a named branch keeps cleanup simple. First confirm safety: `git -C /Users/chaseeasterling/Dev/KitchenOS merge-base --is-ancestor 21bf60b origin/release/mac-apple-plus-recipe-add && echo SAFE`.

- [ ] **Step 1: Create and push the branch**

```bash
cd ~/.codex/worktrees/mac-apple-integration/KitchenOS
git status --porcelain
git switch -c codex/mac-apple-integration
git push -u origin codex/mac-apple-integration
```

Expected: `git status --porcelain` shows only `?? AGENTS.md` and `?? output/`. `git switch -c` succeeds. Push creates the remote branch.

- [ ] **Step 2: Verify**

```bash
git -C /Users/chaseeasterling/Dev/KitchenOS branch --contains 21bf60b
```

Expected: lists `codex/mac-apple-integration` and `release/mac-apple-plus-recipe-add`.

### Task A2: Snapshot every dirty worktree to a backup branch on the remote

This creates a commit object holding the tracked changes **without altering the working tree**, plus a tarball of untracked files.

- [ ] **Step 1: Run the snapshot for each of the three dirty checkouts**

For each `(DIR, NAME)` pair below, run the block with the values substituted:

| DIR | NAME |
|---|---|
| `/Users/chaseeasterling/Dev/KitchenOS` | `main-checkout` |
| `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/weekly-cooking-packet` | `weekly-cooking-packet` |
| `/Users/chaseeasterling/Dev/KitchenOS/.worktrees/receipt-openai` | `receipt-openai` |

```bash
cd "$DIR"
mkdir -p ~/KitchenOS-backups-2026-11-10
SNAP=$(git stash create "snapshot $NAME 2026-11-10")
git branch "backup/2026-11-10-$NAME" "$SNAP"
git push origin "backup/2026-11-10-$NAME"
git ls-files --others --exclude-standard -z | tar --null -czf ~/KitchenOS-backups-2026-11-10/$NAME-untracked.tgz -T -
git status --porcelain | wc -l
```

Expected: `git stash create` prints a SHA (if it prints nothing, there were no tracked changes — skip the `git branch` and `git push` lines for that checkout). The final count is **unchanged** from before the block (61, 20, 9 respectively on 2026-11-10 — the main checkout's count includes this plan file) — `stash create` must not modify the working tree.

- [ ] **Step 2: Verify the tarballs are non-empty**

```bash
ls -la ~/KitchenOS-backups-2026-11-10/
tar -tzf ~/KitchenOS-backups-2026-11-10/weekly-cooking-packet-untracked.tgz | head
```

Expected: three `.tgz` files; the listing shows files such as `lib/cooking_packet_jobs.py`.

### Task A3: Commit the weekly-cooking-packet work in place

**Files:** all 20 changed paths in `.worktrees/weekly-cooking-packet` (11 modified, 9 untracked — see `git status`).

- [ ] **Step 1: Run that worktree's tests as they stand**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/weekly-cooking-packet
../../.venv/bin/python -m pytest -q tests/test_cooking_packet_builder.py tests/test_cooking_packet_store.py tests/test_cooking_packet_api.py tests/test_cooking_packet_jobs.py tests/test_cooking_packet_render.py tests/test_recipe_phases.py tests/test_web_dashboard.py 2>&1 | tail -5
```

Record the result in the log. **Do not fix failures in this task** — the goal is only to get the work committed.

- [ ] **Step 2: Commit as work-in-progress and push**

```bash
git add -A
git status --short
git commit -m "wip: cooking packet API, render, jobs and templates (uncommitted work as found 2026-11-10)"
git push -u origin codex/weekly-cooking-packet
```

Expected: `git status --short` before the commit lists only cooking-packet, `recipe_phases`, `conftest`, `web_dashboard` test, and docs paths. If anything unrelated appears (`.env`, `data/`, `vault/`), STOP — unstage it with `git restore --staged <path>` and report.

### Task A4: Commit receipt-openai in place

(`recipe-add-to-plan` was committed and merged by a parallel session as PR #82 — nothing to do there.)

- [ ] **Step 1: receipt-openai**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS/.worktrees/receipt-openai
git add -A && git status --short
git commit -m "wip: OpenAI receipt extraction (uncommitted work as found 2026-11-10)"
git push -u origin codex/receipt-openai
```

Expected: one new commit, pushed. Log the SHA.

### Task A5: Work out what in the main checkout is NOT already committed elsewhere

The commands below compare against `release/mac-apple-plus-recipe-add` — a superset of the Mac Apple work, and what is live. The main checkout's changes are a mixture of: (a) calendar-planning work already committed in the release branch, (b) the OpenAI-receipt work now committed in Task A4, and (c) possibly unique edits. This task classifies them. **It changes nothing in the main checkout.**

- [ ] **Step 1: Produce the three-way comparison**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
OUT=~/KitchenOS-backups-2026-11-10/main-checkout-classification.txt
: > "$OUT"
for f in $(git diff --name-only; git ls-files --others --exclude-standard); do
  a=DIFF; b=DIFF
  git cat-file -e "release/mac-apple-plus-recipe-add:$f" 2>/dev/null && git diff --quiet release/mac-apple-plus-recipe-add -- "$f" && a=SAME
  git cat-file -e "codex/receipt-openai:$f" 2>/dev/null && git diff --quiet codex/receipt-openai -- "$f" && b=SAME
  echo "$a-vs-apple $b-vs-receipt $f" >> "$OUT"
done
sort "$OUT"
```

- [ ] **Step 2: Classify each line**

- `SAME-vs-apple …` → already safe in the release branch. No action.
- `… SAME-vs-receipt …` → already safe in `codex/receipt-openai`. No action.
- `DIFF-vs-apple DIFF-vs-receipt <file>` → needs a human-readable look. For each such file run:

```bash
git diff release/mac-apple-plus-recipe-add -- "<file>" | head -80
```

  If the working copy is simply an *older* version of what the Apple branch has (the Apple branch has everything the working copy has, plus more), mark it `SUPERSEDED`. If the working copy has lines that exist in neither branch, mark it `UNIQUE`.

Expected on 2026-11-10: `UNIQUE` candidates are `AGENTS.md`, `docs/superpowers/plans/2026-09-05-calendar-opportunities.md`, `docs/superpowers/plans/2026-09-24-phone-surface-and-connectivity.md`, `docs/superpowers/specs/2026-10-09-food-observation-capture-design.md`, `config/item_aliases.json` (165 added lines), `config/storage_locations.json`, and possibly `lib/health_assertions.py`, `lib/inventory_db.py`, `lib/serving_ledger.py`, `lib/failure_logger.py`, `templates/meal_planner.html`.

- [ ] **Step 3: Write the classification into the landing log** as a table (`file | verdict | one-line reason`). Task C7 consumes this table. Do not act on it yet.

---

# Phase B — Repair production

### Task B1: HUMAN GATE — enrichment credits and Instagram capture

These need the human. Post this message and continue with Task B2 while waiting:

> 1. **Nightly enrichment** (`com.kitchenos.enrich`, 03:00) fails 215 of 470 recipes every night: Anthropic returns "credit balance is too low". Either add credits to the key in `.env` (`ANTHROPIC_API_KEY`), or tell me to disable the agent.
> 2. **Instagram capture** fails with a yt-dlp TLS error (installed `2026.6.9`). Please run `.venv/bin/pip install -U yt-dlp` in the main checkout, then re-share one failed reel.
> (Already answered 2026-11-10: the API server is online. `logs/server.log` stopped on 2026-09-27 only because production moved to the rollout release directory.)

Record the human's answers in the landing log.

### Task B2: Make a failing enrichment run visible on `/system-health`

The nightly enricher failed for weeks and nothing reported it. Add an assertion in the established pattern.

**Files:**
- Modify: `lib/health_assertions.py` (add `check_enrichment`; register it in `run_all`)
- Test: `tests/test_health_assertions.py`
- Docs: `docs/OPERATIONS.md` § 4 "Health checks" (one line)

**Interfaces:**
- Consumes: `_check(id, label, status, detail, consequence, fix="")`, constants `OK`, `FAILING`, `UNKNOWN` — all already in `lib/health_assertions.py`.
- Consumes: `logs/enrich-latest.json` — a JSON list of `{"file": str, "status": "complete" | "error", "error": str (only when status is "error")}`.
- Produces: `check_enrichment(report_path: Path | None = None) -> dict` with `id == "enrichment"`.

- [ ] **Step 0: Create the worktree**

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git worktree add .worktrees/enrichment-health -b fix/enrichment-health main
cd .worktrees/enrichment-health
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_health_assertions.py`:

```python
import json


class TestEnrichment:
    def _write(self, tmp_path, rows):
        p = tmp_path / "enrich-latest.json"
        p.write_text(json.dumps(rows), encoding="utf-8")
        return p

    def test_all_complete_is_ok(self, tmp_path):
        p = self._write(tmp_path, [{"file": "a.md", "status": "complete"},
                                   {"file": "b.md", "status": "complete"}])
        assert ha.check_enrichment(p)["status"] == ha.OK

    def test_many_errors_are_failing_and_counted(self, tmp_path):
        rows = [{"file": f"{i}.md", "status": "complete"} for i in range(5)]
        rows += [{"file": f"e{i}.md", "status": "error",
                  "error": "Error code: 400 - credit balance is too low"}
                 for i in range(5)]
        c = ha.check_enrichment(self._write(tmp_path, rows))
        assert c["status"] == ha.FAILING
        assert "5 of 10" in c["detail"]
        assert c["consequence"]
        assert c["fix"]

    def test_credit_exhaustion_is_named_in_the_fix(self, tmp_path):
        rows = [{"file": "e.md", "status": "error",
                 "error": "Your credit balance is too low to access the API"}]
        c = ha.check_enrichment(self._write(tmp_path, rows))
        assert "credit" in c["fix"].lower()

    def test_a_single_error_is_not_a_failure(self, tmp_path):
        rows = [{"file": f"{i}.md", "status": "complete"} for i in range(99)]
        rows.append({"file": "e.md", "status": "error", "error": "timeout"})
        assert ha.check_enrichment(self._write(tmp_path, rows))["status"] == ha.OK

    def test_missing_report_is_unknown(self, tmp_path):
        assert ha.check_enrichment(tmp_path / "nope.json")["status"] == ha.UNKNOWN

    def test_unreadable_report_is_unknown_not_a_crash(self, tmp_path):
        p = tmp_path / "enrich-latest.json"
        p.write_text("{not json", encoding="utf-8")
        assert ha.check_enrichment(p)["status"] == ha.UNKNOWN

    def test_run_all_includes_enrichment(self):
        ids = [c["id"] for c in ha.run_all()["checks"]]
        assert "enrichment" in ids
```

- [ ] **Step 2: Run to verify they fail**

Run: `../../.venv/bin/python -m pytest tests/test_health_assertions.py -k Enrichment -q`
Expected: 7 failures, `AttributeError: module 'lib.health_assertions' has no attribute 'check_enrichment'`.

- [ ] **Step 3: Implement**

Add `import json` to the imports at the top of `lib/health_assertions.py`. Add this function directly above `def _ago(`:

```python
#: Share of recipes that may error in one nightly run before it counts as broken.
#: A handful of bad files is normal; the observed failure was 215 of 470.
ENRICH_ERROR_SHARE = 0.05


def check_enrichment(report_path: Path | None = None) -> dict:
    """Did last night's enrichment run actually enrich anything?

    Reads the report the enricher itself wrote, for the same reason
    ``check_share_sheet_capture`` reads a log: the job runs in its own
    LaunchAgent, and the only honest evidence is what that job recorded.
    """
    label = "Nightly recipe enrichment"
    try:
        path = Path(report_path) if report_path else \
            Path(__file__).resolve().parent.parent / "logs" / "enrich-latest.json"
        if not path.exists():
            return _check("enrichment", label, UNKNOWN, "no enrichment report yet",
                          "Unknown whether new recipes are getting their metadata.")
        rows = json.loads(path.read_text(encoding="utf-8"))
        total = len(rows)
        errors = [r for r in rows if r.get("status") == "error"]
    except Exception as e:
        return _check("enrichment", label, UNKNOWN, f"could not read report: {e}",
                      "Unknown whether new recipes are getting their metadata.")

    if total == 0 or len(errors) / total <= ENRICH_ERROR_SHARE:
        return _check("enrichment", label, OK,
                      f"{total - len(errors)} of {total} recipes processed",
                      "")
    out_of_credit = any("credit balance" in str(r.get("error", "")).lower()
                        for r in errors)
    fix = ("Add credits to the Anthropic account behind ANTHROPIC_API_KEY, "
           "or disable the com.kitchenos.enrich agent."
           if out_of_credit else
           "Read logs/enrich.log for the repeated error.")
    return _check(
        "enrichment", label, FAILING,
        f"{len(errors)} of {total} recipes errored in the last run",
        "New recipes are missing the metadata that filters, Cook Now and the "
        "planner rely on, and the job reports nothing.",
        fix)
```

In `run_all`, add one line to the tuple of lambdas, after `lambda: check_server_freshness(),`:

```python
        lambda: check_enrichment(),
```

- [ ] **Step 4: Run to verify they pass**

Run: `../../.venv/bin/python -m pytest tests/test_health_assertions.py -q`
Expected: all pass, including the 7 new ones. If an existing test pins the *number* of checks `run_all` returns, update that number by exactly one in the same commit.

- [ ] **Step 5: Full suite, lint, docs**

Run: `../../.venv/bin/python -m pytest -q 2>&1 | tail -3` → baseline + 7 passing, 0 failing.
Run: `../../.venv/bin/ruff check . 2>&1 | tail -1` → not higher than the baseline count.
In `docs/OPERATIONS.md` § 4, add: ``- `enrichment` — fails when more than 5% of recipes errored in the last nightly `enrich` run (reads `logs/enrich-latest.json`).``

- [ ] **Step 6: Commit, push, open PR**

```bash
git add lib/health_assertions.py tests/test_health_assertions.py docs/OPERATIONS.md
git commit -m "feat(health): report a failing nightly enrichment run"
git push -u origin fix/enrichment-health
gh pr create --draft --title "feat(health): report a failing nightly enrichment run" --body "Nightly enrichment errored on 215 of 470 recipes for weeks (Anthropic credit exhaustion) with no signal. Adds a /system-health assertion that reads logs/enrich-latest.json. 7 new tests."
```

Merging is covered by the rule in Phase C "How to land one branch". This fix only reaches the live `/system-health` page after step 9 of that procedure (merge into the release branch + human deploy).

### Task B3: Mark the capture-queue retry cap as shipped

`batch_extract.py` already has `_load_retry_tracker`, `_should_dead_letter`, and `_dead_letter`, and `logs/dead_letter.json` has a real entry from 2026-10-07 — but `docs/plans/INDEX.md` still lists `capture-queue-retry-cap` under **Vision** as "blocked on three decisions".

**Files:** Modify `docs/plans/INDEX.md`; modify `docs/plans/capture-queue-retry-cap.md`.

- [ ] **Step 1: Find the commit that shipped it** (in the `fix/enrichment-health` worktree or a new `docs/retry-cap-status` worktree off `main`)

```bash
git log --oneline -S"_should_dead_letter" -- batch_extract.py | tail -1
```

- [ ] **Step 2: Confirm it is tested**

Run: `../../.venv/bin/python -m pytest -q -k "dead_letter or retry" 2>&1 | tail -3`
Expected: some tests selected, all passing. If zero tests are selected, STOP and report — the feature is unpinned and needs a test task added.

- [ ] **Step 3: Move the row** from the `## Vision` table to the top of the `## Done` table in `docs/plans/INDEX.md`, using the columns `Date | Doc | Completed | Notes`, with Completed = the commit date and short SHA from Step 1, and Notes = "Attempt counter in `logs/retry_tracker.json`, category-aware cap, dead-letter to `logs/dead_letter.json`. First real dead-letter 2026-10-07." Add a first line `**Status: shipped — see docs/plans/INDEX.md Done.**` to `capture-queue-retry-cap.md`.

- [ ] **Step 4: Commit** — `git commit -am "docs: record the capture-queue retry cap as shipped"`; push; open a draft PR.

---

# Phase C — Land the finished branches

## How to land one branch (the procedure every Task C* uses)

1. `cd` into that branch's worktree (create one with `git worktree add .worktrees/<name> <branch>` if none exists).
2. `git fetch origin && git merge origin/main` — **merge, do not rebase** (these branches are pushed and stacked). Resolve conflicts only when both sides are understandable; otherwise STOP.
3. Run `../../.venv/bin/python -m pytest -q 2>&1 | tail -3`. Must be ≥ the current `main` pass count with 0 failures.
4. Run `../../.venv/bin/ruff check . | tail -1`. Must be ≤ the `main` error count.
5. If any file under `KitchenOSKit/` or `KitchenOSSiri/` changed versus `main`: `cd KitchenOSKit && swift test`. Must pass.
6. `git push`, then `gh pr create` (or `gh pr ready` if a draft exists). PR body: what it does, test counts, and any HUMAN GATE that remains.
7. **HUMAN GATE: the human merges the PR.** Do not merge it yourself. After the merge, run `git fetch origin` and use `origin/main` (not local `main`) as the reference for all later tasks. Do not move the local `main` branch or touch the main checkout — that happens once, in Task C7 Step 3.
8. Re-record the `origin/main` pass count in the landing log; it is the new bar.
9. **Carry it to production (until Task C3 is merged).** In `.worktrees/release-recipe-add`: `git pull && git merge origin/main`, run the unit suite, `git push`. Then **HUMAN GATE**: post "Release branch is at `<sha>`; ready to stage + activate under a new rollout root per `docs/OPERATIONS.md` 'Reviewed API releases'." Do not run `scripts/deploy_api.py`. Batch several merged PRs into one deploy request where possible.

Land in the order below. Each task starts only after the previous PR is merged.

### Task C1: `food-density-gaps` (smallest, independent)

- [ ] Follow the procedure. Worktree: `.worktrees/food-density-gaps`. One commit, 5 files, nutrition density table.
- [ ] Extra check: `../../.venv/bin/python -m pytest -q tests -k "density" | tail -3` passes.

### Task C2: `fix/recipe-obsidian-link` → then `codex/siri-web-navigation`

These are stacked: `a166f39` → `e5299e9` → `40656fc`.

- [ ] Land `fix/recipe-obsidian-link` (worktree `~/.codex/worktrees/recipe-browser-access/KitchenOS`) by the procedure.
- [ ] Then land `codex/siri-web-navigation` (worktree `~/.codex/worktrees/siri-web-release/KitchenOS`). Its `BRANCH-STATUS.md` is a stale copy from another branch — ignore it. Swift tests are required (step 5).
- [ ] HUMAN GATE in the PR body: "Siri → browser navigation needs one on-device check: say the recipe-open phrase and confirm the recipe page opens."

### Task C3: Make `main` contain the live release (the large one)

**Land `release/mac-apple-plus-recipe-add`, not `codex/mac-apple-integration`.** The release branch is a superset (Mac Apple bridge, calendar-meal-planning, `codex/restore-browser-access`, PR #82, PR #83) and is already running in production, so this PR changes nothing for the user — it ends the split where `main` is behind what is deployed. Work in `.worktrees/release-recipe-add`. After this merges, step 9 of the landing procedure becomes a plain fast-forward and `main` is deployable again.

- [ ] **Step 1:** Read `docs/superpowers/specs/2026-10-08-mac-apple-integration-design.md`, `docs/superpowers/plans/2026-10-08-mac-apple-integration.md`, and `docs/superpowers/plans/2026-09-19-calendar-meal-planning.md` *on that branch*. List every unchecked `- [ ]` box from the two plan files into the landing log.
- [ ] **Step 2:** For each unchecked box, decide: *done in code but box not ticked* (verify by finding the code and its test, then tick it), or *genuinely not done*. Do not implement anything yet.
- [ ] **Step 3:** If any box is genuinely not done, STOP and report the list. The human decides whether to finish before merge or merge with it documented as follow-up.
- [ ] **Step 4:** Follow the landing procedure (open the PR from `release/mac-apple-plus-recipe-add` into `main`; ask the human to use a **merge commit, not squash**, so the deployed SHAs stay ancestors of `main`). Additionally run the e2e files this branch adds, per `docs/OPERATIONS.md` § 7: `../../.venv/bin/pytest tests/e2e/test_planning_calendar.py tests/e2e/test_cooking_availability.py -m e2e -v` (needs a live server — if the harness cannot start one, record "e2e not run" in the PR body rather than skipping silently).
- [ ] **Step 5:** PR body must state the HUMAN GATES recorded in that branch's commit history: Shortcuts signing acceptance, and "production activation remains a separate rollout step".
- [ ] **Step 6:** After merge, confirm `git merge-base --is-ancestor 80e8908 origin/main` exits 0. Then `codex/restore-browser-access` and `codex/mac-apple-integration` are deletable in Task D1. **Keep `release/mac-apple-plus-recipe-add`** — rollouts roll back to SHAs on it; the human decides when to retire it.

### Task C4: `codex/receipt-openai`

- [ ] **Step 1:** In `.worktrees/receipt-openai`, run `../../.venv/bin/python -m pytest -q tests/test_receipt_openai.py tests/test_receipt_parser.py | tail -3`. Fix failures only if the cause is inside the 9 files this branch touches.
- [ ] **Step 2:** Confirm no test makes a real network call: `grep -n "OpenAI(\|openai\." tests/test_receipt_openai.py` — every client must be a mock/fake. If a real call exists, replace it with a `unittest.mock.patch` of the client constructor and assert on the request it was given.
- [ ] **Step 3:** Confirm `.env.example` documents every new variable the code reads: `grep -n "environ" lib/receipt_parser.py ingest_receipts.py`. Each name found must appear in `.env.example`.
- [ ] **Step 4:** Reword the WIP commit: `git commit --amend -m "feat(receipts): optional OpenAI receipt extraction"` is allowed **only if** Task A4's push is the only commit and nobody else has pulled it; otherwise add a normal follow-up commit. Then follow the landing procedure.

### Task C5: `fix/recipe-add-to-plan` — DONE

Merged as PR #82 and deployed by a parallel session. Only check: `git merge-base --is-ancestor b948587 origin/main && echo MERGED`. If it prints `MERGED`, tick this task and move on.

### Task C6: `codex/weekly-cooking-packet`

- [ ] **Step 1:** Read `docs/superpowers/plans/2026-09-26-weekly-cooking-packet.md` on the branch. List unchecked boxes in the landing log, and classify each as in Task C3 Step 2.
- [ ] **Step 2:** Run the seven test files from Task A3 Step 1. All must pass. A failure inside cooking-packet code is in scope to fix (test-first: reproduce with a failing test, fix, re-run).
- [ ] **Step 3:** Verify the non-negotiable from `CLAUDE.md`: **no page render may block on an LLM.** Run `grep -n "anthropic\|ollama\|llm_gate" lib/cooking_packet_*.py`. Any model call reachable from a Flask route must go through `llm_gate.allowed()` and `llm_gate.budget_s(...)`. If `lib/cooking_packet_jobs.py` runs model calls off-request, confirm the route only enqueues/reads and never waits.
- [ ] **Step 4:** New routes must be either token-gated or added to `KNOWN_UNGATED` in `tests/test_api_auth.py` — run `../../.venv/bin/python -m pytest -q tests/test_api_auth.py`; prefer gating.
- [ ] **Step 5:** Docs per § 10: routes in `docs/API.md`; the new page in `SECTIONS` (`lib/web_dashboard.py`); any new DB table in `docs/ARCHITECTURE.md`.
- [ ] **Step 6:** If Step 1 left genuinely-unbuilt boxes, STOP and report them. Otherwise follow the landing procedure.

### Task C7: Resolve the main checkout

Uses the classification table from Task A5.

- [ ] **Step 1:** For every `UNIQUE` file, create a worktree off `origin/main` and bring the change in:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
git worktree add .worktrees/main-checkout-leftovers -b chore/main-checkout-leftovers origin/main
cd .worktrees/main-checkout-leftovers
# for each UNIQUE file:
cp "/Users/chaseeasterling/Dev/KitchenOS/<file>" "<file>"
git diff -- "<file>"
```

  Keep the copy only if the diff shows the unique lines and nothing that reverts newer work on `main`. If the diff also removes lines `main` gained from C1–C6, do not copy the whole file — apply only the unique hunks by hand. Commit in logical groups:
  - `chore(config): item aliases and storage locations learned in use` (`config/item_aliases.json`, `config/storage_locations.json`)
  - `docs: add calendar-opportunities, phone-surface plans and food-observation spec`
  - `docs: track AGENTS.md` — only after Task D2.
  - any `lib/` or `templates/` hunks: one commit each, with a test if behaviour changes.

- [ ] **Step 2:** Follow the landing procedure for `chore/main-checkout-leftovers`.
- [ ] **Step 3: HUMAN GATE — switch the main checkout back to `main`.** Post: "Everything in the main checkout is now on `origin/main` or in `backup/2026-11-10-main-checkout` plus `~/KitchenOS-backups-2026-11-10/main-checkout-untracked.tgz`. To finish, run in `Dev/KitchenOS`: `git stash push --include-untracked -m 'pre-main-switch 2026-11-10'`, then `git switch main`, then `git pull`. The eight non-API LaunchAgents (batch extract, enrich, meal plan, calendar sync, …) run from this folder and will pick up `main`'s code on their next run; the API is unaffected because it runs from the rollout release." Do not run these yourself.

### Task C8: `ios27-new-siri` (do last; needs a device)

- [ ] **Step 1:** In `.worktrees/ios27-new-siri`, `git merge origin/main`. This branch is the furthest behind and touches `KitchenOSKit`, which C2 and C3 also changed — expect Swift conflicts. Resolve by keeping both features; if a conflict is in `Package.swift` deployment targets, the higher floor (iOS 27 / macOS 27) wins only if the human confirms in Step 3.
- [ ] **Step 2:** `cd KitchenOSKit && swift test` and the full Python suite.
- [ ] **Step 3: HUMAN GATE.** This branch raises the deployment floor to iOS 27 / macOS 27 and its own notes say Siri phrase routing was broken at OS level on the beta. Ask: "Is iOS 27 GA on your devices, and do you want the floor raised now? If not, this branch stays parked." Do not open a ready-for-review PR without a yes. Slice 2 (on-phone SwiftData store) is out of scope here — see Phase E.

---

# Phase D — Clean up

### Task D1: Remove merged branches and worktrees

- [ ] **Step 1:** For each branch in the "Merged leftovers" row of the map, plus every branch landed in Phase C, verify then delete:

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
B=<branch>
test "$(git rev-list --count origin/main..$B)" = "0" && echo SAFE || echo "NOT MERGED - skip"
```

  Only when it prints `SAFE` **and** `git -C <its worktree> status --porcelain` is empty:

```bash
git worktree remove <worktree path>
git branch -d "$B"
git push origin --delete "$B"
```

  Use `-d`, never `-D`. Squash-merged branches fail the count test — for those, STOP and list them for the human instead of forcing.

- [ ] **Step 2:** `kitchen-briefing-endpoint` (squash-merged as PR #72): confirm `git diff origin/main kitchen-briefing-endpoint -- lib/kitchen_briefing.py` shows `main` is a superset (only additions on the `main` side), then list it for human deletion.
- [ ] **Step 3:** Stale remote-only branches (`origin/agent-display-names`, `origin/chore/ingredient-audit`, `origin/claude/refine-local-plan-*`, `origin/e2e-harness-and-cold-sidecar`, `origin/inventory-location-visibility`, `origin/planner-*`, `origin/recipe-*`, `origin/stale-server-detection`, `origin/verify-merged-batch-tests`, `origin/week-date-ranges`): for each, check whether its subject line appears in `git log origin/main --oneline`. Report a table (`branch | merged-by-squash? | last commit date`) and let the human delete.
- [ ] **Step 4:** Do **not** delete `release/mac-apple-plus-recipe-add`, its worktree `.worktrees/release-recipe-add`, the `backup/2026-11-10-*` branches or `~/KitchenOS-backups-2026-11-10/`. The human removes those.

### Task D2: Reconcile `AGENTS.md` with `CLAUDE.md`

`AGENTS.md` (untracked, ~40 KB, last edited 2026-09-05) is a drifted copy of `CLAUDE.md` (2026-09-02).

- [ ] **Step 1:** `diff <(sed 's/CLAUDE/AGENT/g' CLAUDE.md) <(sed 's/CLAUDE\|AGENTS/AGENT/g' AGENTS.md) | head -100`
- [ ] **Step 2:** Port every invariant that exists only in `AGENTS.md` into `CLAUDE.md`.
- [ ] **Step 3:** Replace `AGENTS.md` with a three-line file: a title, and "All project rules live in `CLAUDE.md`. Read that file in full." Check `scripts/check_claude_md_drift.sh` still passes: `bash scripts/check_claude_md_drift.sh`.
- [ ] **Step 4:** Commit both in the `chore/main-checkout-leftovers` worktree (Task C7).

### Task D3: Repo hygiene

In a worktree off `origin/main`, branch `chore/repo-hygiene`:

- [ ] Delete the three stale `BRANCH-STATUS.md` copies' *tracked source* if `BRANCH-STATUS.md` is tracked at the repo root on `main` (`git ls-files BRANCH-STATUS.md`): `git rm BRANCH-STATUS.md`, commit `chore: remove stale branch status from main`.
- [ ] Add to `.gitignore` if missing: `output/`, `tmp/`, `.playwright-mcp/`, `.codex/`, `.agents/`, `failure_analysis.log`, `failures/`, `.build-device/`. Verify with `git check-ignore -v output tmp`.
- [ ] Remove the `ComingSoonView` fallback in `KitchenOSSiri/Sources/Shell/AppShell.swift:53-59` only if the `switch` in `detail(for:)` is exhaustive without it (the Swift compiler will say). If not exhaustive, leave it and note why.
- [ ] Commit `docs/plans/2026-11-10-landing-log.md` and this plan.
- [ ] Report (do not delete) for the human: `data/kitchenos.db.bak-*` and `*.pre-claude-reprocess.bak*` (five old DB backups), `vault/KitchenOS/Meal Plans/2099-W20.tasks.json` (test artifact in the live vault), `.build-xcode/` (302 MB), and the orphan folder `/Users/chaseeasterling/KitchenOS`.

### Task D4: Bring the status documents up to date

- [ ] `docs/plans/INDEX.md`: add a **Done** row for each feature landed in Phase C (date, spec/plan links, PR link, one-paragraph note with test counts), newest first. Move `macro-meal-planner` out of **In Progress** into **Done** with the note "partially delivered; weekly bin-packing planner parked" — it has had no branch since July.
- [ ] `docs/ROADMAP.md`: add dated entries under "Done / Shipped" for the same features; strike the "CoreSpotlight ingredient-keyword enrichment" item only if C8 merged.
- [ ] For each landed feature, add `docs/completed/<merge-date>-<name>.md` following the shape of `docs/completed/2026-09-02-truthful-shopping-inventory.md`.

---

# Phase E — Remaining unbuilt work (separate plans, one at a time)

Nothing below is implemented by this plan. Each item needs its own spec → plan → branch, using the repo's existing flow (`docs/plans/INDEX.md`: Vision → Ready → In Progress → Done). **Do not start any of these until Phases A–D are complete.** For each, the first action is to write a plan with `superpowers:writing-plans` from the named source document.

Recommended order (highest daily value first):

| # | Item | Source of truth | Why this order |
|---|---|---|---|
| E1 | **Audit Phase 4 — make the shopping list true** (container-aware crediting; staple-aware list; expired stock excluded from credits; un-trap `prune_expired`) | `docs/plans/2026-08-02-daily-driver-audit.md` §4 items 20–22. First check which parts PRs #78/#79 already delivered. | Used every week |
| E2 | **Audit Phase 3 — fix the nutrition numbers** (re-band portion ledger; `resolution_guard.vet` on the fdc-local path so "egg" resolves to whole raw egg; frying-medium rule; corpus cleanup) | same doc, items 16–19 | ~140 recipes carry wrong macros |
| E3 | **Gate the remaining API routes and send the bearer token from browser pages** | `KNOWN_UNGATED` in `tests/test_api_auth.py`; note in `docs/plans/INDEX.md` plates-ledger-native row | Security debt, now pinned by a test |
| E4 | **iOS app stamps every added inventory row `manual`** | `docs/plans/INDEX.md` inventory-location-visibility row; `KitchenOSSiri/Sources/Inventory/InventoryView.swift` | Small, flagged "should be next" in July |
| E5 | **Audit Phase 5 — retire the legacy markdown week model; collapse nav** | same audit doc items 23, 25; Decisions B and D need the human | Removes the two-model tax; needs decisions |
| E6 | **Food observation capture** | `docs/superpowers/specs/2026-10-09-food-observation-capture-design.md` (lands in C7) | Spec exists, no plan |
| E7 | **Calendar opportunities / phone surface & connectivity** | `docs/superpowers/plans/2026-09-05-calendar-opportunities.md`, `…2026-09-24-phone-surface-and-connectivity.md` — check what C3 already delivered first | Plans exist; overlap with C3 unknown |
| E8 | **Planner polish** (dense board overflow; bottom dock covering the last row; placed vs unplaced chip; recipe view layout) | `docs/ROADMAP.md` "Usage feedback — 2026-07-31" and "2026-08-01" sections | UI polish |
| E9 | **Split `api_server.py`** (3,859 lines) into Flask blueprints by area | none — write a spec first; behaviour-preserving refactor, route table must be byte-identical | Do only when nothing else is in flight |
| E10 | **Parked / low priority:** iOS 27 Siri slice 2 (on-phone store), zone → shelf inventory layout, printable kitchen labels, purchase-based nutrition, weekly bin-packing planner | `docs/ROADMAP.md`; `docs/plans/purchase-based-nutrition.md` | Explicitly parked; revisit after E1–E5 |

---

## Definition of done for this plan

- `git worktree list` shows the main checkout on `main` plus only worktrees with active work.
- `git branch --no-merged origin/main` lists only `ios27-new-siri` (if parked), `backup/2026-11-10-*`, `release/*` (only if it has commits not yet merged back), and anything the human chose to keep.
- `origin/main` unit suite: 0 failures, pass count ≥ baseline + every test added in Phases B and C.
- The **live** `/system-health` shows an `enrichment` check (verify the deployed SHA via the `X-KitchenOS-Release` header on `/health`).
- `git merge-base --is-ancestor <live release SHA> origin/main` exits 0 — `main` contains everything that is deployed.
- `docs/plans/INDEX.md` has no row under **In Progress** without a live branch.
- The landing log lists every HUMAN GATE with its answer.
