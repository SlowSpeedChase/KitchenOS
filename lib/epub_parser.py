"""Structural recipe extraction from cookbook EPUB XHTML.

An EPUB is a zip of XHTML, so this needs no epub library — ``zipfile`` plus the
``bs4`` already used by ``recipe_sources`` covers it.

Extraction is purely structural: the source book tags every recipe element with a
semantic class (``x11-Recipe-Ingredients``, ``x11-Recipe-Direction``, ...) in a fixed
document order, so no LLM is needed to find the fields. Metadata the book doesn't
carry (cuisine, dish_type, difficulty) is inferred downstream by the same Ollama
enrichment ``import_crouton.py`` uses.

Prose classes (head notes, tips, asides, bursts) are deliberately **not** extracted —
only the functional recipe data (ingredient lines, quantities, steps) is imported, and
``description`` is generated fresh downstream.
"""

import re
import warnings
import zipfile
from pathlib import Path
from typing import Iterator, Optional

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# EPUB content is XHTML. The lenient HTML parser is deliberate — real books ship
# malformed markup that the strict XML parser rejects outright — so silence bs4's
# suggestion to switch parsers.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from lib.ingredient_parser import parse_ingredient_best

# Key set on an ingredient dict to mark it as a group header row rather than a real
# ingredient (the recipe template renders a flat table, so groups can only be rows).
SUBHEAD_MARKER = "is_subhead"

TITLE_CLASS = "x11-Recipe-Title"
YIELD_CLASS = "x11-Recipe-Yield"

INGREDIENT_CLASSES = {
    "x11-Recipe-Ingredients",
    "x11-Recipe-Ingredients-First",
    "x11-Recipe-Ingredients-Last",
    "x11-Subrecipe-Ingredients",
    "x11-Subrecipe-Ingredients-First",
}

# A component's title labels the ingredient group that follows it, exactly like an
# explicit ingredients subhead.
INGREDIENT_SUBHEAD_CLASSES = {
    "x11-Recipe-Ingredients-Subhead",
    "x11-Subrecipe-Title",
}

DIRECTION_CLASSES = {
    "x11-Recipe-Direction",
    "x11-Recipe-Direction-1P",
    "x11-Recipe-Direction-First",
    "x11-Recipe-Direction-First-NS",
    "x11-Recipe-Direction-Sub",
    "x11-Recipe-Direction-Sub-2",
    "x11-Subrecipe-Direction",
    "x11-Subrecipe-Direction-1P",
    "x11-Subrecipe-Direction-First",
}

DIRECTION_SUBHEAD_CLASSES = {"x11-Recipe-Direction-Subhead"}

# Every element we read, for a single document-order pass.
_RELEVANT = (
    {TITLE_CLASS, YIELD_CLASS}
    | INGREDIENT_CLASSES
    | INGREDIENT_SUBHEAD_CLASSES
    | DIRECTION_CLASSES
    | DIRECTION_SUBHEAD_CLASSES
)

# Yield lines that measure volume/weight rather than portions carry no serving count.
_NON_PORTION_UNITS = re.compile(
    r"\b(cups?|quarts?|pints?|gallons?|ounces?|oz|pounds?|lbs?|grams?|g|ml|liters?|litres?|tablespoons?|teaspoons?)\b",
    re.I,
)
_YIELD_COUNT = re.compile(r"\b(?:serves|makes|yields?)\s+(?:about\s+)?(\d+)", re.I)

# Yield lines carry the book's own dietary badges after a pipe
# ("Makes 4 cups (960 g) | GF, SF, NF"). Reading them beats having the LLM guess.
# Values outside VALID_DIETARY (e.g. soy-free) are dropped later by
# normalize_recipe_data — this map only has to be faithful to the book.
_DIET_BADGES = {
    "GF": "gluten-free",
    "NF": "nut-free",
    "SF": "soy-free",
    "DF": "dairy-free",
}


def parse_dietary_tags(text: str) -> list:
    """Extract dietary badges from the tail of a yield line."""
    if not text or "|" not in text:
        return []
    tail = text.rsplit("|", 1)[1]
    found = []
    for token in re.split(r"[,\s]+", tail):
        mapped = _DIET_BADGES.get(token.strip().upper())
        if mapped and mapped not in found:
            found.append(mapped)
    return found


