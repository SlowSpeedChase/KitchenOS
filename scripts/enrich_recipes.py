#!/usr/bin/env python3
"""Fill missing recipe frontmatter with Haiku, and flag internal inconsistencies.

Strictly *additive*: a field is only written when its current value is missing,
null, or a known junk placeholder (the literal string "null", "0 seconds",
prose like "Not explicitly mentioned"). An existing good value is never
overwritten — a small model guessing over curated data is how a recipe library
silently rots.

The model is asked only for things derivable from the recipe text in front of
it (servings, times, cuisine, dietary flags) plus internal-consistency checks
(ingredients used in steps but absent from the table, and vice versa). It is
never asked to invent or "correct" ingredients or instructions; suspected
content problems are reported, not applied.

Usage:
    .venv/bin/python scripts/enrich_recipes.py --dry-run [--limit N]
    .venv/bin/python scripts/enrich_recipes.py [--limit N] [--only-servings]
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import anthropic

from lib import frontmatter, normalizer, paths
from lib.backup import create_backup

MODEL = "claude-haiku-4-5-20251001"

# Fields this script may write. Anything not listed is untouchable.
MANAGED_KEYS = {
    "servings", "prep_time", "cook_time", "total_time", "difficulty",
    "cuisine", "protein", "dish_type", "meal_occasion", "dietary",
}

# Allergen-negative claims are never auto-filled. A wrong "vegetarian" is a bad
# dinner; a wrong "nut-free" or "gluten-free" is a medical event, and a small
# model reading a partial ingredient list cannot clear a recipe of trace
# allergens. These stay empty until a human sets them.
ALLERGEN_CLAIMS = {"nut-free", "gluten-free", "dairy-free"}

# Values that mean "absent" even though the key exists.
_JUNK_RE = re.compile(
    r"^\s*(null|none|n/?a|unknown|-|\?|0\s*(seconds?|mins?|minutes?)"
    r"|not\s+explicitly.*|variable.*|see\s+.*)\s*$",
    re.I,
)

_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def is_missing(value) -> bool:
    """True when a frontmatter value carries no usable information."""
    if value is None or value is False:
        return True
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    if isinstance(value, str):
        return not value.strip() or bool(_JUNK_RE.match(value))
    return False


def split_recipe(text: str):
    m = _FM_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_fm(fm_text: str) -> dict:
    import yaml
    try:
        return yaml.safe_load(fm_text) or {}
    except Exception:
        return {}


def section(body: str, name: str, limit: int = 4000) -> str:
    m = re.search(rf"^## {name}\s*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    return m.group(1).strip()[:limit] if m else ""


PROMPT = """You are auditing one recipe from a personal Obsidian cookbook. \
Return ONLY the requested JSON.

Recipe title: {title}
Source: {channel}

## Ingredients
{ingredients}

## Instructions
{instructions}

Fill in ONLY these missing metadata fields: {missing}

Rules:
- servings: a single integer, your best estimate of how many people this recipe \
feeds based on the ingredient quantities. This is the most important field — \
downstream per-serving nutrition is computed by dividing by it. Never return a \
range or prose.
- prep_time / cook_time / total_time: strings like "15 minutes" or "1 hour". \
Estimate from the instructions. Omit a field entirely if you truly cannot tell.
- difficulty: one of easy, medium, hard
- cuisine: a single word/short phrase, e.g. Italian, Mexican, Thai, American
- protein: the ONE main protein, from exactly this list: {proteins}
- dish_type: exactly one of: {dish_types}
- meal_occasion: array, 1-3 values from exactly: {occasions}. Only occasions a \
person would actually use this dish for — do not pad the list.
- dietary: array, only values from exactly: {dietary} — include a tag ONLY if \
the ingredient list genuinely satisfies it (no meat AND no fish AND no dairy \
AND no eggs for vegan, etc.). When unsure, leave it out. Do NOT emit nut-free, \
gluten-free, or dairy-free; those are set by hand.

Also perform an internal-consistency check and report (do not fix):
- "unlisted": ingredients the instructions use that are missing from the \
ingredient table
- "unused": ingredients in the table that no step ever uses
- "issues": any quantity that looks like a transcription error (e.g. 50 cloves \
of garlic, 12 tablespoons of salt), or a step that is impossible as written. \
Be conservative — only flag things that are clearly wrong.

