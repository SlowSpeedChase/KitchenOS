"""Tests for lib.pantry."""
import itertools

import pytest

from lib import pantry as pantry_module
from lib.ingredient_aggregator import (
    COUNT_UNITS,
    VOLUME_UNITS,
    WEIGHT_UNITS,
    parse_amount_to_float,
    unit_compatibility,
)
from lib.pantry import apply_decisions, find_match, split_against_pantry


def test_load_pantry_empty_inventory_returns_empty(tmp_vault, tmp_db):
    assert pantry_module.load_pantry() == []


def test_save_and_load_round_trip(tmp_vault, tmp_db):
    items = [
        {"item": "flour", "amount": "5", "unit": "cup"},
        {"item": "olive oil", "amount": "500", "unit": "ml"},
    ]
    pantry_module.save_pantry(items)
    loaded = sorted(pantry_module.load_pantry(), key=lambda e: e["item"])
    assert loaded == items


def test_save_pantry_drops_blank_items(tmp_vault, tmp_db):
    pantry_module.save_pantry(
        [{"item": "", "amount": "1", "unit": "x"}, {"item": "salt", "amount": "1", "unit": "tsp"}],
    )
    loaded = pantry_module.load_pantry()
    assert len(loaded) == 1
    assert loaded[0]["item"] == "salt"


def test_find_match_exact():
    pantry = [{"item": "Flour", "amount": "5", "unit": "cup"}]
    assert pantry_module.find_match("flour", pantry)["item"] == "Flour"


def test_find_match_substring():
    pantry = [{"item": "all-purpose flour", "amount": "5", "unit": "cup"}]
    match = pantry_module.find_match("flour", pantry)
    assert match["item"] == "all-purpose flour"


def test_find_match_returns_none():
    assert pantry_module.find_match("saffron", [{"item": "salt", "amount": "1", "unit": "tsp"}]) is None


class TestFindMatch:
    def test_exact_name_wins(self):
        pantry = [{"item": "lime", "amount": "3", "unit": "ct"},
                  {"item": "lime juice", "amount": "1", "unit": "oz"}]
        assert find_match("lime", pantry)["item"] == "lime"

    def test_prep_note_variant_matches(self):
        pantry = [{"item": "Capers", "amount": "1", "unit": "ct"}]
        assert find_match("capers, drained", pantry)["item"] == "Capers"

    def test_parenthetical_noise_does_not_produce_a_wrong_match(self):
        # AMENDED: the plan originally normalized ingredient text first and
        # asserted this line matched `Avocado oil`. Normalizing strips
        # parentheses, which is where alternatives live, so it is not done.
        # Instead `_match_text` drops only parentheticals that don't carry an
        # "or"-alternative — "(for softening corn tortillas)" has none, so it
        # is stripped, leaving bare "oil". That must not pull in `Canned
        # corn` (see TestParentheticalHandling for the `Avocado oil` line
        # this same ingredient text is supposed to match).
        pantry = [{"item": "Canned corn", "amount": "1", "unit": "ct"}]
        assert find_match("oil (for softening corn tortillas)", pantry) is None

    def test_an_alternatives_list_still_matches_a_named_alternative(self):
        # Normalizing would collapse this line to "almond butter" and lose the
        # peanut alternative entirely.
        pantry = [{"item": "Peanut butter", "amount": "1", "unit": "ct"}]
        assert find_match(
            "almond butter (or peanut, walnut, or cashew butter, or tahini)",
            pantry)["item"] == "Peanut butter"

    def test_generic_ingredient_does_not_match_a_compound_row(self):
        # The substring matcher gave `lemon` -> `Lemon pepper seasoning`.
        pantry = [{"item": "Lemon pepper seasoning", "amount": "1", "unit": "ct"}]
        assert find_match("lemons", pantry) is None

    def test_peanut_butter_does_not_match_the_butter_staple(self):
        # 11 ingredient lines in the real library hit this.
        pantry = [{"item": "butter", "amount": "1", "unit": "ct"}]
        assert find_match("peanut butter", pantry) is None

    def test_compound_row_still_matches_its_own_ingredient(self):
        pantry = [{"item": "Peanut butter", "amount": "1", "unit": "ct"}]
        assert find_match("creamy peanut butter", pantry)["item"] == "Peanut butter"

    def test_no_match_returns_none(self):
        pantry = [{"item": "flour", "amount": "1", "unit": "ct"}]
        assert find_match("dragon fruit", pantry) is None

    def test_empty_name_returns_none(self):
        assert find_match("", [{"item": "flour", "amount": "1", "unit": "ct"}]) is None


