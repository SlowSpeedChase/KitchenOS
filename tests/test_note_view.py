"""Rendering a generated note as HTML."""
from lib import note_view


def test_a_wikilink_becomes_a_recipe_link():
    html = note_view._inline("[[Osso Buco]]")
    assert 'href="/recipe/Osso%20Buco"' in html
    assert ">Osso Buco</a>" in html


def test_a_meal_wikilink_is_not_rendered_as_a_recipe_link():
    """`[[Meal: X]]` is a plate, and `/recipe/Meal%3A%20X` is a guaranteed 404.

    Legacy weeks still carry this form (rebuild_meal_plan_markdown writes it),
    so the link was dead wherever such a plan was viewed as a note. There is no
    plate page to point at, so it renders as plain text rather than a control
    that cannot be honoured — the same posture the button renderer takes.
    """
    html = note_view._inline("[[Meal: Osso Buco Plate]]")
    assert "/recipe/Meal" not in html
    assert "Osso Buco Plate" in html
    assert "<a " not in html


def test_a_meal_wikilink_with_an_alias_keeps_its_label():
    html = note_view._inline("[[Meal: Osso Buco Plate|Sunday plate]]")
    assert "Sunday plate" in html
    assert "<a " not in html


def test_note_content_still_cannot_inject_markup():
    html = note_view._inline("[[Meal: <script>alert(1)</script>]]")
    assert "<script>" not in html
