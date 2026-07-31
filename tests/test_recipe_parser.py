"""Tests for recipe parser module"""
import tempfile
from pathlib import Path
from lib.recipe_parser import (
    extract_ingredients_section,
    extract_my_notes,
    extract_video_id,
    find_existing_recipe,
    parse_recipe_body,
    parse_recipe_file,
)


def test_parse_recipe_file_extracts_frontmatter():
    """Should extract frontmatter as dict"""
    content = '''---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
servings: 2
---

# Pasta Aglio e Olio

Content here
'''
    result = parse_recipe_file(content)

    assert result['frontmatter']['title'] == 'Pasta Aglio e Olio'
    assert result['frontmatter']['source_url'] == 'https://www.youtube.com/watch?v=bJUiWdM__Qw'
    assert result['frontmatter']['servings'] == 2


def test_parse_recipe_file_extracts_body():
    """Should extract body content after frontmatter"""
    content = '''---
title: "Test"
---

# Test Recipe

Some content here.
'''
    result = parse_recipe_file(content)

    assert '# Test Recipe' in result['body']
    assert 'Some content here.' in result['body']


def test_extract_my_notes_returns_notes_section():
    """Should extract content after ## My Notes heading"""
    content = '''# Recipe

## Ingredients

- flour

## My Notes

This is my personal note.
I added extra garlic.
'''
    notes = extract_my_notes(content)

    assert 'This is my personal note.' in notes
    assert 'I added extra garlic.' in notes


def test_extract_my_notes_returns_empty_when_missing():
    """Should return empty string if no My Notes section"""
    content = '''# Recipe

## Ingredients

- flour
'''
    notes = extract_my_notes(content)

    assert notes == ''


def test_extract_my_notes_preserves_formatting():
    """Should preserve markdown formatting in notes"""
    content = '''## My Notes

- Item 1
- Item 2

**Bold text** and *italic*
'''
    notes = extract_my_notes(content)

    assert '- Item 1' in notes
    assert '**Bold text**' in notes


def test_extract_video_id_from_watch_url():
    """Should extract video ID from standard YouTube URL"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_from_short_url():
    """Should extract video ID from youtu.be URL"""
    url = "https://youtu.be/bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_with_extra_params():
    """Should extract video ID even with extra URL params"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw&t=120"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_find_existing_recipe_finds_match():
    """Should find recipe file with matching video ID"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "2026-01-07-pasta.md"
        recipe.write_text('''---
title: "Pasta"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---

# Pasta
''')
        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")
        assert result == recipe


def test_find_existing_recipe_returns_none_when_not_found():
    """Should return None when no matching recipe exists"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        result = find_existing_recipe(recipes_dir, "nonexistent123")
        assert result is None


def test_find_existing_recipe_ignores_history_folder():
    """Should not search in .history directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        history_dir = recipes_dir / ".history"
        history_dir.mkdir()
        backup = history_dir / "2026-01-07-pasta.md"
        backup.write_text('''---
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---
''')
        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")
        assert result is None


# ---- Grouped ingredient sections (regression) ----

GROUPED_BODY = """# Spiced Chicken

> A chicken with a rub.

## Ingredients

| Amount | Unit | Ingredient |
|--------|------|------------|
| 2 | lb | chicken thighs |

### For the spice rub

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | tsp | paprika |
| 1 | tsp | cumin |

#### Optional heat

| Amount | Unit | Ingredient |
|--------|------|------------|
| 1 | pinch | cayenne |

## Instructions

1. Rub the chicken.
2. Roast it.

## Notes

Do not let this leak into the ingredients.
"""


def test_grouped_ingredient_sections_are_all_parsed():
    """REGRESSION: everything after the first blank line used to vanish.

    parse_recipe_body matched one *contiguous* run of table rows, so a recipe
    whose ingredients are grouped under sub-headings kept only the first group —
    the spices silently didn't exist for the recipe page, the grid card, the
    shopping list or the suggester's ingredient overlap.
    """
    items = [i["item"] for i in parse_recipe_body(GROUPED_BODY)["ingredients"]]
    assert items == ["chicken thighs", "paprika", "cumin", "cayenne"]


def test_ingredients_section_stops_at_the_next_h2():
    """Sub-headings stay inside the section; a sibling h2 ends it."""
    section = extract_ingredients_section(GROUPED_BODY)
    assert "cayenne" in section
    assert "Roast it" not in section
    assert "leak into the ingredients" not in section


def test_ingredients_parse_without_a_blank_line_after_the_heading():
    """REGRESSION: a table not preceded by exactly one blank line yielded zero rows."""
    body = (
        "## Ingredients\n"
        "| Amount | Unit | Ingredient |\n"
        "|---|---|---|\n"
        "| 1 | tsp | salt |\n"
        "\n## Instructions\n\n1. Season.\n"
    )
    items = [i["item"] for i in parse_recipe_body(body)["ingredients"]]
    assert items == ["salt"]


def test_grouped_sections_do_not_break_instructions():
    steps = parse_recipe_body(GROUPED_BODY)["instructions"]
    assert [s["step"] for s in steps] == [1, 2]


def test_no_ingredients_section_returns_empty():
    assert extract_ingredients_section("# Just a title\n\n## Instructions\n\n1. Go.\n") == ""
    assert parse_recipe_body("# Nothing\n")["ingredients"] == []