Respond with JSON only:
{{"servings": 4, "prep_time": "...", "unlisted": [], "unused": [], "issues": []}}
Omit any metadata key you were not asked for or cannot determine."""


def build_prompt(title, channel, ingredients, instructions, missing):
    return PROMPT.format(
        title=title, channel=channel or "unknown",
        ingredients=ingredients or "(none listed)",
        instructions=instructions or "(none listed)",
        missing=", ".join(missing),
        proteins=", ".join(sorted(set(normalizer.PROTEIN_MAP.values()))),
        dish_types=", ".join(sorted(set(normalizer.DISH_TYPE_MAP.values()))),
        occasions=", ".join(sorted(normalizer.VALID_MEAL_OCCASIONS)),
        dietary=", ".join(sorted(normalizer.VALID_DIETARY)),
    )


def call_model(client, prompt: str) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=900, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in response: {text[:120]}")
    return json.loads(m.group())


# Fields we ask the model to fill, and how each is validated before writing.
INFERABLE = ["servings", "prep_time", "cook_time", "total_time", "difficulty",
             "cuisine", "protein", "dish_type", "meal_occasion", "dietary"]


def clean_value(field: str, value):
    """Validate/normalize one model-supplied value. Returns None to skip."""
    if value is None or value == "" or value == []:
        return None
    if field == "servings":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return n if 1 <= n <= 100 else None
    if field in ("prep_time", "cook_time", "total_time"):
        s = str(value).strip()
        return s if s and not _JUNK_RE.match(s) and re.search(r"\d", s) else None
    if field == "cuisine":
        s = str(value).strip()
        return s if 0 < len(s) <= 30 else None
    if field in ("protein", "dish_type", "difficulty", "dietary", "meal_occasion"):
        out = normalizer.normalize_field(field, value)
        if isinstance(out, tuple):  # ("unknown", original) — reject
            return None
        if field == "dietary" and out:
            out = [d for d in out if d not in ALLERGEN_CLAIMS]
        return out or None
    return None


def yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(f'"{x}"' for x in v) + "]"
    return f'"{v}"'


def process(path: Path, client, args):
    text = path.read_text(encoding="utf-8")
    fm_text, body = split_recipe(text)
    if fm_text is None:
        return {"file": path.name, "status": "no-frontmatter"}
    fm = parse_fm(fm_text)

    wanted = ["servings"] if args.only_servings else INFERABLE
    missing = [f for f in wanted if is_missing(fm.get(f))]
    if not missing:
        return {"file": path.name, "status": "complete"}

    prompt = build_prompt(
        fm.get("title") or path.stem, fm.get("source_channel"),
        section(body, "Ingredients"), section(body, "Instructions"), missing,
    )
    try:
        data = call_model(client, prompt)
    except Exception as e:
        return {"file": path.name, "status": "error", "error": str(e)[:140]}

    updates = {}
    for field in missing:
        if field not in data:
            continue
        cleaned = clean_value(field, data[field])
        if cleaned is not None:
            updates[field] = cleaned

    flags = {k: data.get(k) or [] for k in ("unlisted", "unused", "issues")}
    flags = {k: v for k, v in flags.items() if v}

    result = {
        "file": path.name, "status": "updated" if updates else "no-op",
        "updates": updates, "flags": flags, "asked": missing,
    }
    if args.dry_run or not updates:
        return result

    create_backup(path)
    new_fm = frontmatter.rewrite(
        fm_text, {k: yaml_scalar(v) for k, v in updates.items()}, MANAGED_KEYS
    )
    path.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only-servings", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None, help="write JSON report here")
    args = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key)

    files = sorted(paths.recipes_dir().glob("*.md"))
    if args.limit:
        files = files[: args.limit]

    print(f"{'DRY RUN — ' if args.dry_run else ''}{len(files)} recipes, model={MODEL}")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, r in enumerate(pool.map(lambda p: process(p, client, args), files), 1):
            results.append(r)
            if r["status"] in ("updated", "error") or r.get("flags"):
                bits = ", ".join(f"{k}={v}" for k, v in r.get("updates", {}).items())
                print(f"[{i}/{len(files)}] {r['status']:9s} {r['file']}"
                      + (f" | {bits}" if bits else "")
                      + (f" | FLAGS {r['flags']}" if r.get("flags") else "")
                      + (f" | {r.get('error','')}" if r["status"] == "error" else ""))

    from collections import Counter
    print("\n=== SUMMARY ===")
    for k, v in Counter(r["status"] for r in results).most_common():
        print(f"  {k:14s} {v}")
    filled = Counter()
    for r in results:
        for k in r.get("updates", {}):
            filled[k] += 1
    print("  fields filled:", dict(filled))
    flagged = [r for r in results if r.get("flags")]
    print(f"  recipes with consistency flags: {len(flagged)}")

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"  report → {args.out}")


if __name__ == "__main__":
    main()
