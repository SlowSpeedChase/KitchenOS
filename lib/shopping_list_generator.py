"""Shopping list generation from meal plans.

Core logic extracted from shopping_list.py for API use.
"""

import base64
import json
import re
from pathlib import Path
from typing import Optional

from lib.recipe_parser import (
    extract_ingredients_section,
    parse_ingredient_table,
    parse_recipe_file,
)
from lib.ingredient_aggregator import aggregate_ingredients, format_ingredient, parse_amount_to_float, format_amount
from lib.ingredient_normalizer import normalize_name
from lib.ingredient_parser import parse_ingredient_best
from lib import meal_loader, paths
from lib.meal_plan_parser import sub_multiplier
from lib.safe_paths import shopping_list_path

# Configuration
OBSIDIAN_VAULT = paths.vault_root()
MEAL_PLANS_PATH = paths.meal_plans_dir()
RECIPES_PATH = paths.recipes_dir()
SHOPPING_LISTS_PATH = paths.shopping_lists_dir()

_NON_PURCHASE_ITEMS = {"water", "ice"}
_EMBEDDED_SCOOP = re.compile(r"^one\s+scoops?\s+", re.IGNORECASE)


def parse_week_string(week_str: str) -> Path:
    """Parse a week string like '2026-W04' into a meal plan path.

    Raises:
        ValueError: If format is invalid or file doesn't exist.
    """
    match = re.match(r'^(\d{4})-W(\d{2})$', week_str)
    if not match:
        raise ValueError(f"Invalid week format: {week_str}. Expected: YYYY-WNN")

    filepath = MEAL_PLANS_PATH / f"{week_str}.md"
    if not filepath.exists():
        raise ValueError(f"Meal plan not found: {week_str}")

    return filepath


def extract_recipe_links(meal_plan_path: Path) -> list[tuple[str, float]]:
    """Extract recipe references from a meal plan, expanding any meals.

    Recognizes both `[[Recipe Name]]` and `[[Meal: Bundle Name]]` (the latter
    is resolved to its sub-recipes via lib.meal_loader). Outer `xN`
    multipliers propagate through to each sub-recipe and stack with the
    sub-recipe's own per-bundle servings override.

    Returns:
        List of (recipe_name, multiplier: float) tuples. Unknown meals are
        emitted as-is so the caller can surface a "Recipe not found" warning.
    """
    content = meal_plan_path.read_text(encoding='utf-8')
    matches = re.findall(r'\[\[(Meal:\s*)?([^\]]+)\]\]\s*(?:x([\d.]+))?', content)
    out: list[tuple[str, float]] = []
    for prefix, name, mult in matches:
        servings = float(mult) if mult else 1.0
        name = name.strip()
        if prefix:
            meal = meal_loader.load_meal(name)
            if meal and meal.sub_recipes:
                for sub in meal.sub_recipes:
                    out.append((sub.recipe, sub_multiplier(servings, sub.servings)))
                continue
        out.append((name, servings))
    return out


