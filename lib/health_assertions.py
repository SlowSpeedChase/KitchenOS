"""Assertions for the failures that don't announce themselves.

The 2026-08-02 audit found ten defects across every stage of KitchenOS, and
what they had in common mattered more than any one of them: **not one produced
an error.** A TCC denial returns an empty directory listing. A missing `claude`
binary exits into a log while the caller prints "triggered in background". A
disabled suggester returns early with no toast. Wrong macros ship as
`coverage: 1.0`. The system was built to degrade gracefully and had degraded so
far that it no longer said so.

`/system-health` reported services as "ok" through all of it, because it
checked whether things were *running*, not whether they were *working*.

Each assertion here therefore carries three fields beyond its status:

- ``detail`` — what is actually true right now, with numbers.
- ``consequence`` — what silently stops working when this fails. This is the
  field that matters. "No Reminders stores readable" means nothing; "every
  recipe you share from your phone is discarded" is the same fact, usable.
- ``fix`` — the next action, including when that action is the user's rather
  than the code's (a Full Disk Access grant cannot be made from here).

Every check degrades to ``unknown`` rather than raising: a health page that
500s because one probe failed is the same class of bug it exists to catch.
"""

from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path

OK = "ok"
FAILING = "failing"
UNKNOWN = "unknown"

#: Consecutive all-zero batch runs before the capture queue counts as jammed.
#: Two is noise (an empty list, one bad link); the observed failure was 719.
JAMMED_RUN_THRESHOLD = 3


def _check(id, label, status, detail, consequence, fix=""):
    return {
        "id": id,
        "label": label,
        "status": status,
        "detail": detail,
        "consequence": consequence,
        "fix": fix,
    }


#: What lib/reminders_url logs when its store listing comes back empty.
FDA_DENIAL_MARKER = "lacks Full Disk Access"

#: Lines of batch_extract.log to consider "recent". A run logs a few dozen.
_LOG_TAIL_LINES = 400


def check_share_sheet_capture(log_path: Path | None = None) -> dict:
    """Can the *batch extractor* read share-sheet URLs out of Reminders?

    Share-sheet links live in a Reminders Core Data attachment, not in the
    reminder's title, URL field or notes. Reading it needs Full Disk Access on
    whatever launchd execs — the launcher shim, not the interpreter. A denial
    is not an exception: the directory stats fine and its listing comes back
    empty, which is indistinguishable from "no links saved".

    **This reads batch-extract's log rather than probing the store directly**,
    because TCC grants are per-executable and this code runs inside the *API*
    LaunchAgent. Probing from here answers "can the API server read Reminders",
    which is a different process with a different grant and is not the job that
    fails. The only honest evidence about batch-extract is what batch-extract
    itself recorded.
    """
    try:
        path = Path(log_path) if log_path else \
            Path(__file__).resolve().parent.parent / "logs" / "batch_extract.log"
        if not path.exists():
            return _check(
                "share_sheet_capture", "Share-sheet capture can read Reminders",
                UNKNOWN, "no batch-extract log yet",
                "Unknown whether phone captures are reaching the extractor.")
        tail = path.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = tail[-_LOG_TAIL_LINES:]
        denied = sum(1 for line in recent if FDA_DENIAL_MARKER in line)
    except Exception as e:
        return _check(
            "share_sheet_capture", "Share-sheet capture can read Reminders",
            UNKNOWN, f"probe failed: {e}",
            "Unknown whether phone captures are reaching the extractor.")

    if not denied:
        return _check("share_sheet_capture",
                      "Share-sheet capture can read Reminders", OK,
                      "no Full Disk Access denials in recent runs", "", "")
    return _check(
        "share_sheet_capture", "Share-sheet capture can read Reminders",
        FAILING, f"{denied} Full Disk Access denial(s) in recent runs",
        "Every recipe shared from the phone is filed as 'Not a URL' and "
        "retried hourly, forever. This is the whole phone capture path.",
        "Grant Full Disk Access to 'ops/agents/KitchenOS · Batch Extract' — "
        "the shim launchd execs, not .venv/bin/python, and not this API "
        "server. Verify functionally; a TCC denial looks like success with "
        "empty results.",
    )


def check_capture_queue(run_logs: list) -> dict:
    """Is the extraction queue draining, or retrying the same items forever?

    ``batch_extract`` leaves a failed or unparseable reminder unchecked so the
    next run retries it, and keeps no attempt counter — so a permanently dead
    item is indistinguishable from a transient one and is reprocessed every
    hour indefinitely.
    """
    if not run_logs:
        return _check("capture_queue", "Extraction queue is draining",
                      UNKNOWN, "no run logs found",
                      "Unknown whether captured links are being processed.")

    recent = run_logs[:JAMMED_RUN_THRESHOLD]
    stuck = [r for r in recent
             if (r.get("succeeded") or 0) == 0 and (r.get("total") or 0) > 0]
    if len(stuck) >= min(JAMMED_RUN_THRESHOLD, len(recent)) and stuck:
        worked = sum(r.get("total") or 0 for r in stuck)
        return _check(
            "capture_queue", "Extraction queue is draining",
            FAILING,
            f"last {len(stuck)} run(s) captured nothing from {worked} attempt(s)",
            "The same items are being retried every hour and will never "
            "succeed. Real failures are buried in the repetition.",
            "Resolve the underlying capture fault, then give the queue a "
            "retry cap and a dead-letter path so dead items leave it.",
        )
    return _check("capture_queue", "Extraction queue is draining", OK,
                  f"{len(run_logs)} recent run(s), most recent captured "
                  f"{run_logs[0].get('succeeded', 0)}", "", "")


