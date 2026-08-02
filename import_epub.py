#!/usr/bin/env python3
"""
Import recipes from a cookbook EPUB into the KitchenOS Obsidian vault.

Structural extraction only — ingredient lines, quantities and steps. The book's
written prose (head notes, tips) is not imported; `description` is generated fresh
by the same Ollama enrichment used elsewhere.

Usage:
    python import_epub.py "/path/to/book.epub"
    python import_epub.py --dry-run "/path/to/book.epub"
    python import_epub.py --limit 5 "/path/to/book.epub"
    python import_epub.py --no-enrich "/path/to/book.epub"
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from lib import backup
from lib import paths
from lib.epub_parser import parse_epub
from lib.normalizer import normalize_recipe_data
from lib.recipe_parser import parse_recipe_file
from templates.recipe_template import format_recipe_markdown, generate_filename

# The Ollama enrichment call and duplicate check are identical to the Crouton
# importer's; reused rather than reimplemented.
from import_crouton import enrich_with_ollama, check_duplicate

OBSIDIAN_RECIPES_PATH = paths.recipes_dir()


def book_title(epub_path: Path) -> str:
    """A human-readable source name for attribution, derived from the filename."""
    stem = epub_path.stem
    # Calibre-style "Title_ Subtitle - Author" -> "Title"
    stem = stem.split(" - ")[0]
    stem = stem.split("_")[0]
    return stem.strip() or epub_path.stem


def _existing_source(recipe_name: str):
    """The source_channel of an already-present note of this name, or None."""
    path = OBSIDIAN_RECIPES_PATH / generate_filename(recipe_name)
    if not path.exists():
        return None
    try:
        parsed = parse_recipe_file(path.read_text(encoding="utf-8"))
        return parsed["frontmatter"].get("source_channel")
    except Exception:
        return None


def save_imported_recipe(recipe_data: dict, source_name: str) -> tuple:
    """Write one parsed recipe into the vault.

    Returns:
        Tuple of (filepath, is_duplicate).
    """
    recipe_name = recipe_data["recipe_name"]
    is_duplicate = check_duplicate(recipe_name)

    # Re-running the importer must update this book's own notes in place, not spawn
    # "X (Book Title)" twins. Only a name collision with a *different* source gets
    # the suffix.
    if is_duplicate and _existing_source(recipe_name) == source_name:
        is_duplicate = False

    recipe_name_for_file = f"{recipe_name} ({source_name})" if is_duplicate else recipe_name

    today = date.today().isoformat()

    file_recipe_data = dict(recipe_data)
    file_recipe_data["recipe_name"] = recipe_name_for_file

    markdown = format_recipe_markdown(
        file_recipe_data,
        video_url="",
        video_title=source_name,
        channel=source_name,
        date_added=today,
    )

    # The template's footer assumes a web source; restate it as a book citation,
    # carrying the print page so the recipe can be found in the physical book.
    page = recipe_data.get("book_page")
    citation = f"{source_name}, p. {page}" if page else source_name
    markdown = re.sub(
        r"\*Extracted from \[.*?\]\(.*?\) on " + re.escape(today) + r"\*",
        f"*Imported from {citation} on {today}*",
        markdown,
    )

    # book_page is an OPTIONAL_KEYS field (lib/recipe_schema.py) written only by this
    # importer, so it's injected here rather than added to the shared template.
    if page:
        markdown = re.sub(
            r"^(recipe_source: .*)$",
            rf"\1\nbook_page: {page}",
            markdown,
            count=1,
            flags=re.M,
        )

    OBSIDIAN_RECIPES_PATH.mkdir(parents=True, exist_ok=True)
    filepath = OBSIDIAN_RECIPES_PATH / generate_filename(recipe_name_for_file)
    # A collision replaces the WHOLE file, "My Notes" included — the one part the
    # user wrote. Snapshot first; write_note no-ops when nothing changed.
    backup.write_note(filepath, markdown)

    return filepath, is_duplicate


def main():
    parser = argparse.ArgumentParser(
        description="Import cookbook EPUB recipes into KitchenOS"
    )
    parser.add_argument("epub_path", type=str, help="Path to the .epub file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be imported without writing files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Import at most N recipes (for spot-checking)")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip Ollama enrichment (fast, but dish_type/cuisine stay null)")
    args = parser.parse_args()

    epub_path = Path(args.epub_path).expanduser()
    if not epub_path.is_file():
        print(f"Error: {epub_path} is not a file", file=sys.stderr)
        sys.exit(1)

    source_name = book_title(epub_path)
    recipes = [r for _, r in parse_epub(epub_path)]
    if args.limit:
        recipes = recipes[:args.limit]

    if not recipes:
        print(f"No recipes found in {epub_path.name}")
        sys.exit(0)

    total = len(recipes)
    imported = duplicates = failed = 0

    print(f"Found {total} recipes in {epub_path.name} (source: {source_name})")
    if args.dry_run:
        print("DRY RUN — no files will be written\n")
    if args.no_enrich:
        print("Skipping Ollama enrichment\n")

    for i, recipe_data in enumerate(recipes, 1):
        prefix = f"[{i:3d}/{total}]"
        recipe_name = recipe_data["recipe_name"]

        try:
            is_dup = check_duplicate(recipe_name)
            dup_label = " (duplicate)" if is_dup else ""

            if args.dry_run:
                n_ing = len([x for x in recipe_data["ingredients"]
                             if not x.get("is_subhead")])
                n_step = len(recipe_data["instructions"])
                serves = recipe_data["servings"] or "-"
                print(f"{prefix} {recipe_name}{dup_label} "
                      f"[{n_ing} ing, {n_step} steps, serves {serves}]")
                imported += 1
                duplicates += 1 if is_dup else 0
                continue

            if not args.no_enrich:
                print(f"{prefix} {recipe_name}{dup_label} ... enriching",
                      end="", flush=True)
                recipe_data = enrich_with_ollama(recipe_data)
                print(" ... ", end="", flush=True)
            else:
                print(f"{prefix} {recipe_name}{dup_label} ... ", end="", flush=True)

            normalize_recipe_data(recipe_data)

            filepath, was_dup = save_imported_recipe(recipe_data, source_name)
            print(f"saved → {filepath.name}")

            imported += 1
            duplicates += 1 if was_dup else 0

        except Exception as e:
            print(f"{prefix} {recipe_name} ... FAILED: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {imported} imported ({duplicates} duplicates), {failed} failed")


if __name__ == "__main__":
    main()