class TestParentheticalHandling:
    """`_match_text` drops a parenthetical unless it names an alternative.

    Prep-note parentheticals ("for enchilada red sauce", "optional", "see
    note") are noise that produces wrong matches and get stripped;
    alternatives-list parentheticals ("or peanut, walnut, ...", "sub 2 tbsp
    honey") name a real substitute ingredient and must be kept, even when
    nested inside another parenthetical. The recipe library phrases the same
    kind of substitution both with "or" and with "sub", so both must be
    recognized.
    """

    def test_prep_note_parenthetical_does_not_match_the_named_dish(self):
        pantry = [{"item": "Canned enchilada sauce", "amount": "1", "unit": "ct"}]
        assert find_match("cooking oil (for enchilada red sauce)", pantry) is None

    def test_stripped_prep_note_still_matches_the_bare_ingredient(self):
        # The cost of not fully normalizing: with the parenthetical gone,
        # "oil (for softening corn tortillas)" reduces to "oil" and matches
        # an oil row it should match.
        pantry = [{"item": "Avocado oil", "amount": "1", "unit": "ct"}]
        assert find_match("oil (for softening corn tortillas)", pantry)["item"] == "Avocado oil"

    def test_stripped_prep_note_does_not_match_an_unrelated_row(self):
        pantry = [{"item": "Canned corn", "amount": "1", "unit": "ct"}]
        assert find_match("oil (for softening corn tortillas)", pantry) is None

    def test_alternatives_parenthetical_is_kept_and_matches_the_alternative(self):
        pantry = [{"item": "Peanut butter", "amount": "1", "unit": "ct"}]
        assert find_match(
            "almond butter (or peanut, walnut, or cashew butter, or tahini)",
            pantry,
        )["item"] == "Peanut butter"

    def test_alternatives_parenthetical_nested_inside_another_is_kept(self):
        pantry = [{"item": "Cashew pieces", "amount": "1", "unit": "ct"}]
        assert find_match(
            "silken tofu (or 1 cup cashews (see note))", pantry,
        )["item"] == "Cashew pieces"

    def test_sub_phrased_alternative_is_kept(self):
        # Real corpus case: "Maple Sweet Potato Salad" has a sibling line
        # phrased "maple syrup (or 2 1/2 tbsp honey)" that already matches
        # under the "or" rule alone. This line says the same thing with "sub"
        # instead of "or" — both phrasings name a real substitute ingredient
        # and must survive, not just the one spelled with "or".
        pantry = [{"item": "Honey", "amount": "1", "unit": "ct"}]
        assert find_match("maple syrup (sub 2 tbsp honey)", pantry)["item"] == "Honey"

    def test_malformed_source_data_losing_its_match_is_accepted(self):
        # "Peanut Butter Cookie"'s ingredient table literally has item text
        # "beaten (about 1 1/2 large eggs)" — the food noun "eggs" exists only
        # inside a parenthetical that is an amount clarification, not an
        # alternative, so it is correctly stripped. The previous raw-text
        # match to "egg" was incidental (the noun happened to be present
        # somewhere in the string), not earned by the matcher, and recovering
        # it would require keeping prep-note parentheticals in general — the
        # exact behavior this fix removes. This is an accepted loss caused by
        # malformed source data, not a matching-rule defect; it is pinned
        # here rather than "fixed".
        pantry = [{"item": "egg", "amount": "1", "unit": "ct"}]
        assert find_match("beaten (about 1 1/2 large eggs)", pantry) is None

    def test_optional_parenthetical_is_dropped_and_still_matches(self):
        pantry = [{"item": "Smoked paprika", "amount": "1", "unit": "ct"}]
        assert find_match("paprika (optional)", pantry)["item"] == "Smoked paprika"

    def test_optional_parenthetical_dropped_matches_a_different_row(self):
        pantry = [{"item": "Sucralose sweetener", "amount": "1", "unit": "ct"}]
        assert find_match("sweetener (optional)", pantry)["item"] == "Sucralose sweetener"


