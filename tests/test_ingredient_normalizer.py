from lib.ingredient_normalizer import normalize_name, is_noise_unit


def test_strips_parentheticals_and_prep():
    assert normalize_name("red onion, thinly sliced") == "red onion"
    assert normalize_name("0.25 head of iceberg lettuce (about 2-3 cups)") == "head of iceberg lettuce"
    assert normalize_name("basil leaves, slivered (8g)") == "basil leaves"


def test_strips_noise_tokens():
    assert normalize_name("boiled potatoes *(inferred)*") == "boiled potatoes"
    assert normalize_name("paprika (optional)") == "paprika"
    assert normalize_name("white vinegar (not shown)") == "white vinegar"
    assert normalize_name("optional: rosemary") == "rosemary"


def test_strips_leading_article_and_size():
    assert normalize_name("1 of a large red onion, (thinly sliced)") == "red onion"


def test_alias_map_merges_synonyms():
    assert normalize_name("mayo") == "mayonnaise"
    assert normalize_name("limes juice of") == "lime juice"


def test_variants_share_a_grouping_key():
    keys = {
        normalize_name("red onion, thinly sliced"),
        normalize_name("0.5 small red onion, (very thinly sliced)"),
        normalize_name("2 whole red onion"),
    }
    assert keys == {"red onion"}


def test_noise_units():
    assert is_noise_unit("to tastes") is True
    assert is_noise_unit("taste") is True
    assert is_noise_unit("pinch") is True
    assert is_noise_unit("cup") is False
    assert is_noise_unit("") is False
