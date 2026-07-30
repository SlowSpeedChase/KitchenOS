"""Grid ("Cooking for Engineers" matrix) view of a recipe.

Turns a recipe's flat ingredient list + numbered steps into a *grid spec* — an
ordered chain of combine-groups — and renders it as the staircase-of-merged-cells
table that reads the whole method at a glance: ingredients down the left (with
gram weights when they resolve), a cascade of action cells to the right showing
what combines with what, in what order.

Deriving the grouping is LLM inference (Claude Haiku -> Ollama -> a plain
heuristic), so it is cached in a ``<recipe>.grid.json`` sidecar keyed by the
recipe's mtime and always carries ``needs_review: true`` — it is a suggestion to
sanity-check, never authoritative, and it never rewrites the recipe's own steps.

The chain model is linear (group 1 combined, group 2 added to it, ...). It fits
the common single-bowl recipe; genuinely branched recipes (two separate
mixtures merged late) collapse to a best-effort linear order — flagged for
review like everything else.
"""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from typing import Optional

import requests

try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    _anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:
    _anthropic_client = None

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 700
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"


# ---- ingredient display (best-effort grams) ------------------------------

def _ingredient_display(ing: dict) -> str:
    """Human-readable ingredient line: ``1 cup (120 g) flour``.

    Grams are best-effort: ``to_grams`` resolves mass units always and volume
    units when a density is known for the item; when it can't resolve, the gram
    parenthetical is simply omitted (honest, no guessing).
    """
    amount = str(ing.get("amount", "")).strip()
    unit = str(ing.get("unit", "")).strip()
    item = str(ing.get("item", "")).strip()

    grams_str = ""
    try:
        from lib.units import to_grams
        result = to_grams(amount or "1", unit or "whole", item)
        if result is not None and getattr(result, "grams", None) and not getattr(result, "needs_review", True):
            grams = round(result.grams)
            if grams > 0:
                grams_str = f" ({grams} g)"
    except Exception:
        grams_str = ""

    unit_part = "" if unit in ("", "whole") else f" {unit}"
    amount_part = amount if amount else ""
    prefix = f"{amount_part}{unit_part}".strip()
    return f"{prefix}{grams_str} {item}".strip()


# ---- LLM tiering (mirrors lib/task_extractor.py) --------------------------

def _group_with_claude(prompt: str) -> Optional[dict]:
    if _anthropic_client is None:
        return None
    try:
        message = _anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_json_object(message.content[0].text)
    except Exception:
        return None


def _group_with_ollama(prompt: str) -> Optional[dict]:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        if response.status_code != 200:
            return None
        return _extract_json_object(response.json().get("response", ""))
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None


def _extract_json_object(raw: str) -> Optional[dict]:
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _heuristic_grid(ingredients: list[dict], instructions: list[dict]) -> dict:
    """Offline fallback: no grouping inference, just the raw steps.

    Renders as ingredients-on-the-left with the numbered method in a single
    right-hand cell — still a clean card, just without the merged-cell chain.
    """
    return {
        "prep": [],
        "groups": [],
        "finish": "",
        "steps": [s.get("text", "") for s in instructions],
        "source": "heuristic",
        "needs_review": True,
    }


# ---- spec building + caching ---------------------------------------------

def _grid_prompt(ingredients: list[dict], instructions: list[dict]) -> str:
    from prompts.recipe_grid import GRID_PROMPT
    ing_lines = "\n".join(f"- {i.get('item', '')}" for i in ingredients)
    step_lines = "\n".join(
        f"{s.get('step', n + 1)}. {s.get('text', '')}" for n, s in enumerate(instructions)
    )
    return GRID_PROMPT.format(ingredients=ing_lines, steps=step_lines)


def _normalize_spec(raw: dict, source: str) -> dict:
    """Coerce an LLM object into the stored spec shape; drop malformed groups."""
    groups = []
    for g in raw.get("groups", []) or []:
        if not isinstance(g, dict):
            continue
        action = str(g.get("action", "")).strip()
        items = [str(x).strip() for x in (g.get("ingredients") or []) if str(x).strip()]
        if action or items:
            groups.append({"action": action, "ingredients": items})
    prep = [str(p).strip() for p in (raw.get("prep") or []) if str(p).strip()]
    return {
        "prep": prep,
        "groups": groups,
        "finish": str(raw.get("finish", "")).strip(),
        "steps": [],
        "source": source,
        "needs_review": True,
    }


def _sidecar_path(recipe_path: Path) -> Path:
    return recipe_path.with_suffix(".grid.json")


def _is_fresh(recipe_path: Path, sidecar: Path) -> bool:
    return sidecar.exists() and sidecar.stat().st_mtime >= recipe_path.stat().st_mtime