def test_split_no_match_returns_full_to_buy():
    result = pantry_module.split_against_pantry("saffron", "1", "tsp", [])
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "1", "unit": "tsp"}


@pytest.mark.parametrize(
    ("demand", "pantry_name", "amount", "unit"),
    [
        ("bone-in chicken breast", "Canned chicken breast", "1", "whole"),
        ("garlic", "Garlic powder", "4", "clove"),
        ("onion", "caramelized onions", "2", "whole"),
        ("potatoes", "diced fried potatoes", "1", "whole"),
        ("banana", "frozen bananas", "5", "whole"),
    ],
)
def test_related_food_form_is_review_only(demand, pantry_name, amount, unit):
    """A discovery-quality match cannot silently remove shopping demand."""
    pantry = [{"item": pantry_name, "amount": "1", "unit": "ct"}]

    result = split_against_pantry(demand, amount, unit, pantry)

    assert result == {
        "from_pantry": None,
        "to_buy": {"amount": amount, "unit": unit},
        "warning": f"inventory has {pantry_name} (1 ct), a related item; not credited",
        "status": "review",
        "matched_inventory": pantry[0],
    }


def test_package_count_is_review_only_against_ingredient_count():
    """One receipt package is not evidence that one usable egg remains."""
    pantry = [{"item": "eggs", "amount": "1", "unit": "ct"}]

    result = split_against_pantry("eggs", "3", "each", pantry)

    assert result == {
        "from_pantry": None,
        "to_buy": {"amount": "3", "unit": "each"},
        "warning": "inventory has eggs (1 ct), but the package quantity is unknown; not credited",
        "status": "review",
        "matched_inventory": pantry[0],
    }


def test_no_candidate_is_an_explicit_buy_disposition():
    result = split_against_pantry("saffron", "1", "tsp", [])

    assert result["status"] == "buy"
    assert result["matched_inventory"] is None


@pytest.mark.parametrize(
    ("pantry", "amount", "unit"),
    [
        ({"item": "flour", "amount": "1", "unit": "lb"}, "1", "bag"),
        ({"item": "salt", "amount": "", "unit": ""}, "1", "tsp"),
        ({"item": "salt", "amount": "1", "unit": "tsp"}, "", "tsp"),
    ],
)
def test_unknown_units_or_quantities_are_review_only(pantry, amount, unit):
    result = split_against_pantry(pantry["item"], amount, unit, [pantry])

    assert result["status"] == "review"
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": amount, "unit": unit}


def test_normalized_alias_identity_can_receive_exact_credit():
    pantry = [{"item": "mayo", "amount": "2", "unit": "cup"}]

    result = split_against_pantry("mayonnaise", "1", "cup", pantry)

    assert result["status"] == "credited"
    assert result["matched_inventory"] == pantry[0]
    assert result["to_buy"] is None


def test_split_pantry_fully_covers_same_unit():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    result = pantry_module.split_against_pantry("flour", "1", "cup", pantry)
    assert result["from_pantry"] == {"amount": "1", "unit": "cup"}
    assert result["to_buy"] is None
    assert result["status"] == "credited"
    assert result["matched_inventory"] == pantry[0]


