"""Kitchen Today — the live state shown on the '/' home page.

The home page's job is *recall*, not navigation. A list of page names ("every page,
one tap away") cannot remind anyone that a feature exists; a live number can. So each
card here carries a fact computed from real data — "6 recipes need nothing you don't
have" — and that fact doubles as the entry point to the workflow behind it.

Two things this module is careful about:

**It parses the recipe library once.** ``cook_now.generate`` and ``use_it_up.generate``
each fall back to reading and parsing every recipe file when called bare. Building both
for one page therefore has to load the inventory and the recipe index here and inject
them, or the home page reintroduces exactly the full-vault-scan cost that made the old
Obsidian canvas homepage unusable on a phone.

**No single card can take the page down.** Every card is computed under ``_safe`` and
degrades to a still-tappable link if its query raises or returns nothing. A home page
that 500s is strictly worse than the canvas it replaces.

``render_html`` emits the fragment substituted into ``templates/home.html``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from typing import Callable, Optional
from urllib.parse import quote

# How far back "recently added" reaches. Recipes arrive in bursts from
# batch extraction (10 landed on a single day in July), so a week is enough
# to catch a haul without the card going stale and always reading "0".
RECENT_DAYS = 7


@dataclass(frozen=True)
class Card:
    """One home-page row: a live fact that is also a link into a workflow.

    ``tone`` is ``"urgent"`` only when something has already gone wrong (food
    actually expired) — it drives colour, and it stops meaning anything if
    every card claims it.
    """

    emoji: str
    title: str
    line: str
    href: str
    tone: str = "normal"


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    """"1 recipe" / "6 recipes" — cards read as prose, not as `count: 6`."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _safe(build: Callable[[], Card], fallback: Card) -> Card:
    """Run a card builder, falling back to a plain link if it fails.

    Deliberately broad: the point is that a bad row in the DB, a half-written
    recipe file, or a missing vault folder costs you one card's *number*, never
    the whole page.
    """
    try:
        return build() or fallback
    except Exception:
        return fallback


# --- individual cards -------------------------------------------------------

def _cook_card(items: list, recipe_index: list, today: date) -> Card:
    """What you could cook right now, led by the zero-shopping count."""
    from lib import cook_now

    ranked = cook_now.generate(
        items=items, recipe_index=recipe_index, today=today, limit=60
    ).get("recipes", [])

    ready = [r for r in ranked if (r.get("coverage") or 0) >= 1.0]
    if ready:
        line = f"{_plural(len(ready), 'recipe')} need nothing you don't have"
    elif ranked:
        # Nothing is fully covered, so lead with the closest thing instead of
        # reporting a bare "0" that reads as "this feature is broken".
        best = ranked[0]
        missing = len(best.get("missing") or [])
        line = (f"closest is {best.get('recipe', 'a recipe')} — "
                f"{_plural(missing, 'item')} short")
    else:
        line = "see what's closest to cookable"
    return Card("🍳", "Cook something now", line, "/cook-now")


def _recent_card(recipe_index: list, today: date) -> Card:
    """Recipes that have landed lately — the extraction pipeline's output."""
    cutoff = today.toordinal() - RECENT_DAYS
    fresh = [
        r for r in recipe_index
        if (r.get("added") and _ordinal(r["added"]) and _ordinal(r["added"]) >= cutoff)
    ]
    if fresh:
        newest = max(_ordinal(r["added"]) for r in fresh)
        when = "today" if newest == today.toordinal() else (
            "yesterday" if newest == today.toordinal() - 1
            else date.fromordinal(newest).strftime("%b %-d")
        )
        line = f"{_plural(len(fresh), 'recipe')} added — newest {when}"
    else:
        line = f"{_plural(len(recipe_index), 'recipe')} in the library"
    return Card("✨", "New recipes", line, "/recent")


def _use_it_up_card(items: list, recipe_index: list, today: date) -> Card:
    """What's dying, and whether any of it is already lost."""
    from lib import use_it_up

    at_risk = use_it_up.generate(
        items=items, recipe_index=recipe_index, today=today, limit=10
    ).get("at_risk", [])
    if not at_risk:
        return Card("⏳", "Use it up", "nothing expiring soon", "/review")

    expired = [a for a in at_risk if a.get("status") == "expired"]
    soon = sorted(
        (a for a in at_risk if a.get("status") != "expired"),
        key=lambda a: a.get("expires") or "",
    )

    parts = []
    if expired:
        parts.append(f"{_plural(len(expired), 'item')} expired")
    if soon:
        nxt = soon[0]
        parts.append(f"{nxt.get('name', 'something')} goes {_day_word(nxt.get('expires'), today)}")
    return Card("⏳", "Use it up", " · ".join(parts), "/review",
                tone="urgent" if expired else "normal")


