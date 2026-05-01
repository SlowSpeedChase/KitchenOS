"""Cross-recipe task extraction.

Given a week's meal plan, classify every instruction step as prep / active /
passive, identify do-ahead and parallelizable steps, and cache the result in
a sidecar `<week>.tasks.json` next to the meal plan markdown.

Model: Claude Haiku via the Anthropic SDK (already wired in the project).
Falls back to Ollama mistral:7b when ANTHROPIC_API_KEY is missing, mirroring
lib/meal_suggester.py.

The sidecar is regenerated when the meal plan's mtime is newer than the
sidecar's `generated_at`. `done` flags are preserved across regeneration
because task IDs are deterministic (sha1 of recipe + step number).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

try:
    import anthropic
    _api_key = os.getenv("ANTHROPIC_API_KEY")
    _anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except ImportError:
    _anthropic_client = None

from lib import paths
from lib.meal_plan_parser import flatten_to_recipes, parse_meal_plan
from lib.recipe_parser import parse_recipe_body, parse_recipe_file
from lib.shopping_list_generator import find_recipe_file


CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 4000
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"


@dataclass
class ScheduledStep:
    recipe: str
    day: str
    slot: str
    step: int
    text: str
    time_hint: Optional[str] = None


def _stable_task_id(recipe: str, day: str, slot: str, step: int) -> str:
    digest = hashlib.sha1(f"{recipe}|{day}|{slot}|{step}".encode("utf-8")).hexdigest()
    return digest[:12]


def _parse_week_to_year(week: str) -> tuple[int, int]:
    match = re.match(r"^(\d{4})-W(\d{2})$", week)
    if not match:
        raise ValueError(f"Invalid week format: {week}. Expected YYYY-WNN")
    return int(match.group(1)), int(match.group(2))


def _meal_plan_path(week: str) -> Path:
    return paths.meal_plans_dir() / f"{week}.md"


def _sidecar_path(week: str) -> Path:
    return paths.meal_plans_dir() / f"{week}.tasks.json"


def _collect_scheduled_steps(week: str) -> list[ScheduledStep]:
    """Walk the meal plan, expand meals, and collect every instruction step."""
    plan_path = _meal_plan_path(week)
    if not plan_path.exists():
        return []
    year, week_num = _parse_week_to_year(week)
    days = parse_meal_plan(plan_path.read_text(encoding="utf-8"), year, week_num)

    steps: list[ScheduledStep] = []
    seen: set[tuple[str, str, str]] = set()  # (recipe, day, slot)

    for day in days:
        day_name = day["day"]
        for slot in ("breakfast", "lunch", "snack", "dinner"):
            entry = day.get(slot)
            if entry is None:
                continue
            recipes = flatten_to_recipes(entry)
            for recipe_entry in recipes:
                key = (recipe_entry.name, day_name, slot)
                if key in seen:
                    continue
                seen.add(key)
                instructions = _load_instructions(recipe_entry.name)
                for inst in instructions:
                    steps.append(ScheduledStep(
                        recipe=recipe_entry.name,
                        day=day_name,
                        slot=slot,
                        step=inst.get("step", 0),
                        text=inst.get("text", ""),
                        time_hint=inst.get("time"),
                    ))
    return steps


def _load_instructions(recipe_name: str) -> list[dict]:
    recipe_file = find_recipe_file(recipe_name)
    if not recipe_file:
        return []
    try:
        content = recipe_file.read_text(encoding="utf-8")
        parsed = parse_recipe_file(content)
        body = parse_recipe_body(parsed["body"])
        return body.get("instructions", [])
    except Exception:
        return []


def _build_recipes_block(steps: list[ScheduledStep]) -> str:
    """Group steps by (recipe, day, slot) for the prompt."""
    grouped: dict[tuple[str, str, str], list[ScheduledStep]] = {}
    for step in steps:
        grouped.setdefault((step.recipe, step.day, step.slot), []).append(step)

    blocks = []
    for (recipe, day, slot), group in grouped.items():
        block = [f"### {recipe} — {day} {slot}"]
        for s in sorted(group, key=lambda x: x.step):
            time_part = f" (recipe says: {s.time_hint})" if s.time_hint else ""
            block.append(f"  {s.step}. {s.text}{time_part}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _classify_with_claude(prompt: str) -> Optional[list[dict]]:
    if _anthropic_client is None:
        return None
    try:
        message = _anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        return _extract_json_array(raw)
    except Exception:
        return None


def _classify_with_ollama(prompt: str) -> Optional[list[dict]]:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        if response.status_code != 200:
            return None
        raw = response.json().get("response", "")
        return _extract_json_array(raw)
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None


def _extract_json_array(raw: str) -> Optional[list[dict]]:
    if not raw:
        return None
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        return None
    return None


def _heuristic_classify(steps: list[ScheduledStep]) -> list[dict]:
    """Last-resort classifier when neither Claude nor Ollama is available.

    Provides a usable but generic classification so the UI still works offline.
    """
    PREP_KEYWORDS = ("chop", "dice", "mince", "slice", "marinate", "season", "rinse", "soak")
    PASSIVE_KEYWORDS = ("simmer", "bake", "rest", "cool", "marinat", "rise", "chill")

    out = []
    for step in steps:
        text_l = step.text.lower()
        if any(kw in text_l for kw in PREP_KEYWORDS):
            ttype, can_ahead = "prep", True
        elif any(kw in text_l for kw in PASSIVE_KEYWORDS):
            ttype, can_ahead = "passive", False
        else:
            ttype, can_ahead = "active", False
        out.append({
            "recipe": step.recipe,
            "day": step.day,
            "slot": step.slot,
            "step": step.step,
            "text": step.text,
            "type": ttype,
            "time_minutes": _parse_time_hint(step.time_hint) or 5,
            "can_do_ahead": can_ahead,
            "depends_on": [],
        })
    return out


def _parse_time_hint(hint: Optional[str]) -> Optional[int]:
    if not hint:
        return None
    match = re.search(r"(\d+)", hint)
    if match:
        return int(match.group(1))
    return None


def _normalize_classified(raw: list[dict], steps: list[ScheduledStep]) -> list[dict]:
    """Reconcile model output back to scheduled steps, attach stable IDs."""
    by_key = {(s.recipe, s.day, s.slot, s.step): s for s in steps}

    out = []
    for entry in raw:
        recipe = str(entry.get("recipe") or "").strip()
        day = str(entry.get("day") or "").strip()
        slot = str(entry.get("slot") or "").strip().lower()
        try:
            step_num = int(entry.get("step"))
        except (TypeError, ValueError):
            continue
        key = (recipe, day, slot, step_num)
        if key not in by_key:
            continue
        scheduled = by_key[key]
        ttype = entry.get("type", "active")
        if ttype not in ("prep", "active", "passive"):
            ttype = "active"
        try:
            time_minutes = int(entry.get("time_minutes", 5))
        except (TypeError, ValueError):
            time_minutes = 5
        depends = entry.get("depends_on") or []
        if not isinstance(depends, list):
            depends = []
        depends_ids = [
            _stable_task_id(recipe, day, slot, int(d))
            for d in depends
            if isinstance(d, int) or (isinstance(d, str) and d.isdigit())
        ]
        out.append({
            "id": _stable_task_id(recipe, day, slot, step_num),
            "recipe": recipe,
            "day": day,
            "slot": slot,
            "step": step_num,
            "text": entry.get("text") or scheduled.text,
            "type": ttype,
            "time_minutes": time_minutes,
            "can_do_ahead": bool(entry.get("can_do_ahead", False)),
            "depends_on": depends_ids,
            "done": False,
        })
    return out


def load_cached_tasks(week: str) -> Optional[dict]:
    sidecar = _sidecar_path(week)
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_cache_fresh(week: str, cached: dict) -> bool:
    plan = _meal_plan_path(week)
    if not plan.exists():
        return False
    sidecar = _sidecar_path(week)
    if not sidecar.exists():
        return False
    return sidecar.stat().st_mtime >= plan.stat().st_mtime


def extract_tasks(week: str, force: bool = False) -> dict:
    """Return the tasks payload for `week`, regenerating when stale.

    When the meal plan markdown has been touched since the sidecar was
    written (or when `force=True`), this re-classifies and persists. Done
    flags from the prior run are preserved by stable task ID.
    """
    cached = load_cached_tasks(week)
    if cached is not None and not force and _is_cache_fresh(week, cached):
        return cached

    steps = _collect_scheduled_steps(week)
    if not steps:
        payload = {"week": week, "generated_at": _now_iso(), "tasks": []}
        _save_sidecar(week, payload)
        return payload

    prompt = _build_prompt(steps)

    classified = _classify_with_claude(prompt)
    if classified is None:
        classified = _classify_with_ollama(prompt)
    if classified is None:
        classified = _heuristic_classify(steps)

    tasks = _normalize_classified(classified, steps)

    # Carry forward done flags from prior cache by stable id.
    if cached is not None:
        prior_done = {t["id"]: t.get("done", False) for t in cached.get("tasks", [])}
        for task in tasks:
            if prior_done.get(task["id"]):
                task["done"] = True

    payload = {"week": week, "generated_at": _now_iso(), "tasks": tasks}
    _save_sidecar(week, payload)
    return payload


def mark_task_done(week: str, task_id: str, done: bool = True) -> dict:
    """Flip the `done` flag of a single task in the cached sidecar."""
    cached = load_cached_tasks(week) or extract_tasks(week)
    found = False
    for task in cached.get("tasks", []):
        if task.get("id") == task_id:
            task["done"] = bool(done)
            found = True
            break
    if not found:
        return {"success": False, "error": f"task {task_id} not found"}
    _save_sidecar(week, cached)
    return {"success": True, "task_id": task_id, "done": bool(done)}


def _build_prompt(steps: list[ScheduledStep]) -> str:
    from prompts.task_classification import CLASSIFY_PROMPT
    return CLASSIFY_PROMPT.format(recipes_block=_build_recipes_block(steps))


def _save_sidecar(week: str, payload: dict) -> None:
    sidecar = _sidecar_path(week)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(sidecar)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
