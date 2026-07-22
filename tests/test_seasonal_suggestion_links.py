"""Seasonal-suggestion wikilinks must actually resolve in Obsidian.

Found in the wild: the generated plan linked
`[[Sheet Pan Chicken & Potatoes + Tzatziki Sauce]]` while the file on disk was
`... Tzatziki Sauce Recipe.md`. Obsidian resolves wikilinks by **filename**,
not by frontmatter title, so the link dangled — and clicking it silently
created an empty note at the vault root.

Five recipes in the real library differ from their filename by more than case,
two of them containing a `|`, which is Obsidian's alias separator and breaks
the link a second way. Linking by filename stem fixes all of it at once.
"""
import pytest

from generate_meal_plan import get_seasonal_suggestions


@pytest.fixture
def recipes(tmp_path):
    d = tmp_path / "Recipes"
    d.mkdir()
    return d


def _recipe(recipes, filename, title, seasonal="potato"):
    (recipes / f"{filename}.md").write_text(
        "---\n"
        f'title: "{title}"\n'
        f"seasonal_ingredients: [{seasonal}]\n"
        "peak_months: [1,2,3,4,5,6,7,8,9,10,11,12]\n"
        "---\n\n# Recipe\n",
        encoding="utf-8",
    )


def test_links_use_the_filename_not_the_title(recipes):
    """The exact bug: title lacks the ' Recipe' suffix the filename carries."""
    _recipe(recipes, "Sheet Pan Chicken Recipe", "Sheet Pan Chicken")
    out = get_seasonal_suggestions(recipes, 2026, 30)
    assert "[[Sheet Pan Chicken Recipe]]" in out
    assert "[[Sheet Pan Chicken]]" not in out


def test_titles_containing_a_pipe_do_not_break_the_link(recipes):
    """`|` is Obsidian's alias separator — a title with one splits the link."""
    _recipe(recipes, "Chilaquiles Rojos Recipe", "How To Make CHILAQUILES | Rojos")
    out = get_seasonal_suggestions(recipes, 2026, 30)
    assert "[[Chilaquiles Rojos Recipe]]" in out
    assert "|" not in out.split("[[")[1].split("]]")[0]


def test_title_stripped_characters_still_resolve(recipes):
    """'30/10 smoothie' becomes '3010 Smoothie' on disk; the slash is dropped."""
    _recipe(recipes, "3010 Blueberry Banana Smoothie", "30/10 blueberry banana smoothie")
    out = get_seasonal_suggestions(recipes, 2026, 30)
    assert "[[3010 Blueberry Banana Smoothie]]" in out


def test_matching_title_and_filename_are_unaffected(recipes):
    _recipe(recipes, "Potato Soup", "Potato Soup")
    assert "[[Potato Soup]]" in get_seasonal_suggestions(recipes, 2026, 30)


def test_every_emitted_link_names_a_real_file(recipes):
    """The invariant that actually matters, stated directly."""
    _recipe(recipes, "Sheet Pan Chicken Recipe", "Sheet Pan Chicken")
    _recipe(recipes, "Potato Soup", "Potato Soup")
    _recipe(recipes, "Okroshka", "OKROSHKA")

    out = get_seasonal_suggestions(recipes, 2026, 30)
    links = [seg.split("]]")[0] for seg in out.split("[[")[1:]]
    assert links, "no suggestions generated — fixture problem"
    for link in links:
        assert (recipes / f"{link}.md").exists(), f"[[{link}]] resolves to nothing"
