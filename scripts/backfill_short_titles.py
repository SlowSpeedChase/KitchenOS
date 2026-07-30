#!/usr/bin/env python3
"""Give over-long recipe names a short display title, via the LLM.

70 of 252 recipe names are over 32 characters because the extractor used to echo
the video title — ``Maple Sweet Potato Salad - With Whipped Tahini And Crispy
Chickpeas``, ``Deconstructed Strawberry Cheesecake 20G Protein 🍓 - Youtube``.
On a ~104px planner card those are unreadable.

This writes a ``short_title`` frontmatter field. It does NOT rename anything:
``cooks.recipe`` is a name string, meal plans reference names, and
``task_extractor`` hashes ``recipe|day|slot|step``, so renaming a recipe would
orphan its planned cooks and silently reset its task checkboxes. The file name
stays the identity; only what surfaces *render* changes.

Every proposal is checked by ``lib.short_title.validate_short_title`` before it
is written — the model is the cheap part, the validator is what makes the result
trustworthy. Rejections are reported, not silently dropped, so a bad batch is
visible rather than mysterious.

Usage:
    .venv/bin/python scripts/backfill_short_titles.py              # dry run
    .venv/bin/python scripts/backfill_short_titles.py --apply
    .venv/bin/python scripts/backfill_short_titles.py --apply --limit 10
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from lib import backup, frontmatter, paths, short_title  # noqa: E402
from lib.recipe_parser import parse_recipe_body, parse_recipe_file  # noqa: E402
from prompts.recipe_extraction import SHORT_TITLE_PROMPT  # noqa: E402

MANAGED = ("short_title", "short_title_inferred")


def _ingredients_hint(body: str, limit: int = 8) -> str:
    """A few ingredients, so the model can tell which dish it is actually naming."""
    try:
        items = [i["item"] for i in parse_recipe_body(body).get("ingredients", [])]
    except Exception:
        return "unknown"
    return ", ".join(items[:limit]) or "unknown"


def _ask(prompt: str, provider: str) -> tuple[str | None, float, str]:
    from lib import food_resolver  # local: keeps the network client off module import

    payload = food_resolver.json_call(prompt, provider)
    if not isinstance(payload, dict):
        return None, 0.0, ""
    candidate = payload.get("short_title")
    if not isinstance(candidate, str):
        return None, 0.0, ""
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return candidate.strip(), confidence, str(payload.get("dropped", ""))[:60]


def propose(name, ingredients, provider, validate, attempts=3):
    """Ask for a short title, re-asking with the rejection reason on failure.

    The single biggest cause of rejection is a title a few characters over the
    limit — the model can fix that when told, and cannot when not asked again.
    Feeding the validator's own reason back is what turns a ~60% reject rate into
    a usable one, and it costs one extra local call.

    Returns ``(candidate|None, confidence, dropped, tries, last_reason)``.
    """
    prompt = SHORT_TITLE_PROMPT.format(
        name=name, ingredients=ingredients, max_len=short_title.MAX_SHORT_LEN)
    reason = "no usable response"

    for attempt in range(1, attempts + 1):
        candidate, confidence, dropped = _ask(prompt, provider)
        if candidate is None:
            continue
        ok, reason = validate(candidate)
        if ok:
            return candidate, confidence, dropped, attempt, ""
        prompt += (f"\n\nYour previous answer {candidate!r} was REJECTED: {reason}. "
                   f"Answer again, fixing exactly that.")
    return None, 0.0, "", attempts, reason


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the frontmatter (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N recipes")
    ap.add_argument("--redo", action="store_true",
                    help="re-propose for recipes that already have a short_title")
    ap.add_argument("--provider", default="ollama", choices=["ollama", "claude"],
                    help="which model proposes (the validator is the same either way)")
    ap.add_argument("--attempts", type=int, default=3,
                    help="re-asks allowed per recipe, each fed the rejection reason")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()
    files = sorted(p for p in recipes_dir.glob("*.md"))

    # Every name AND every existing short title — a new short title must not
    # collide with either, or two different dishes start rendering identically.
    taken: set[str] = set()
    parsed_cache: dict[str, dict] = {}
    for path in files:
        taken.add(path.stem)
        try:
            parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        parsed_cache[path.stem] = parsed
        existing = parsed["frontmatter"].get("short_title")
        if existing:
            taken.add(str(existing))

    todo = [p for p in files if short_title.needs_shortening(p.stem)
            and (args.redo or not parsed_cache.get(p.stem, {})
                 .get("frontmatter", {}).get("short_title"))]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(files)} recipes, {len(todo)} over "
          f"{short_title.SHORTEN_THRESHOLD} chars without a short title"
          f"{'' if args.apply else '  [DRY RUN]'}\n")

    written = rejected = failed = 0
    for path in todo:
        name = path.stem
        parsed = parsed_cache.get(name)
        if parsed is None:
            print(f"  SKIP   {name[:46]:48} unparseable")
            failed += 1
            continue

        candidate, confidence, dropped, tries, reason = propose(
            name, _ingredients_hint(parsed["body"]), args.provider,
            lambda c: short_title.validate_short_title(name, c, taken),
            attempts=args.attempts,
        )
        if candidate is None:
            print(f"  REJECT {name[:46]:48} after {tries} tries: {reason}")
            rejected += 1
            continue

        print(f"  {len(candidate):>2}ch   {name[:46]:48} -> {candidate!r}"
              f"  (conf {confidence:.1f}, {tries} "
              f"{'try' if tries == 1 else 'tries'}"
              f"{', dropped ' + dropped if dropped else ''})")
        taken.add(candidate)
        written += 1

        if args.apply:
            backup.create_backup(path)
            updated = frontmatter.apply(
                path.read_text(encoding="utf-8"),
                # Inferred, not measured — same honesty rule as servings_inferred.
                {"short_title": candidate, "short_title_inferred": "true"},
                MANAGED,
            )
            if updated is None:
                print(f"  FAIL   {name[:46]:48} no frontmatter to write into")
                written -= 1
                failed += 1
                continue
            path.write_text(updated, encoding="utf-8")

    verb = "written" if args.apply else "would write"
    print(f"\n  {written} {verb}, {rejected} rejected by the validator, {failed} failed")
    if not args.apply and written:
        print("  Re-run with --apply to write them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
