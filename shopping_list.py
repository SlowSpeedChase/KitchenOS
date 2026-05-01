#!/usr/bin/env python3
"""Generate shopping list from meal plan.

Reads recipe links from a Meal Plan note (resolving any `[[Meal: ...]]`
bundles into their sub-recipes), aggregates ingredients, optionally
walks an interactive pantry-prompt to subtract what you already have,
and pushes the remaining list to Apple Reminders.

Usage:
    python shopping_list.py                       # Auto-detect current week
    python shopping_list.py --week 2026-W03       # Use specific week
    python shopping_list.py --plan custom.md      # Use custom meal plan file
    python shopping_list.py --dry-run             # Preview only (no Reminders, no pantry decrement)
    python shopping_list.py --no-interactive      # Skip pantry prompt
    python shopping_list.py --no-pantry           # Ignore pantry entirely
    python shopping_list.py --output list.txt     # Save to file
    python shopping_list.py --clear               # Clear Reminders list first
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from lib.ingredient_aggregator import format_ingredient
from lib.reminders import add_to_reminders, clear_reminders_list, create_reminders_list
from lib.shopping_list_generator import (
    MEAL_PLANS_PATH,
    generate_shopping_list_from_path,
    parse_week_string,
)
from lib import pantry as pantry_module
from lib import paths

OBSIDIAN_VAULT = paths.vault_root()
LEGACY_MEAL_PLAN_PATH = OBSIDIAN_VAULT / "Meal Plan.md"
REMINDERS_LIST = "Shopping"


def get_current_week_plan() -> Path | None:
    today = date.today()
    iso_cal = today.isocalendar()
    filepath = MEAL_PLANS_PATH / f"{iso_cal.year}-W{iso_cal.week:02d}.md"
    return filepath if filepath.exists() else None


def resolve_meal_plan_path(args) -> Path:
    if args.plan:
        return args.plan
    if args.week:
        return parse_week_string(args.week)
    current = get_current_week_plan()
    if current:
        return current
    return LEGACY_MEAL_PLAN_PATH


def _format_qty(amount, unit) -> str:
    parts = [str(amount)] if amount not in ("", None) else []
    if unit and unit not in ("whole", ""):
        parts.append(unit)
    return " ".join(parts).strip() or "?"


def prompt_pantry_decisions(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Walk pantry-overlapping lines and ask the user what to do.

    Returns (final_buy_lines, decisions_to_decrement).
    """
    final_buy: list[dict] = []
    decisions: list[dict] = []

    for line in lines:
        from_pantry = line.get("from_pantry")
        to_buy = line.get("to_buy")
        item = line["item"]

        if not from_pantry:
            if to_buy is not None:
                final_buy.append({**to_buy, "item": item})
            continue

        needed = line["needed"]
        suggested_pantry = _format_qty(from_pantry["amount"], from_pantry["unit"])
        warning = f"  ⚠ {line['warning']}" if line.get("warning") else ""
        print(
            f"\n[{item}] need {_format_qty(needed['amount'], needed['unit'])}, "
            f"pantry can cover {suggested_pantry}.{warning}"
        )
        choice = input("  Use pantry? [a]ll / [s]ome / [n]one (default a): ").strip().lower() or "a"

        if choice.startswith("n"):
            final_buy.append({**needed, "item": item})
            continue

        if choice.startswith("s"):
            partial = input("  How much from pantry (e.g. '0.5 cup'): ").strip()
            tokens = partial.split(maxsplit=1)
            if len(tokens) >= 1:
                used_amount = tokens[0]
                used_unit = tokens[1] if len(tokens) > 1 else from_pantry["unit"]
            else:
                used_amount, used_unit = from_pantry["amount"], from_pantry["unit"]
            decisions.append({"item": item, "amount": used_amount, "unit": used_unit})
            # Anything still required is added to the buy list, conservatively in
            # the recipe's unit. We let the user re-aggregate if needed.
            final_buy.append({**needed, "item": item, "_note": "partial pantry"})
            continue

        # 'all' — pantry covers, decrement by from_pantry suggestion
        decisions.append({"item": item, "amount": from_pantry["amount"], "unit": from_pantry["unit"]})
        if to_buy is not None:
            final_buy.append({**to_buy, "item": item})

    return final_buy, decisions


def main():
    parser = argparse.ArgumentParser(description="Generate shopping list from meal plan")
    parser.add_argument("--week", type=str, help="Week to use (e.g., 2026-W03)")
    parser.add_argument("--plan", type=Path, help="Custom meal plan file")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; no Reminders, no pantry decrement")
    parser.add_argument("--output", type=Path, help="Output to file instead of Reminders")
    parser.add_argument("--clear", action="store_true", help="Clear Reminders list before adding")
    parser.add_argument("--no-pantry", action="store_true", help="Ignore pantry inventory entirely")
    parser.add_argument("--no-interactive", action="store_true", help="Skip pantry prompt; subtract automatically")
    args = parser.parse_args()

    try:
        meal_plan_path = resolve_meal_plan_path(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Using meal plan: {meal_plan_path.name}")

    pantry = None if args.no_pantry else pantry_module.load_pantry()
    if pantry:
        print(f"Loaded pantry inventory: {len(pantry)} items")

    result = generate_shopping_list_from_path(meal_plan_path, pantry=pantry)
    if not result["success"]:
        print(f"Error: {result.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)

    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")

    print(f"Loaded ingredients from {len(result['recipes'])} recipes")
    lines = result["lines"]

    interactive = (
        pantry is not None
        and not args.no_interactive
        and not args.dry_run
        and sys.stdin.isatty()
        and any(line.get("from_pantry") for line in lines)
    )

    if interactive:
        buy_records, decisions = prompt_pantry_decisions(lines)
        formatted = sorted(format_ingredient(rec) for rec in buy_records)
    else:
        formatted = list(result["items"])
        decisions = []

    print(f"Aggregated to {len(formatted)} items to buy")

    if args.dry_run:
        print("\nShopping List:")
        for item in formatted:
            print(f"  - {item}")
        if decisions:
            print("\nWould decrement pantry:")
            for d in decisions:
                print(f"  - {d['item']}: -{_format_qty(d['amount'], d['unit'])}")
        return

    if args.output:
        args.output.write_text("\n".join(formatted), encoding="utf-8")
        print(f"Saved to {args.output}")
    else:
        try:
            create_reminders_list(REMINDERS_LIST)
            if args.clear:
                clear_reminders_list(REMINDERS_LIST)
                print(f"Cleared {REMINDERS_LIST} list")
            add_to_reminders(formatted, REMINDERS_LIST)
            print(f"Added {len(formatted)} items to {REMINDERS_LIST}")
        except Exception as e:
            print(f"Error adding to Reminders: {e}", file=sys.stderr)
            print("Use --output to save to a file instead.")
            sys.exit(1)

    if decisions and pantry is not None:
        updated_pantry = pantry_module.apply_decisions(decisions, pantry)
        pantry_module.save_pantry(updated_pantry)
        print(f"Decremented {len(decisions)} pantry items")


if __name__ == "__main__":
    main()
