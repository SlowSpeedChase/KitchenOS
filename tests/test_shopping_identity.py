import pytest

from lib.shopping_identity import shopping_identity


@pytest.mark.parametrize("a, b", [
    ("freshly ground black pepper", "black pepper"),
    ("extra-virgin olive oil", "extra virgin olive oil"),
    ("ground cinnamon", "Cinnamon"),
    ("ground allspice", "Allspice"),
    ("fresh thyme", "Thyme"),
    ("fresh parsley", "parsley"),
    ("freshly squeezed lemon juice", "lemon juice"),
    ("pure maple syrup", "maple syrup"),
    ("salt", "Kosher salt"),
    ("sea salt", "Celtic sea salt"),
    ("kosher salt such as diamond crystal", "Diamond Crystal kosher salt"),
    ("fine sea salt", "salt"),
])
def test_same_food_shares_identity(a, b):
    assert shopping_identity(a) == shopping_identity(b)


@pytest.mark.parametrize("a, b", [
    ("ground beef", "beef"),          # ground is the cut for meat, not a descriptor
    ("ground turkey", "turkey"),
    ("garlic salt", "salt"),          # seasoned salts are not salt
    ("celery salt", "salt"),
    ("onion salt", "kosher salt"),
    ("dried oregano", "oregano"),     # dried vs fresh herbs differ
    ("garlic", "garlic powder"),
    ("smoked paprika", "paprika"),
])
def test_different_foods_stay_distinct(a, b):
    assert shopping_identity(a) != shopping_identity(b)


def test_empty_is_empty():
    assert shopping_identity("") == ""
    assert shopping_identity(None) == ""
