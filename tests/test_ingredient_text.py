import lib.ingredient_text as ingredient_text
from lib.ingredient_text import clean_for_matching, apply_aliases


def test_strips_parentheticals():
    assert clean_for_matching(
        "blanched almond flour (spooned and leveled)") == "blanched almond flour"


def test_strips_inferred_marker():
    assert clean_for_matching("olive oil *(inferred)*") == "olive oil"


def test_strips_prep_phrases():
    assert clean_for_matching("extra-virgin olive oil, plus more for serving") \
        == "extra-virgin olive oil"
    assert clean_for_matching("fresh cilantro, finely chopped") == "fresh cilantro"


def test_collapses_doubled_words():
    assert clean_for_matching("garlic garlic cloves") == "garlic cloves"


def test_alias_lookup():
    assert apply_aliases("evoo") == "olive oil"


def test_alias_passthrough():
    assert apply_aliases("ground beef") == "ground beef"


def test_prep_tail_leaves_non_prep_trailing_word():
    # "nuts" is food identity, not prep — the whole tail must survive.
    assert clean_for_matching("salt, chopped nuts") == "salt, chopped nuts"


def test_prep_tail_strips_pure_prep_segment():
    # A trailing segment that is entirely prep vocabulary strips away, even
    # when that leaves just the base food — matching favors the base food.
    assert clean_for_matching("tomatoes, diced") == "tomatoes"


def test_prep_tail_covers_toasted():
    assert clean_for_matching("walnuts, toasted") == "walnuts"


def test_prep_tail_strips_multiple_pure_prep_segments():
    assert clean_for_matching("chicken, cooked, shredded") == "chicken"


def test_aliases_malformed_yaml_passthrough(tmp_path, monkeypatch):
    bad = tmp_path / "food_aliases.yml"
    bad.write_text("evoo: [unterminated\n", encoding="utf-8")
    monkeypatch.setattr(ingredient_text, "_ALIASES_PATH", bad)
    assert apply_aliases("evoo") == "evoo"


def test_aliases_non_dict_yaml_passthrough(tmp_path, monkeypatch):
    bad = tmp_path / "food_aliases.yml"
    bad.write_text("- one\n- two\n", encoding="utf-8")
    monkeypatch.setattr(ingredient_text, "_ALIASES_PATH", bad)
    assert apply_aliases("evoo") == "evoo"
