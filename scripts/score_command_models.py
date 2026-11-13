#!/usr/bin/env python
"""Score local models on the gold command set. Run before changing model or prompt.

    .venv/bin/python scripts/score_command_models.py                 # default model
    .venv/bin/python scripts/score_command_models.py qwen2.5:3b granite4.1:8b

The gate is the WRONG column: it must be 0. A model that ends a command in a
question is safe; one that runs a different action than the gold answer is not.
Run it with nothing else using Ollama, or the timings mean nothing.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _status(outcome):
    from lib.command.planner import Failure, Question
    if isinstance(outcome, Failure):
        return "failed"
    if isinstance(outcome, Question):
        return "ask"
    return "confirm" if outcome.confirm else "done"


def _matches(case, outcome) -> bool:
    from lib.command.planner import Plan, Question
    expect = case["expect"]
    if _status(outcome) != expect["status"]:
        return False
    if isinstance(outcome, Question):
        return [o.id for o in outcome.options] == expect["options"]
    if isinstance(outcome, Plan):
        got = [a.to_json() for a in outcome.actions]
        return len(got) == len(expect["actions"]) and all(
            want.items() <= have.items() for want, have in zip(expect["actions"], got))
    return True


def score(cases, decider, load_kitchen) -> dict:
    from lib.command import planner
    from lib.command.planner import Plan

    out = {"passed": 0, "asked": 0, "wrong": 0, "total": len(cases), "seconds": [], "failures": []}
    for case in cases:
        context = case["context"]
        kitchen = load_kitchen([context["week"]] if context.get("week") else [])
        started = time.time()
        outcome = planner.plan(case["say"], context, kitchen, decider)
        out["seconds"].append(time.time() - started)
        if _matches(case, outcome):
            out["passed"] += 1
        elif isinstance(outcome, Plan):
            out["wrong"] += 1
            out["failures"].append((case["id"], _status(outcome)))
        else:
            out["asked"] += 1
            out["failures"].append((case["id"], _status(outcome)))
    return out


def main(models) -> int:
    from lib.command.decider import DEFAULT_MODEL, OllamaDecider
    from lib.command.resolve import Kitchen
    from tests.gold import kitchen as gold

    cases = json.loads((ROOT / "tests" / "gold" / "commands.json").read_text())
    worst = 0
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["KITCHENOS_VAULT"] = str(Path(tmp) / "vault")
        os.environ["KITCHENOS_DB"] = str(Path(tmp) / "gold.db")
        os.environ["KITCHENOS_STORAGE_TABLE"] = str(Path(tmp) / "storage.json")
        gold.build()
        print(f"{'model':<20} {'pass':>5} {'ask':>4} {'WRONG':>6} {'median s':>9} {'max s':>7}")
        for model in models or [DEFAULT_MODEL]:
            result = score(cases, OllamaDecider(model), lambda extra: Kitchen.load(gold.TODAY, extra))
            times = sorted(result["seconds"])
            print(f"{model:<20} {result['passed']:>5} {result['asked']:>4} {result['wrong']:>6} "
                  f"{times[len(times) // 2]:>9.1f} {times[-1]:>7.1f}")
            for case_id, status in result["failures"]:
                print(f"    {case_id}: got {status}")
            worst = max(worst, result["wrong"])
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