def check_instagram_cookies(failure_logs: list) -> dict:
    """Instagram needs a logged-in session; without cookies it is 0%."""
    configured = bool(os.getenv("INSTAGRAM_COOKIES_FROM_BROWSER")
                      or os.getenv("INSTAGRAM_COOKIES_FILE"))
    if configured:
        return _check("instagram_cookies", "Instagram capture is configured",
                      OK, "cookie source configured", "", "")

    hits = sum(1 for f in failure_logs
               if "instagram" in str(f.get("error", "")).lower()
               or "instagram" in str(f.get("url", "")).lower())
    if not hits:
        return _check("instagram_cookies", "Instagram capture is configured",
                      UNKNOWN, "no cookie source set; no recent Instagram attempts",
                      "Any Instagram link shared will fail.",
                      "Set INSTAGRAM_COOKIES_FROM_BROWSER in .env if you save Reels.")
    return _check(
        "instagram_cookies", "Instagram capture is configured",
        FAILING, f"no cookie source set; {hits} recent Instagram failure(s)",
        "Every Instagram Reel shared is discarded. It cannot succeed without "
        "a logged-in session.",
        "Set INSTAGRAM_COOKIES_FROM_BROWSER=safari (or chrome) in .env, and be "
        "signed in to instagram.com in that browser.",
    )


def check_nutrition_plausibility(recipes_dir: Path) -> dict:
    """How many recipes claim per-serving macros that cannot be true?

    These are excluded from planning rather than trusted, so this is a backlog
    figure, not an active lie — but it is the size of the correctness debt.
    """
    try:
        from lib import nutrition_quality, recipe_parser
        total = 0
        bad = 0
        for path in Path(recipes_dir).glob("*.md"):
            fm = recipe_parser.parse_recipe_file(
                path.read_text(encoding="utf-8"))["frontmatter"]
            if fm.get("nutrition_calories") is None:
                continue
            total += 1
            if nutrition_quality.implausible(fm)[0]:
                bad += 1
    except Exception as e:
        return _check("nutrition_plausibility", "Recipe macros are plausible",
                      UNKNOWN, f"probe failed: {e}",
                      "Unknown how much of the corpus is unusable for planning.")

    if not total:
        return _check("nutrition_plausibility", "Recipe macros are plausible",
                      UNKNOWN, "no recipes carry nutrition data", "")
    if not bad:
        return _check("nutrition_plausibility", "Recipe macros are plausible",
                      OK, f"0 of {total} outside plausible bounds", "", "")
    return _check(
        "nutrition_plausibility", "Recipe macros are plausible",
        FAILING, f"{bad} of {total} ({bad / total:.0%}) outside plausible bounds",
        "These recipes are refused by the suggester and excluded from day "
        "totals, so planning has a smaller pool than the library suggests.",
        "Work the /nutrition-review queue — it is now ordered worst-first.",
    )


def check_inventory_consumption() -> dict:
    """Does cooking ever reduce or use-stamp the pantry?

    Inventory is incremented by receipts and decremented only by an explicit
    shopping-list confirm whose UI trigger is unreachable. If nothing has ever
    been use-stamped, the kitchen's state only ever grows.
    """
    try:
        from lib import inventory_db
        conn = inventory_db.read_conn()
        rows = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        used = conn.execute(
            "SELECT COUNT(*) FROM inventory "
            "WHERE last_used IS NOT NULL OR COALESCE(use_count, 0) > 0"
        ).fetchone()[0]
    except Exception as e:
        return _check("inventory_consumption", "Cooking updates the pantry",
                      UNKNOWN, f"probe failed: {e}",
                      "Unknown whether the cook-to-inventory loop is closed.")

    if not rows:
        return _check("inventory_consumption", "Cooking updates the pantry",
                      UNKNOWN, "inventory is empty", "")
    if used:
        return _check("inventory_consumption", "Cooking updates the pantry",
                      OK, f"{used} of {rows} row(s) show use", "", "")
    return _check(
        "inventory_consumption", "Cooking updates the pantry",
        FAILING, f"0 of {rows} rows have ever been used or use-stamped",
        "Inventory only grows. Shopping lists credit food that may be long "
        "gone, and Cook Now ranks recipes against stock that was eaten weeks "
        "ago.",
        "Consume on the cooked_at transition server-side, so every surface "
        "that records a cook closes the loop.",
    )


