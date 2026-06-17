"""Generate the Price Tracker dashboard (markdown) from the purchases ledger.

Aggregation happens in Python (the data volume is tiny — a few thousand
ledger rows after years of use). Money is cents in the DB, dollars in the
rendered output.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from lib import paths
from lib.inventory_db import connect

TOP_ITEMS = 20


def _dollars(cents: Optional[int]) -> str:
    return f"${(cents or 0) / 100:.2f}"


def _iso_week(d: str) -> str:
    try:
        iso = date.fromisoformat(d).isocalendar()
    except ValueError:
        return "unknown"
    return f"{iso.year}-W{iso.week:02d}"


def _load_rows() -> tuple[list[dict], list[dict]]:
    conn = connect()
    try:
        trips = [dict(r) for r in conn.execute(
            "SELECT * FROM trips ORDER BY date").fetchall()]
        purchases = [dict(r) for r in conn.execute(
            "SELECT p.*, t.date AS trip_date FROM purchases p"
            " JOIN trips t ON t.id = p.trip_id"
            " WHERE t.needs_review = 0 ORDER BY t.date").fetchall()]
        return trips, purchases
    finally:
        conn.close()


def generate_dashboard(today: Optional[str] = None) -> str:
    """Render the full dashboard markdown. ``today`` is injectable for tests."""
    ref = date.fromisoformat(today) if today else date.today()
    trips, purchases = _load_rows()
    ok_trips = [t for t in trips if not t["needs_review"]]

    lines = [
        "---",
        "type: price-tracker",
        f"last_updated: {ref.isoformat()}",
        "---",
        "",
        "# Price Tracker",
        "",
        "> Generated from grocery receipts. Do not edit — regenerated on every ingest.",
        "",
        "## Spending",
        "",
    ]

    # --- per-week, last 4 ISO weeks ---
    week_totals: dict[str, int] = defaultdict(int)
    for t in ok_trips:
        if t["total_cents"] and t["date"]:
            week_totals[_iso_week(t["date"])] += t["total_cents"]
    recent_weeks = [
        f"{(ref - timedelta(weeks=i)).isocalendar().year}-W"
        f"{(ref - timedelta(weeks=i)).isocalendar().week:02d}"
        for i in range(3, -1, -1)
    ]
    lines += ["| Week | Spend |", "|------|-------|"]
    lines += [f"| {w} | {_dollars(week_totals.get(w, 0))} |" for w in recent_weeks]
    lines.append("")

    # --- by category, last 12 months ---
    cutoff = (ref - timedelta(days=365)).isoformat()
    cat_totals: dict[str, int] = defaultdict(int)
    for p in purchases:
        if p["trip_date"] >= cutoff and p["total_cents"]:
            cat_totals[p["category"]] += p["total_cents"]
    lines += ["**By category (last 12 months):**", "",
              "| Category | Spend |", "|----------|-------|"]
    for cat, cents in sorted(cat_totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {_dollars(cents)} |")
    lines.append("")

    # --- average trip ---
    totals = [t["total_cents"] for t in ok_trips if t["total_cents"]]
    if totals:
        lines += [f"**Average trip:** {_dollars(sum(totals) // len(totals))}"
                  f" across {len(totals)} trips", ""]

    # --- price trends: top items by purchase count ---
    lines += ["## Price Trends", ""]
    by_item: dict[str, list[dict]] = defaultdict(list)
    for p in purchases:
        if p["category"] != "fee" and p["unit_price_cents"]:
            by_item[p["canonical_name"]].append(p)
    top = sorted(by_item.items(), key=lambda kv: -len(kv[1]))[:TOP_ITEMS]
    cutoff_90 = (ref - timedelta(days=90)).isoformat()
    lines += ["| Item | Last price | 90-day avg | Trend |",
              "|------|-----------|------------|-------|"]
    for name, rows in top:
        last = rows[-1]["unit_price_cents"]
        recent = [r["unit_price_cents"] for r in rows if r["trip_date"] >= cutoff_90]
        avg = sum(recent) // len(recent) if recent else last
        marker = "▲" if last > avg else ("▼" if last < avg else "—")
        lines.append(
            f"| {name} | {_dollars(last)}/{rows[-1]['unit']} |"
            f" {_dollars(avg)} | {marker} |"
        )
    lines.append("")

    # --- per-item history, collapsible ---
    lines += ["<details><summary>Per-item price history</summary>", ""]
    for name, rows in top:
        lines += [f"**{name}**", "", "| Date | Price | Qty |", "|------|-------|-----|"]
        lines += [
            f"| {r['trip_date']} | {_dollars(r['unit_price_cents'])}/{r['unit']}"
            f" | {r['quantity']} |"
            for r in rows[-12:]
        ]
        lines.append("")
    lines += ["</details>", ""]

    # --- needs review ---
    flagged = [t for t in trips if t["needs_review"]]
    if flagged:
        lines += ["## Needs Review", ""]
        for t in flagged:
            lines.append(
                f"- {t['date'] or '?'} — {t['source']} — id `{t['source_id']}`"
            )
        lines.append("")

    return "\n".join(lines)


def save_dashboard(today: Optional[str] = None) -> Path:
    path = paths.vault_root() / "Price Tracker.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_dashboard(today=today), encoding="utf-8")
    return path