def _plan_card(today: date) -> Card:
    """The Sunday ritual, reported by what's still missing from it."""
    from lib import paths, plan_week, serving_ledger
    from templates.shopping_list_template import generate_filename

    # Must match what /plan-week will actually open (next week), or the card
    # describes one week and navigates to another.
    week = plan_week.default_week(today)
    label = f"Plan week {int(week.split('-W')[1])}"

    cooks = serving_ledger.cooks_for_week(week)
    has_list = (paths.shopping_lists_dir() / generate_filename(week)).exists()

    if not cooks:
        line = "nothing planned yet"
    elif not has_list:
        line = f"{_plural(len(cooks), 'meal')} planned · no shopping list yet"
    else:
        line = f"{_plural(len(cooks), 'meal')} planned · list ready"
    return Card("🗓️", label, line, f"/plan-week?week={week}")


def _prep_card(today: date) -> Card:
    """What you're meant to be doing in the kitchen this afternoon.

    Reads the week's task sidecar **only when it is already fresh**. The obvious
    call, ``task_extractor.extract_tasks``, regenerates a stale sidecar with an
    LLM classification pass — seconds of it — and this runs on every home-page
    load. A card is worth a number, never a page that hangs. When the sidecar is
    stale the card says so and links to ``/prep``, which is where regenerating
    belongs.
    """
    from lib import plan_week, task_extractor

    week = plan_week.current_week(today)
    cached = task_extractor.load_cached_tasks(week)
    if cached is None:
        return Card("🔪", "Today's prep", "nothing planned yet", "/prep")
    if not task_extractor._is_cache_fresh(week, cached):
        return Card("🔪", "Today's prep", "plan changed — open to refresh", "/prep")

    day_name = today.strftime("%A")
    tasks = cached.get("tasks", []) or []
    todays = [t for t in tasks if t.get("day") == day_name and not t.get("done")]
    ahead = [t for t in tasks
             if t.get("day") != day_name and t.get("can_do_ahead") and not t.get("done")]

    if not todays and not ahead:
        return Card("🔪", "Today's prep", "nothing to prep today", "/prep")

    parts = []
    if todays:
        parts.append(f"{_plural(len(todays), 'step')} today")
    if ahead:
        parts.append(f"{len(ahead)} can be done ahead")
    return Card("🔪", "Today's prep", " · ".join(parts), "/prep",
                tone="urgent" if todays else "normal")


def prep_tasks(today: Optional[date] = None, force: bool = False) -> dict:
    """Today's prep, split into what's due today and what can be pulled forward.

    Returns ``{"week", "today", "ahead", "day"}``. Unlike :func:`_prep_card`
    this *may* regenerate a stale sidecar (an LLM pass) — that's the point of
    it living on ``/prep`` rather than on the home page.
    """
    from lib import plan_week, task_extractor

    today = today or date.today()
    week = plan_week.current_week(today)
    day_name = today.strftime("%A")
    payload = task_extractor.extract_tasks(week, force=force) or {}
    tasks = payload.get("tasks", []) or []

    return {
        "week": week,
        "day": day_name,
        "today": [t for t in tasks if t.get("day") == day_name],
        # Get-ahead excludes today's own steps — they're already in the first
        # list, and showing a step twice makes the count meaningless.
        "ahead": [t for t in tasks
                  if t.get("day") != day_name and t.get("can_do_ahead")],
    }


def _task_row_html(task: dict) -> str:
    done = " done" if task.get("done") else ""
    checked = " checked" if task.get("done") else ""
    recipe = task.get("recipe") or ""
    day = task.get("day") or ""
    meta = " · ".join(p for p in (recipe, day) if p)
    return (
        f'<label class="task{done}" data-task-id="{escape(task.get("id", ""))}">'
        f'<input type="checkbox"{checked}>'
        f'<span class="text">'
        f'<span class="step">{escape(task.get("text", ""))}</span>'
        f'<span class="meta">{escape(meta)}</span>'
        f'</span></label>'
    )


