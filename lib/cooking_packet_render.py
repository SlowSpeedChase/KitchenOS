"""Pure, escaped presentation of an already merged saved cooking packet.

No repository, network or inference calls belong here. Only this function's
escaped HTML fragment may be passed to print_cooking_packet's packet_html|safe.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape
from urllib.parse import quote, urlsplit

PHASE_LABELS = {
    "prep_or_flavor_base": "Prep or flavor base", "cook": "Cook",
    "finish_and_taste": "Finish and taste", "freeze_and_store": "Freeze and store",
    "reheat": "Reheat", "instructions": "Instructions",
}

STAGE_LABELS = {
    "bag_now": "Put in the freezer bag now", "prep_then_bag": "Prep first, then bag",
    "freeze_separately": "Freeze separately", "add_at_cook_time": "Add when starting the Instant Pot",
    "finish_after_cooking": "Stir in after pressure release", "serve_separately": "Serve separately",
    "needs_review": "Needs placement review — keep out of the bag",
}
BAG_RULE = "Only items listed under Put in the freezer bag now or Prep first, then bag belong in this bag."


def _stage(row):
    stage = row.get("prep_stage")
    return stage if isinstance(stage, str) and stage in STAGE_LABELS and row.get("needs_review") is False else "needs_review"


def _pull_groups(packet):
    """Display saved credits once; legacy/unconfirmed mappings stay for cook day.

    Allocation belongs to the builder. This conservative presentation fallback
    never estimates or duplicates a credited quantity from an old packet.
    """
    ingredients = {row.get("item_id"): row for card in _rows(packet.get("recipe_cards")) for row in _rows(card.get("ingredients"))}
    groups = {"Pull for freezer prep": [], "Keep for cook day": []}
    seen = set()
    for row in _rows(packet.get("pull_list")) + _rows(packet.get("cook_day_pull")):
        identity = _text(row.get("item_id")) or repr(row)
        if identity in seen:
            continue
        seen.add(identity)
        ids = row.get("source_ingredient_ids")
        mapped = [ingredients.get(identity) for identity in ids] if isinstance(ids, list) and ids and all(isinstance(identity, str) for identity in ids) else []
        stages = {_stage(ingredient) for ingredient in mapped if ingredient}
        review = not mapped or not all(mapped) or "needs_review" in stages or row.get("needs_review") is True
        freezer = not review and stages <= {"bag_now", "prep_then_bag", "freeze_separately"}
        destination = STAGE_LABELS["needs_review"] if review else "; ".join(STAGE_LABELS[stage] for stage in STAGE_LABELS if stage in stages)
        groups["Pull for freezer prep" if freezer else "Keep for cook day"].append((row, destination))
    return groups


def _freezer_prep(card):
    groups = defaultdict(list)
    for row in _rows(card.get("ingredients")):
        groups[_stage(row)].append(row)
    def group(stage):
        if not groups[stage]:
            return ""
        lines = "".join(f'<li class="freezer-ingredient" data-ingredient-id="{_e(row.get("item_id"))}">{_e(_quantity(row))} {_e(_name(row))}'
                        f'<p class="packet-note">{_e(row.get("stage_reason"))}</p>{_notes(row)}</li>' for row in groups[stage])
        return f'<section class="placement-group" data-prep-stage="{stage}"><h4>{STAGE_LABELS[stage]}</h4><ul class="ingredient-list">{lines}</ul></section>'
    bag = "".join(group(stage) for stage in ("bag_now", "prep_then_bag"))
    if not bag:
        bag = '<p class="review-flag">No ingredients are confirmed for this freezer bag yet.</p>'
    outside = "".join(group(stage) for stage in STAGE_LABELS if stage not in {"bag_now", "prep_then_bag"})
    keep_out = f'<section class="keep-out"><h3>Keep out of the freezer bag</h3>{outside}</section>' if outside else ""
    return f'<section class="freezer-prep"><h3>Freezer prep</h3><p class="bag-rule">{BAG_RULE}</p>{bag}</section>{keep_out}'


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_text(child)}" for key, child in list(value.items())[:30])
    if isinstance(value, list):
        return "; ".join(_text(child) for child in value[:100])
    return str(value)


def _e(value) -> str:
    return escape(_text(value), quote=True)


def _rows(value) -> list[dict]:
    return [row for row in value[:2000] if isinstance(row, dict)] if isinstance(value, list) else []


def _date(value) -> str:
    try:
        day = date.fromisoformat(value)
        return f"{day.strftime('%a, %b')} {day.day}, {day.year}"
    except (TypeError, ValueError):
        return _text(value) or "Date not set"


def _range(packet) -> str:
    bounds = packet.get("date_range") or {}
    return f"{_date(bounds.get('start'))} - {_date(bounds.get('end'))}" if isinstance(bounds, dict) and bounds else "Dates not set"


def _name(row) -> str:
    return _text(row.get("text") or row.get("display_name") or row.get("recipe") or row.get("item") or row.get("ingredient") or "Untitled task")


def _quantity(row) -> str:
    return " ".join(_text(row.get(key)) for key in ("amount", "unit") if row.get(key) is not None)


def _url(value) -> str | None:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    try:
        parts = urlsplit(value)
        return value if parts.scheme.lower() in {"http", "https"} and parts.hostname and not parts.username and not parts.password else None
    except ValueError:
        return None


def _source(value) -> str:
    url = _url(value)
    return f'<p class="source-line">Source: <a class="packet-source" href="{_e(url)}" rel="noopener noreferrer">{_e(url)}</a></p>' if url else ""


def _notes(row) -> str:
    pieces = []
    for field in ("notes", "warning", "review_reason"):
        if row.get(field):
            pieces.append(f'<p class="packet-note">{_e(row[field])}</p>')
    if row.get("needs_review"):
        pieces.append('<p class="review-flag">Needs review</p>')
    return "".join(pieces)


def _check(row) -> str:
    return '<span class="paper-check" aria-label="Done">[x]</span> ' if row.get("done") is True else '<span class="paper-check" aria-label="Not done">[ ]</span> '


def _list(rows, title, *, classes="", quantity=False) -> str:
    if not rows:
        return ""
    items = []
    for row in rows:
        amount = f"{_e(_quantity(row))} " if quantity and _quantity(row) else ""
        recipe = f'<span class="packet-meta">For {_e(row.get("recipe") or row.get("recipes"))}</span>' if row.get("recipe") or row.get("recipes") else ""
        contributions = "".join(
            f'<span class="packet-meta"><a href="/recipe/{_e(quote(_text(part.get("recipe")), safe=""))}">{_e(part.get("recipe"))}</a>: {_e(_quantity(part))}</span>'
            for part in _rows(row.get("contributions")))
        items.append(f'<li>{_check(row)}{amount}{_e(_name(row))}{recipe}{contributions}{_notes(row)}</li>')
    return f'<section class="packet-section {classes}"><h2>{title}</h2><ul class="paper-list">{"".join(items)}</ul></section>'


def render_print_packet(packet: dict) -> str:
    """Return an escaped HTML fragment from supplied saved data only."""
    header = (f'<header class="packet-heading"><h1>{_e(packet.get("title") or "Weekly cooking packet")}</h1>'
              f'<p class="packet-range">{_e(_range(packet))}</p>'
              f'<p class="packet-meta">{_e(packet.get("status", "draft")).capitalize()} · Revision {_e(packet.get("revision", "—"))}'
              f' · Generated {_e(packet.get("generated_at") or "not recorded")}</p>{_notes(packet)}</header>')
    schedule = []
    for row in _rows(packet.get("production_schedule")):
        timing = _text(row.get("time") or row.get("start"))
        duration = f'{_e(row["duration_minutes"])} min' if row.get("duration_minutes") is not None else "Duration unknown"
        provenance = "Cook schedule" if row.get("source") == "cook_schedule" else "Packet prep"
        duration_source = _text(row.get("duration_source"))
        duration_source = {"cook_schedule": "Scheduled", "recipe": "Recipe timing", "estimate": "Estimated", "estimated": "Estimated", "user": "Your value"}.get(duration_source, duration_source)
        schedule.append(f'<tr><th scope="row">{_e(_date(row.get("date")))}<span class="packet-meta">{_e(timing)}</span></th>'
                        f'<td>{_check(row)}{_e(_name(row))}<span class="packet-meta">{provenance}</span>{_notes(row)}</td>'
                        f'<td class="numeric">{duration}<span class="packet-meta">{_e(duration_source)}</span></td></tr>')
    table = ('<section class="packet-section production"><table class="production-table"><caption>Weekly schedule</caption>'
             '<thead><tr><th scope="col">Day / start</th><th scope="col">Production task</th><th scope="col">Duration</th></tr></thead>'
             f'<tbody>{"".join(schedule)}</tbody></table>' + ('' if schedule else '<p>No scheduled tasks. Set cook times in the weekly schedule.</p>') + '</section>')
    pieces = [header, table]
    shopping_by_id = {row.get("item_id"): row for row in _rows(packet.get("shopping_list"))}
    for title, pulls in _pull_groups(packet).items():
        grouped = defaultdict(list)
        for row, destination in pulls:
            grouped[_text(row.get("location") or "Location not recorded")].append((row, destination))
        if not grouped:
            continue
        locations = []
        for location, located in grouped.items():
            items = []
            for row, destination in located:
                requirement = shopping_by_id.get(row.get("line_id"), {}).get("needed")
                required = f'<span class="packet-meta">Required: {_e(_quantity(requirement))}</span>' if isinstance(requirement, dict) else ""
                uncertainty = ' <strong class="review-flag">Location unsure</strong>' if row.get("location_uncertain") else ""
                items.append(f'<li>{_check(row)}{_e(_quantity(row))} {_e(_name(row))}{uncertainty}'
                             f'<span class="packet-meta">Credited from home: {_e(_quantity(row))}</span>{required}'
                             f'<p class="pull-destination">Destination: {_e(destination)}</p>'
                             f'<p class="packet-note">{_e(row.get("stage_reason"))}</p>{_notes(row)}</li>')
            locations.append(f'<div class="location-group"><h3>{_e(location)}</h3><ul class="paper-list">{"".join(items)}</ul></div>')
        pieces.append(f'<section class="packet-section"><h2>{title}</h2><div class="location-columns">{"".join(locations)}</div></section>')
    buys = []
    for row in _rows(packet.get("shopping_list")):
        if row.get("to_buy"):
            buys.append({**row["to_buy"], **row})
    if buys:
        pieces.append('<p class="packet-note">Complete-meal shopping covers every ingredient stage; use Pull for freezer prep for today’s session.</p>')
    pieces.append(_list(buys, "Shopping for the complete meal", quantity=True))
    snapshot = packet.get("store_snapshot") if isinstance(packet.get("store_snapshot"), dict) else {}
    picks = _rows(snapshot.get("recommendations"))
    if picks:
        products = []
        for pick in picks:
            products.append(f'<li><strong>{_e(pick.get("ingredient") or "Ingredient")}</strong>: {_e(pick.get("product_name") or "No verified product")}'
                            f'<span class="packet-meta">{_e(pick.get("retailer"))} · {_e(pick.get("brand"))} · {_e(pick.get("package"))}</span>'
                            f'<p>{_e(pick.get("display_price") or pick.get("price") or "Price unknown")} · {_e(pick.get("status") or "Availability unverified")}</p>'
                            f'<p>{_e(pick.get("evidence") or "No comparison evidence")}</p>'
                            f'<p class="packet-meta">Checked {_e(pick.get("checked_at") or "time not recorded")}</p>{_notes(pick)}{_source(pick.get("url"))}</li>')
        pieces.append(f'<section class="packet-section utility"><h2>Store picks</h2><ul class="paper-list">{"".join(products)}</ul></section>')
    pieces.append(_list(_rows(packet.get("shared_prep")), "Shared prep", classes="prep-section", quantity=True))
    for index, card in enumerate(_rows(packet.get("recipe_cards")), 1):
        source_phases = card.get("instruction_phases") if isinstance(card.get("instruction_phases"), dict) else {}
        phases = defaultdict(list)
        for original_phase, instructions in source_phases.items():
            for row in _rows(instructions):
                effective = row.get("phase") if row.get("phase") in PHASE_LABELS else original_phase
                if effective in PHASE_LABELS:
                    phases[effective].append(row)
        blocks = []
        for phase, title in PHASE_LABELS.items():
            rows = _rows(phases.get(phase))
            if rows:
                steps = "".join(f'<li>{_check(row)}{_e(_name(row))}{_notes(row)}</li>' for row in rows)
                blocks.append(f'<div class="recipe-phase"><h4>{title}</h4><ol>{steps}</ol></div>')
        if not phases and _rows(card.get("instructions")):
            steps = "".join(f'<li>{_e(_name(row))}{_notes(row)}</li>' for row in _rows(card["instructions"]))
            blocks.append(f'<div class="recipe-phase"><h4>Instructions</h4><ol>{steps}</ol></div>')
        equipment = f'<p class="packet-note">Equipment: {_e(card["equipment"])}</p>' if card.get("equipment") else ""
        pieces.append(f'<section class="packet-section recipe-sheet"><h2><span class="recipe-number">{index}</span> {_e(card.get("display_name") or card.get("recipe"))}</h2>'
                      f'<p class="packet-meta">Batch multiplier: {_e(card.get("scale", 1))}</p>{equipment}{_notes(card)}{_freezer_prep(card)}<section class="cook-day-directions"><h3>Cook-day directions</h3>{"".join(blocks)}</section>{_source(card.get("source_url"))}</section>')
    pieces.append(_list(_rows(packet.get("freeze_reheat")), "Freeze and reheat", classes="prep-section"))
    pieces.append(_list(_rows(packet.get("equipment")), "Equipment"))
    pieces.append(_list(_rows(packet.get("warnings")), "Warnings", classes="utility"))
    reviews = _rows(packet.get("needs_review"))
    if reviews:
        lines = "".join(f'<li><strong>{_e(row.get("reason") or "Needs review")}</strong> · {_e(row.get("item_id"))}'
                        f'<p>{_e(row.get("field"))}: {_e(row.get("value"))}</p>{_notes(row)}</li>' for row in reviews)
        pieces.append(f'<section class="packet-section utility"><h2>Needs review</h2><ul class="paper-list">{lines}</ul></section>')
    retailers = snapshot.get("retailers") if isinstance(snapshot.get("retailers"), dict) else {}
    if retailers:
        places = []
        for key, place in list(retailers.items())[:20]:
            if not isinstance(place, dict):
                continue
            places.append(f'<li><strong>{_e(place.get("display_name") or place.get("display") or key)}</strong> · {_e(place.get("location") or place.get("address"))}'
                          f'<p>{"Stale · " if place.get("stale") else ""}Checked {_e(place.get("checked_at") or place.get("timestamp") or "time not recorded")}</p>'
                          f'<p>{_e(place.get("error"))}</p>{_notes(place)}</li>')
        pieces.append(f'<section class="packet-section"><h2>Locations used</h2><ul class="paper-list">{"".join(places)}</ul></section>')
    pieces.append(f'<footer class="packet-footer">KitchenOS · Weekly cooking packet · Revision {_e(packet.get("revision", "—"))}<span class="page-counter"></span></footer>')
    return "".join(pieces)
