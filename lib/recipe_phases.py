"""Packet-only phases, conservative shared prep and dependency scheduling.

Model access requires classification_refresh() in a background refresh worker.
The default path is pure; source instructions and the ledger are never mutated.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
import os
import re
from typing import Callable

import requests

from lib import llm_gate
from lib.ingredient_aggregator import (convert_from_base_unit, convert_to_base_unit,
    get_unit_family, parse_amount_to_float, unit_compatibility)
from lib.ingredient_normalizer import normalize_name
from lib.recipe_parser import INSTRUCTION_PHASE_HEADINGS
from prompts.cooking_packet import classification_prompt

_REFRESH = ContextVar("packet_classification_refresh", default=None)
PHASES = frozenset(INSTRUCTION_PHASE_HEADINGS) | {"instructions"}
_PHASE_VERBS = {
    "prep_or_flavor_base": r"^(?:soak|chop|dice|mince|slice|peel|rinse|wash|measure|mix|whisk)\b",
    "cook": r"^(?:pressure[- ]cook|cook|simmer|boil|bake|roast|fry|saute|sauté|steam)\b",
    "finish_and_taste": r"^(?:taste|season|garnish|serve|finish)\b",
    "freeze_and_store": r"^(?:cool|freeze|refrigerate|store|unmold|bag)\b",
    "reheat": r"^(?:reheat|warm)\b",
}
_ANIMAL = re.compile(r"\b(?:chicken|turkey|duck|beef|pork|lamb|veal|fish|salmon|tuna|shrimp|prawn|seafood|egg|eggs|meat|sausage|bacon|shellfish)\b", re.I)


def _id(kind, *parts):
    return kind + ":" + hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:24]


@contextmanager
def classification_refresh(proposer: Callable | None = None):
    """Authorize inference for this explicit worker only; gates still apply.

    An injected proposer takes (payload, *, timeout) and returns decoded JSON.
    Do not enter this context from a page renderer or a GET handler.
    """
    token = _REFRESH.set({"proposer": proposer})
    try:
        yield
    finally:
        _REFRESH.reset(token)


def _model_propose(payload, *, timeout):
    prompt = classification_prompt(payload)
    # Stream and cap the HTTP body before decoding untrusted model output.
    with requests.post(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/generate",
                       json={"model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
                             "prompt": prompt, "stream": False, "format": "json",
                             "options": {"num_predict": 4096}}, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(8192):
            body.extend(chunk)
            if len(body) > 131072:
                raise ValueError("model response exceeds limit")
        return json.loads(json.loads(body)["response"])


def _propose(payload, proposer=None):
    refresh = _REFRESH.get()
    if refresh is None or llm_gate.on_page_render() or not llm_gate.allowed():
        return None
    budget = llm_gate.budget_s(30.0)
    if budget <= 0:
        return None
    try:
        classification_prompt(payload)  # Also bounds injected proposers' input.
        result = (proposer or refresh["proposer"] or _model_propose)(deepcopy(payload), timeout=budget)
        encoded = json.dumps(result, allow_nan=False)
        if len(encoded) > 60000 or not isinstance(result, dict):
            return None
        return result
    except (requests.RequestException, ValueError, TypeError, KeyError, RecursionError):
        return None


def _phase(text):
    text = text.strip().lower()
    if re.search(r"\b(?:not|never|don't)\b|\?", text):
        return "instructions"
    clauses = re.split(r"\b(?:then|and)\b|[.;]", text)
    recognized = {phase for clause in clauses for phase, pattern in _PHASE_VERBS.items()
                  if re.search(pattern, clause.strip())}
    if len(recognized) > 1:
        return "instructions"
    for phase, pattern in _PHASE_VERBS.items():
        if re.search(pattern, text):
            return phase
    return "instructions"


def _duration(text):
    matches = re.findall(r"\b(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", text, re.I)
    # Multiple timings and ranges are ambiguous, not additive durations.
    if len(matches) != 1 or re.search(r"\d\s*(?:-|–|to)\s*\d", text):
        return None
    value, unit = matches[0]
    minutes = float(value) * (60 if unit.lower().startswith(("hour", "hr")) else 1)
    return minutes if 0 < minutes <= 1440 else None


def classify_legacy_steps(recipe: str, instructions: list[dict]) -> dict:
    """Retain every source step; uncertainty is explicit and no advice is added.

    ``instructions`` is the ordered enriched copy and ``instruction_phases``
    groups those same records. Native canonical phases bypass model inference.
    IDs use recipe identity and document ordinal, never instruction wording.
    """
    rows = []
    for ordinal, instruction in enumerate(instructions, 1):
        text = str(instruction.get("text", ""))
        native = instruction.get("phase") in INSTRUCTION_PHASE_HEADINGS
        phase = instruction["phase"] if native else _phase(text)
        source_id = instruction.get("source_id") or _id("instruction", recipe, ordinal)
        sensitive = bool(instruction.get("time_sensitive")) or bool(re.search(
            r"\b(?:just before|immediately|right before|at serving)\b", text, re.I))
        ahead = bool(re.search(r"\b(?:day before|in advance|ahead of time|overnight)\b", text, re.I)) and not sensitive
        rows.append({**deepcopy(instruction), "source_id": source_id, "source_ordinal": ordinal,
            "recipe": recipe, "phase": phase, "can_do_ahead": ahead,
            "time_sensitive": sensitive, "duration_minutes": _duration(text),
            "duration_source": "recipe" if _duration(text) is not None else None,
            "depends_on": [], "confidence": 1.0 if native else 0.5 if phase != "instructions" else 0.0,
            "needs_review": not native, "source": "native_phase" if native else "heuristic"})
    known = {row["source_id"] for row in rows}
    for original, row in zip(instructions, rows):
        deps = original.get("depends_on", [])
        if isinstance(deps, list) and all(isinstance(d, str) and d in known and d != row["source_id"] for d in deps):
            row["depends_on"] = list(deps)
        elif deps:
            row["needs_review"] = True
    legacy = [row for row in rows if row["source"] != "native_phase"]
    result = _propose({"recipe": recipe, "instructions": legacy}) if legacy else None
    proposals = result.get("instructions") if result else None
    if isinstance(proposals, list) and len(proposals) == len(legacy):
        by_id = {r.get("source_id"): r for r in proposals if isinstance(r, dict) and isinstance(r.get("source_id"), str)}
        if len(by_id) == len(legacy) and set(by_id) == {r["source_id"] for r in legacy}:
            for row in legacy:
                proposal = by_id[row["source_id"]]
                confidence = proposal.get("confidence")
                # The model cannot upgrade an unsupported phase or invent safety data.
                if (set(proposal) <= {"source_id", "phase", "confidence"}
                    and proposal.get("phase") == row["phase"]
                    and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                    and math.isfinite(confidence) and 0 <= confidence <= 1):
                    row.update(source="model_validated", confidence=min(confidence, 0.8), needs_review=True)
    groups = {}
    for row in rows:
        groups.setdefault(row["phase"], []).append(row)
    return {"recipe": recipe, "instructions": rows, "instruction_phases": groups,
            "needs_review": any(row["needs_review"] for row in rows)}


def _candidate(recipe, instruction, ordinal):
    prep = instruction.get("prep")
    if not isinstance(prep, dict):
        prep = _source_prep(str(instruction.get("text", "")))
        if prep is None and instruction.get("phase") != "prep_or_flavor_base":
            return None
        prep = prep or {}  # Keep ambiguous prep visible, but never combine it.
    source_id = instruction.get("source_id") or _id("instruction", recipe, ordinal)
    return {**deepcopy(prep), "text": instruction.get("text", ""), "recipe": recipe,
            "source_id": source_id, "source_ordinal": ordinal,
            "phase": instruction.get("phase", "instructions"),
            "can_do_ahead": instruction.get("can_do_ahead", False),
            "time_sensitive": instruction.get("time_sensitive", False),
            "duration_minutes": instruction.get("duration_minutes"),
            "duration_source": instruction.get("duration_source"),
            "depends_on": list(instruction.get("depends_on") or []),
            "needs_review": bool(prep.get("needs_review", instruction.get("needs_review", True)))}


def _source_prep(text):
    """Recognize only explicit single-ingredient bean pressure-cooking steps.

    Unknown prose remains a separate task. In particular a recipe ingredient
    list cannot prove that its entire quantity belongs to this instruction.
    """
    match = re.match(r"pressure[- ]cook\s+(\d+(?:\.\d+)?)\s+(lb|oz|g|kg|cups?)\s+"
                     r"(black[- ]eyed peas|black beans|pinto beans|chickpeas|lentils)\s+for\s+"
                     r"(\d+(?:\.\d+)?)\s+minutes?\b(.*)", text.strip(), re.I)
    if not match:
        return {} if re.match(r"pressure[- ]cook\b", text.strip(), re.I) else None
    amount, unit, ingredient, minutes, tail = match.groups()
    ratio = re.search(r"\b(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)\s+water-to-bean ratio\b", tail, re.I)
    release = re.search(r"\b(natural|quick) release\b", tail, re.I)
    storage = "use immediately" if re.search(r"\buse immediately\b", tail, re.I) else None
    # Only the recognized clauses may trail the bean instruction: an extra
    # ingredient (notably acid) or parameter makes compatibility uncertain.
    residue = re.sub(r"\bwith a \d+(?:\.\d+)?:\d+(?:\.\d+)? water-to-bean ratio\b|"
                     r"\b(?:natural|quick) release\b|\buse immediately\b", "", tail, flags=re.I)
    complete = bool(ratio and release and storage and not residue.strip(" ;,."))
    return {"ingredient": ingredient.lower(), "amount": float(amount), "unit": unit.lower(),
            "method": "pressure cook", "pressure_minutes": float(minutes),
            "pressure_release": release[1].lower() if release else None,
            "liquid_ratio": f"{ratio[1]}:{ratio[2]}" if ratio else None,
            "outcome": "cooked beans", "storage": storage,
            "raw_animal_protein": False, "needs_review": not complete}


def _merge_key(row):
    required = ("ingredient", "unit", "method", "outcome", "storage")
    if row["needs_review"] or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
        return None
    if row.get("raw_animal_protein") is not False or _ANIMAL.search(row["ingredient"]):
        return None
    amount = parse_amount_to_float(row.get("amount"))
    if not amount or not math.isfinite(amount) or amount <= 0:
        return None
    method = row["method"].casefold().strip()
    if "pressure" in method:
        time = row.get("pressure_minutes")
        if not isinstance(time, (int, float)) or isinstance(time, bool) or not math.isfinite(time) or time <= 0:
            return None
        ratio = row.get("liquid_ratio")
        if not isinstance(ratio, str) or not re.fullmatch(r"\d+(?:\.\d+)?:\d+(?:\.\d+)?", ratio):
            return None
        if any(not math.isfinite(float(n)) or float(n) <= 0 for n in ratio.split(":")):
            return None
        if row.get("pressure_release") not in ("natural", "quick"):
            return None
    # Compare all pressure parameters even when another method is named.
    attributes = [normalize_name(row["ingredient"]), method, row["outcome"].casefold().strip(),
                  row["storage"].casefold().strip(), row.get("pressure_minutes"),
                  row.get("pressure_release"), row.get("liquid_ratio"),
                  row["can_do_ahead"], row["time_sensitive"], row["duration_minutes"]]
    return json.dumps(attributes, sort_keys=True, allow_nan=False)


def build_shared_prep(recipes: list[dict], proposer: Callable | None = None) -> list[dict]:
    """Merge only complete source-backed prep descriptions with matching safety.

    ``prep`` metadata belongs to a source instruction, with ingredient, amount,
    unit, method, outcome, storage, raw_animal_protein, needs_review and, for
    pressure cooking, pressure_minutes, pressure_release and liquid_ratio.
    Missing metadata keeps prep separate. Model groups cannot supply metadata.
    """
    candidates = []
    for recipe in sorted(recipes, key=lambda r: r["recipe"]):
        rows = recipe.get("classified_instructions", recipe.get("instructions", []))
        for ordinal, instruction in enumerate(rows, 1):
            candidate = _candidate(recipe["recipe"], instruction, ordinal)
            if candidate:
                scale = recipe.get("scale", 1)
                amount = parse_amount_to_float(candidate.get("amount"))
                if isinstance(scale, (int, float)) and not isinstance(scale, bool) and math.isfinite(scale) and scale > 0:
                    if amount is not None:
                        candidate["amount"] = amount * scale
                else:
                    candidate["needs_review"] = True
                candidates.append(candidate)
    source_ids = {row["source_id"] for row in candidates}
    suggestion = _propose({"kind": "shared_prep", "source_ids": sorted(source_ids),
                          "candidates": candidates}, proposer) if candidates else None
    groups = suggestion.get("groups") if suggestion else None
    proposed_group = None
    if isinstance(groups, list) and len(groups) <= len(candidates):
        seen = set()
        valid = True
        for group in groups:
            if (not isinstance(group, list) or len(group) < 2 or
                any(not isinstance(source, str) or source not in source_ids for source in group) or
                len(set(group)) != len(group) or seen.intersection(group)):
                valid = False
                break
            seen.update(group)
        if valid:
            proposed_group = {source: index for index, group in enumerate(groups) for source in group}
    buckets = []
    for candidate in candidates:
        key = _merge_key(candidate)
        bucket = next((b for k, b in buckets if key is not None and k == key and
                       (proposed_group is None or
                        (candidate["source_id"] in proposed_group and
                         proposed_group[candidate["source_id"]] == proposed_group.get(b[0]["source_id"]))) and
                       all(candidate["recipe"] != other["recipe"] and
                           candidate["source_id"] not in other["depends_on"] and
                           other["source_id"] not in candidate["depends_on"] for other in b) and
                       unit_compatibility(candidate["unit"], b[0]["unit"]) in ("convert", "one_to_one")), None)
        if bucket is None:
            buckets.append((key, [candidate]))
        else:
            bucket.append(candidate)
    result, remap = [], {}
    for key, bucket in buckets:
        first = bucket[0]
        source_ids = sorted(row["source_id"] for row in bucket)
        item_id = _id("shared", *source_ids)
        remap.update({source_id: item_id for source_id in source_ids})
        row = {k: deepcopy(v) for k, v in first.items() if k not in ("recipe", "source_id", "source_ordinal", "prep")}
        if key is not None:
            unit = first["unit"]
            amount = 0.0
            for candidate in bucket:
                value = parse_amount_to_float(candidate["amount"])
                if unit_compatibility(candidate["unit"], unit) == "convert":
                    family = get_unit_family(unit)
                    value = convert_from_base_unit(convert_to_base_unit(value, candidate["unit"], family), unit, family)
                amount += value
            row["amount"] = amount
        row.update(item_id=item_id, source_ids=source_ids, recipes=sorted({r["recipe"] for r in bucket}),
                   contributions=[{"source_id": r["source_id"], "recipe": r["recipe"],
                                   "amount": r.get("amount"), "unit": r.get("unit")} for r in bucket],
                   depends_on=sorted({d for r in bucket for d in r["depends_on"]}),
                   needs_review=key is None or any(r["needs_review"] for r in bucket), source="shared_prep", done=False)
        result.append(row)
    for row in result:
        row["depends_on"] = sorted({remap.get(d, d) for d in row["depends_on"] if remap.get(d, d) != row["item_id"]})
    return result


def build_production_schedule(cooks: list[dict], shared_prep: list[dict], storage_tasks: list[dict]) -> list[dict]:
    """Topologically schedule packet tasks without moving authoritative cooks.

    Input cooks are authoritative schedule rows. Prep is anchored to the earliest
    matching recipe cook. Cycles/missing links stay visible with an unknown date.
    """
    tasks = {row["item_id"]: deepcopy(row) for row in shared_prep + storage_tasks}
    cook_dates = {row["item_id"]: date.fromisoformat(row["date"]) if row.get("date") else None for row in cooks}
    storage = {row["item_id"] for row in storage_tasks}
    aliases = {source: key for key, row in tasks.items() for source in row.get("source_ids", [])}
    deps = {key: {aliases.get(d, d) for d in row.get("depends_on", [])} for key, row in tasks.items()}
    children = defaultdict(set)
    for key, parents in deps.items():
        for parent in parents:
            children[parent].add(key)
    indegree = {key: len(parents - cook_dates.keys()) for key, parents in deps.items()}
    ready = sorted(key for key in tasks if not indegree[key])
    order = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for child in sorted(children[key]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    unresolved = set(tasks) - set(order)
    dates = dict(cook_dates)
    for key, row in tasks.items():
        names = row.get("recipes") or [row.get("recipe")]
        anchors = [date.fromisoformat(c["date"]) for c in cooks if c.get("recipe") in names and c.get("date")]
        dates[key] = min(anchors) if anchors and key not in unresolved else None
    # Work backwards so each do-ahead dependency precedes its first dependent.
    for key in reversed(order):
        row = tasks[key]
        if key in storage or dates[key] is None:
            continue
        dependent_dates = [dates[c] for c in children[key] if dates.get(c) is not None]
        if dependent_dates and not row.get("time_sensitive"):
            dates[key] = min([dates[key], *dependent_dates])
        if row.get("can_do_ahead") and not row.get("time_sensitive"):
            dates[key] -= timedelta(days=1)
    for key in order:
        if key not in storage or dates[key] is None:
            continue
        row = tasks[key]
        parent_dates = [dates[d] for d in deps[key] if dates.get(d)]
        action = row.get("action") or str(row.get("text", "")).strip().split(" ")[0].lower().rstrip(".,")
        if parent_dates:
            dates[key] = max([dates[key], *parent_dates])
        if action in ("bag", "unmold", "unmolding", "bagging"):
            freezes = [d for d in deps[key] if d in tasks and (tasks[d].get("action") == "freeze" or
                       re.match(r"freeze\b", str(tasks[d].get("text", "")), re.I))]
            if freezes and all(dates.get(d) for d in freezes):
                dates[key] = max(dates[d] for d in freezes) + timedelta(days=1)
            else:
                dates[key] = None
                row["needs_review"] = True
    output = deepcopy(cooks)
    for key in order + sorted(unresolved):
        row = tasks[key]
        violated = any(dates.get(d) is None or (dates[key] and dates[d] > dates[key]) for d in deps[key])
        if violated:
            dates[key] = None
        output.append({**row, "item_id": _id("schedule", key), "task_id": key,
            "date": dates[key].isoformat() if dates[key] else None,
            "source_ids": row.get("source_ids", [key]), "source": "packet",
            "needs_review": bool(row.get("needs_review")) or dates[key] is None,
            "review_reason": "Unresolved dependency or cook date" if dates[key] is None else None})
    rank = {key: n for n, key in enumerate(order + sorted(unresolved))}
    return sorted(output, key=lambda r: (r.get("date") or "9999-12-31",
        1 if r.get("source") == "cook_schedule" else 2 if r.get("task_id") in storage else 0,
        rank.get(r.get("task_id"), -1), r.get("start") or "", r["item_id"]))
