"""The "am I on track" view — assembled from what was actually cooked.

Answers the question the whole health-goals effort exists to serve, and answers
it honestly. Every number comes from the serving ledger, so it reports cooking
that happened rather than planning that was intended. A dashboard that counted
*planned* meals would flatter, and flattery here is worse than silence: the
point is to be able to trust the answer.

Three deliberate refusals:

- An un-judged cook is never counted as good or bad. Most cooks go un-judged,
  and reading that as disapproval would make the numbers meaningless.
- An untagged recipe is never counted as unhealthy. Missing data is missing
  data, and it is reported as such rather than folded into the denominator.
- No streaks, no targets, no grades. The profile note is explicit that guilt
  triggers more eating, not less; this view describes, it does not score.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from lib import inventory_db, paths
from lib.recipe_parser import parse_recipe_file

DEFAULT_WINDOW_DAYS = 28
MAX_NOTES = 12

_TRUE = {"true", "True", True, "yes", 1}


def _plural(n, noun: str) -> str:
    """"1 cook" / "2 cooks" — this note is read by a person, not a parser."""
    return f"{n:g} {noun}" if n == 1 else f"{n:g} {noun}s"


def _is_assessed(meta: dict) -> bool:
    """Any ``fit_*`` key means the recipe has been through the tagger.

    Deliberately not keyed on one specific field: a partially-written or
    hand-edited note would otherwise read as never assessed, and silently drop
    out of every count here.
    """
    return any(k.startswith("fit_") for k in meta)


def _recipe_fit_index(recipes_dir: Optional[Path] = None) -> dict:
    """`{recipe_name: fit_fields}` for every recipe note that has been tagged."""
    d = recipes_dir or paths.recipes_dir()
    index = {}
    if not d.exists():
        return index
    for path in d.glob("*.md"):
        try:
            fm = parse_recipe_file(path.read_text(encoding="utf-8"))["frontmatter"]
        except Exception:
            continue
        index[path.stem] = fm or {}
    return index


def summarize(since: Optional[str] = None, recipes_dir: Optional[Path] = None) -> dict:
    """Aggregate the cooking that actually happened since ``since`` (ISO date)."""
    if since is None:
        since = (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()

    conn = inventory_db.connect()
    try:
        rows = conn.execute(
            "SELECT recipe, date, cooked_at, make_again, cook_note, servings_produced"
            " FROM cooks WHERE COALESCE(date, substr(cooked_at, 1, 10)) >= ?"
            " ORDER BY COALESCE(date, cooked_at)", (since,)
        ).fetchall()
    finally:
        conn.close()

    fit = _recipe_fit_index(recipes_dir)
    lanes: Counter = Counter()
    heart = steady = untagged = 0
    verdicts = make_again = 0
    notes: list[dict] = []
    servings = 0.0

    for r in rows:
        meta = fit.get(r["recipe"], {})
        if not _is_assessed(meta):
            untagged += 1
        elif meta.get("fit_craving_lane"):
            lanes[str(meta["fit_craving_lane"])] += 1
        if meta.get("fit_heart") in _TRUE:
            heart += 1
        if meta.get("fit_steady") in _TRUE:
            steady += 1

        if r["make_again"] is not None:
            verdicts += 1
            make_again += 1 if r["make_again"] else 0
        if r["cook_note"]:
            notes.append({"recipe": r["recipe"], "note": r["cook_note"]})
        servings += float(r["servings_produced"] or 0)

    return {
        "since": since,
        "cooks": len(rows),
        "servings": round(servings, 1),
        "distinct_recipes": len({r["recipe"] for r in rows}),
        "heart_cooks": heart,
        "steady_cooks": steady,
        "untagged_cooks": untagged,
        "verdicts": verdicts,
        "make_again": make_again,
        "lanes": dict(lanes),
        "notes": notes[-MAX_NOTES:],
    }


def library_gaps(recipes_dir: Optional[Path] = None) -> dict:
    """What the saved library is thin on, judged against the profile's shape."""
    fit = _recipe_fit_index(recipes_dir)
    tagged = {n: m for n, m in fit.items() if _is_assessed(m)}
    lanes: Counter = Counter(str(m["fit_craving_lane"]) for m in tagged.values()
                             if m.get("fit_craving_lane"))
    return {
        "recipes": len(fit),
        "tagged": len(tagged),
        "buffer_candidates": sum(1 for m in tagged.values()
                                 if m.get("fit_buffer_candidate") in _TRUE),
        "heart": sum(1 for m in tagged.values() if m.get("fit_heart") in _TRUE),
        "steady": sum(1 for m in tagged.values() if m.get("fit_steady") in _TRUE),
        "assembly": sum(1 for m in tagged.values()
                        if str(m.get("fit_effort")) == "assembly"),
        "lanes": dict(lanes),
    }


