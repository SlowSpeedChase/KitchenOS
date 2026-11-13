import json
from pathlib import Path

from lib.command.decider import NoDecider, ScriptedDecider
from lib.command.resolve import Kitchen
from scripts.score_command_models import score
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


def test_no_model_scores_the_gold_set_with_zero_wrong_actions(gold_kitchen):
    result = score(CASES, NoDecider(), lambda extra: Kitchen.load(TODAY, extra))
    assert result["total"] == len(CASES)
    assert result["wrong"] == 0
    assert result["passed"] == len(CASES)


def test_a_wrong_choice_is_counted_as_wrong_not_as_asked(gold_kitchen):
    tie = [c for c in CASES if c["id"] == "plan-or-move"]
    result = score(tie, ScriptedDecider({"x": "move_cook"}), lambda extra: Kitchen.load(TODAY, extra))
    assert (result["passed"], result["asked"], result["wrong"]) == (0, 0, 1)