def render_prep_html(prep: dict) -> str:
    """The body of ``/prep``: today's steps, then what can be pulled forward."""
    todays, ahead = prep.get("today", []), prep.get("ahead", [])
    if not todays and not ahead:
        return ('<div class="empty">Nothing to prep — no recipes planned for '
                'today, or every step is done. 🎉</div>')

    out = []
    if todays:
        out.append(f'<h2>Today · {escape(prep.get("day", ""))}</h2>')
        out.extend(_task_row_html(t) for t in todays)
    if ahead:
        out.append("<h2>Get ahead</h2>")
        out.extend(_task_row_html(t) for t in ahead)

    # The button follows whatever is actually on the page. Gating it on today's
    # steps alone left a dead end: on a day with only get-ahead work — which is
    # precisely the work you'd want queued — there was nothing to press.
    scope = "today" if todays else "ahead"
    label = "Send today to Reminders" if todays else "Send get-ahead to Reminders"
    note = (
        "Sends today&rsquo;s steps only — get-ahead is a suggestion, not "
        "today&rsquo;s work."
        if todays else
        "Nothing is due today, so this sends the steps you could pull forward."
    )
    out.append(
        f'<div class="actions">'
        f'<button class="btn primary" id="send-reminders" data-scope="{scope}">📋 {label}</button>'
        f"</div>"
        f'<div class="note">Goes to a <strong>Prep</strong> list, separate from '
        f"Shopping. {note}</div>"
    )
    return "\n".join(out)


def verdict_prompt(today: Optional[date] = None) -> Optional[dict]:
    """The single most recent cook awaiting a verdict, or None.

    One, not a list. The whole point is that answering costs a tap; a queue of
    six turns it back into a chore, which is what the existing flow already was
    — reopen the planner, find the card, open the sheet on touch, tap ⋮, tap the
    verdict. Two of sixteen cooks were ever judged. The next one appears after
    this one is answered.
    """
    from lib import verdict_nudge

    today = today or date.today()
    pending = verdict_nudge.pending(today=today)
    if not pending:
        return None
    item = pending[0]
    return {
        "cook_id": item["id"],
        "recipe": item["recipe"],
        "when": _day_word(item.get("date") or (item.get("cooked_at") or "")[:10], today),
    }


def render_verdict_html(prompt: Optional[dict]) -> str:
    """The ask, rendered identically wherever it appears.

    Shared by the home page and ``/prep`` so the two cannot drift into asking
    the same question two different ways. Empty string when there is nothing to
    ask — a card that says "no verdicts pending" is noise on every other day.

    The buttons PATCH the ledger directly. No navigation, no confirm, no sheet:
    the reason `make_again` is empty is that recording it cost five gestures.
    """
    if not prompt:
        return ""
    return (
        '<div class="verdict-ask" data-cook-id="{cid}">'
        '<span class="verdict-q">How was <strong>{recipe}</strong>{when}?</span>'
        '<span class="verdict-btns">'
        '<button class="verdict-btn" data-verdict="1" aria-label="Make again">'
        "&#128077;</button>"
        '<button class="verdict-btn" data-verdict="0" aria-label="Not again">'
        "&#128078;</button>"
        "</span></div>"
    ).format(
        cid=int(prompt["cook_id"]),
        recipe=escape(str(prompt["recipe"])),
        when=f" {escape(prompt['when'])}" if prompt.get("when") else "",
    )


# --- helpers ----------------------------------------------------------------

def _ordinal(iso: str) -> Optional[int]:
    """ISO date string → ordinal day, or None if it isn't one."""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").date().toordinal()
    except (TypeError, ValueError):
        return None


def _day_word(iso: Optional[str], today: date) -> str:
    """"today" / "tomorrow" / "Friday" — a weekday name beats a bare date.

    Past a week out, weekday names stop being unambiguous, so fall back to the
    date itself.
    """
    o = _ordinal(iso or "")
    if o is None:
        return "soon"
    delta = o - today.toordinal()
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta <= 6:
        return date.fromordinal(o).strftime("%A")
    return date.fromordinal(o).strftime("%b %-d")


# --- public API -------------------------------------------------------------