def test_split_pantry_partial_cover_same_family():
    # pantry has 1 cup (= 48 tsp); recipe asks 100 tsp → buy 52 tsp
    pantry = [{"item": "sugar", "amount": "1", "unit": "cup"}]
    result = pantry_module.split_against_pantry("sugar", "100", "tsp", pantry)
    assert result["from_pantry"] == {"amount": "48", "unit": "tsp"}
    assert result["to_buy"] == {"amount": "52", "unit": "tsp"}
    assert result["warning"] is None


def test_split_pantry_unit_conversion_within_volume():
    # pantry has 500ml; recipe asks 1 cup (~236.6 ml).
    pantry = [{"item": "olive oil", "amount": "500", "unit": "ml"}]
    result = pantry_module.split_against_pantry("olive oil", "1", "cup", pantry)
    assert result["to_buy"] is None  # pantry covers
    assert result["from_pantry"] == {"amount": "1", "unit": "cup"}


def test_split_cross_family_warns_and_does_not_subtract():
    # Recipe in tsp (volume), pantry in oz (weight) → warn, no subtraction.
    pantry = [{"item": "honey", "amount": "8", "unit": "oz"}]
    result = pantry_module.split_against_pantry("honey", "2", "tsp", pantry)
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "2", "unit": "tsp"}
    assert "different units" in (result["warning"] or "")


def test_split_pantry_no_amount_requires_review():
    pantry = [{"item": "salt", "amount": "", "unit": ""}]
    result = pantry_module.split_against_pantry("salt", "1", "tsp", pantry)
    assert result["to_buy"] == {"amount": "1", "unit": "tsp"}
    assert result["from_pantry"] is None
    assert result["status"] == "review"


def test_split_recipe_no_amount_requires_review():
    pantry = [{"item": "salt", "amount": "1", "unit": "lb"}]
    result = pantry_module.split_against_pantry("salt", "", "to taste", pantry)
    assert result["to_buy"] == {"amount": "", "unit": "to taste"}
    assert result["from_pantry"] is None
    assert result["status"] == "review"


def test_apply_decisions_subtracts_within_family():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    decisions = [{"item": "flour", "amount": "1", "unit": "cup"}]
    updated = pantry_module.apply_decisions(decisions, pantry)
    assert updated[0]["amount"] == "4"


def test_apply_decisions_whitespace_padded_unit_still_converts():
    """Regression: get_unit_family/convert_to_base_unit only lowercase, they
    don't strip. A padded pantry unit ("10 lb ") used to resolve to family
    "other" inside apply_decisions's convert branch, which silently skipped
    the base-unit conversion and subtracted the *raw* decision amount from
    the *raw* pantry amount as if they were already the same unit — 100 g
    off a "10 lb" row went straight to `max(0, 10 - 100)` and wiped the row
    out entirely, instead of the correct ~9.78 lb remaining.

    100 g (not 1 g, as in the originally reported repro) is used so the
    visible amount isn't swallowed by format_amount's rounding: 10 lb - 1 g
    rounds right back to "10".
    """
    pantry = [{"item": "t", "amount": "10", "unit": " lb "}]
    updated = pantry_module.apply_decisions(
        [{"item": "t", "amount": "100", "unit": "g"}], pantry)
    assert updated, "row was wiped out — the pre-fix naive-subtraction bug"
    remaining = parse_amount_to_float(updated[0]["amount"])
    # Correct: 10 lb - 100 g ≈ 9.7795 lb → "9.78".
    assert remaining == pytest.approx(9.78, abs=0.01)


def test_apply_decisions_removes_when_depleted():
    pantry = [{"item": "flour", "amount": "1", "unit": "cup"}]
    decisions = [{"item": "flour", "amount": "1", "unit": "cup"}]
    updated = pantry_module.apply_decisions(decisions, pantry)
    assert updated == []


def test_apply_decisions_does_not_mutate_input():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    pantry_copy = [dict(e) for e in pantry]
    pantry_module.apply_decisions([{"item": "flour", "amount": "1", "unit": "cup"}], pantry)
    assert pantry == pantry_copy


