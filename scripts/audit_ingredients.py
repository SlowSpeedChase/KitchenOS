#!/usr/bin/env python3
"""Audit every recipe's ingredient table for lines a cook could not act on.

Written after a note came in reading "This has a whole greek yogurt which doesn't
make sense and same for cocoa powder." Both were real, and neither was reachable
by any existing check: the only countability knowledge in the codebase is a
23-word `_BULK_SUBSTANCES` tuple in fdc_local.py, which catches "powder" by
substring and misses "dark chocolate" entirely.

This reports; it does not mutate. Run it before and after any corpus fix.

    .venv/bin/python scripts/audit_ingredients.py
    .venv/bin/python scripts/audit_ingredients.py --report docs/ingredient-audit.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backfill_nutrition import extract_ingredients  # noqa: E402
from lib.paths import recipes_dir  # noqa: E402
from lib.units import get_unit_family, lookup_density, normalize_unit  # noqa: E402

# Words that signal a poured/spooned substance. Same list the ledger guard uses —
# quoted rather than imported so the audit still reports if that guard changes.
BULK_WORDS = (
    "oil", "water", "flour", "honey", "syrup", "mayo", "mayonnaise", "sauce",
    "milk", "cream", "juice", "vinegar", "broth", "stock", "yogurt", "sugar",
    "salt", "powder", "mustard", "ketchup", "butter", "granola", "rice",
    "cocoa", "chocolate", "paste", "puree", "extract", "spice", "seasoning",
)

# Measurement words that belong in the Unit column. Finding one inside the
# Ingredient column means the extractor's parse leaked.
UNIT_WORDS = (
    "cup", "cups", "tbsp", "tablespoon", "tsp", "teaspoon", "oz", "ounce",
    "lb", "pound", "gram", "grams", "g", "ml", "liter", "litre", "pinch",
    "clove", "cloves", "can", "cans", "slice", "slices",
)


# An exact weight the recipe author supplied, sitting unused inside the name.
GRAM_EQUIV = re.compile(
    r"\((?:about\s+)?[\d.,/ ]+\s*(?:g|gram|grams|ml|kg|oz|ounce|ounces|lb|pound)s?\b[^)]*\)",
    re.I)
PRICE = re.compile(r"\$\s?\d")
SPONSOR = re.compile(r"code:|@[a-z0-9._]+\.", re.I)
XREF = re.compile(r"\bsee note\b|\boriginal recipe\b", re.I)
NO_AMOUNT = re.compile(
    r"quantity not specified|to your liking|a few splashes|\bhandful\b", re.I)
OVEN_TEMP = re.compile(r"^\s*f?\s*\d{3}\s*$|^\s*\d{3}\s*f\s*$", re.I)

# Triage. Only `defect` should drive a corpus fix; `info` exists so the headline
# number isn't inflated by lines that read perfectly well to a cook.
#   defect      — mechanically wrong, deterministic fix, no judgement needed
#   filler      — the recipe stated no amount and the extractor invented one
#   recoverable — real data being discarded; fixing this ADDS precision
#   junk        — source-page noise that should never have been an ingredient
#   info        — flagged by a strict rule but legitimate recipe language
SEVERITY = {
    "unknown_unit": "defect",
    "unit_repeated_in_item": "defect",
    "leading_punctuation": "defect",
    "doubled_word": "defect",
    "empty_item": "defect",
    "whole_on_bulk": "filler",
    "count_unit_on_pourable": "filler",
    "no_amount_stated": "filler",
    "gram_equivalent_discarded": "recoverable",
    "price_leaked": "junk",
    "cross_reference": "junk",
    "sponsor_code": "junk",
    "oven_temp_as_ingredient": "junk",
    "alternatives": "info",
    "parenthetical": "info",
    "digits_in_item": "info",
    "unit_word_in_item": "info",
}
ORDER = ["defect", "recoverable", "filler", "junk", "info"]


def parse_rows(text: str) -> list[tuple[str, str, str]]:
    """(amount, unit, item) for each ingredient row.

    Delegates to the same ``extract_ingredients`` the nutrition backfill uses,
    so the audit can never disagree with the pipeline about what an ingredient
    line is — an audit that parses differently from the code it audits reports
    on a corpus that doesn't exist.
    """
    return [(str(d.get("amount", "")), str(d.get("unit", "")), str(d.get("item", "")))
            for d in extract_ingredients(text)]


def _bulk_hit(item: str) -> str | None:
    low = item.lower()
    return next((w for w in BULK_WORDS if re.search(rf"\b{re.escape(w)}\b", low)), None)


def check(amount: str, unit: str, item: str) -> list[tuple[str, str]]:
    """(issue_key, detail) for one row. Empty means the line reads fine."""
    issues = []
    # The inferred marker is rendered inconsistently across the corpus —
    # "*(inferred)*", "** (inferred)", "*(inferred)" — so strip it loosely or the
    # marker itself gets counted as a parenthetical aside in the ingredient name.
    clean = re.sub(r"\*+\s*\(\s*inferred\s*\)\s*\**", "", item, flags=re.I).strip()
    clean = clean.strip("* ").strip()
    low = clean.lower()
    u = unit.strip().lower()

    if u == "whole":
        hit = _bulk_hit(clean)
        if hit:
            issues.append(("whole_on_bulk",
                           f"'{amount} whole {clean}' — {hit} is poured or spooned"))

    words = low.split()
    for a, b in zip(words, words[1:]):
        if a == b and len(a) > 2:
            issues.append(("doubled_word", f"'{clean}' repeats '{a}'"))
            break
    if u and words and u == words[0]:
        issues.append(("unit_repeated_in_item",
                       f"unit '{unit}' also starts the item '{clean}'"))

    if re.search(r"\d", clean):
        issues.append(("digits_in_item", f"'{clean}' contains a number"))
    for w in UNIT_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            issues.append(("unit_word_in_item", f"'{clean}' contains unit word '{w}'"))
            break
    if clean.startswith(("+", "%", ",", "-", "or ", "and ")) or "%" in clean[:3]:
        issues.append(("leading_punctuation", f"'{clean}' starts mid-phrase"))
    if "(" in clean or ")" in clean:
        issues.append(("parenthetical", f"'{clean}' carries an aside"))
    if re.search(r"\bor\b", low):
        issues.append(("alternatives", f"'{clean}' offers a choice"))

    if u:
        fam = get_unit_family(normalize_unit(u))
        if fam == "other":
            issues.append(("unknown_unit", f"unit '{unit}' is unrecognized"))
        elif fam == "count" and lookup_density(clean) is not None:
            issues.append(("count_unit_on_pourable",
                           f"'{clean}' has a density but a count unit '{unit}'"))
    if not clean:
        issues.append(("empty_item", "ingredient name is blank"))

    if GRAM_EQUIV.search(clean):
        issues.append(("gram_equivalent_discarded",
                       f"'{clean}' states an exact weight that is being thrown away"))
    if PRICE.search(clean):
        issues.append(("price_leaked", f"'{clean}' carries a price from the source page"))
    if SPONSOR.search(clean):
        issues.append(("sponsor_code", f"'{clean}' carries a sponsor/affiliate code"))
    if XREF.search(clean):
        issues.append(("cross_reference", f"'{clean}' points at a note that wasn't kept"))
    if NO_AMOUNT.search(clean):
        issues.append(("no_amount_stated",
                       f"'{clean}' says outright that no amount was given"))
    if OVEN_TEMP.search(clean):
        issues.append(("oven_temp_as_ingredient",
                       f"'{clean}' is an oven temperature, not an ingredient"))
    return issues


TITLES = {
    "whole_on_bulk": "'whole' used for something poured or spooned",
    "doubled_word": "a word repeats inside the ingredient name",
    "unit_repeated_in_item": "the unit is duplicated into the ingredient name",
    "digits_in_item": "a number leaked into the ingredient name",
    "unit_word_in_item": "a measurement word leaked into the ingredient name",
    "leading_punctuation": "the name starts mid-phrase",
    "parenthetical": "the name carries a parenthetical aside",
    "alternatives": "the name offers a choice ('x or y')",
    "unknown_unit": "unrecognized unit",
    "count_unit_on_pourable": "count unit on a pourable item",
    "empty_item": "blank ingredient name",
    "gram_equivalent_discarded": "an exact weight is sitting unused in the name",
    "price_leaked": "a price came along from the source page",
    "cross_reference": "points at a note that wasn't kept",
    "sponsor_code": "a sponsor/affiliate code came along",
    "no_amount_stated": "the line says outright that no amount was given",
    "oven_temp_as_ingredient": "an oven temperature parsed as an ingredient",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", help="write a markdown report here")
    ap.add_argument("--issue", help="show every occurrence of one issue key")
    args = ap.parse_args()

    counts, affected = Counter(), defaultdict(set)
    examples, total_rows, total_recipes = defaultdict(list), 0, 0
    dirty_recipes = set()

    for path in sorted(Path(recipes_dir()).glob("*.md")):
        total_recipes += 1
        rows = parse_rows(path.read_text(encoding="utf-8"))
        total_rows += len(rows)
        for amount, unit, item in rows:
            for key, detail in check(amount, unit, item):
                counts[key] += 1
                affected[key].add(path.name)
                dirty_recipes.add(path.name)
                examples[key].append((path.name, detail))

    if args.issue:
        for name, detail in examples.get(args.issue, []):
            print(f"{name}\n    {detail}")
        return 0

    actionable = {k for k in counts if SEVERITY.get(k, "info") != "info"}
    dirty_actionable = set().union(*(affected[k] for k in actionable)) if actionable else set()

    lines = [
        "# Ingredient audit",
        "",
        f"- recipes scanned: **{total_recipes}**",
        f"- ingredient lines: **{total_rows}**",
        f"- recipes with an *actionable* issue: **{len(dirty_actionable)}** "
        f"({len(dirty_actionable) / max(total_recipes, 1):.0%})",
        f"- recipes flagged by any rule incl. `info`: {len(dirty_recipes)} "
        f"({len(dirty_recipes) / max(total_recipes, 1):.0%})",
        "",
        "`info` lines read fine to a cook and are excluded from the headline —",
        "\"almond or cashew butter\" is how recipes talk, not a defect.",
        "",
        "| severity | issue | lines | recipes | what it means |",
        "|---|---|---:|---:|---|",
    ]
    for sev in ORDER:
        for key, n in counts.most_common():
            if SEVERITY.get(key, "info") != sev:
                continue
            lines.append(f"| `{sev}` | `{key}` | {n} | {len(affected[key])} "
                         f"| {TITLES.get(key, '')} |")
    lines += ["", "## Examples", ""]
    for key, _ in counts.most_common():
        lines.append(f"### `{key}`")
        for name, detail in examples[key][:6]:
            lines.append(f"- **{name}** — {detail}")
        if counts[key] > 6:
            lines.append(f"- …and {counts[key] - 6} more "
                         f"(`--issue {key}` for all)")
        lines.append("")

    out = "\n".join(lines)
    print(out)
    if args.report:
        Path(args.report).write_text(out + "\n", encoding="utf-8")
        print(f"\nwrote {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