def parse_yield(text: str) -> Optional[int]:
    """Extract a serving count from a yield line.

    Returns the first number in a "Serves N" / "Makes N" phrase, or None when the
    line measures volume ("Makes about 2 cups") or carries no number at all. For a
    range ("Serves 4 to 6") the lower bound is used, matching how the rest of
    KitchenOS treats servings as a planning floor.
    """
    if not text:
        return None
    match = _YIELD_COUNT.search(text)
    if not match:
        return None
    # "Makes 12 cookies" is a portion count; "Makes about 2 cups" is not.
    tail = text[match.end():]
    if _NON_PORTION_UNITS.match(tail.strip()):
        return None
    return int(match.group(1))


def _classes(tag) -> set:
    value = tag.get("class")
    if not value:
        return set()
    if isinstance(value, str):
        return {value}
    return set(value)


def _text(tag) -> str:
    return tag.get_text(" ", strip=True)


def _subhead_row(label: str) -> dict:
    """A group header rendered as a bolded, quantity-less table row."""
    return {"amount": "", "unit": "", "item": f"**{label}**",
            "inferred": False, SUBHEAD_MARKER: True}


def parse_recipe_xhtml(html: str) -> Optional[dict]:
    """Parse one recipe XHTML document into KitchenOS recipe_data.

    Returns None if the document holds no recipe (front matter, chapter intros,
    index pages).
    """
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find(class_=TITLE_CLASS)
    if title_tag is None:
        return None
    recipe_name = _text(title_tag)
    if not recipe_name:
        return None

    servings = None
    ingredients = []
    instructions = []
    # The source book is entirely plant-based, so vegan is known rather than inferred;
    # per-recipe badges off the yield line are appended as they're encountered.
    dietary = ["vegan"]
    pending_section = None
    step_num = 1

    # One document-order pass so ingredient subheads and component groups land in
    # the right position relative to the lines they label.
    for tag in soup.find_all(class_=lambda c: bool(c) and bool(_RELEVANT & (
            {c} if isinstance(c, str) else set(c)))):
        classes = _classes(tag)
        text = _text(tag)
        if not text:
            continue

        if TITLE_CLASS in classes:
            continue

        if YIELD_CLASS in classes:
            if servings is None:
                servings = parse_yield(text)
            for tag in parse_dietary_tags(text):
                if tag not in dietary:
                    dietary.append(tag)

        elif classes & INGREDIENT_SUBHEAD_CLASSES:
            ingredients.append(_subhead_row(text))

        elif classes & INGREDIENT_CLASSES:
            parsed = parse_ingredient_best(text)
            ingredients.append({
                "amount": parsed["amount"],
                "unit": parsed["unit"],
                "item": parsed["item"],
                "inferred": False,
            })

        elif classes & DIRECTION_SUBHEAD_CLASSES:
            pending_section = text

        elif classes & DIRECTION_CLASSES:
            # Section headers ride along on the following step, matching how
            # lib/crouton_parser handles isSection steps.
            body = f"**{pending_section}** {text}" if pending_section else text
            pending_section = None
            instructions.append({"step": step_num, "text": body})
            step_num += 1

    if not ingredients and not instructions:
        return None

    return {
        "recipe_name": recipe_name,
        "servings": servings,
        "ingredients": ingredients,
        "instructions": instructions,
        "source": "epub_import",
        "source_url": "",
        "source_channel": "",
        "prep_time": "",
        "cook_time": "",
        "notes": "",
        "needs_review": True,
        "confidence_notes": "Imported from EPUB. Metadata enriched by AI.",
        "description": "",
        "cuisine": None,
        "protein": None,
        "difficulty": None,
        "dish_type": None,
        "meal_occasion": [],
        "dietary": dietary,
        "equipment": [],
    }


def iter_recipe_documents(epub_path: Path) -> Iterator[tuple]:
    """Yield ``(archive_name, html)`` for each document containing a recipe title.

    Reads text entries only — cover art and fonts make up most of the archive and
    are never opened.
    """
    with zipfile.ZipFile(epub_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            try:
                raw = zf.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            if TITLE_CLASS not in raw:
                continue
            yield name, raw


def parse_epub(epub_path: Path) -> Iterator[tuple]:
    """Yield ``(archive_name, recipe_data)`` for every parsable recipe in the book."""
    for name, html in iter_recipe_documents(epub_path):
        recipe = parse_recipe_xhtml(html)
        if recipe is not None:
            yield name, recipe
