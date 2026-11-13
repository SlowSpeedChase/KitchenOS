"""The gold-standard kitchen: one fixed fake kitchen every command is run through.

Today is frozen at Thursday 2026-11-12 (ISO week 2026-W46). Next week, 2026-W47,
runs Mon Nov 16 - Sun Nov 22. Change this file and tests/gold/commands.json together.
"""
from datetime import date

TODAY = date(2026, 11, 12)

# name -> (servings, short_title, [(amount, unit, ingredient)])
RECIPES = {
    "Chicken Caldo A": (6, None, [("2", "lb", "chicken thighs"), ("3", "whole", "carrots")]),
    "Chicken Caldo B": (4, None, [("1", "lb", "chicken breast"), ("2", "whole", "potatoes")]),
    "Black Bean Chili": (6, "Bean Chili", [("2", "can", "black beans"), ("1", "whole", "onion")]),
    "Butter Biscuits": (8, None, [("2", "cup", "flour"), ("1", "stick", "butter")]),
    "Miso Salmon Bowls": (2, None, [("2", "whole", "salmon fillets"), ("1", "cup", "rice")]),
    "Mystery Stew": ("null", None, [("1", "lb", "beef")]),
}

# (name, quantity, unit, location)
INVENTORY = [
    ("eggs", 12, "ct", "fridge"),
    ("bread", 1, "loaf", "counter"),
    ("olive oil", 1, "bottle", "pantry"),
    ("milk", 1, "carton", "fridge"),
    ("milk", 1, "carton", "freezer"),
]


def _recipe_md(name, servings, short, rows):
    front = [f'title: "{name}"', f"servings: {servings}"]
    if short:
        front.append(f'short_title: "{short}"')
    table = "\n".join(f"| {a} | {u} | {i} |" for a, u, i in rows)
    return (
        "---\n" + "\n".join(front) + "\n---\n\n## Ingredients\n\n"
        "| Amount | Unit | Ingredient |\n|--------|------|------------|\n"
        + table + "\n\n## Instructions\n\n1. Cook it.\n"
    )


def build() -> dict:
    """Write the kitchen into whatever vault and DB the environment points at.

    Call only under the tmp_vault + tmp_db fixtures. Returns the seeded cook ids.
    """
    from lib import paths, serving_ledger
    from lib.inventory import InventoryItem, add_items

    paths.recipes_dir().mkdir(parents=True, exist_ok=True)
    paths.meal_plans_dir().mkdir(parents=True, exist_ok=True)
    for name, (servings, short, rows) in RECIPES.items():
        (paths.recipes_dir() / f"{name}.md").write_text(
            _recipe_md(name, servings, short, rows), encoding="utf-8")

    chili = serving_ledger.create_cook(
        "Black Bean Chili", "2026-W47", servings_produced=6.0,
        date="2026-11-17", meal="dinner")
    salmon = serving_ledger.create_cook(
        "Miso Salmon Bowls", "2026-W47", servings_produced=2.0,
        date="2026-11-18", meal="dinner")
    frozen_caldo = serving_ledger.create_cook(
        "Chicken Caldo A", "2026-W44", servings_produced=6.0,
        date="2026-10-27", meal="dinner")
    serving_ledger.add_placement(frozen_caldo["id"], "freezer", 3)
    frozen_chili = serving_ledger.create_cook(
        "Black Bean Chili", "2026-W44", servings_produced=6.0,
        date="2026-10-28", meal="dinner")
    serving_ledger.add_placement(frozen_chili["id"], "freezer", 2)

    add_items([
        InventoryItem(name=n, quantity=q, unit=u, category="other",
                      location=loc, location_source="manual")
        for n, q, u, loc in INVENTORY
    ])
    return {"chili": chili["id"], "salmon": salmon["id"],
            "frozen_caldo": frozen_caldo["id"], "frozen_chili": frozen_chili["id"]}