def render_markdown(summary: dict, gaps: dict, today: Optional[date] = None) -> str:
    today = today or date.today()
    lines = [
        "---",
        "type: on-track",
        f"last_updated: {today.isoformat()}",
        "---",
        "",
        "# 🧭 On Track",
        "",
        "> ⚠️ **Generated** from the KitchenOS database — built from cooks you "
        "actually logged, not meals you planned. Do not edit here; changes are "
        "overwritten.",
        "",
    ]

    if not summary["cooks"]:
        lines += [
            f"## Since {summary['since']}",
            "",
            "**Nothing logged yet.** This view fills in as you log cooks on the "
            "meal planner — it deliberately shows nothing rather than counting "
            "meals you planned but never made.",
            "",
        ]
    else:
        lines += [
            f"## Since {summary['since']}",
            "",
            f"- **{_plural(summary['cooks'], 'cook')}** across "
            f"{_plural(summary['distinct_recipes'], 'recipe')} "
            f"(~{_plural(summary['servings'], 'serving')})",
        ]
        if summary["verdicts"]:
            lines.append(
                f"- **{summary['make_again']} of {summary['verdicts']} judged** "
                "were worth making again"
            )
        else:
            lines.append("- No verdicts recorded yet — tap ⋮ on a cook card to add one")

        tagged_cooks = summary["cooks"] - summary["untagged_cooks"]
        if tagged_cooks:
            lines += [
                f"- **{summary['heart_cooks']}** leaned heart-healthy, "
                f"**{summary['steady_cooks']}** blood-sugar-steady "
                f"(of {tagged_cooks} tagged)",
            ]
        if summary["untagged_cooks"]:
            lines.append(
                f"- {summary['untagged_cooks']} cooks were of untagged recipes — "
                "counted as unknown, not as unhealthy"
            )
        lines.append("")

        if summary["lanes"]:
            lines += ["### Cravings served", "",
                      "| Lane | Cooks |", "|------|-------|"]
            for lane, n in sorted(summary["lanes"].items(), key=lambda kv: -kv[1]):
                lines.append(f"| {lane} | {n} |")
            lines.append("")

        if summary["notes"]:
            lines += ["### What you noticed", ""]
            lines += [f"- **{n['recipe']}** — {n['note']}" for n in summary["notes"]]
            lines.append("")

    lines += [
        "## The library you're drawing from",
        "",
        f"- {gaps['tagged']} of {_plural(gaps['recipes'], 'recipe')} assessed "
        "against your food system",
    ]
    if gaps["tagged"]:
        lines += [
            f"- **{gaps['buffer_candidates']}** could work as zero-prep buffer "
            "foods — the ones that win the four-second race",
            f"- **{gaps['assembly']}** need no cooking at all",
            f"- **{gaps['heart']}** heart-leaning, **{gaps['steady']}** steady-leaning",
        ]
        if gaps["lanes"]:
            spread = ", ".join(f"{lane} {n}" for lane, n in
                               sorted(gaps["lanes"].items(), key=lambda kv: -kv[1]))
            lines.append(f"- Craving spread: {spread}")
    else:
        lines.append("- Nothing assessed yet — run `backfill_fit.py`")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_note(today: Optional[date] = None) -> Path:
    """Regenerate `Dashboards/On Track.md`. Returns its path."""
    summary = summarize()
    gaps = library_gaps()
    path = paths.vault_root() / "Dashboards" / "On Track.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(summary, gaps, today=today), encoding="utf-8")
    return path
