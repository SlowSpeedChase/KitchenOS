from datetime import date

from lib.command.resolve import Kitchen
from tests.gold.kitchen import TODAY


def _kitchen():
    return Kitchen.load(TODAY)


def test_load_sees_recipes_plan_freezer_inventory(gold_kitchen):
    k = _kitchen()
    assert "Chicken Caldo A" in k.recipes and len(k.recipes) == 6
    assert k.planned_names() == ["Black Bean Chili", "Miso Salmon Bowls"]
    assert k.frozen_names() == ["Black Bean Chili", "Chicken Caldo A"]
    assert len(k.inventory) == 5


def test_exact_name_wins(gold_kitchen):
    m = _kitchen().find_recipe("show me the black bean chili")
    assert (m.name, m.how) == ("Black Bean Chili", "exact")


def test_pointer_uses_the_screen_recipe_before_fuzzy(gold_kitchen):
    m = _kitchen().find_recipe("put this on the bean plan", screen_recipe="Chicken Caldo A")
    assert (m.name, m.how) == ("Chicken Caldo A", "pointer")


def test_fuzzy_single_hit(gold_kitchen):
    m = _kitchen().find_recipe("move the salmon to saturday")
    assert (m.name, m.how) == ("Miso Salmon Bowls", "fuzzy")


def test_lookalikes_are_options_not_a_guess(gold_kitchen):
    m = _kitchen().find_recipe("put the caldo on monday")
    assert m.name is None and m.options == ["Chicken Caldo A", "Chicken Caldo B"]


def test_pool_narrows_lookalikes(gold_kitchen):
    k = _kitchen()
    assert k.find_recipe("pull a caldo out", pool=k.frozen_names()).name == "Chicken Caldo A"


def test_pointer_ignored_when_screen_recipe_not_in_pool(gold_kitchen):
    k = _kitchen()
    m = k.find_recipe("move this", screen_recipe="Chicken Caldo A", pool=k.planned_names())
    assert m.name is None and m.options == []


def test_planned_filters_by_date(gold_kitchen):
    k = _kitchen()
    assert len(k.planned("Black Bean Chili")) == 1
    assert k.planned("Black Bean Chili", on=date(2026, 11, 18)) == []


def test_inventory_rows_match_whole_words(gold_kitchen):
    k = _kitchen()
    assert [r["name"] for r in k.inventory_rows("eggs")] == ["eggs"]
    assert len(k.inventory_rows("milk")) == 2
    assert k.inventory_rows("oil")[0]["name"] == "olive oil"
    assert k.inventory_rows("saffron") == []


def test_display_uses_short_title(gold_kitchen):
    k = _kitchen()
    assert k.display("Black Bean Chili") == "Bean Chili"
    assert k.display("Chicken Caldo A") == "Chicken Caldo A"
