#!/usr/bin/env python3
"""Record whether each recipe's leftovers survive the freezer, via the LLM.

Batch cooking only buys variety if the leftovers keep — cook once, freeze the
rest, rotate so you are not eating the same dinner three nights running. Some of
this library's best-yielding recipes don't freeze: sirloin reheats tough, a
potato-based dish goes grainy, a leafy salad collapses. Nothing recorded that, so
every piece of batch advice was a guess from the recipe name.

The extractor now asks for `freezes_well` on new captures. This fills in the
recipes that were caught before the field existed.

Tri-state, and biased hard toward `null`. A wrong `true` sends a portion into the
freezer to be thrown out weeks later, which is worse than no answer at all — so
anything that isn't a real boolean is refused rather than coerced, and `null`
answers are not written (an absent key already means unknown, and writing the
absence would only make the file bigger).

MEASURED 2026-08-02, and NOT yet accurate enough to run with --apply.
On a 40-recipe dry run the local model (ollama) answered `true` 12 times, `false`
never, and `null` 28 times. Ten of the twelve were right; two were wrong in the
expensive direction:

  Beef Steak Pepper Lunch Skillet -> true   (sliced sirloin reheats tough)
  Boiled Egg With Soy Sauce Marinade -> true
      (egg white goes rubbery frozen — and the stated reason, "contains cooked
       grains", describes ingredients the recipe does not have)

One wrong `true` in six is the failure this field exists to prevent. Several
`null` answers also carried a *reason* contradicting the verdict ("baked tofu is
unambiguous about freezing" -> null), so the model is not merely cautious, it is
inconsistent with itself.

The better signal is at extraction time, where the transcript or page usually
says outright whether leftovers keep — which is why prompts/recipe_extraction.py
now asks for the field on every new capture. Re-measure here before trusting a
bulk run; `--provider claude` needs API credit the account currently lacks.

Usage:
    .venv/bin/python scripts/backfill_freezes_well.py              # dry run
    .venv/bin/python scripts/backfill_freezes_well.py --apply
    .venv/bin/python scripts/backfill_freezes_well.py --apply --limit 20
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from lib import backup, frontmatter, paths  # noqa: E402
from lib.recipe_parser import parse_recipe_body, parse_recipe_file  # noqa: E402
from prompts.recipe_extraction import FREEZES_WELL_PROMPT  # noqa: E402

MANAGED = ("freezes_well",)


def _ingredients_hint(body: str, limit: int = 12) -> str:
    """The ingredients, which are what actually decide this — not the name.

    "Chicken Caldo B" tells a model nothing; a list containing rice, broth and
    shredded chicken tells it everything.
    """
    try:
        items = [i["item"] for i in parse_recipe_body(body).get("ingredients", [])]
    except Exception:
        return "unknown"
    return ", ".join(items[:limit]) or "unknown"


def propose(name: str, ingredients: str, provider: str):
    """Ask the model. Returns ``(verdict, reason)`` where verdict is True/False/None.

    Anything that is not a JSON boolean comes back None. The model will happily
    answer "probably", "yes for the sauce", or "true" as a string, and on a field
    whose unknown state is load-bearing, none of those may become a confident
    boolean.
    """
    from lib import food_resolver  # local: keeps the network client off import

    payload = food_resolver.json_call(
        FREEZES_WELL_PROMPT.format(name=name, ingredients=ingredients), provider)
    if not isinstance(payload, dict):
        return None, "no usable response"
    verdict = payload.get("freezes_well")
    reason = str(payload.get("reason", ""))[:60]
    if not isinstance(verdict, bool):
        return None, reason or "not a boolean"
    return verdict, reason


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the frontmatter (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N recipes")
    ap.add_argument("--redo", action="store_true",
                    help="re-ask for recipes that already carry a verdict")
    ap.add_argument("--provider", default="ollama", choices=["ollama", "claude"])
    args = ap.parse_args()

    files = sorted(paths.recipes_dir().glob("*.md"))
    todo = []
    for path in files:
        try:
            parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if args.redo or not isinstance(
                parsed["frontmatter"].get("freezes_well"), bool):
            todo.append((path, parsed))
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(files)} recipes, {len(todo)} without a freezing verdict"
          f"{'' if args.apply else '  [DRY RUN]'}\n")

    yes = no = unknown = failed = 0
    for path, parsed in todo:
        name = path.stem
        verdict, reason = propose(
            name, _ingredients_hint(parsed["body"]), args.provider)

        if verdict is None:
            # Not written: an absent key already means unknown, so recording the
            # absence would only grow the file without adding information.
            print(f"  ?      {name[:46]:48} {reason}")
            unknown += 1
            continue

        print(f"  {'FREEZES' if verdict else 'no':<7}{name[:46]:48} {reason}")
        yes, no = (yes + 1, no) if verdict else (yes, no + 1)

        if args.apply:
            backup.create_backup(path)
            updated = frontmatter.apply(
                path.read_text(encoding="utf-8"),
                {"freezes_well": frontmatter.scalar(verdict)},
                MANAGED,
            )
            if updated is None:
                print(f"  FAIL   {name[:46]:48} no frontmatter to write into")
                failed += 1
                continue
            path.write_text(updated, encoding="utf-8")

    print(f"\n{yes} freeze, {no} don't, {unknown} unknown, {failed} failed"
          f"{'' if args.apply else '  (dry run — nothing written)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