def check_expiry_pruning() -> dict:
    """Is auto-age-out running? The project's own principle depends on it."""
    try:
        from lib import inventory_db
        conn = inventory_db.read_conn()
        expired = conn.execute(
            "SELECT COUNT(*) FROM inventory "
            "WHERE expires IS NOT NULL AND expires < ?",
            (date.today().isoformat(),),
        ).fetchone()[0]
    except Exception as e:
        return _check("expiry_pruning", "Expired stock is pruned",
                      UNKNOWN, f"probe failed: {e}",
                      "Unknown whether inventory self-cleans.")

    if expired == 0:
        return _check("expiry_pruning", "Expired stock is pruned", OK,
                      "no expired rows present", "", "")
    return _check(
        "expiry_pruning", "Expired stock is pruned", FAILING,
        f"{expired} expired row(s) still in inventory",
        "Expired food is credited against shopping lists, so the list omits "
        "things you need to buy.",
        "prune_expired() is called from generate_meal_plan.py after its "
        "'file already exists' early return, so it rarely runs. Move it.",
    )


def check_failure_analysis_agent() -> dict:
    """Report the agent's real state rather than assuming it launched."""
    from batch_extract import _env_flag  # local: batch_extract imports EventKit

    enabled = _env_flag("KITCHENOS_FAILURE_ANALYSIS")
    if not enabled:
        return _check(
            "failure_analysis", "Failure-analysis agent", OK,
            "disabled (KITCHENOS_FAILURE_ANALYSIS unset)",
            "", "Deliberate: the agent commits and opens PRs unattended.",
        )
    if shutil.which("claude") is None:
        return _check(
            "failure_analysis", "Failure-analysis agent", FAILING,
            "enabled, but 'claude' is not on PATH",
            "Every spawn dies immediately. launchd runs with a bare PATH.",
            "Give the shim an absolute path to the claude binary.",
        )
    return _check("failure_analysis", "Failure-analysis agent", OK,
                  "enabled and launchable", "", "")


def check_prep_sidecar(meal_plans_dir: Path, week: str) -> dict:
    """Is this week's prep-task sidecar fresh, or will /prep block on an LLM?

    The sidecar is stale whenever the plan file's mtime moves past it — and the
    plan file is rewritten on *every* ledger mutation, including ones that
    change nothing in the rendered markdown. A stale sidecar means the next
    /prep visit pays a full LLM round trip while rendering nothing.
    """
    try:
        plan = Path(meal_plans_dir) / f"{week}.md"
        sidecar = Path(meal_plans_dir) / f"{week}.tasks.json"
        if not plan.exists():
            return _check("prep_sidecar", "Today's prep is precomputed",
                          UNKNOWN, f"no plan file for {week}", "")
        if not sidecar.exists():
            fresh = False
            detail = "no sidecar for this week"
        else:
            fresh = sidecar.stat().st_mtime >= plan.stat().st_mtime
            detail = "fresh" if fresh else "stale (plan is newer)"
    except Exception as e:
        return _check("prep_sidecar", "Today's prep is precomputed",
                      UNKNOWN, f"probe failed: {e}",
                      "Unknown whether /prep will block on inference.")

    if fresh:
        return _check("prep_sidecar", "Today's prep is precomputed", OK,
                      detail, "", "")
    return _check(
        "prep_sidecar", "Today's prep is precomputed", FAILING, detail,
        "The next /prep visit runs an LLM during page render and shows a "
        "blank tab until it returns.",
        "Precompute tasks when the plan changes, and stop rewriting the plan "
        "file when its content hasn't changed.",
    )


def run_all(recipes_dir=None, meal_plans_dir=None, week=None,
            run_logs=None, failure_logs=None) -> dict:
    """Every assertion, plus a rollup. Never raises."""
    from lib import paths

    recipes_dir = recipes_dir or paths.recipes_dir()
    meal_plans_dir = meal_plans_dir or paths.meal_plans_dir()
    week = week or datetime.now().strftime("%G-W%V")

    checks = []
    for fn in (
        lambda: check_share_sheet_capture(),
        lambda: check_capture_queue(run_logs or []),
        lambda: check_instagram_cookies(failure_logs or []),
        lambda: check_nutrition_plausibility(recipes_dir),
        lambda: check_inventory_consumption(),
        lambda: check_expiry_pruning(),
        lambda: check_failure_analysis_agent(),
        lambda: check_prep_sidecar(meal_plans_dir, week),
    ):
        try:
            checks.append(fn())
        except Exception as e:
            # A probe that throws is itself a silent failure; surface it.
            checks.append(_check("unknown_probe", "Health probe", UNKNOWN,
                                 f"probe raised: {e}",
                                 "This check could not run."))

    failing = [c for c in checks if c["status"] == FAILING]
    return {
        "checks": checks,
        "failing": len(failing),
        "unknown": sum(1 for c in checks if c["status"] == UNKNOWN),
        "ok": sum(1 for c in checks if c["status"] == OK),
    }