def test_apply_decisions_skips_unmatched_item():
    pantry = [{"item": "flour", "amount": "5", "unit": "cup"}]
    updated = pantry_module.apply_decisions(
        [{"item": "saffron", "amount": "1", "unit": "tsp"}], pantry
    )
    assert updated == pantry


def test_split_count_whole_wildcard_pantry_covers():
    # Pantry "6 cloves garlic" should cover recipe "5 whole garlic" 1:1.
    pantry = [{"item": "garlic", "amount": "6", "unit": "cloves"}]
    result = pantry_module.split_against_pantry("garlic", "5", "whole", pantry)
    assert result["from_pantry"] == {"amount": "5", "unit": "whole"}
    assert result["to_buy"] is None
    assert result["warning"] is None


def test_split_count_whole_wildcard_partial_cover():
    # Pantry "6 cloves" partially covers recipe "10 whole" → buy the rest.
    pantry = [{"item": "garlic", "amount": "6", "unit": "cloves"}]
    result = pantry_module.split_against_pantry("garlic", "10", "whole", pantry)
    assert result["from_pantry"] == {"amount": "6", "unit": "cloves"}
    assert result["to_buy"] == {"amount": "4", "unit": "cloves"}
    assert result["warning"] is None


def test_split_count_ct_package_requires_review():
    # Inventory "ct" records package presence, not an ingredient quantity.
    pantry = [{"item": "lemons", "amount": "5", "unit": "ct"}]
    result = pantry_module.split_against_pantry("lemons", "5", "whole", pantry)
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "5", "unit": "whole"}
    assert result["status"] == "review"


def test_split_count_distinct_units_still_warns():
    # Slices vs cloves are both count but neither is "whole" — must still warn.
    pantry = [{"item": "bread", "amount": "1", "unit": "loaf"}]
    result = pantry_module.split_against_pantry("bread", "2", "slices", pantry)
    # "loaf" is not in COUNT_UNITS → cross-family warning fires upstream.
    assert result["from_pantry"] is None
    assert result["to_buy"] == {"amount": "2", "unit": "slices"}
    assert result["warning"]


def test_load_pantry_reads_inventory_db(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items
    from lib.pantry import load_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Butter", quantity=1, unit="lb", location="fridge"),
        InventoryItem(name="Butter", quantity=0.5, unit="lb", location="freezer"),
    ])
    pantry = load_pantry()
    by_item = {e["item"]: e for e in pantry}
    assert by_item["Flour"]["amount"] == "5"
    assert by_item["Flour"]["unit"] == "lb"
    assert by_item["Butter"]["amount"] == "1.5"  # summed across locations


