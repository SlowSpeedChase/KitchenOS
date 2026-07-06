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
