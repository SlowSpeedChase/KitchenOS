"""Pure version-one packet composition from ledger, recipes and raw inventory.

No saves, source mutations, inference or network calls occur here. Native
phases and legacy source instructions are retained for the refresh worker's
separate classification stage. Quantities on a recipe card sum every weekly
cook of that recipe; cook and schedule identities remain independent.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import math
from pathlib import Path
import re

from lib import inventory_db, serving_ledger, shopping_list_generator as shopping
from lib.ingredient_aggregator import (
    aggregate_ingredients, convert_from_base_unit, convert_to_base_unit,
    get_unit_family, parse_amount_to_float, unit_compatibility,
)
from lib.ingredient_normalizer import normalize_name
from lib.inventory import normalize_location_source
from lib.pantry import split_against_pantry
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.safe_paths import contained_markdown, parse_iso_week


def _id(kind: str, *sources) -> str:
    identity = "\x1f".join(str(source) for source in sources)
    return f"{kind}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _quantity(value) -> float:
    amount = parse_amount_to_float(value)
    return amount if amount is not None and math.isfinite(amount) and amount > 0 else 0.0


def _expiry(row: dict) -> str:
    try:
        return date.fromisoformat(row.get("expires") or "").isoformat()
    except (ValueError, TypeError):
        return "9999-12-31"


def _usable_rows(rows: list[dict], today: date) -> list[dict]:
    return [dict(row) for row in rows
            if _quantity(row.get("quantity", row.get("amount")))
            and _expiry(row) >= today.isoformat()]


def _pantry_view(rows: list[dict]) -> list[dict]:
    """The shopping pantry shape, summing identical units across locations."""
    totals = {}
    for row in sorted(rows, key=lambda row: row["id"]):
        name = row.get("name", row.get("item", ""))
        unit = (row.get("unit") or "").lower().strip()
        key = (name.lower().strip(), unit)
        if key not in totals:
            totals[key] = {"item": name, "unit": unit, "amount": 0.0}
        totals[key]["amount"] += _quantity(row.get("quantity", row.get("amount")))
    return list(totals.values())


def _convert(amount: float, source_unit: str, target_unit: str) -> float:
    """Convert only after the shared compatibility authority approves."""
    source = (source_unit or "").lower().strip()
    target = (target_unit or "").lower().strip()
    compatibility = unit_compatibility(source, target)
    if compatibility == "convert":
        family = get_unit_family(source)
        return convert_from_base_unit(convert_to_base_unit(amount, source, family), target, family)
    if compatibility == "one_to_one":
        return amount
    raise ValueError("incompatible credited inventory units")


def allocate_pull_sources(lines: list[dict], inventory_rows: list[dict]) -> list[dict]:
    """Allocate credited demands to real containers, expiry then row ID.

    ``lines`` uses the shopping generator's needed/from_pantry records. Each
    raw row's available quantity is tracked once across the entire call.
    Output amounts use the demand's unit; inventory_amount uses the row unit.
    Matching and credit eligibility are delegated to the existing pantry rule.
    """
    rows = sorted((dict(row) for row in inventory_rows), key=lambda row: (_expiry(row), row["id"]))
    remaining = {row["id"]: _quantity(row.get("quantity", row.get("amount"))) for row in rows}
    pulls = []
    for ordinal, line in enumerate(lines):
        credited = line.get("from_pantry")
        if not credited:
            continue
        item = line.get("item") or ""
        needed = line.get("needed") or credited
        unit = credited.get("unit") or ""
        needed_in_credit_units = _convert(_quantity(needed.get("amount")), needed.get("unit") or "", unit)
        demand = min(_quantity(credited.get("amount")), needed_in_credit_units)
        line_id = line.get("item_id") or _id("demand", normalize_name(item), get_unit_family(unit), ordinal)
        for row in rows:
            available = remaining[row["id"]]
            if demand <= 1e-12 or available <= 1e-12:
                continue
            inventory_unit = row.get("unit") or ""
            entry = {"item": row.get("name", row.get("item", "")), "amount": available, "unit": inventory_unit}
            split = split_against_pantry(item, demand, unit, [entry])
            if not split.get("from_pantry"):
                continue
            amount = min(demand, _convert(available, inventory_unit, unit))
            inventory_amount = min(available, _convert(amount, unit, inventory_unit))
            remaining[row["id"]] = max(0.0, available - inventory_amount)
            demand = max(0.0, demand - amount)
            provenance = normalize_location_source(row.get("location_source"))
            pulls.append({
                "item_id": _id("pull", line_id, normalize_name(item), row["id"]),
                "line_id": line_id, "item": item, "amount": amount, "unit": unit,
                "inventory_row_id": row["id"], "inventory_name": entry["item"],
                "inventory_amount": inventory_amount, "inventory_unit": inventory_unit,
                "location": row.get("location") or "pantry", "location_source": provenance,
                "location_uncertain": provenance == "default", "expires": row.get("expires"),
                "source": "inventory", "done": False,
            })
    return pulls


def _warning(recipe: str, code: str, text: str, source=None) -> dict:
    return {"item_id": _id("warning", recipe, code, source), "recipe": recipe,
            "code": code, "text": text, "source": "recipe"}


def _equipment(frontmatter: dict, body: str) -> list[str]:
    equipment = frontmatter.get("equipment")
    if isinstance(equipment, list) and equipment:
        return [str(value) for value in equipment if value]
    section = re.search(r"^## Equipment\s*\n(.*?)(?=\n##\s|\Z)", body, re.MULTILINE | re.DOTALL)
    return [line.strip()[2:].strip() for line in section[1].splitlines()
            if line.strip().startswith("- ")] if section else []


def _ingredient_group(ingredient: dict) -> tuple[str, str, str]:
    """Source identities for a group produced by the existing aggregator."""
    identity = normalize_name(ingredient.get("item") or "")
    if parse_amount_to_float(ingredient.get("amount")) is None:
        return identity, "unquantified", ""
    unit = (ingredient.get("unit") or "").lower().strip()
    family = get_unit_family(unit)
    return identity, family, unit if family == "other" else ""


def build_week_draft(week: str, recipes_dir: Path, *, inventory_rows: list[dict] | None = None,
                     now: datetime | None = None) -> dict:
    """Build a deterministic draft, including every cook regardless of placement."""
    week = parse_iso_week(week)
    today = (now or datetime.now(timezone.utc)).date()
    monday = date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    sunday = date.fromisocalendar(int(week[:4]), int(week[6:]), 7)
    cooks = serving_ledger.cooks_for_week(week)
    schedules = serving_ledger.schedules_for_week(week)
    rows = _usable_rows(inventory_db.fetch_inventory_rows_with_ids() if inventory_rows is None else inventory_rows, today)
    packet = {"version": 1, "week": week, "status": "draft",
              "date_range": {"start": monday.isoformat(), "end": sunday.isoformat()},
              "cooks": [], "production_schedule": [], "recipe_cards": [], "pull_list": [],
              "shopping_list": [], "equipment": [], "freeze_reheat": [], "warnings": [],
              "shared_prep": [], "needs_review": []}
    by_recipe = defaultdict(list)
    for cook in cooks:
        packet["cooks"].append({**cook, "item_id": f"cook:{cook['id']}", "cook_id": cook["id"], "source": "cook"})
        by_recipe[cook["recipe"]].append(cook)
    for schedule in schedules:
        packet["production_schedule"].append({**schedule, "item_id": f"schedule:cook:{schedule['cook_id']}",
            "source": "cook_schedule", "duration_source": "cook_schedule", "done": False})

    all_ingredients = []
    for recipe, recipe_cooks in by_recipe.items():
        recipe_id = _id("recipe", recipe)
        scale = sum(float(cook["scale"]) for cook in recipe_cooks)
        card = {"item_id": recipe_id, "recipe": recipe, "scale": scale,
                "source_cook_ids": [cook["id"] for cook in recipe_cooks], "source": "recipe",
                "ingredients": [], "instructions": [], "instruction_phases": {}, "equipment": [],
                "source_url": None, "needs_classification": False, "missing": False}
        packet["recipe_cards"].append(card)
        try:
            recipe_path = contained_markdown(Path(recipes_dir), f"{recipe}.md")
            parsed = parse_recipe_file(recipe_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            card["missing"] = True
            packet["warnings"].append(_warning(recipe, "missing_recipe", f"Could not read recipe: {recipe} ({exc})"))
            continue
        frontmatter, body = parsed["frontmatter"], parsed["body"]
        content = parse_recipe_body(body)
        card.update(source_path=recipe_path.name, source_url=frontmatter.get("source_url"),
                    display_name=frontmatter.get("short_title") or recipe,
                    servings=frontmatter.get("servings"), instructions=content["instructions"],
                    equipment=_equipment(frontmatter, body))
        for ordinal, ingredient in enumerate(shopping.multiply_ingredients(content["ingredients"], scale), 1):
            row = {**ingredient, "item_id": _id("ingredient", recipe_id, ordinal),
                   "recipe": recipe, "source_ordinal": ordinal}
            card["ingredients"].append(row)
            all_ingredients.append(row)
        if not content["ingredients"]:
            packet["warnings"].append(_warning(recipe, "missing_ingredients", f"No ingredients table in: {recipe}"))
        for ordinal, equipment in enumerate(card["equipment"], 1):
            packet["equipment"].append({"item_id": _id("equipment", recipe_id, ordinal),
                                        "recipe": recipe, "text": equipment, "source": "recipe"})
        for phase, instructions in content.get("instruction_phases", {}).items():
            card["instruction_phases"][phase] = []
            for instruction in instructions:
                ordinal = instruction["step"]
                row = {**instruction, "item_id": _id("phase", recipe_id, ordinal), "recipe": recipe,
                       "source_ordinal": ordinal, "source": "native_phase", "done": False}
                card["instruction_phases"][phase].append(row)
                if phase in ("freeze_and_store", "reheat"):
                    packet["freeze_reheat"].append({**row, "item_id": _id("storage", recipe_id, ordinal)})
        if content["instructions"] and not content.get("instruction_phases"):
            card["needs_classification"] = True
            packet["warnings"].append(_warning(recipe, "legacy_phases", f"Instruction phases need review: {recipe}"))

    lines = shopping.compute_lines(aggregate_ingredients(all_ingredients), pantry=_pantry_view(rows))
    for line in lines:
        group = _ingredient_group({"item": line["item"], **line["needed"]})
        sources = sorted(ingredient["item_id"] for ingredient in all_ingredients
                         if _ingredient_group(ingredient) == group)
        line["item_id"] = _id("requirement", *group, *sources)
        line["source_ingredient_ids"] = sources
    packet["pull_list"] = allocate_pull_sources(lines, rows)
    for line in lines:
        pulls = [pull for pull in packet["pull_list"] if pull["line_id"] == line["item_id"]]
        credited = sum(_convert(pull["amount"], pull["unit"], line["needed"]["unit"])
                       for pull in pulls)
        inventory_ids = sorted(pull["inventory_row_id"] for pull in pulls)
        line["item_id"] = _id("shopping", line["item_id"], *inventory_ids)
        line["source_inventory_row_ids"] = inventory_ids
        for pull in pulls:
            pull["line_id"] = line["item_id"]
        if line.get("from_pantry"):
            needed_amount = _quantity(line["needed"]["amount"])
            line["from_pantry"] = {"amount": credited, "unit": line["needed"]["unit"]} if credited else None
            line["to_buy"] = {"amount": max(0.0, needed_amount - credited), "unit": line["needed"]["unit"]} if needed_amount > credited + 1e-12 else None
        line["done"] = False
        if line.get("warning"):
            packet["warnings"].append({"item_id": _id("warning", line["item_id"], "inventory_match"),
                                       "text": line["warning"], "source": "inventory", "line_id": line["item_id"]})
    packet["shopping_list"] = lines
    return packet
