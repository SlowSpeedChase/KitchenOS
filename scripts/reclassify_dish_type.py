"""One-off repair: reclassify every recipe's dish_type with Claude.

Why this exists: dish_type is the field the Cook Now meal-type filter reads, and
it drifted. Twelve recipes carry one-off values ("Dinner", "Tostada",
"biscuits"), and the dessert bucket is contaminated because normalizer.py used
to map "biscuit" -> "dessert". A hand-written mapping of the visible strays
would not have caught Butter Biscuits, which looks perfectly well-formed.

Dry-run by default: prints a CHANGE / KEEP / UNRESOLVED report and writes
nothing. --apply writes dish_type into recipe frontmatter, backing each file up
into .history/ first.

    .venv/bin/python scripts/reclassify_dish_type.py            # report only
    .venv/bin/python scripts/reclassify_dish_type.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import frontmatter, paths  # noqa: E402
from lib.backup import create_backup  # noqa: E402
from lib.normalizer import VALID_DISH_TYPES  # noqa: E402
from lib.recipe_index import get_recipe_index  # noqa: E402

CLAUDE_MODEL = "claude-opus-5"

# Structured output: the model physically cannot answer outside the vocabulary,
# so there is no validation branch here that could drift from normalizer.py.
DISH_TYPE_SCHEMA = {
    "type": "object",
    "properties": {"dish_type": {"type": "string", "enum": sorted(VALID_DISH_TYPES)}},
    "required": ["dish_type"],
    "additionalProperties": False,
}


def build_prompt(recipe: dict) -> str:
    """One classification prompt. Current value is included as a hint, not an answer."""
    ingredients = ", ".join(recipe.get("ingredient_items") or []) or "(none listed)"
    return (
        "Classify this recipe into exactly one dish type.\n\n"
        f"Recipe name: {recipe['name']}\n"
        f"Ingredients: {ingredients}\n"
        f"Currently filed as: {recipe.get('dish_type') or '(unset)'}\n\n"
        "The current value may be wrong — judge from the name and ingredients. "
        "A savory baked good is bread or breakfast, not dessert."
    )


def classify(recipes: list[dict], client) -> dict[str, str]:
    """Batch-classify every recipe. Returns {custom_id: dish_type} for successes."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    batch = client.messages.batches.create(requests=[
        Request(
            # custom_id is alphanumerics/underscores/dashes only, so it cannot be
            # the recipe name — this library has "Arayes 🥙" and "Hardee's Biscuits".
            custom_id=f"r{i}",
            params=MessageCreateParamsNonStreaming(
                model=CLAUDE_MODEL,
                # Opus 5 thinks by default and max_tokens bounds thinking + text
                # together, so a one-field answer still needs real headroom.
                max_tokens=2000,
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": DISH_TYPE_SCHEMA}},
                messages=[{"role": "user", "content": build_prompt(r)}],
            ),
        )
        for i, r in enumerate(recipes)
    ])
    print(f"Batch {batch.id} submitted ({len(recipes)} recipes). Waiting…")

    while True:
        status = client.messages.batches.retrieve(batch.id)
        if status.processing_status == "ended":
            break
        print(f"  {status.processing_status}: "
              f"{status.request_counts.processing} processing")
        time.sleep(30)

    results: dict[str, str] = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type != "succeeded":
            continue
        text = next((b.text for b in result.result.message.content
                     if getattr(b, "type", None) == "text"), "")
        try:
            results[result.custom_id] = json.loads(text)["dish_type"]
        except (json.JSONDecodeError, KeyError):
            continue  # falls through to UNRESOLVED
    return results


def diff(recipes: list[dict], results: dict[str, str]) -> dict:
    """Split recipes into change / keep / unresolved.

    Keyed by custom_id, never by position — batch results arrive in arbitrary
    order. Every recipe lands in exactly one bucket; a silently dropped recipe
    would read as "nothing to do".
    """
    change, keep, unresolved = [], [], []
    for i, recipe in enumerate(recipes):
        current = recipe.get("dish_type")
        new = results.get(f"r{i}")
        if new is None:
            unresolved.append((recipe["name"], current))
        elif new != current:
            change.append((recipe["name"], current, new))
        else:
            keep.append((recipe["name"], current))
    return {"change": change, "keep": keep, "unresolved": unresolved}


def apply_changes(changes: list[tuple[str, str, str]]) -> tuple[int, list[str]]:
    """Write new dish_type values into frontmatter. Returns (written, skipped)."""
    written, skipped = 0, []
    for name, _old, new in changes:
        path = paths.recipes_dir() / f"{name}.md"
        if not path.exists():
            skipped.append(name)
            continue
        content = path.read_text(encoding="utf-8")
        # managed_keys scoped to dish_type so no other frontmatter field moves.
        updated = frontmatter.apply(content, {"dish_type": new}, ("dish_type",))
        if updated is None:
            skipped.append(name)
            continue
        create_backup(path)
        path.write_text(updated, encoding="utf-8")
        written += 1
    return written, skipped


def _report(result: dict) -> None:
    print(f"\n  CHANGE     {len(result['change'])}")
    for name, old, new in result["change"]:
        print(f"    {name[:44]:46} {str(old):18} -> {new}")
    print(f"\n  KEEP       {len(result['keep'])}")
    print(f"  UNRESOLVED {len(result['unresolved'])}")
    for name, current in result["unresolved"]:
        print(f"    {name[:44]:46} kept as {current}")
    total = sum(len(result[k]) for k in ("change", "keep", "unresolved"))
    print(f"\n  total      {total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry-run report)")
    args = parser.parse_args()

    import anthropic

    recipes = get_recipe_index(paths.recipes_dir(), include_ingredients=True)
    print(f"{len(recipes)} recipes")

    results = classify(recipes, anthropic.Anthropic())
    result = diff(recipes, results)
    _report(result)

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to write.")
        return 0

    written, skipped = apply_changes(result["change"])
    print(f"\nWrote {written} files (backups in .history/).")
    if skipped:
        print(f"Skipped {len(skipped)}: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