def slugify(text: str) -> str:
    """Convert text to slug format."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def find_recipe_file(recipe_name: str) -> Path | None:
    """Find recipe file by name."""
    exact = RECIPES_PATH / f"{recipe_name}.md"
    if exact.exists():
        return exact

    slug = slugify(recipe_name)
    for file in RECIPES_PATH.glob("*.md"):
        if slugify(file.stem) == slug:
            return file
    return None


def extract_ingredient_table(body: str) -> str:
    """Extract the ingredients section from a recipe body.

    Delegates to `recipe_parser.extract_ingredients_section` — this used to carry
    its own regex, which stopped at `\\n##` and so truncated at a `###` sub-heading,
    dropping every ingredient group after the first from the shopping list.
    """
    return extract_ingredients_section(body)


def repair_shopping_ingredient(ingredient: dict) -> dict:
    """Repair known parser artifacts before scaling and aggregation."""
    repaired = ingredient.copy()
    item = str(repaired.get("item") or "").strip()
    unit = str(repaired.get("unit") or "").strip().lower()
    if unit in ("", "whole") and _EMBEDDED_SCOOP.match(item):
        repaired["item"] = _EMBEDDED_SCOOP.sub("", item).strip()
        repaired["unit"] = "scoop"
        if repaired.get("amount") in (None, ""):
            repaired["amount"] = "1"
    return repaired


def multiply_ingredients(ingredients: list[dict], multiplier: float) -> list[dict]:
    """Scale ingredient amounts by a multiplier.

    Args:
        ingredients: List of ingredient dicts with 'amount', 'unit', 'item' keys
        multiplier: Number to multiply amounts by

    Returns:
        New list of ingredient dicts with scaled amounts
    """
    repaired = [repair_shopping_ingredient(ing) for ing in ingredients]
    if multiplier == 1:
        return ingredients if repaired == ingredients else repaired

    scaled = []
    for ing in repaired:
        new_ing = ing.copy()
        amount = parse_amount_to_float(ing.get('amount'))
        if amount is not None:
            new_ing['amount'] = format_amount(amount * multiplier)
        scaled.append(new_ing)
    return scaled


def load_recipe_ingredients(recipe_name: str) -> tuple[list[dict], str | None]:
    """Load ingredients from a recipe file.

    Returns:
        Tuple of (ingredients list, warning message or None)
    """
    recipe_file = find_recipe_file(recipe_name)
    if not recipe_file:
        return [], f"Recipe not found: {recipe_name}"

    try:
        content = recipe_file.read_text(encoding='utf-8')
        parsed = parse_recipe_file(content)
        table_text = extract_ingredient_table(parsed['body'])
        if not table_text:
            return [], f"No ingredients table in: {recipe_name}"

        ingredients = parse_ingredient_table(table_text)
        return ingredients, None
    except Exception as e:
        return [], f"Could not parse {recipe_name}: {e}"


def compute_lines(aggregated: list[dict], pantry: Optional[list[dict]] = None) -> list[dict]:
    """Build per-line shopping records, optionally split against pantry inventory.

    Each record has the shape:
        {
            "item": str,                            # normalized item name
            "needed": {amount, unit},               # what the recipes call for
            "from_pantry": {amount, unit} | None,   # what to take from pantry
            "to_buy": {amount, unit} | None,        # what still needs purchasing
            "display": str,                         # full formatted ingredient
            "warning": str | None,                  # cross-family mismatch, etc.
            "status": "buy" | "credited" | "review" | "excluded",
            "matched_inventory": dict | None,
        }

    When `pantry` is None, every line has `from_pantry=None` and
    `to_buy=needed`. When `pantry` is provided, lib.pantry.split_against_pantry()
    is consulted to subtract.
    """
    splitter = None
    if pantry is not None:
        from lib import pantry as pantry_module  # local import to avoid cycle
        splitter = pantry_module.split_against_pantry

    lines: list[dict] = []
    for ing in aggregated:
        amount = ing.get("amount", "")
        unit = ing.get("unit", "")
        item = ing.get("item", "")
        needed = {"amount": amount, "unit": unit}
        from_pantry: Optional[dict] = None
        to_buy: Optional[dict] = needed
        warning: Optional[str] = None
        status = "buy"
        matched_inventory: Optional[dict] = None

        if item.strip().lower() in _NON_PURCHASE_ITEMS:
            to_buy = None
            status = "excluded"
        elif splitter is not None:
            split = splitter(item, amount, unit, pantry)
            from_pantry = split.get("from_pantry")
            to_buy = split.get("to_buy")
            warning = split.get("warning")
            status = split.get("status", "review" if warning else "buy")
            matched_inventory = split.get("matched_inventory")

        lines.append({
            "item": item,
            "needed": needed,
            "from_pantry": from_pantry,
            "to_buy": to_buy,
            "display": format_ingredient(ing),
            "warning": warning,
            "status": status,
            "matched_inventory": matched_inventory,
        })
    return lines


def format_qty(amount, unit) -> str:
    """"2 cup", or a bare "3" for the `whole` pseudo-unit ("3 whole eggs" reads badly).

    The one quantity formatter for shopping-list prose — `shopping_list.py`'s
    interactive pantry prompt delegates here rather than keeping its own copy.
    """
    parts = [str(amount)] if amount not in ("", None) else []
    if unit and unit not in ("whole", ""):
        parts.append(str(unit))
    return " ".join(parts).strip() or "?"


def _fmt_qty(qty: Optional[dict]) -> str:
    """`format_qty` for a `{amount, unit}` record."""
    if not qty:
        return ""
    return format_qty(qty.get("amount"), qty.get("unit"))


def inventory_notes(lines: list[dict]) -> dict[str, list[str]]:
    """Separate confirmed credits from inventory matches needing review.

    The pantry-aware list drops a fully-covered line from ``items`` entirely, so
    without this the ingredient just silently isn't there and you can't tell
    whether the system credited your stock or forgot the ingredient. These notes
    are **informational only** — they say what was credited, and nothing here
    decrements inventory (only ``pantry.apply_decisions`` does that, from the
    confirm step).

    Review notes explain uncertain candidates, but those ingredients stay on the
    buy list. This distinction prevents a related product or unknown package
    count from being presented as stock that definitely satisfies the recipe.
    """
    credited: list[str] = []
    review: list[str] = []
    for line in lines:
        item = line.get("item", "")
        warning = line.get("warning")
        status = line.get("status")
        if status == "review" or warning:
            if warning:
                review.append(f"{item} — {warning}; still on the list")
            continue
        from_pantry = line.get("from_pantry")
        if not from_pantry:
            continue
        have = _fmt_qty(from_pantry)
        to_buy = line.get("to_buy")
        if to_buy:
            credited.append(f"{item} — using {have} from the pantry, "
                            f"buying {_fmt_qty(to_buy)}")
        else:
            # `have` is the credited amount, which for a fully covered line equals
            # what the recipes asked for — not how much is in the kitchen. Say
            # "needed" so the note can't be read as a stock level.
            credited.append(f"{item} — in stock, {have} needed")
    return {"credited": credited, "review": review}


def on_hand_notes(lines: list[dict]) -> list[str]:
    """Backward-compatible access to confirmed inventory-credit notes only."""
    return inventory_notes(lines)["credited"]


def _line_display(line: dict, quantity_key: str) -> Optional[str]:
    quantity = line.get(quantity_key)
    if not quantity:
        return None
    return format_ingredient({
        "amount": quantity.get("amount", ""),
        "unit": quantity.get("unit", ""),
        "item": line.get("item", ""),
    })


def _inventory_match_note(line: dict) -> Optional[str]:
    matched = line.get("matched_inventory")
    if not matched:
        return None

    needed_text = _line_display(line, "needed") or line.get("item", "")
    matched_qty = format_qty(matched.get("amount"), matched.get("unit"))
    warning = (line.get("warning") or "").lower()
    to_buy = line.get("to_buy")
    if line.get("status") == "credited" and to_buy:
        suffix = f"exact match; {_fmt_qty(to_buy)} still needed"
    elif line.get("status") == "credited":
        suffix = "exact match; enough recorded"
    elif "related item" in warning:
        suffix = "related item; verify amount and form"
    elif "package quantity is unknown" in warning:
        suffix = "package quantity unknown; verify amount"
    elif "different units" in warning:
        suffix = "different units; verify amount"
    elif "usable quantity is unknown" in warning:
        suffix = "quantity unknown; verify amount"
    else:
        suffix = "verify amount and form"
    return (
        f"{needed_text} → {matched.get('item', 'inventory item')} "
        f"({matched_qty}) — {suffix}"
    )


def _shopping_line_payload(line: dict) -> dict:
    """Add stable display strings used by non-Python preview consumers."""
    return {
        **line,
        "needed_display": _line_display(line, "needed"),
        "to_buy_display": _line_display(line, "to_buy"),
        "inventory_match_note": _inventory_match_note(line),
    }


def shopping_sections(lines: list[dict]) -> dict[str, list[str]]:
    """Split generated demand into purchases and inventory matches to verify.

    Any inventory candidate belongs in the verification section, regardless of
    whether its quantity was creditable. Only lines with no candidate become
    purchase checkboxes (and therefore Reminders items).
    """
    purchase: list[str] = []
    inventory_matches: list[str] = []
    for line in lines:
        if line.get("status") == "excluded":
            continue

        matched = line.get("matched_inventory")
        if matched:
            inventory_matches.append(_inventory_match_note(line))
            continue

        to_buy = line.get("to_buy")
        if to_buy:
            purchase.append(format_ingredient({
                "amount": to_buy.get("amount", ""),
                "unit": to_buy.get("unit", ""),
                "item": line.get("item", ""),
            }))

    return {"purchase": purchase, "inventory_matches": inventory_matches}


def generate_shopping_list_from_path(meal_plan_path: Path, pantry: Optional[list[dict]] = None) -> dict:
    """Same contract as `generate_shopping_list` but operates on a path.

    Used by the CLI which supports `--plan custom.md` in addition to weeks.
    """
    if not meal_plan_path.exists():
        return {"success": False, "error": f"Meal plan not found: {meal_plan_path}"}

    recipe_links = extract_recipe_links(meal_plan_path)
    if not recipe_links:
        return {"success": False, "error": "No recipes found in meal plan"}

    all_ingredients = []
    loaded_recipes = []
    warnings = []

    for name, servings in recipe_links:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(multiply_ingredients(ingredients, servings))
            loaded_recipes.append(name)

    if not all_ingredients:
        return {
            "success": False,
            "error": "No ingredients found in any recipes",
            "warnings": warnings
        }

    aggregated = aggregate_ingredients(all_ingredients)
    lines = [_shopping_line_payload(line)
             for line in compute_lines(aggregated, pantry=pantry)]
    sections = shopping_sections(lines)
    purchase_items = sorted(sections["purchase"])

    return {
        "success": True,
        "items": purchase_items,
        "purchase_items": purchase_items,
        "inventory_matches": sections["inventory_matches"],
        "lines": lines,
        "recipes": loaded_recipes,
        "warnings": warnings
    }


def _build_from_recipe_multipliers(pairs: list[tuple[str, float]],
                                   pantry: Optional[list[dict]] = None) -> dict:
    """Shared assembly: (recipe, multiplier) pairs → aggregated list dict."""
    all_ingredients = []
    loaded_recipes = []
    warnings = []
    for name, mult in pairs:
        ingredients, warning = load_recipe_ingredients(name)
        if warning:
            warnings.append(warning)
        if ingredients:
            all_ingredients.extend(multiply_ingredients(ingredients, mult))
            loaded_recipes.append(name)
    if not all_ingredients:
        return {"success": True, "items": [], "purchase_items": [],
                "inventory_matches": [], "lines": [],
                "recipes": loaded_recipes, "warnings": warnings}
    aggregated = aggregate_ingredients(all_ingredients)
    lines = [_shopping_line_payload(line)
             for line in compute_lines(aggregated, pantry=pantry)]
    sections = shopping_sections(lines)
    purchase_items = sorted(sections["purchase"])
    return {"success": True, "items": purchase_items,
            "purchase_items": purchase_items,
            "inventory_matches": sections["inventory_matches"], "lines": lines,
            "recipes": loaded_recipes, "warnings": warnings}


def generate_shopping_list(week: str, pantry: Optional[list[dict]] = None) -> dict:
    """Generate shopping list from a week — ledger cooks first, links fallback.

    The ledger path activates when the week has any cooks or slot placements.
    Only cooks anchored to the week contribute (ingredients × scale); meals
    eaten from the freezer add nothing.
    """
    from lib import serving_ledger

    try:
        cooks = serving_ledger.cooks_for_week(week)
        placements = serving_ledger.placements_for_week(week)
    except (ValueError, IndexError):
        # Invalid week format — fall through to link-scan path
        cooks = []
        placements = []

    if cooks or placements:
        pairs = [(c["recipe"], float(c["scale"])) for c in cooks]
        result = _build_from_recipe_multipliers(pairs, pantry=pantry)
        result["source"] = "ledger"
        return result

    try:
        meal_plan_path = parse_week_string(week)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    result = generate_shopping_list_from_path(meal_plan_path, pantry=pantry)
    result["source"] = "links"
    return result


def parse_shopping_list_file(week: str) -> dict:
    """Parse shopping list file and extract unchecked items.

    Args:
        week: Week identifier like '2026-W04'

    Returns:
        Dict with keys:
            - success: bool
            - items: list of unchecked item strings
            - skipped: count of checked items
            - error: error message (if success=False)
    """
    try:
        filepath = shopping_list_path(SHOPPING_LISTS_PATH, week)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not filepath.exists():
        return {"success": False, "error": f"Shopping list not found: {week}. Generate it first."}

    content = filepath.read_text(encoding='utf-8')

    unchecked = []
    checked_count = 0
    generated_items = None
    generated_items_version = None

    metadata = re.search(
        r'<!-- kitchenos-generated-items(-v2)?:([A-Za-z0-9_=-]+) -->', content)
    if metadata:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(
                metadata.group(2).encode("ascii")).decode("utf-8"))
            if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
                generated_items = decoded
                generated_items_version = 2 if metadata.group(1) else 1
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            generated_items = None
            generated_items_version = None

    for line in content.split('\n'):
        # Match unchecked: - [ ] item
        if re.match(r'^- \[ \] ', line):
            item = line[6:].strip()  # Remove "- [ ] " prefix
            if item:
                unchecked.append(item)
        # Match checked: - [x] item
        elif re.match(r'^- \[x\] ', line, re.IGNORECASE):
            checked_count += 1

    return {
        "success": True,
        "items": unchecked,
        "skipped": checked_count,
        "generated_items": generated_items,
        "generated_items_version": generated_items_version,
    }


def extract_manual_items(existing_items: list[str], generated_items: list[str]) -> list[str]:
    """Find items that were manually added (not from generation).

    Args:
        existing_items: Items currently in the shopping list
        generated_items: Items freshly generated from meal plan

    Returns:
        List of items that exist but weren't generated (manual additions)
    """
    generated_set = set(generated_items)
    return [item for item in existing_items if item not in generated_set]


def extract_legacy_manual_items(existing_items: list[str], lines: list[dict]) -> list[str]:
    """Preserve true manual items while migrating a pre-provenance note.

    Older generation could change both quantity and display name after pantry
    subtraction (``2 cts eggs``) or parser bugs (``1 red`` and ``one scoop``).
    Compare parsed food identity, not the full rendered string, during this
    one-time migration. New notes use the encoded generated-item snapshot.
    """
    identities = {normalize_name(line.get("item") or "") for line in lines}
    generated_texts = {
        rendered
        for line in lines
        for rendered in (_line_display(line, "needed"),
                         _line_display(line, "to_buy"))
        if rendered
    }
    alternative_heads = {
        identity.split(",", 1)[0].strip()
        for identity in identities if "," in identity and " or " in identity
    }

    manual: list[str] = []
    for existing in existing_items:
        if existing in generated_texts:
            continue
        parsed = parse_ingredient_best(existing)
        item = parsed.get("item") or existing
        legacy_shape = bool(re.search(
            r"(?:^|\s)(?:cts?|one\s+scoops?)(?:\s|$)",
            existing,
            flags=re.IGNORECASE,
        ))
        item = re.sub(r"^(?:cts?|one\s+scoops?)\s+", "", item, flags=re.IGNORECASE)
        identity = normalize_name(item)
        if ((legacy_shape and identity in identities)
                or identity in alternative_heads):
            continue
        manual.append(existing)
    return manual
