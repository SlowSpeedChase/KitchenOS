import json
from pathlib import Path

import pytest

from lib.command import planner
from lib.command.decider import NoDecider, ScriptedDecider
from lib.command.planner import Failure, Plan, Question
from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY

CASES = json.loads((Path(__file__).parent / "gold" / "commands.json").read_text())


def _plan(say, context, decider=None, answers=None):
    return planner.plan(say, context, Kitchen.load(TODAY, [context["week"]] if context.get("week") else []),
                        decider or NoDecider(), answers)


def _status(outcome):
    if isinstance(outcome, Failure):
        return "failed"
    if isinstance(outcome, Question):
        return "ask"
    return "confirm" if outcome.confirm else "done"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_gold_command_plans_as_expected(gold_kitchen, case):
    outcome = _plan(case["say"], case["context"])
    expect = case["expect"]
    assert _status(outcome) == expect["status"]
    if isinstance(outcome, Plan):
        got = [a.to_json() for a in outcome.actions]
        assert len(got) == len(expect["actions"])
        for want, have in zip(expect["actions"], got):
            assert want.items() <= have.items(), (want, have)
    if isinstance(outcome, Question):
        assert [o.id for o in outcome.options] == expect["options"]


def test_no_model_is_called_when_rules_and_feasibility_decide(gold_kitchen):
    d = ScriptedDecider({"x": "plan_cook"})
    _plan("put this on friday dinner", {"screen": "recipe", "recipe": "Chicken Caldo A"}, d)
    _plan("we're out of eggs", {"screen": "home"}, d)
    assert d.calls == []


def test_decider_breaks_a_plan_or_move_tie(gold_kitchen):
    d = ScriptedDecider({"x": "move_cook"})
    outcome = _plan("put this on friday", {"screen": "recipe", "recipe": "Miso Salmon Bowls"}, d)
    assert [a.type for a in outcome.actions] == ["move_cook"]
    assert d.calls[0][1] == ["plan_cook", "move_cook"]


def test_an_answer_resolves_the_question_it_was_asked(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Miso Salmon Bowls"}
    first = _plan("put this on friday", context)
    assert first.key == "intent:0"
    second = _plan("put this on friday", context, answers={"intent:0": "plan_cook"})
    assert [a.type for a in second.actions] == ["plan_cook"]


def test_recipe_answer_must_be_one_of_the_options(gold_kitchen):
    context = {"screen": "home"}
    ok = _plan("put the caldo on monday", context, answers={"recipe:0": "Chicken Caldo B"})
    assert ok.actions[0].args["recipe"] == "Chicken Caldo B"
    bad = _plan("put the caldo on monday", context, answers={"recipe:0": "Butter Biscuits"})
    assert isinstance(bad, Question) and bad.key == "recipe:0"


def test_next_friday_asks_which_friday(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    q = _plan("put this on next friday", context)
    assert q.key == "date:0" and [o.id for o in q.options] == ["2026-11-13", "2026-11-20"]
    done = _plan("put this on next friday", context, answers={"date:0": "2026-11-20"})
    assert done.actions[0].args["date"] == "2026-11-20"


def test_leftovers_without_a_meal_asks_which_meal(gold_kitchen):
    context = {"screen": "recipe", "recipe": "Chicken Caldo A"}
    q = _plan("put this on friday and the leftovers on saturday", context)
    assert q.key == "meal:1" and [o.id for o in q.options] == ["breakfast", "lunch", "dinner"]


def test_leftovers_refer_to_the_cook_planned_in_the_same_sentence(gold_kitchen):
    outcome = _plan(CASES[0]["say"], CASES[0]["context"])
    assert outcome.actions[1].args["cook"] == {"new": 0}
    assert outcome.actions[2].args["cook"] == {"new": 0}


def test_rule_that_cannot_run_explains_why(gold_kitchen):
    outcome = _plan("thaw the biscuits for friday", {"screen": "home"})
    assert isinstance(outcome, Failure) and "freezer" in outcome.reason


def test_out_of_something_we_do_not_have(gold_kitchen):
    outcome = _plan("we're out of saffron", {"screen": "home"})
    assert isinstance(outcome, Failure) and "saffron" in outcome.reason


def test_describe_uses_words_not_ids(gold_kitchen):
    k = Kitchen.load(TODAY, ["2026-W47"])
    outcome = planner.plan("take the chili off tuesday",
                           {"screen": "planner", "week": "2026-W47"}, k, NoDecider())
    assert outcome.confirm == ["Remove Bean Chili from Tue Nov 17"]


def test_weeks_touched(gold_kitchen):
    outcome = _plan(CASES[0]["say"], CASES[0]["context"])
    assert planner.weeks_touched(outcome) == {"2026-W47"}
