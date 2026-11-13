import pytest

from lib.command import intents
from lib.command.intents import Facts
from lib.command.resolve import Match
from lib.command.slots import extract, item_text
from tests.gold.kitchen import TODAY


@pytest.mark.parametrize("phrase,expected", [
    ("open saturday", "open_page"),
    ("show me the black bean chili", "open_page"),
    ("freeze the rest", "freeze_rest"),
    ("to distribute the leftovers for lunch the next day", "place_leftovers"),
    ("pull a caldo out of the freezer for friday dinner", "thaw"),
    ("we're out of eggs", "inventory_remove"),
    ("I cooked this tonight", "mark_cooked"),
    ("take the chili off tuesday", "remove_cook"),
    ("move the bread to the freezer", "inventory_move"),
    ("put the bread in the freezer", "inventory_move"),
    ("move the salmon from wednesday to saturday", "move_cook"),
    ("put this on friday dinner", None),
    ("add two cans of chickpeas", None),
])
def test_rules(phrase, expected):
    assert intents.rule_for(phrase) == expected


def test_shopping_phrases_are_flagged_unsupported():
    assert intents.UNSUPPORTED.search("add olive oil to the shopping list")
    assert intents.UNSUPPORTED.search("send it to reminders")
    assert not intents.UNSUPPORTED.search("add olive oil")


def _facts(phrase, any_=Match(), planned=Match(), frozen=Match(), prior=False):
    return Facts(phrase=phrase, slots=extract(phrase, today=TODAY), any=any_,
                 planned=planned, frozen=frozen, item=item_text(phrase),
                 has_prior_cook=prior)


def test_plan_needs_a_recipe_and_a_day():
    caldo = Match("Chicken Caldo A", [], "pointer")
    assert intents.feasible("plan_cook", _facts("put this on friday", any_=caldo))
    assert not intents.feasible("plan_cook", _facts("put this on the plan", any_=caldo))
    assert not intents.feasible("plan_cook", _facts("put that on friday"))


def test_move_needs_a_planned_cook():
    salmon = Match("Miso Salmon Bowls", [], "pointer")
    assert intents.feasible("move_cook", _facts("put this on friday", planned=salmon))
    assert not intents.feasible("move_cook", _facts("put this on friday"))


def test_open_candidates_tie_only_when_both_could_run():
    salmon = Match("Miso Salmon Bowls", [], "pointer")
    tie = _facts("put this on friday", any_=salmon, planned=salmon)
    assert intents.candidates(tie, "recipe") == ["plan_cook", "move_cook"]
    caldo = Match("Chicken Caldo A", [], "pointer")
    assert intents.candidates(_facts("put this on friday", any_=caldo), "recipe") == ["plan_cook"]


def test_only_the_user_breaks_a_plan_or_move_tie():
    assert intents.user_decides(["plan_cook", "move_cook"])
    assert not intents.user_decides(["plan_cook"])
    assert not intents.user_decides(["plan_cook", "inventory_add"])


def test_inventory_add_needs_an_add_verb_and_no_day():
    assert intents.candidates(_facts("add two cans of chickpeas"), "home") == ["inventory_add"]
    assert intents.candidates(_facts("put that thing on whenever"), "home") == []


def test_a_fuzzy_recipe_hit_does_not_block_inventory_add():
    fuzzy = Match("Black Bean Chili", [], "fuzzy")
    assert intents.candidates(_facts("add two cans of black beans", any_=fuzzy), "home") == [
        "inventory_add"]


def test_a_named_recipe_blocks_inventory_add():
    exact = Match("Butter Biscuits", [], "exact")
    assert intents.candidates(_facts("add butter biscuits", any_=exact), "home") == []


def test_inventory_screen_hides_plan_actions_unless_a_recipe_is_named():
    fuzzy = Match("Miso Salmon Bowls", [], "fuzzy")
    f = _facts("put salmon on friday", any_=fuzzy)
    assert intents.candidates(f, "home") == ["plan_cook"]
    assert intents.candidates(f, "inventory") == []


def test_why_not_is_a_sentence_a_person_can_act_on():
    assert "day" in intents.why_not("plan_cook", _facts("put this on the plan"))
    assert "freezer" in intents.why_not("thaw", _facts("thaw the caldo for friday"))
