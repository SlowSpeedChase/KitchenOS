#!/usr/bin/env python3
"""Repair recipe frontmatter that drifts from the declared schema.

Reads what is wrong from lib.recipe_schema and fixes the three repairable
classes: a non-numeric ``servings``, a surviving legacy nutrition key, and a
key the user decided to drop. Anything else the checker reports is surfaced and
left alone — a normalizer that invents values is worse than the drift.

Writes are line-surgical, through lib.frontmatter, for two reasons: a YAML
round-trip would reformat all 252 files and bury the real change, and
lib.frontmatter is already the shared editor used by backfill_nutrition.py and
the cook-history sync, so this tool cannot drift from them.

IMPORTANT: changing ``servings`` invalidates the file's stored per-serving
macros, which were derived as batch / servings. Re-derive them afterwards:

    .venv/bin/python backfill_nutrition.py --force --only "<Recipe Name>"

Usage:
    python scripts/normalize_recipes.py            # dry run (default)
    python scripts/normalize_recipes.py --apply
    python scripts/normalize_recipes.py --check    # exit 1 if the corpus drifts
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import frontmatter, paths
from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file
from lib.recipe_schema import (
    DROPPED_KEYS,
    LEGACY_NUTRITION_KEYS,
    Violation,
    check_frontmatter,
    servings_low_end,
)

# Keys this tool rewrites in place. Passing them as `managed` to
# frontmatter.rewrite also de-duplicates them, which is free insurance against
# a file that already carries two.
_MANAGED_KEYS = {"servings", "servings_inferred", "servings_needs_review"}


def normalize_content(recipe: str, content: str) -> tuple[str, list[str]]:
    """Return ``(new_content, changes)``. ``changes`` is empty when conforming."""
    fm_text, rest = frontmatter.split_frontmatter(content)
    if fm_text is None:
        return content, []

    fm = parse_recipe_file(content)["frontmatter"]
    violations = check_frontmatter(recipe, fm)
    if not violations:
        return content, []

    updates: dict = {}
    remove: set[str] = set()
    changes: list[str] = []

    for v in violations:
        if v.code == "servings_not_numeric":
            low = servings_low_end(fm.get("servings"))
            if low is None:
                # Nothing numeric to recover; leave it rather than invent one.
                changes.append(f"SKIPPED servings={fm.get('servings')!r} (no number in it)")
                continue
            updates["servings"] = low
            updates["servings_inferred"] = "true"
            updates["servings_needs_review"] = "true"
            changes.append(
                f"servings {fm['servings']!r} -> {low} (low end, flagged for review)"
            )

        elif v.code == "legacy_nutrition_key":
            remove.add(v.key)
            changes.append(f"dropped legacy {v.key!r} (superseded by 'nutrition_{v.key}')")

        elif v.code == "unknown_key" and v.key in DROPPED_KEYS:
            remove.add(v.key)
            changes.append(f"dropped {v.key!r} (user decision, 2026-07-31)")

        else:
            # Reported, deliberately not repaired.
            changes.append(f"UNREPAIRED {v.code}: {v.detail}")

    if not updates and not remove:
        return content, changes

    managed = _MANAGED_KEYS | LEGACY_NUTRITION_KEYS | DROPPED_KEYS
    new_fm = frontmatter.rewrite(fm_text, updates, managed, remove=remove)
    return f"---{new_fm}---{rest}", changes


def normalize_file(path: Path, apply: bool) -> list[str]:
    """Normalize one recipe file. Returns the changes made (or that would be)."""
    content = path.read_text(encoding="utf-8")
    new_content, changes = normalize_content(path.stem, content)

    if apply and new_content != content:
        create_backup(path)
        path.write_text(new_content, encoding="utf-8")

    return changes


def audit(recipes_dir: Path) -> list[Violation]:
    """Every violation across the corpus, for --check."""
    out: list[Violation] = []
    for p in sorted(recipes_dir.glob("*.md")):
        fm = parse_recipe_file(p.read_text(encoding="utf-8"))["frontmatter"]
        out.extend(check_frontmatter(p.stem, fm))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 if any exists; never writes")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()

    if args.check:
        violations = audit(recipes_dir)
        for v in violations:
            print(f"  {v.recipe[:46]:48} {v.code:22} {v.detail}")
        total = len(list(recipes_dir.glob("*.md")))
        print(f"\n{len(violations)} violation(s) across {total} recipes")
        return 1 if violations else 0

    if not args.apply:
        print("DRY RUN — no files will be modified (pass --apply to write)\n")

    touched = servings_changed = 0
    for p in sorted(recipes_dir.glob("*.md")):
        changes = normalize_file(p, apply=args.apply)
        if not changes:
            continue
        touched += 1
        if any(c.startswith("servings ") for c in changes):
            servings_changed += 1
        print(f"{p.stem}")
        for c in changes:
            print(f"    {c}")

    print(f"\n{'Modified' if args.apply else 'Would modify'}: {touched} file(s)")
    if servings_changed:
        print(
            f"\n{servings_changed} file(s) had servings changed — their stored\n"
            "per-serving macros were derived from the OLD count and are now stale.\n"
            'Re-derive them:  .venv/bin/python backfill_nutrition.py --force --only "<name>"'
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