def test_load_pantry_excludes_expired_rows_without_deleting_them(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, read_inventory
    from lib.pantry import load_pantry, save_pantry

    add_items([
        InventoryItem(name="Fresh milk", quantity=1, unit="ct", expires="2999-01-01"),
        InventoryItem(name="Expired milk", quantity=1, unit="ct", expires="2000-01-01"),
    ])

    assert [entry["item"] for entry in load_pantry()] == ["Fresh milk"]
    assert sorted(item.name for item in read_inventory()) == ["Expired milk", "Fresh milk"]

    # The confirm flow saves the filtered pantry after applying decisions.
    # An expired row omitted from that view is historical, not "used up."
    save_pantry(load_pantry())
    assert sorted(item.name for item in read_inventory()) == ["Expired milk", "Fresh milk"]


def test_save_pantry_revives_an_expired_row_when_the_same_item_is_restocked(
        tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, read_inventory
    from lib.pantry import load_pantry, save_pantry

    add_items([
        InventoryItem(name="Milk", quantity=1, unit="ct", expires="2000-01-01"),
    ])

    save_pantry([{"item": "Milk", "amount": "2", "unit": "ct"}])

    rows = read_inventory()
    assert len(rows) == 1
    assert rows[0].quantity == 2
    assert rows[0].expires is None
    assert load_pantry() == [{"item": "Milk", "amount": "2", "unit": "ct"}]


def test_save_pantry_decrements_and_removes(tmp_vault, tmp_db):
    from lib.inventory import InventoryItem, add_items, read_inventory
    from lib.pantry import load_pantry, save_pantry
    add_items([
        InventoryItem(name="Flour", quantity=5, unit="lb"),
        InventoryItem(name="Sugar", quantity=2, unit="lb"),
    ])
    # simulate apply_decisions output: flour reduced, sugar used up
    save_pantry([{"item": "Flour", "amount": "3", "unit": "lb"}])
    items = {it.name: it for it in read_inventory()}
    assert items["Flour"].quantity == 3.0
    assert "Sugar" not in items
    assert load_pantry() == [{"item": "Flour", "amount": "3", "unit": "lb"}]


def test_save_pantry_inserts_new_items(tmp_vault, tmp_db):
    from lib.inventory import read_inventory
    from lib.pantry import save_pantry
    save_pantry([{"item": "Olive oil", "amount": "16", "unit": "oz"}])
    items = read_inventory()
    assert items[0].name == "Olive oil"
    assert items[0].location == "pantry"
    assert items[0].source == "manual"


def test_save_pantry_unchanged_skips_replace_and_refresh(
    tmp_vault, tmp_db, monkeypatch
):
    import lib.inventory as inventory
    from lib import inventory_db

    inventory_db.replace_inventory_rows([
        {"name": "Flour", "quantity": 5.0, "unit": "lb"}
    ])
    replacements = []
    refreshes = []
    real_replace = inventory_db._replace_inventory_rows
    monkeypatch.setattr(
        inventory_db,
        "_replace_inventory_rows",
        lambda conn, rows: replacements.append(rows) or real_replace(conn, rows),
    )
    monkeypatch.setattr(
        inventory, "refresh_inventory_views", lambda: refreshes.append(True)
    )

    pantry_module.save_pantry([
        {"item": "Flour", "amount": "5", "unit": "lb"}
    ])

    assert replacements == []
    assert refreshes == []


def test_ct_pantry_is_spent_by_a_whole_recipe_line():
    """The reported bug: 3 ct lime, recipe wants 1 whole lime."""
    pantry = [{"item": "lime", "amount": "3", "unit": "ct"}]
    updated = apply_decisions(
        [{"item": "lime", "amount": "1", "unit": "whole"}], pantry)
    assert parse_amount_to_float(updated[0]["amount"]) == 2.0


def test_ct_pantry_depletes_to_removal():
    pantry = [{"item": "lime", "amount": "2", "unit": "ct"}]
    updated = apply_decisions(
        [{"item": "lime", "amount": "2", "unit": "whole"}], pantry)
    assert updated == []


# A representative unit from every group that behaves differently, rather than
# the full cross product of ~40 units, which would add 1600 slow cases for no
# extra coverage.
PARITY_UNITS = [
    "", "whole", "ct", "count", "ea", "each", "piece",   # generic count
    "clove", "slice", "can", "bunch", "head", "package",  # specific count
    "cup", "tbsp", "tsp", "qt",                           # volume
    "oz", "lb", "g",                                      # weight
    " lb ",  # weight, whitespace-padded — covers the get_unit_family /
             # convert_to_base_unit whitespace-desync regression (they
             # lowercase but don't strip, unlike unit_compatibility)
    "a sprinkle", "loaf", "jar", "bag", "box",            # unknown / garbage
]


_ALL_PARITY_PAIRS = list(itertools.product(PARITY_UNITS, PARITY_UNITS))

# Independent reference for "should p_unit (pantry) and n_unit (recipe) be
# treated as convertible" — deliberately reimplemented from the same
# underlying tables rather than built by calling unit_compatibility()
# itself. split_against_pantry and apply_decisions both delegate to that one
# function, so if its *logic* ever regresses (e.g. the count branch stops
# recognizing "ct"/"whole" as compatible), both callers would agree to
# refuse it — and a pair list filtered through the same broken function
# would just quietly drop that pair instead of failing a test. Mirroring the
# classification here keeps the pair list, and therefore the assertion
# below, independent of whether unit_compatibility is currently correct.
#
# Residual coupling: this oracle still reads COUNT_UNITS/VOLUME_UNITS/
# WEIGHT_UNITS from the module under test (rebuilding those tables here
# would be its own source of drift), so a regression that shrinks one of
# those tables would partly mirror into these pair lists too — the
# independence is about the *logic* (which branch fires, generic/equality
# rules), not about the table contents.
_GENERIC = {"", "whole", "ct", "count", "ea", "each", "piece", "pieces"}


def _family(unit: str) -> str:
    unit = (unit or "").lower().strip()
    if unit in VOLUME_UNITS:
        return "volume"
    if unit in WEIGHT_UNITS:
        return "weight"
    if unit in COUNT_UNITS or unit == "":
        return "count"
    return "other"


def _should_be_compatible(p_unit: str, n_unit: str) -> bool:
    p_family, n_family = _family(p_unit), _family(n_unit)
    if p_family in ("volume", "weight") and p_family == n_family:
        return True
    # Identical units are exact arithmetic regardless of family/table —
    # mirrors unit_compatibility's same-string shortcut (e.g. "jar" == "jar"
    # is compatible even though "jar" is in no table at all).
    if p_unit and p_unit == n_unit:
        return True
    if p_family == "count" and n_family == "count":
        return p_unit == n_unit or p_unit in _GENERIC or n_unit in _GENERIC
    return False


COMPATIBLE_PAIRS = [
    (p, n) for p, n in _ALL_PARITY_PAIRS if _should_be_compatible(p, n)
]

# A package-count inventory row is convertible for the cook ledger only after
# a person confirms its contents. It must not automatically reduce shopping
# demand expressed in ingredient counts.
AUTO_CREDIT_PAIRS = [
    (p, n) for p, n in COMPATIBLE_PAIRS if not (p == "ct" and n != "ct")
]

INCOMPATIBLE_PAIRS = [
    (p, n) for p, n in _ALL_PARITY_PAIRS if not _should_be_compatible(p, n)
]

@pytest.mark.parametrize("p_unit,n_unit", AUTO_CREDIT_PAIRS)
def test_compatible_units_are_both_credited_and_spendable(p_unit, n_unit):
    """Whatever unit_compatibility says is convertible must be both
    creditable on the shopping list and spendable on the cook path.

    Package-count inventory rows are intentionally excluded: they remain
    spendable after an explicit cook decision but are only review candidates
    on a generated shopping list.
    """
    # Count pairs ("one_to_one") subtract exact integers, so "1" from a
    # pantry of "10" is always visible. Volume/weight pairs ("convert") go
    # through a base-unit conversion first; a decrement that's tiny in the
    # pantry's own unit (e.g. subtracting a few grams from a "10 lb" row)
    # can round back to "10" in format_amount's 2-decimal display. "10" is
    # large enough to stay visible even for the widest mismatch in
    # PARITY_UNITS (lb vs g, ~453:1).
    amount = "1" if _family(p_unit) == "count" else "10"

    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    credited = split_against_pantry(
        "thing", amount, n_unit, pantry)["from_pantry"] is not None

    updated = apply_decisions(
        [{"item": "thing", "amount": amount, "unit": n_unit}], pantry)
    if not updated:
        spent = True                      # row removed entirely
    else:
        spent = parse_amount_to_float(updated[0]["amount"]) < 10.0 - 0.001

    assert credited and spent, (
        f"pantry {p_unit!r} vs recipe {n_unit!r}: "
        f"credited={credited} spent={spent}")


@pytest.mark.parametrize("p_unit,n_unit", INCOMPATIBLE_PAIRS)
def test_incompatible_units_are_never_spent(p_unit, n_unit):
    """apply_decisions must never subtract across units it cannot convert.

    This is the dangerous direction: silently subtracting, say, "2 g" from a
    "10 lb" row would corrupt inventory with an invented conversion. The old
    parity test only ever checked `credited == spent`, so a caller that
    started spending across incompatible units without also crediting them
    would have slipped through unnoticed.
    """
    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    updated = apply_decisions(
        [{"item": "thing", "amount": "2", "unit": n_unit}], pantry)
    assert updated == pantry


@pytest.mark.parametrize("p_unit,n_unit", INCOMPATIBLE_PAIRS)
def test_incompatible_units_are_not_credited(p_unit, n_unit):
    """An incompatible pair must not be credited from the pantry either.

    Shopping may nominate a candidate across unknown units, but it may never
    turn uncertainty into an automatic credit.
    """
    pantry = [{"item": "thing", "amount": "10", "unit": p_unit}]
    result = split_against_pantry("thing", "1", n_unit, pantry)
    assert result["from_pantry"] is None


def test_parity_units_cover_every_count_unit_group():
    """Guard: if COUNT_UNITS grows a new *kind* of unit, extend PARITY_UNITS."""
    assert set(PARITY_UNITS) & COUNT_UNITS, "parity list lost its count units"
    assert unit_compatibility("ct", "whole") == "one_to_one"


def test_split_does_not_display_a_package_as_a_generic_ingredient_count():
    pantry = [{"item": "lime", "amount": "1", "unit": "ct"}]
    split = split_against_pantry("lime", "3", "whole", pantry)
    assert split["from_pantry"] is None
    assert split["to_buy"] == {"amount": "3", "unit": "whole"}
    assert split["status"] == "review"


def test_split_does_not_display_a_package_as_a_specific_ingredient_count():
    pantry = [{"item": "garlic", "amount": "1", "unit": "ct"}]
    split = split_against_pantry("garlic", "3", "cloves", pantry)
    assert split["from_pantry"] is None
    assert split["to_buy"] == {"amount": "3", "unit": "cloves"}
    assert split["status"] == "review"


class TestStockForIngredients:
    """Presence of each ingredient in inventory — the recipe page's colouring."""

    PANTRY = [
        {"item": "Chicken thighs", "amount": "3", "unit": "lb"},
        {"item": "Paprika", "amount": "1", "unit": "jar"},
    ]

    def test_positionally_aligned_with_the_input(self):
        result = pantry_module.stock_for_ingredients(
            ["chicken thighs", "saffron", "paprika"], self.PANTRY)
        assert len(result) == 3
        assert result[0]["item"] == "Chicken thighs"
        assert result[1] is None
        assert result[2]["item"] == "Paprika"

    def test_matching_is_case_insensitive(self):
        assert pantry_module.stock_for_ingredients(["PAPRIKA"], self.PANTRY)[0] is not None

    def test_delegates_to_find_match(self, monkeypatch):
        """The page and the shopping list must never disagree about what you own."""
        calls = []

        def spy(item, pantry):
            calls.append(item)
            return None

        monkeypatch.setattr(pantry_module, "find_match", spy)
        pantry_module.stock_for_ingredients(["a", "b"], self.PANTRY)
        assert calls == ["a", "b"]

    def test_empty_and_missing_names_are_unmatched_not_errors(self):
        assert pantry_module.stock_for_ingredients(["", None], self.PANTRY) == [None, None]

    def test_empty_pantry_matches_nothing(self):
        assert pantry_module.stock_for_ingredients(["paprika"], []) == [None]

    def test_presence_not_sufficiency(self):
        """A pantry row smaller than the recipe needs is still 'in stock'.

        Sufficiency depends on the scale the reader picks, so it can't be
        answered here — and answering it wrongly is worse than not answering.
        """
        pantry = [{"item": "Paprika", "amount": "0.5", "unit": "tsp"}]
        assert pantry_module.stock_for_ingredients(["paprika"], pantry)[0] is not None
