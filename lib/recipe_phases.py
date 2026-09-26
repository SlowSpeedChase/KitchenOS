"""Packet-only phases, conservative shared prep and dependency scheduling.

Model access requires classification_refresh() in a background refresh worker.
The default path is pure; source instructions and the ledger are never mutated.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timedelta
from fractions import Fraction
import hashlib
import json
import math
import os
import re
from typing import Callable
from zoneinfo import ZoneInfo

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
    matches = list(re.finditer(r"(?<![\w/.])(\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:\.\d+)?)"
                              r"\s*(minutes?|mins?|hours?|hrs?)\b", text, re.I))
    # Multiple timings and ranges are ambiguous, not additive durations.
    if len(matches) != 1 or re.search(r"\d\s*(?:-|–|to)\s*\d", text):
        return None
    match = matches[0]
    # Unsupported surrounding arithmetic belongs to the duration phrase too.
    # Do not certify just the numeric tail/head of '1 and 1/2 hours' or
    # '1 hour and a half'. Those forms remain unknown until fully supported.
    before, after = text[:match.start()], text[match.end():]
    number_words = r"(?:a|an|another|one|two|three|four|five|six|seven|eight|nine|ten|half|halves|quarter|third)"
    if re.search(r"(?:\b(?:and|plus|minus|to|or)|[+−\-\d¼½¾]|\b" + number_words + r")\s*$", before, re.I):
        return None
    continuation = after.lstrip(" (,\t\n")
    continuation = re.sub(r"^(?:(?:and|plus|minus|or)\b|[+−-])\s*", "", continuation, flags=re.I)
    if re.match(r"(?:[\d¼½¾\u2150-\u215e]|" + number_words + r"\b)", continuation, re.I):
        return None
    value, unit = match.groups()
    try:
        value = re.sub(r"\s*/\s*", "/", value)
        minutes = float(sum(Fraction(part) for part in value.split())) * (
            60 if unit.lower().startswith(("hour", "hr")) else 1)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return minutes if 0 < minutes <= 1440 else None


def _timing(text, instruction):
    """Source phases cannot grant advance-preparation permission."""
    text = text.replace("’", "'")
    sensitive = bool(instruction.get("time_sensitive")) or bool(re.search(
        r"\b(?:just before|immediately|right before|at serving)\b", text, re.I))
    advance = bool(re.search(r"\b(?:day before|in advance|ahead(?: of time)?|overnight)\b", text, re.I))
    negated = advance and bool(re.search(r"\b(?:not|never|cannot|\w+n't)\b", text, re.I))
    return advance and not (sensitive or negated), sensitive, negated or (advance and sensitive)


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
        ahead, sensitive, timing_review = _timing(text, instruction)
        duration = _duration(text)
        duration_review = duration is None and bool(re.search(r"\b(?:minutes?|mins?|hours?|hrs?)\b", text, re.I))
        rows.append({**deepcopy(instruction), "source_id": source_id, "source_ordinal": ordinal,
            "recipe": recipe, "phase": phase, "can_do_ahead": ahead,
            "time_sensitive": sensitive, "duration_minutes": duration,
            "duration_source": "recipe" if duration is not None else None,
            "depends_on": [], "confidence": 1.0 if native else 0.5 if phase != "instructions" else 0.0,
            "needs_review": not native or timing_review or duration_review,
            "source": "native_phase" if native else "heuristic"})
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
            "recipe_source_id": instruction.get("recipe_source_id", source_id),
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
    if _requires_session(row):
        session = _session_key(row.get("dependent_cooks", []))
        if session is None:
            return None
        attributes.append(session)
    return json.dumps(attributes, sort_keys=True, allow_nan=False)


def _requires_session(row):
    storage = str(row.get("storage") or "").strip().casefold()
    return (row.get("time_sensitive") or not row.get("can_do_ahead") or
            storage in ("", "none", "no storage", "use immediately"))


def _session_key(cooks):
    """Only authoritative, fully timed, identical local sessions are compatible."""
    if not cooks:
        return None
    sessions = set()
    try:
        for cook in cooks:
            zone = cook["timezone"]
            if not isinstance(zone, str) or not zone.strip():
                return None
            timezone = ZoneInfo(zone)
            start = datetime.fromisoformat(cook["start"])
            if start.utcoffset() is None or start.date().isoformat() != cook["date"]:
                return None
            local = start.astimezone(timezone)
            if local.date().isoformat() != cook["date"] or local.utcoffset() != start.utcoffset():
                return None
            sessions.add((cook["date"], start.isoformat(), zone))
    except (KeyError, TypeError, ValueError):
        return None
    return next(iter(sessions)) if len(sessions) == 1 else None


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
                candidate["dependent_cooks"] = deepcopy(recipe.get("dependent_cooks", []))
                candidate["dependent_cook_ids"] = [row["cook_id"] for row in candidate["dependent_cooks"]]
                candidate["session_unresolved"] = bool(_requires_session(candidate) and
                    _session_key(candidate["dependent_cooks"]) is None)
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
                   dependent_cook_ids=sorted({cook_id for r in bucket for cook_id in r["dependent_cook_ids"]}),
                   dependent_cooks=[cook for r in bucket for cook in r["dependent_cooks"]],
                   contributions=[{"source_id": r["source_id"], "recipe": r["recipe"],
                                   "recipe_source_id": r["recipe_source_id"],
                                   "amount": r.get("amount"), "unit": r.get("unit"),
                                   "dependent_cook_ids": r["dependent_cook_ids"]} for r in bucket],
                   depends_on=sorted({d for r in bucket for d in r["depends_on"]}),
                   needs_review=key is None or any(r["needs_review"] for r in bucket), source="shared_prep", done=False)
        result.append(row)
    for row in result:
        row["depends_on"] = sorted({remap.get(d, d) for d in row["depends_on"] if remap.get(d, d) != row["item_id"]})
    return result


def _topological(nodes, dependencies, tie_key):
    """Kahn order: presentation preferences apply only to independent nodes."""
    children = defaultdict(set)
    indegree = {}
    for key in nodes:
        parents = dependencies[key].intersection(nodes)
        indegree[key] = len(parents)
        for parent in parents:
            children[parent].add(key)
    ready = [key for key in nodes if not indegree[key]]
    order = []
    while ready:
        key = min(ready, key=tie_key)
        ready.remove(key)
        order.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return order, set(nodes) - set(order), children


def build_production_schedule(cooks: list[dict], shared_prep: list[dict], storage_tasks: list[dict]) -> list[dict]:
    """Preserve cook timing and order every row through one dependency graph.

    Only explicitly permitted prep moves backward. Conflicting fixed dates are
    retained; the dependent packet task becomes undated and both rows are flagged.
    """
    tasks = {row["item_id"]: deepcopy(row) for row in shared_prep + storage_tasks}
    cook_rows = {row["item_id"]: deepcopy(row) for row in cooks}
    nodes = {**cook_rows, **tasks}
    storage = {row["item_id"] for row in storage_tasks}
    aliases = {source: key for key, row in tasks.items() for source in row.get("source_ids", [])}
    deps = {key: {aliases.get(d, d) for d in row.get("depends_on", [])} for key, row in nodes.items()}
    order, cyclic, children = _topological(nodes, deps, lambda key: key)
    reasons = defaultdict(set)
    dates = {key: date.fromisoformat(row["date"]) if row.get("date") else None
             for key, row in cook_rows.items()}
    for key, row in nodes.items():
        if deps[key] - nodes.keys():
            reasons[key].add("Missing dependency")
        if key in cyclic:
            reasons[key].add("Dependency cycle or dependency blocked by a cycle")
        if key not in tasks:
            continue
        names = row.get("recipes") or [row.get("recipe")]
        cook_ids = row.get("dependent_cook_ids")
        anchors = [dates[c["item_id"]] for c in cooks if dates[c["item_id"]] and
                   (c.get("cook_id") in cook_ids if cook_ids is not None else c.get("recipe") in names)]
        dates[key] = date.fromisoformat(row["date"]) if row.get("date") else min(anchors) if anchors else None
        if row.get("session_unresolved"):
            reasons[key].add("Dependent cooking session is unknown or incompatible")
        if reasons[key] or dates[key] is None:
            dates[key] = None
            reasons[key].add("Unresolved cook date or dependency")

    # Walk back once per permitted preparation link. A fixed/on-day parent is
    # never shifted merely because its child was placed on an earlier date.
    for key in reversed(order):
        if key not in tasks or key in storage or dates[key] is None:
            continue
        row = tasks[key]
        if row.get("can_do_ahead") and not row.get("time_sensitive") and not row.get("date"):
            child_dates = [dates[child] for child in children[key] if dates.get(child) is not None]
            dates[key] = min([dates[key], *child_dates]) - timedelta(days=1)

    # Storage follows its explicit parents. An unmold/bag row needs an actual
    # source freezing step; no freezing instruction or duration is synthesized.
    for key in order:
        if key not in storage or dates[key] is None:
            continue
        row = tasks[key]
        parent_dates = [dates[d] for d in deps[key] if dates.get(d)]
        action = row.get("action") or str(row.get("text", "")).strip().split(" ")[0].lower().rstrip(".,")
        if parent_dates and not row.get("date"):
            dates[key] = max([dates[key], *parent_dates])
        if action in ("bag", "unmold", "unmolding", "bagging"):
            freezes = [d for d in deps[key] if d in tasks and (tasks[d].get("action") == "freeze" or
                       re.match(r"freeze\b", str(tasks[d].get("text", "")), re.I))]
            if freezes and all(dates.get(d) for d in freezes):
                required_date = max(dates[d] for d in freezes) + timedelta(days=1)
                if row.get("date") and dates[key] != required_date:
                    reasons[key].add("Storage date conflicts with the freezing dependency")
                    row["requested_date"] = row["date"]
                    dates[key] = None
                else:
                    dates[key] = max(dates[key], required_date)
            else:
                dates[key] = None
                reasons[key].add("Unmolding or bagging requires a dated freezing step")

    # Discover conflicts before propagating them, so an earlier-visited sibling
    # cannot retain a valid-looking date when its shared dependency conflicts.
    for key in order:
        for parent in deps[key]:
            if dates.get(parent) and dates.get(key) and dates[parent] > dates[key]:
                reason = "Timing conflict: dependency occurs after its dependent task"
                reasons[parent].add(reason)
                reasons[key].add(reason)
                if key in tasks:
                    dates[key] = None
    for key in order:
        if any(dates.get(parent) is None or reasons[parent] for parent in deps[key]):
            reasons[key].add("Dependency date is unresolved or conflicting")
            if key in tasks:
                dates[key] = None

    output = {}
    for key, row in nodes.items():
        if key in cook_rows:
            output[key] = row
            if reasons[key]:
                output[key].update(needs_review=True, review_reason="; ".join(sorted(reasons[key])))
        else:
            output[key] = {**row, "item_id": _id("schedule", key), "task_id": key,
                "date": dates[key].isoformat() if dates[key] else None,
                "source_ids": row.get("source_ids", [key]), "source": "packet",
                "needs_review": bool(row.get("needs_review")) or bool(reasons[key]),
                "review_reason": "; ".join(sorted(reasons[key])) or None}

    def tie_key(key):
        row = output[key]
        return (row.get("date") or "9999-12-31",
                1 if key in cook_rows else 2 if key in storage else 0,
                row.get("start") or "", key)

    final_order, unresolved, _ = _topological(nodes, deps, tie_key)
    return [output[key] for key in final_order + sorted(unresolved, key=tie_key)]