def gather(items: Optional[list] = None, recipe_index: Optional[list] = None,
           today: Optional[date] = None) -> list[Card]:
    """The four Kitchen Today cards, in the order they appear on the page.

    ``items`` and ``recipe_index`` are injectable for tests and to let a caller
    that already holds them avoid a second full scan.
    """
    today = today or date.today()
    if items is None:
        from lib.inventory import read_inventory
        items = read_inventory()
    if recipe_index is None:
        from lib import paths
        from lib.recipe_index import get_recipe_index
        # include_ingredients=True because both cook_now and use_it_up need it;
        # this is the one parse of the library the whole page gets.
        recipe_index = get_recipe_index(paths.recipes_dir(), include_ingredients=True)

    return [
        _safe(lambda: _cook_card(items, recipe_index, today),
              Card("🍳", "Cook something now", "ranked by what's on hand", "/cook-now")),
        _safe(lambda: _recent_card(recipe_index, today),
              Card("✨", "New recipes", "what's landed lately", "/recent")),
        _safe(lambda: _use_it_up_card(items, recipe_index, today),
              Card("⏳", "Use it up", "what's on hand, soonest-expiring first", "/review")),
        _safe(lambda: _prep_card(today),
              Card("🔪", "Today's prep", "what to get ahead on", "/prep")),
        _safe(lambda: _plan_card(today),
              Card("🗓️", "Plan the week", "fill the week, then print it", "/plan-week")),
    ]


def recent_recipes(recipe_index: Optional[list] = None,
                   limit: int = 60) -> list[dict]:
    """Recipes newest-first by arrival date, for the ``/recent`` page.

    Loads the index *without* ingredients when it has to load one itself —
    unlike the home cards, this page only needs frontmatter, and parsing every
    recipe body for it would cost far more than the page is worth.
    """
    if recipe_index is None:
        from lib import paths
        from lib.recipe_index import get_recipe_index
        recipe_index = get_recipe_index(paths.recipes_dir())

    dated = [r for r in recipe_index if _ordinal(r.get("added") or "")]
    dated.sort(key=lambda r: (_ordinal(r["added"]), r["name"]), reverse=True)
    return dated[:limit]


def render_recent_html(recipes: Optional[list[dict]] = None,
                       today: Optional[date] = None) -> str:
    """Render ``/recent`` — recipes grouped under the day they arrived."""
    today = today or date.today()
    if recipes is None:
        recipes = recent_recipes()
    if not recipes:
        return ('<p class="empty">No recipes yet. Extract one and it shows up '
                'here.</p>')

    out: list[str] = []
    current: Optional[str] = None
    for r in recipes:
        if r["added"] != current:
            current = r["added"]
            out.append(f'<h2>{escape(arrival_word(current, today))}</h2>')
        meta = " · ".join(
            str(v) for v in (r.get("cuisine"), r.get("protein"),
                             r.get("dish_type")) if v
        )
        cals = r.get("nutrition_calories")
        if cals:
            meta = f"{meta} · {cals} cal" if meta else f"{cals} cal"
        out.append(
            f'<a class="card" href="/recipe/{quote(r["name"])}">'
            f'<span class="text">'
            f'<span class="title">{escape(r["name"])}</span>'
            + (f'<span class="desc">{escape(meta)}</span>' if meta else '')
            + '</span><span class="chev" aria-hidden="true">›</span></a>'
        )
    return "\n".join(out)


def arrival_word(iso: str, today: date) -> str:
    """A date heading for /recent: "Today" / "Yesterday" / "Monday" / "Jul 22".

    Public because the route reuses it for the page subtitle — the heading and
    the subtitle have to agree about what day it is.
    """
    o = _ordinal(iso)
    if o is None:
        return "Undated"
    delta = today.toordinal() - o
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return date.fromordinal(o).strftime("%A")
    return date.fromordinal(o).strftime("%b %-d, %Y")


def render_html(cards: Optional[list[Card]] = None) -> str:
    """Render the cards as the HTML fragment for the home page."""
    if cards is None:
        cards = gather()
    out = ['<section class="today">']
    for c in cards:
        tone = " urgent" if c.tone == "urgent" else ""
        out.append(
            f'<a class="today-card{tone}" href="{escape(c.href)}">'
            f'<span class="emoji">{escape(c.emoji)}</span>'
            f'<span class="text">'
            f'<span class="title">{escape(c.title)}</span>'
            f'<span class="line">{escape(c.line)}</span>'
            f'</span>'
            f'<span class="chev" aria-hidden="true">›</span>'
            f'</a>'
        )
    out.append("</section>")
    return "\n".join(out)
