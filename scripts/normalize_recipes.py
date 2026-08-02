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
    duplicate_keys,
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
            # The stored nutrition_* values are per-serving, derived as
            # batch / servings, so changing the count invalidates them. Marking
            # the file is what makes that survivable: a console line scrolls
            # away, and on any re-run the file is conforming, so the list of
            # recipes owing a re-derive would never be printed again.
            updates["nutrition_needs_review"] = "true"
            changes.append(
                f"servings {fm['servings']!r} -> {low} (low end, flagged for review; "
                f"macros marked stale)"
            )

        elif v.code == "legacy_nutrition_key":
            # Only safe when the canonical key actually holds a value. Every
            # corpus file carrying a legacy key had one on 2026-08-01, but that
            # was a property of the data, not a guarantee — deleting on sight
            # would destroy a file's only calorie value. This is the mirror of
            # the migrate_recipes rule: that one refuses to rename ONTO an
            # existing key, this one refuses to delete WITHOUT one.
            canonical = fm.get(f"nutrition_{v.key}")
            if canonical is None:
                changes.append(
                    f"UNREPAIRED legacy_nutrition_key: kept {v.key!r} — "
                    f"'nutrition_{v.key}' is missing or null, so this is the "
                    f"only value the file has"
                )
                continue
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


def normalize_file(path: Path, apply: bool) -> tuple[list[str], bool]:
    """Normalize one recipe file.

    Returns ``(changes, written)``. ``written`` is what the run should count as
    modified — a file can report changes and still be written to zero times when
    every violation it has is unrepairable.
    """
    content = path.read_text(encoding="utf-8")
    new_content, changes = normalize_content(path.stem, content)

    written = False
    if apply and new_content != content:
        create_backup(path)
        path.write_text(new_content, encoding="utf-8")
        written = True

    return changes, written


def recipe_files(recipes_dir: Path) -> list[Path]:
    """The corpus, in a stable order.

    ``Path.glob`` matches dotfiles (unlike the ``glob`` module), so an editor
    swapfile or a stray hidden note would otherwise be normalized as a recipe —
    and one alone would satisfy the "empty corpus" guard.
    """
    return sorted(p for p in recipes_dir.glob("*.md") if not p.name.startswith("."))


def audit(recipes_dir: Path) -> tuple[list[Violation], list[str]]:
    """Every violation across the corpus, for --check.

    Returns ``(violations, unreadable)``. A file that cannot be read is reported
    rather than allowed to abort the run — a guard that crashes on one bad file
    tells you nothing about the other 251.
    """
    out: list[Violation] = []
    unreadable: list[str] = []
    for p in recipe_files(recipes_dir):
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            unreadable.append(f"{p.stem}: {type(e).__name__}: {e}")
            continue
        out.extend(check_frontmatter(p.stem, parse_recipe_file(content)["frontmatter"]))

        # Duplicates are invisible to the dict-based check above — the mapping
        # has already collapsed them — so they are found in the raw text.
        fm_text, _ = frontmatter.split_frontmatter(content)
        for key in duplicate_keys(fm_text or ""):
            out.append(Violation(
                p.stem, key, "duplicate_key",
                f"{key!r} appears more than once; YAML keeps only the last, so "
                f"the earlier value is silently discarded",
            ))
    return out, unreadable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1 if any exists; never writes")
    args = ap.parse_args()

    recipes_dir = paths.recipes_dir()

    # An empty corpus must never report "0 violations". lib/paths.py resolves
    # KITCHENOS_VAULT from the repo's own .env, which is git-ignored and so
    # absent from every linked worktree — running this from .worktrees/ found
    # zero recipes and exited 0, which reads as "the corpus is clean" when it
    # means "the corpus was never looked at". Same failure shape as --only
    # matching nothing: silence that looks like success.
    if not recipes_dir.is_dir() or not any(recipes_dir.glob("*.md")):
        raise SystemExit(
            f"no recipes found in {recipes_dir}\n"
            "If you are in a linked worktree, .env lives only in the main "
            "checkout — set KITCHENOS_VAULT explicitly, e.g.\n"
            "  KITCHENOS_VAULT=/Users/<you>/Dev/KitchenOS/vault/KitchenOS \\\n"
            "    ../../.venv/bin/python scripts/normalize_recipes.py --check"
        )

    if args.check:
        violations, unreadable = audit(recipes_dir)
        for v in violations:
            # The recipe name is the join key and is what gets pasted into
            # --only, so it is never truncated: 17 corpus names exceed 46 chars.
            print(f"  {v.code:22} {v.recipe}\n{'':24}{v.detail}")
        for u in unreadable:
            print(f"  UNREADABLE             {u}")
        total = len(recipe_files(recipes_dir))
        print(f"\n{len(violations)} violation(s) across {total} recipes")
        if unreadable:
            print(f"{len(unreadable)} file(s) could not be read")
        return 1 if (violations or unreadable) else 0

    if not args.apply:
        print("DRY RUN — no files will be modified (pass --apply to write)\n")

    written = 0
    repairable = 0
    servings_changed: list[str] = []
    unrepaired: list[str] = []
    failed: list[str] = []

    for p in recipe_files(recipes_dir):
        # Contain per-file failures: one unreadable note must not abort the run
        # and swallow the trailing summary for everything already processed.
        try:
            changes, did_write = normalize_file(p, apply=args.apply)
        except (OSError, UnicodeDecodeError) as e:
            failed.append(f"{p.stem}: {type(e).__name__}: {e}")
            print(f"{p.stem}\n    FAILED {type(e).__name__}: {e}")
            continue

        if not changes:
            continue
        if did_write:
            written += 1
        # What a real apply would write: any change that isn't purely a report.
        if any(not c.startswith(("UNREPAIRED", "SKIPPED", "FAILED")) for c in changes):
            repairable += 1
        if any(c.startswith("servings ") for c in changes):
            servings_changed.append(p.stem)
        if any(c.startswith(("UNREPAIRED", "SKIPPED")) for c in changes):
            unrepaired.append(p.stem)
        print(f"{p.stem}")
        for c in changes:
            print(f"    {c}")

    # A dry run writes nothing, so its count is what an apply *would* write —
    # not `written`, which is structurally zero there.
    label = "Modified" if args.apply else "Would modify"
    print(f"\n{label}: {written if args.apply else repairable} file(s)")

    if servings_changed:
        print(
            f"\n{len(servings_changed)} file(s) had servings changed — their stored\n"
            "per-serving macros came from the OLD count and are now stale. Each is\n"
            "marked nutrition_needs_review: true; re-derive them with:\n"
            + "".join(
                f'  .venv/bin/python backfill_nutrition.py --force --only "{n}"\n'
                for n in servings_changed
            )
        )

    # Exit non-zero on work the tool could not do. Reporting success while
    # --check will fail forever on the same file is the exact "silence that
    # looks like success" shape the other guards in this tool exist to prevent.
    if unrepaired or failed:
        if unrepaired:
            print(
                f"\n{len(unrepaired)} file(s) could not be fully repaired — "
                "--check will keep reporting these:\n"
                + "".join(f"  {n}\n" for n in unrepaired)
            )
        if failed:
            print(f"\n{len(failed)} file(s) failed to process:\n"
                  + "".join(f"  {n}\n" for n in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