def build_grid(recipe_name: str, recipes_dir: Path, force: bool = False) -> Optional[dict]:
    """Return the grid spec for a recipe, using a cached sidecar when fresh.

    Returns None if the recipe file doesn't exist. The spec always carries
    ``ingredient_rows`` (display strings) so the renderer needs nothing else.
    """
    recipe_path = recipes_dir / f"{recipe_name}.md"
    if not recipe_path.exists():
        return None

    from lib.recipe_parser import parse_recipe_file, parse_recipe_body
    parsed = parse_recipe_file(recipe_path.read_text(encoding="utf-8"))
    body = parse_recipe_body(parsed["body"])
    ingredients = body.get("ingredients", [])
    instructions = body.get("instructions", [])
    ingredient_rows = [_ingredient_display(i) for i in ingredients]

    sidecar = _sidecar_path(recipe_path)
    if not force and _is_fresh(recipe_path, sidecar):
        try:
            spec = json.loads(sidecar.read_text(encoding="utf-8"))
            spec["ingredient_rows"] = ingredient_rows
            return spec
        except (json.JSONDecodeError, OSError):
            pass  # fall through and rebuild

    prompt = _grid_prompt(ingredients, instructions)
    raw = _group_with_claude(prompt)
    source = "claude"
    if raw is None:
        raw = _group_with_ollama(prompt)
        source = "ollama"
    if raw is None:
        spec = _heuristic_grid(ingredients, instructions)
    else:
        spec = _normalize_spec(raw, source)

    try:
        sidecar.write_text(json.dumps({k: v for k, v in spec.items()
                                       if k != "ingredient_rows"}, indent=2),
                           encoding="utf-8")
    except OSError:
        pass

    spec["ingredient_rows"] = ingredient_rows
    return spec


# ---- rendering ------------------------------------------------------------

def _assign_rows_to_groups(ingredient_rows: list[str], ingredients: list[dict],
                           groups: list[dict]) -> list[dict]:
    """Order ingredient display rows by their group; unmatched rows lead.

    Returns a list of groups ``[{"action", "rows": [display, ...]}]`` in
    application order. Ingredients not claimed by any group are surfaced in a
    leading group with an empty action so nothing is ever dropped.
    """
    items = [str(i.get("item", "")).lower() for i in ingredients]
    claimed = set()
    ordered = []
    for g in groups:
        names = [n.lower() for n in g.get("ingredients", [])]
        rows = []
        for idx, item in enumerate(items):
            if idx in claimed:
                continue
            if any(n and (n in item or item in n) for n in names):
                rows.append(ingredient_rows[idx])
                claimed.add(idx)
        ordered.append({"action": g.get("action", ""), "rows": rows})

    leftover = [ingredient_rows[idx] for idx in range(len(items)) if idx not in claimed]
    if leftover:
        ordered.insert(0, {"action": "", "rows": leftover})
    return ordered


def render_grid_html(spec: dict, ingredients: list[dict]) -> str:
    """Render the grid spec as a self-contained HTML table (matrix).

    Pure: no I/O. The staircase is built by anchoring each action cell at the
    top row with an increasing rowspan (cumulative group sizes), so later
    actions visually enclose earlier ones — the Cooking-for-Engineers look.
    """
    ingredient_rows = spec.get("ingredient_rows", [])
    groups = spec.get("groups", [])

    prep_html = ""
    if spec.get("prep"):
        prep_html = "".join(f"<div class='grid-prep'>{escape(p)}</div>" for p in spec["prep"])

    # Fallback: no groups -> ingredients left, numbered steps in one right cell.
    if not groups:
        left = "".join(f"<tr><td class='ing'>{escape(r)}</td></tr>" for r in ingredient_rows) \
            or "<tr><td class='ing'>—</td></tr>"
        steps = spec.get("steps", [])
        steps_html = "<ol class='grid-steps'>" + "".join(
            f"<li>{escape(s)}</li>" for s in steps) + "</ol>" if steps else "<span>—</span>"
        n_rows = max(len(ingredient_rows), 1)
        return (
            f"{prep_html}<table class='recipe-grid'><tbody>"
            f"<tr><td class='ing'>{escape(ingredient_rows[0]) if ingredient_rows else '—'}</td>"
            f"<td class='action' rowspan='{n_rows}'>{steps_html}</td></tr>"
            + "".join(f"<tr><td class='ing'>{escape(r)}</td></tr>"
                      for r in ingredient_rows[1:])
            + "</tbody></table>"
        )

    ordered = _assign_rows_to_groups(ingredient_rows, ingredients, groups)
    # Flatten to a row list; remember each group's row span.
    flat_rows: list[str] = []
    spans: list[tuple[str, int]] = []  # (action, cumulative_rows_through_this_group)
    running = 0
    for g in ordered:
        rows = g["rows"] or []
        flat_rows.extend(rows)
        running += len(rows)
        spans.append((g["action"], running))

    total = max(len(flat_rows), 1)
    if not flat_rows:
        flat_rows = ["—"]

    # Action columns, anchored at the top row, each spanning cumulative rows.
    action_cells = []
    for action, cum in spans:
        if not action:
            continue
        action_cells.append(f"<td class='action' rowspan='{cum}'>{escape(action)}</td>")
    finish = spec.get("finish", "")
    if finish:
        action_cells.append(f"<td class='action finish' rowspan='{total}'>{escape(finish)}</td>")

    # First row carries the ingredient + all the staircase action cells.
    first = (f"<tr><td class='ing'>{escape(flat_rows[0])}</td>"
             + "".join(action_cells) + "</tr>")
    rest = "".join(f"<tr><td class='ing'>{escape(r)}</td></tr>" for r in flat_rows[1:])
    return f"{prep_html}<table class='recipe-grid'><tbody>{first}{rest}</tbody></table>"
