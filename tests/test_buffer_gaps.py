"""Can a buffer food actually win the four-second race tonight?

The Meal System note's whole premise is that when the urge hits, something you
genuinely like has to be reachable with no prep. That makes the useful question
a **stock** question, not a recipe question — most of the buffer menu ("apple +
nut butter", "handful of pistachios") is an assembly of things you either have
or don't, and no amount of recipe acquisition fixes an empty fruit bowl.

So these check the menu against real inventory, lane by lane. A lane with
nothing available is the actionable finding; the note says to keep at least one
per row stocked.
"""
import pytest

from lib import buffer_gaps
from lib.inventory import InventoryItem
from lib.profile import Profile


def _profile(**lanes):
    return Profile(prose="", buffer_menu=dict(lanes))


def _stock(*names):
    return [InventoryItem(name=n, quantity=1, unit="ct") for n in names]


def test_item_is_ready_when_its_ingredients_are_stocked():
    p = _profile(Sweet=["Apple + nut butter [heart]"])
    out = buffer_gaps.lane_readiness(p, _stock("apples", "peanut butter"))
    assert out["Sweet"]["ready"] == ["Apple + nut butter"]


def test_item_is_missing_when_an_ingredient_is_absent():
    p = _profile(Sweet=["Apple + nut butter"])
    out = buffer_gaps.lane_readiness(p, _stock("apples"))
    assert out["Sweet"]["ready"] == []
    assert "nut butter" in out["Sweet"]["missing"][0]["needs"]


def test_slash_alternatives_count_as_either():
    """'Apple/pear' means either one will do — not both."""
    p = _profile(Sweet=["Apple/pear + nut butter"])
    out = buffer_gaps.lane_readiness(p, _stock("pears", "almond butter"))
    assert out["Sweet"]["ready"], "a pear should satisfy 'Apple/pear'"


def test_parenthetical_ingredients_are_used_when_present():
    """'Chocolate chia pudding (chia + soy milk + cocoa)' — the parens are the recipe."""
    p = _profile(Sweet=["Chocolate chia pudding (chia + soy milk + cocoa)"])
    out = buffer_gaps.lane_readiness(p, _stock("chia seeds", "soy milk", "cocoa powder"))
    assert out["Sweet"]["ready"]


def test_health_tags_are_not_treated_as_ingredients():
    p = _profile(Sweet=["Berries + dark chocolate [heart][steady]"])
    out = buffer_gaps.lane_readiness(p, _stock("blueberries", "dark chocolate"))
    assert out["Sweet"]["ready"], "the [heart] tag must not count as a missing item"


def test_pantry_staples_are_assumed_present():
    """Salt and olive oil are always in the house; demanding them is noise."""
    p = _profile(Salty=["Popcorn + olive oil + salt"])
    out = buffer_gaps.lane_readiness(p, _stock("popcorn kernels"),
                                     staples={"olive oil", "salt"})
    assert out["Salty"]["ready"]


def test_reports_a_lane_with_nothing_available(tmp_vault):
    p = _profile(Sweet=["Apple + nut butter"], Salty=["Roasted chickpeas"])
    out = buffer_gaps.lane_readiness(p, _stock("chickpeas"))
    assert buffer_gaps.bare_lanes(out) == ["Sweet"]


def test_no_bare_lanes_when_each_row_has_one():
    p = _profile(Sweet=["Apple"], Salty=["Chickpeas"])
    out = buffer_gaps.lane_readiness(p, _stock("apples", "chickpeas"))
    assert buffer_gaps.bare_lanes(out) == []


def test_shopping_targets_come_from_bare_lanes_only():
    """Don't shop for a lane that's already covered — that's how lists get ignored."""
    p = _profile(Sweet=["Apple + nut butter"], Salty=["Roasted chickpeas"])
    out = buffer_gaps.lane_readiness(p, _stock("chickpeas"))
    targets = buffer_gaps.shopping_targets(out)
    assert any("nut butter" in t.lower() or "apple" in t.lower() for t in targets)
    assert not any("chickpea" in t.lower() for t in targets)


def test_building_block_gaps_list_what_is_not_stocked():
    p = Profile(prose="", building_blocks={"Protein": ["tofu", "edamame", "eggs"]})
    gaps = buffer_gaps.block_gaps(p, _stock("tofu"))
    assert gaps["Protein"] == ["edamame", "eggs"]


def test_no_profile_degrades_quietly():
    assert buffer_gaps.lane_readiness(None, _stock("apples")) == {}


def test_block_parenthetical_is_an_annotation_not_a_shopping_item():
    """"nutritional yeast (cheesy)" is one item; "cheesy" is not a thing to buy."""
    p = Profile(prose="", building_blocks={"Flavor": ["nutritional yeast (cheesy)"]})
    assert buffer_gaps.block_gaps(p, _stock("nutritional yeast")) == {}


def test_block_slash_options_count_as_either():
    p = Profile(prose="", building_blocks={"Fat": ["peanut/almond butter"]})
    assert buffer_gaps.block_gaps(p, _stock("almond butter")) == {}


def test_block_or_options_count_as_either():
    p = Profile(prose="", building_blocks={"Protein": ["plain soy or low-fat Greek yogurt"]})
    assert buffer_gaps.block_gaps(p, _stock("greek yogurt")) == {}
